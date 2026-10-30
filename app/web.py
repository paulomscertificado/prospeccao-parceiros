"""Apoio às telas: modelos HTML (Jinja2), avisos ("flash") e respostas comuns."""

import json
from datetime import date
from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import autorizacao, config, score, util
from .seguranca import token_csrf

PASTA = Path(__file__).resolve().parent
modelos_html = Jinja2Templates(directory=str(PASTA / "templates"))
f = modelos_html.env.filters
f["moeda"] = util.moeda
f["pct"] = util.porcentagem
f["data"] = util.so_data_br
f["datahora"] = util.data_br
f["telefone"] = util.formatar_telefone
f["cnpj"] = util.formatar_cnpj
f["selo"] = score.classe_css
f["insta"] = util.link_instagram
f["whats"] = util.link_whatsapp
f["json"] = lambda v: Markup(json.dumps(v, ensure_ascii=False, default=str).replace("</", "<\\/"))
f["primeiro_nome"] = util.primeiro_nome
modelos_html.env.globals.update(config=config, CANAIS=config.CANAIS, PERFIS=config.PERFIS)

# Cada item aparece só para quem tem a permissão (e com o módulo ligado). A proteção de verdade é a da rota.
PERMISSAO_DO_MENU = {
    "/": "painel.ver", "/campanhas": "campanhas.ver", "/envios": "envios.ver", "/fila": "fila.ver",
    "/oportunidades": "oportunidades.ver", "/prospeccao": "prospeccao.buscar", "/leads": "leads.ver",
    "/agenda": "agenda.ver", "/cadencias": "cadencias.ver", "/parceiros": "parceiros.ver", "/clientes": "clientes.ver",
    "/vencimentos": "vencimentos.ver", "/vendas": "vendas.ver", "/comissoes": "comissoes.ver",
    "/relatorios": "relatorios.ver", "/inteligencia": "inteligencia.ver", "/ia": "ia.usar", "/conversas": "conversas.ver",
    "/whatsapp": "whatsapp.ver", "/email": "email.ver", "/permissoes": "permissoes.gerenciar",
    "/configuracoes": "configuracoes.ver",
    "/portal": "portal.usar", "/portal/indicar": "portal.usar", "/portal/clientes": "portal.usar",
    "/portal/vencimentos": "portal.usar",
}
MENU_EQUIPE = [
    ("/", "Dashboard", "grafico"),
    ("/campanhas", "IA SDR (campanhas)", "megafone"),
    ("/envios", "Envios", "enviar"),
    ("/fila", "Minha fila", "relogio"),
    ("/oportunidades", "Oportunidades", "fogo"),
    ("/prospeccao", "Prospecção", "lupa"),
    ("/leads", "Leads", "pessoas"),
    ("/agenda", "Agenda", "agenda"),
    ("/cadencias", "Cadências", "fluxo"),
    ("/parceiros", "Parceiros", "aperto"),
    ("/clientes", "Clientes", "predio"),
    ("/vencimentos", "Vencimentos", "relogio"),
    ("/vendas", "Vendas", "carrinho"),
    ("/comissoes", "Comissões", "moeda"),
    ("/relatorios", "Relatórios", "documento"),
    ("/inteligencia", "Inteligência", "alvo"),
    ("/ia", "IA Comercial", "brilho"),
    ("/conversas", "Conversas", "conversa"),
    ("/whatsapp", "WhatsApp", "celular"),
    ("/email", "E-mail", "carta"),
    ("/permissoes", "Permissões", "cadeado"),
    ("/configuracoes", "Configurações", "engrenagem"),
]
MENU_PARCEIRO = [
    ("/portal", "Meu painel", "grafico"),
    ("/portal/indicar", "Indicar cliente", "pessoas"),
    ("/portal/clientes", "Minha carteira", "predio"),
    ("/portal/vencimentos", "Vencimentos", "relogio"),
]


def avisar(request: Request, texto: str, tipo: str = "ok") -> None:
    avisos = request.session.get("avisos", [])
    avisos.append([tipo, texto])
    request.session["avisos"] = avisos[-5:]


def tela(request: Request, nome: str, contexto: dict | None = None, status_code: int = 200):
    usuario = getattr(request.state, "usuario", None)
    avisos_novos = 0
    mostrar_vendas = mostrar_agenda = False
    wl = {"disponivel": False, "conectado": False}
    if usuario and usuario.perfil != "parceiro":
        from sqlalchemy import func, select

        from .banco import FabricaSessao, ler_config
        from .modelos import Notificacao

        with FabricaSessao() as db:
            avisos_novos = db.execute(select(func.count(Notificacao.id)).where(
                Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False))).scalar() or 0
            mostrar_vendas = ler_config(db, "mostrar_vendas") == "1"
            mostrar_agenda = ler_config(db, "mostrar_agenda") == "1"
        from . import conexoes

        with FabricaSessao() as db:
            wl = conexoes.para_o_menu(db, usuario)
            db.commit()
    permissoes = autorizacao.efetivas(usuario) if usuario else {}
    menu = MENU_PARCEIRO if usuario and usuario.perfil == "parceiro" else MENU_EQUIPE
    dados = {
        "request": request,
        "usuario": usuario,
        "avisos_novos": avisos_novos,
        "wl": wl,
        "csrf": token_csrf(request),
        "avisos": request.session.pop("avisos", []),
        "menu": [m for m in menu if PERMISSAO_DO_MENU[m[0]] in permissoes] if usuario else [],
        # nas telas: {% if pode('leads.atribuir') %} (só esconde o botão; a rota confere de novo)
        "pode": lambda codigo: codigo in permissoes,
        "ve_tudo_em": lambda codigo: permissoes.get(codigo) == autorizacao.TUDO,
        "mostrar_vendas": mostrar_vendas,
        "mostrar_agenda": mostrar_agenda,
        "caminho": request.url.path,
        "hoje": date.today(),
    }
    dados.update(contexto or {})
    return modelos_html.TemplateResponse(request, nome, dados, status_code=status_code)


def voltar(destino: str) -> RedirectResponse:
    return RedirectResponse(destino, status_code=303)


def arquivo(conteudo: bytes, nome: str, tipo: str) -> Response:
    return Response(conteudo, media_type=tipo, headers={"Content-Disposition": f'attachment; filename="{nome}"'})


TIPOS_ARQUIVO = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
