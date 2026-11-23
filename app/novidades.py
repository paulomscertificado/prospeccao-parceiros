"""Avisos como no WhatsApp (pedido da Maria em 23/11/2026: "replique o funcionamento de notificações do WhatsApp para o
sistema, além de que adicione esse som para quando alguém responder em alguma conversa ou algum disparo de alguma
campanha"). Aqui ficam os números vermelhos do menu e o que chegou de novo desde a última olhada do navegador; o
static/notificacoes.js usa isso para atualizar o menu sem recarregar, pôr o número no título da aba, tocar o som
(static/sons/notificacao.wav) e mostrar o aviso na tela do computador.

A sessão já enxerga só a AR de quem vê (isolamento) e cada parte só vale para quem tem a permissão da tela:
- conversa: mensagem recebida, ainda não lida, num número cujas conversas a pessoa vê (conexoes.acessiveis);
- oficial: mensagem recebida no número da API oficial da AR;
- resposta: aviso do sininho de resposta a uma campanha (sdr.notificar, link para as Oportunidades).
"""

from urllib.parse import urlencode

from sqlalchemy import func, select

from . import autorizacao, conexoes, util
from .modelos import (ContaWhatsAppOficial, ContatoWhatsApp, Lead, MensagemOficial, MensagemWhatsApp, Notificacao,
                      Oportunidade)

MAXIMO = 5  # novidades de cada tipo por pergunta (as mais antigas; com mais que isso, o som e o menu já avisam)
SEM_FILTRO = {"sem_filtro_de_ar": True}
# Chave de cada tipo no que o navegador guarda ("até onde eu já vi")
CHAVES = {"conversa": "c", "oficial": "o", "resposta": "n"}


def tem_api_oficial(db) -> bool:
    """A AR de quem vê tem a API oficial configurada (o item "API Oficial" do menu só aparece nela)."""
    return db.execute(select(ContaWhatsAppOficial.id).where(ContaWhatsAppOficial.token_cripto != "")
                      .limit(1)).first() is not None


def contadores(db, usuario, numeros: list[str] | None = None) -> dict[str, int]:
    """Os números vermelhos do menu (só os das telas que a pessoa vê) e os avisos do sininho dela. `numeros` = os ids
    dos números de WhatsApp que ela vê, se já estiverem à mão."""
    r = {"avisos": db.execute(select(func.count(Notificacao.id)).where(  # os da pessoa, de qualquer AR
        Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False)).execution_options(**SEM_FILTRO)).scalar() or 0}
    if autorizacao.pode(usuario, "oportunidades.ver"):
        # as novas da AR de quem vê, a mesma conta da aba "Novas" (19/11/2026)
        r["oportunidades"] = db.execute(select(func.count(Oportunidade.id)).join(
            Lead, Oportunidade.lead_id == Lead.id).where(Oportunidade.status == "nova")).scalar() or 0
    if autorizacao.pode(usuario, "oficial.ver") and tem_api_oficial(db):
        r["oficial"] = db.execute(select(func.count(MensagemOficial.id)).where(
            MensagemOficial.direcao == "entrada", MensagemOficial.lida.is_(False))).scalar() or 0
    if autorizacao.pode(usuario, "conversas.ver"):
        r["conversas"] = (conexoes.mensagens_nao_lidas(db, usuario) if numeros is None
                          else _nao_lidas_nos_numeros(db, numeros))
    return r


def _nao_lidas_nos_numeros(db, numeros: list[str]) -> int:
    if not numeros:
        return 0
    return db.execute(select(func.count(MensagemWhatsApp.id)).where(
        MensagemWhatsApp.conexao.in_(numeros), MensagemWhatsApp.direcao == "entrada",
        MensagemWhatsApp.lida == False)).scalar() or 0  # noqa: E712  (usa o índice das não lidas)


def ultimos(db) -> dict[str, int]:
    """O maior id de cada tipo (pelo índice principal, sem passar pelas linhas): até onde o navegador já viu."""
    return {"c": db.execute(select(func.max(MensagemWhatsApp.id)).execution_options(**SEM_FILTRO)).scalar() or 0,
            "o": db.execute(select(func.max(MensagemOficial.id)).execution_options(**SEM_FILTRO)).scalar() or 0,
            "n": db.execute(select(func.max(Notificacao.id)).execution_options(**SEM_FILTRO)).scalar() or 0}


def _curto(texto: str, limite: int = 140) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "…"


def resumo(db, usuario, desde: dict[str, int] | None = None) -> dict:
    """Para o navegador: os contadores, até onde ele já viu e as novidades depois de `desde` ({"c", "o", "n"}; sem
    `desde`, a primeira pergunta: só os contadores e o ponto de partida, sem avisar o que já estava lá)."""
    numeros = ([c.id for c in conexoes.acessiveis(db, usuario)] if autorizacao.pode(usuario, "conversas.ver")
               else [])
    conta = contadores(db, usuario, numeros)
    novas: list[dict] = []
    desde = desde or {}
    if "conversas" in conta and numeros and "c" in desde:
        linhas = db.execute(select(MensagemWhatsApp).where(
            MensagemWhatsApp.id > desde["c"], MensagemWhatsApp.conexao.in_(numeros),
            MensagemWhatsApp.direcao == "entrada", MensagemWhatsApp.lida == False)  # noqa: E712
            .order_by(MensagemWhatsApp.id).limit(MAXIMO)).scalars().all()
        nomes = dict(db.execute(select(ContatoWhatsApp.telefone, ContatoWhatsApp.nome).where(
            ContatoWhatsApp.telefone.in_({m.telefone for m in linhas}), ContatoWhatsApp.nome != "")).all()) if linhas else {}
        for m in linhas:
            novas.append({"tipo": "conversa", "id": m.id, "chave": f"conversa-{m.conexao}-{m.telefone}",
                          "titulo": nomes.get(m.telefone) or m.nome or util.formatar_telefone(m.telefone),
                          "texto": _curto(m.texto) or "Mensagem nova", "telefone": m.telefone, "numero": m.conexao,
                          "link": "/conversas?" + urlencode({"telefone": m.telefone, "numero": m.conexao})})
    if "oficial" in conta and "o" in desde:
        for m in db.execute(select(MensagemOficial).where(
                MensagemOficial.id > desde["o"], MensagemOficial.direcao == "entrada", MensagemOficial.lida.is_(False))
                .order_by(MensagemOficial.id).limit(MAXIMO)).scalars():
            novas.append({"tipo": "oficial", "id": m.id, "chave": f"oficial-{m.telefone}",
                          "titulo": (m.nome or util.formatar_telefone(m.telefone)) + " · número oficial",
                          "texto": _curto(m.texto) or "Mensagem nova", "telefone": m.telefone, "numero": "",
                          "link": "/oficial?" + urlencode({"telefone": m.telefone})})
    if "n" in desde:  # resposta a uma campanha: o aviso do sininho que leva às Oportunidades
        for n in db.execute(select(Notificacao).where(
                Notificacao.usuario_id == usuario.id, Notificacao.id > desde["n"], Notificacao.lida.is_(False),
                Notificacao.link.like("/oportunidades%")).order_by(Notificacao.id).limit(MAXIMO)
                .execution_options(**SEM_FILTRO)).scalars():
            novas.append({"tipo": "resposta", "id": n.id, "chave": f"resposta-{n.id}", "titulo": "Resposta de campanha",
                          "texto": _curto(n.texto), "telefone": "", "numero": "", "link": n.link})
    return {"contadores": conta, "ultimos": ultimos(db), "novas": novas}
