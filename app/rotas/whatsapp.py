"""Tela WhatsApp: cada pessoa conecta o PRÓPRIO número; o dono (ou o administrador) pode compartilhar.

Os números ficam ligados no computador da MS (WhatsApp Leads, um conector por número; ver app/conexoes.py).
Na nuvem, cada botão vira um pedido (tabela comandos_whatsapp, com o id do número) que o WhatsApp Leads busca
pela ponte; a situação e o QR code de cada número voltam pela ponte. Enquanto esta tela está aberta, a ponte
troca a cada 3 segundos (ver /api/ponte/troca).
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import autorizacao, config, conexoes
from ..banco import agora, gravar_config, obter_db
from ..integracoes import whatsapp_leads
from ..modelos import ComandoWhatsApp, ConexaoWhatsApp, Usuario
from ..seguranca import exige, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()

ACOES = {"conectar": "Conectar", "pausar": "Pausar conexão", "desligar": "Desligar o número",
         "remover": "Remover o número", "salvar_regras": "Salvar regras de envio", "renomear_contato": "Renomear contato"}


def _cartao(db: Session, usuario: Usuario, c: ConexaoWhatsApp, base: dict, nomes: dict[int, str]) -> dict:
    return {"id": c.id, "nome": c.nome, "dono": nomes.get(c.dono_id, ""), "minha": c.dono_id == usuario.id,
            "principal": c.id == conexoes.PRINCIPAL, "gerenciar": conexoes.pode_gerenciar(usuario, c),
            "compartilhar": conexoes.pode_compartilhar(usuario, c),
            "compartilhada_todos": c.compartilhada_todos, "compartilhada_com": conexoes.compartilhada_com(c),
            "situacao": conexoes.situacao(c.id, base)}


def _estado(db: Session, usuario: Usuario) -> dict:
    """Situação para a tela (e para a atualização automática a cada 3 s)."""
    gravar_config(db, "wl_tela_vista_em", agora().isoformat())  # a ponte passa a trocar a cada 3 s
    db.commit()
    base = whatsapp_leads.status(usar_cache=False)
    nomes = {u.id: u.nome for u in db.execute(select(Usuario)).scalars()}
    lista = (conexoes.todas(db) if autorizacao.pode(usuario, "whatsapp.compartilhar_todos")
             else conexoes.acessiveis(db, usuario))  # quem compartilha os números de todos vê todos
    cartoes = [_cartao(db, usuario, c, base, nomes) for c in lista]
    ultimo = db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.usuario_id == usuario.id)
                        .order_by(ComandoWhatsApp.id.desc()).limit(1)).scalars().first()
    pedido = None
    if ultimo and ultimo.acao != "renomear_contato" and (agora() - ultimo.criado_em).total_seconds() < 600:
        pedido = {"acao": ACOES.get(ultimo.acao, ultimo.acao), "status": ultimo.status, "erro": ultimo.erro,
                  "numero": json.loads(ultimo.dados or "{}").get("conexao", conexoes.PRINCIPAL)}
    db.commit()
    return {"ponte": config.WHATSAPP_PONTE, "computador": {"disponivel": bool(base.get("disponivel")),
                                                            "erro": base.get("erro", "")},
            "minha_id": conexoes.id_do_usuario(usuario.id), "numeros": cartoes, "pedido": pedido,
            "regras": base.get("regras") or {}}


@rotas.get("/whatsapp")
def tela_whatsapp(request: Request, usuario: Usuario = Depends(exige("whatsapp.ver")), db: Session = Depends(obter_db)):
    estado = _estado(db, usuario)
    equipe_ = [{"id": u.id, "nome": u.nome} for u in db.execute(
        select(Usuario).where(Usuario.perfil != "parceiro", Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars()]
    return tela(request, "whatsapp.html", {"estado": estado, "regras": estado["regras"], "equipe": equipe_,
                                           "url_local": config.WHATSAPP_LEADS_URL + "/whatsapp"})


@rotas.get("/whatsapp/estado")
def estado_whatsapp(usuario: Usuario = Depends(exige("whatsapp.ver")), db: Session = Depends(obter_db)):
    return JSONResponse(_estado(db, usuario))


@rotas.post("/whatsapp/comando", dependencies=[Depends(verificar_csrf)])
async def comando_whatsapp(request: Request, acao: str = Form(...), numero: str = Form(""),
                           usuario: Usuario = Depends(exige("whatsapp.ver")), db: Session = Depends(obter_db)):
    if not config.WHATSAPP_PONTE:
        avisar(request, "Neste computador, use a tela WhatsApp do próprio WhatsApp Leads.", "alerta")
        return voltar("/whatsapp")
    if acao not in ACOES or acao == "renomear_contato":
        avisar(request, "Pedido desconhecido.", "erro")
        return voltar("/whatsapp")
    form = await request.form()
    dados: dict = {}
    if acao == "salvar_regras":
        if not autorizacao.pode(usuario, "whatsapp.regras"):
            avisar(request, "Só o administrador muda as regras de envio.", "erro")
            return voltar("/whatsapp")
        dados = {c: str(form.get(c, "")).strip() for c in ("intervalo_min_seg", "intervalo_max_seg", "limite_diario",
                                                            "horario_inicio", "horario_fim", "palavras_sair")}
        try:
            minimo, maximo, limite = (int(dados["intervalo_min_seg"]), int(dados["intervalo_max_seg"]),
                                      int(dados["limite_diario"]))
        except ValueError:
            avisar(request, "Use só números nas pausas e no limite diário.", "erro")
            return voltar("/whatsapp")
        if minimo < 1 or maximo < minimo or limite < 1:
            avisar(request, "A pausa máxima precisa ser maior ou igual à mínima.", "erro")
            return voltar("/whatsapp")
    else:
        # "meu" = o número da própria pessoa (criado na primeira conexão)
        if numero in ("", "meu"):
            c = conexoes.minha(db, usuario, criar=acao == "conectar")
        else:
            c = db.get(ConexaoWhatsApp, numero)
        if c is None or not conexoes.pode_gerenciar(usuario, c):
            avisar(request, "Só o dono do número (ou o administrador) pode fazer isso.", "erro")
            return voltar("/whatsapp")
        if acao == "remover" and c.id == conexoes.PRINCIPAL:
            avisar(request, "O número principal da MS não pode ser removido (use Desligar).", "erro")
            return voltar("/whatsapp")
        dados = {"conexao": c.id}
        if acao == "conectar":
            dados["tipo"] = "teste" if form.get("tipo") == "teste" else "qr"
        if acao == "remover":
            db.delete(c)
    db.add(ComandoWhatsApp(acao=acao, dados=json.dumps(dados, ensure_ascii=False), usuario_id=usuario.id))
    registrar_log(db, usuario, "whatsapp_" + acao, "whatsapp", None, json.dumps(dados, ensure_ascii=False)[:200], request)
    db.commit()
    if not whatsapp_leads.status(usar_cache=False).get("disponivel"):
        avisar(request, "Pedido guardado. Ele será feito quando o computador com o WhatsApp Leads ligar.", "alerta")
    else:
        avisar(request, f"{ACOES[acao]}: pedido enviado ao computador do WhatsApp. Leva alguns segundos.")
    return voltar("/whatsapp")


@rotas.post("/whatsapp/compartilhar", dependencies=[Depends(verificar_csrf)])
async def compartilhar(request: Request, numero: str = Form(...), usuario: Usuario = Depends(exige("whatsapp.ver")),
                       db: Session = Depends(obter_db)):
    """Compartilhar um número com toda a equipe ou com pessoas escolhidas (o dono, o administrador e o gestor)."""
    c = db.get(ConexaoWhatsApp, numero)
    if c is None or not conexoes.pode_compartilhar(usuario, c):
        avisar(request, "Só o dono do número, o administrador ou o gestor podem compartilhar.", "erro")
        return voltar("/whatsapp")
    form = await request.form()
    ids = sorted({int(i) for i in form.getlist("usuarios") if str(i).isdigit() and int(i) != c.dono_id})
    c.compartilhada_todos = form.get("todos") == "on"
    c.compartilhada_com = json.dumps(ids)
    nome = str(form.get("nome", "")).strip()
    if nome:
        c.nome = nome[:120]
    registrar_log(db, usuario, "whatsapp_compartilhar", "whatsapp", None,
                  f"{c.id}: todos={c.compartilhada_todos} usuarios={ids}", request)
    db.commit()
    avisar(request, "Compartilhamento salvo." if (c.compartilhada_todos or ids) else "Número não compartilhado: só o dono usa.")
    return voltar("/whatsapp")
