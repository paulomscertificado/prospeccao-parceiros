"""Tela WhatsApp: a mesma da do WhatsApp Leads (situação, QR code, modo teste, pausar, desligar, regras de envio).

A conexão continua rodando no computador da MS (WhatsApp Leads). Na nuvem, cada botão vira um pedido
(tabela comandos_whatsapp) que o WhatsApp Leads busca pela ponte; o status e o QR code voltam pela ponte.
Enquanto esta tela está aberta, a ponte troca a cada 3 segundos (ver /api/ponte/troca).
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..banco import agora, gravar_config, obter_db
from ..integracoes import whatsapp_leads
from ..modelos import ComandoWhatsApp, Usuario
from ..seguranca import admin, equipe, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()

ACOES = {"conectar": "Conectar", "pausar": "Pausar conexão", "desligar": "Desligar este número",
         "salvar_regras": "Salvar regras de envio"}


def _estado(db: Session) -> dict:
    """Situação para a tela (e para a atualização automática a cada 3 s)."""
    gravar_config(db, "wl_tela_vista_em", agora().isoformat())  # a ponte passa a trocar a cada 3 s
    db.commit()
    situacao = whatsapp_leads.status(usar_cache=False)
    ultimos = db.execute(select(ComandoWhatsApp).order_by(ComandoWhatsApp.id.desc()).limit(1)).scalars().first()
    pedido = None
    if ultimos and (agora() - ultimos.criado_em).total_seconds() < 600:
        pedido = {"acao": ACOES.get(ultimos.acao, ultimos.acao), "status": ultimos.status, "erro": ultimos.erro}
    return {"ponte": config.WHATSAPP_PONTE, "situacao": situacao, "pedido": pedido}


@rotas.get("/whatsapp")
def tela_whatsapp(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    estado = _estado(db)
    regras = estado["situacao"].get("regras") or {}
    return tela(request, "whatsapp.html", {"estado": estado, "regras": regras,
                                           "url_local": config.WHATSAPP_LEADS_URL + "/whatsapp"})


@rotas.get("/whatsapp/estado")
def estado_whatsapp(usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    return JSONResponse(_estado(db))


@rotas.post("/whatsapp/comando", dependencies=[Depends(verificar_csrf)])
async def comando_whatsapp(request: Request, acao: str = Form(...), usuario: Usuario = Depends(admin),
                           db: Session = Depends(obter_db)):
    if not config.WHATSAPP_PONTE:
        avisar(request, "Neste computador, use a tela WhatsApp do próprio WhatsApp Leads.", "alerta")
        return voltar("/whatsapp")
    if acao not in ACOES:
        avisar(request, "Pedido desconhecido.", "erro")
        return voltar("/whatsapp")
    form = await request.form()
    dados: dict = {}
    if acao == "conectar":
        dados["tipo"] = "qr" if form.get("tipo") == "qr" else "teste"
    elif acao == "salvar_regras":
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
    db.add(ComandoWhatsApp(acao=acao, dados=json.dumps(dados, ensure_ascii=False), usuario_id=usuario.id))
    registrar_log(db, usuario, "whatsapp_" + acao, "whatsapp", None, json.dumps(dados, ensure_ascii=False)[:200], request)
    db.commit()
    if not whatsapp_leads.status(usar_cache=False).get("disponivel"):
        avisar(request, "Pedido guardado. Ele será feito quando o computador com o WhatsApp Leads ligar.", "alerta")
    else:
        avisar(request, f"{ACOES[acao]}: pedido enviado ao computador do WhatsApp. Leva alguns segundos.")
    return voltar("/whatsapp")
