"""Apoio às telas: modelos HTML (Jinja2), avisos ("flash") e respostas comuns."""

import json
from datetime import date, datetime
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


def _lista_de_mudancas(texto: str) -> list:
    """O "antes e depois" do registro de atividades (JSON {campo: [antes, depois]}) para a tela."""
    if not texto:
        return []
    try:
        return [(campo, antes, depois) for campo, (antes, depois) in json.loads(texto).items()]
    except (ValueError, TypeError):
        return []


f["mudancas"] = _lista_de_mudancas
modelos_html.env.globals.update(config=config, CANAIS=config.CANAIS, PERFIS=config.PERFIS)

# Cada item aparece só para quem tem a permissão (e com o módulo ligado). A proteção de verdade é a da rota.
PERMISSAO_DO_MENU = {
    "/": "painel.ver", "/campanhas": "campanhas.ver", "/envios": "envios.ver", "/fila": "fila.ver",
    "/oportunidades": "oportunidades.ver", "/empresas-novas": "campanhas.configurar", "/renovacao": "campanhas.configurar", "/prospeccao": "prospeccao.buscar", "/assertiva": "assertiva.consultar", "/leads": "leads.ver",
    "/agenda": "agenda.ver", "/cadencias": "cadencias.ver", "/parceiros": "parceiros.ver", "/clientes": "clientes.ver",
    "/vencimentos": "vencimentos.ver", "/vendas": "vendas.ver", "/comissoes": "comissoes.ver",
    "/relatorios": "relatorios.ver", "/inteligencia": "inteligencia.ver", "/ia": "ia.usar", "/conversas": "conversas.ver", "/oficial": "oficial.ver",
    "/whatsapp": "whatsapp.ver", "/email": "email.ver", "/permissoes": "permissoes.gerenciar",
    "/configuracoes": "configuracoes.ver",
    "/portal": "portal.usar", "/portal/indicar": "portal.usar", "/portal/clientes": "portal.usar",
    "/portal/vencimentos": "portal.usar",
}
DENTRO_DAS_CONFIGURACOES = {"/permissoes", "/whatsapp", "/email"}  # no menu lateral só para quem não vê as Configurações
MENU_EQUIPE = [
    ("/", "Dashboard", "grafico"),
    ("/campanhas", "IA SDR (campanhas)", "megafone"),
    ("/empresas-novas", "Empresas novas", "predio"),
    ("/renovacao", "Renovação", "agenda"),
    ("/envios", "Envios", "enviar"),
    ("/fila", "Minha fila", "relogio"),
    ("/oportunidades", "Oportunidades", "fogo"),
    ("/prospeccao", "Prospecção", "lupa"),
    ("/assertiva", "Consulta Assertiva", "lupa"),
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
    ("/oficial", "API Oficial", "selo"),
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
    avisos_novos = oportunidades_novas = oficial_nao_lidas = conversas_nao_lidas = 0
    tem_api_oficial = False
    mostrar_vendas = mostrar_agenda = False
    wl = {"disponivel": False, "conectado": False}
    if usuario and usuario.perfil != "parceiro":
        from sqlalchemy import func, select

        from .banco import FabricaSessao, ler_config
        from .modelos import Notificacao

        with FabricaSessao() as db:
            from .banco import usar_config_da_ar

            usar_config_da_ar(db, request.session.get("ar_entrada") if usuario.master else usuario.tenant_id)
            avisos_novos = db.execute(select(func.count(Notificacao.id)).where(
                Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False))).scalar() or 0
            mostrar_vendas = ler_config(db, "mostrar_vendas") == "1"
            mostrar_agenda = ler_config(db, "mostrar_agenda") == "1"
            from . import isolamento

            isolamento.ligar(db, usuario, request.session.get("ar_entrada") if usuario.master else None)  # a AR de quem vê
            if autorizacao.pode(usuario, "oportunidades.ver"):
                # O número do menu Oportunidades: as novas da AR de quem vê, a mesma conta da aba "Novas" (antes eram
                # os avisos não lidos do sininho, que já estão em "Avisos (N)" no rodapé: no Grupo Certy o menu dizia 6
                # e a tela, 0 novas; pedido da Maria em 19/11/2026)
                from .modelos import Lead, Oportunidade

                oportunidades_novas = db.execute(select(func.count(Oportunidade.id)).join(
                    Lead, Oportunidade.lead_id == Lead.id).where(Oportunidade.status == "nova")).scalar() or 0
            if autorizacao.pode(usuario, "oficial.ver"):
                # Item "API Oficial" (21/11/2026): só na AR que tem a API oficial; o número vermelho = mensagens novas
                from .modelos import ContaWhatsAppOficial, MensagemOficial

                tem_api_oficial = db.execute(select(ContaWhatsAppOficial.id).where(
                    ContaWhatsAppOficial.token_cripto != "").limit(1)).first() is not None
                if tem_api_oficial:
                    oficial_nao_lidas = db.execute(select(func.count(MensagemOficial.id)).where(
                        MensagemOficial.direcao == "entrada", MensagemOficial.lida.is_(False))).scalar() or 0
            if autorizacao.pode(usuario, "conversas.ver"):
                # Item "Conversas" (23/11/2026, pedido da Maria: "assim como oportunidades tem um contador"): as
                # mensagens recebidas não lidas nos números que a pessoa vê (a soma dos números da lista da tela)
                from . import conexoes

                conversas_nao_lidas = conexoes.mensagens_nao_lidas(db, usuario)
        from . import conexoes

        with FabricaSessao() as db:
            wl = conexoes.para_o_menu(db, usuario)
            db.commit()
    from . import marca
    from .banco import FabricaSessao as _Fabrica

    with _Fabrica() as db:  # white label, Fase 5: a marca da AR de quem vê (antes de entrar: a plataforma, neutra)
        marca_tela = marca.da_tela(request, usuario, db)
    permissoes = autorizacao.efetivas(usuario) if usuario else {}
    menu = MENU_PARCEIRO if usuario and usuario.perfil == "parceiro" else MENU_EQUIPE
    dados = {
        "request": request,
        "usuario": usuario,
        "ar_entrada_nome": request.session.get("ar_entrada_nome", "") if usuario and usuario.master else "",
        "ar_entrada_ate": request.session.get("ar_entrada_ate") if usuario and usuario.master else None,
        "hora_de": lambda segundos: datetime.fromtimestamp(segundos).strftime("%H:%M"),
        "avisos_novos": avisos_novos,
        "oportunidades_novas": oportunidades_novas,
        "oficial_nao_lidas": oficial_nao_lidas,
        "conversas_nao_lidas": conversas_nao_lidas,
        "wl": wl,
        "csrf": token_csrf(request),
        "avisos": request.session.pop("avisos", []),
        # Permissões, WhatsApp e E-mail ficam dentro de Configurações; no menu lateral só para quem não vê as Configurações
        "menu": [m for m in menu if PERMISSAO_DO_MENU[m[0]] in permissoes
                 and not (m[0] in DENTRO_DAS_CONFIGURACOES and "configuracoes.ver" in permissoes)
                 and (m[0] != "/oficial" or tem_api_oficial)] if usuario else [],
        # nas telas: {% if pode('leads.atribuir') %} (só esconde o botão; a rota confere de novo)
        "pode": lambda codigo: codigo in permissoes,
        "ve_tudo_em": lambda codigo: permissoes.get(codigo) == autorizacao.TUDO,
        # filtro "de quem": quem alcança registros de outras pessoas (tudo, quem está abaixo ou a equipe)
        "escolhe_de_quem": lambda codigo: autorizacao.escolhe_de_quem(usuario, codigo),
        "mostrar_vendas": mostrar_vendas,
        "mostrar_agenda": mostrar_agenda,
        "caminho": request.url.path,
        "hoje": date.today(),
        # {{ marca.curto }}, {{ marca.frase('com') }} ("com a MS", "com o Grupo Certy"), {{ marca.logo_url }}...
        "marca": marca_tela,
        # textos do sistema escritos com o nome da MS (ex.: exemplos dos tons): com a empresa de quem vê
        "com_marca": lambda texto: marca.aplicar(texto, usuario, marca_tela["ar"]) if marca_tela["ar"] else texto,
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
