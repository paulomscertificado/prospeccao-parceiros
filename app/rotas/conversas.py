"""Tela Conversas: as conversas do número conectado (todas) e envio de mensagem para qualquer número.

As mensagens vêm do WhatsApp Leads pela ponte (tabela mensagens_whatsapp, ver /api/ponte/retorno). O que se
escreve aqui vira um envio "manual" na fila da ponte (ponte_whatsapp.manual) e sai na hora pelo número,
como as respostas escritas na tela Conversas do WhatsApp Leads. Quem pediu SAIR não recebe.
"""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import config, sdr, util
from ..banco import agora, gravar_config, obter_db
from ..integracoes import whatsapp_leads
from ..leads_servico import historico
from ..modelos import ComandoWhatsApp, ContatoWhatsApp, MensagemWhatsApp, PonteWhatsApp, Usuario
from ..seguranca import equipe, verificar_csrf
from ..web import tela

rotas = APIRouter()


def _chave(telefone: str) -> str:
    """Chave da conversa: DDD + número, sem o 55 (números estrangeiros: só os dígitos)."""
    return util.normalizar_telefone(telefone) or util.so_digitos(telefone)


def _nomes_escolhidos(db: Session) -> dict[str, str]:
    return {c.telefone: c.nome for c in db.execute(select(ContatoWhatsApp)).scalars() if c.nome}


def _salvar_nome(db: Session, chave: str, nome: str, usuario: Usuario) -> None:
    """Guarda o nome aqui e pede ao WhatsApp Leads para trocar o nome do contato lá também."""
    nome = nome.strip()[:200]
    contato = db.get(ContatoWhatsApp, chave)
    if contato is None:
        db.add(ContatoWhatsApp(telefone=chave, nome=nome))
    else:
        contato.nome, contato.atualizado_em = nome, agora()
    if nome and config.WHATSAPP_PONTE:
        db.add(ComandoWhatsApp(acao="renomear_contato", usuario_id=usuario.id,
                               dados=json.dumps({"telefone": "55" + chave if len(chave) in (10, 11) else chave,
                                                 "nome": nome}, ensure_ascii=False)))


def _tela_vista(db: Session) -> None:
    gravar_config(db, "wl_tela_vista_em", agora().isoformat())  # a ponte troca a cada 3 s enquanto a tela está aberta
    db.commit()


@rotas.get("/conversas")
def tela_conversas(request: Request, telefone: str = "", usuario: Usuario = Depends(equipe),
                   db: Session = Depends(obter_db)):
    _tela_vista(db)
    return tela(request, "conversas.html", {"telefone_inicial": _chave(telefone) if telefone else "",
                                            "ponte": config.WHATSAPP_PONTE})


@rotas.get("/conversas/api/lista")
def lista(busca: str = "", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    _tela_vista(db)
    # Uma linha por contato, a conversa mais recente primeiro (pela data da mensagem: o histórico antigo chega depois)
    consulta = (select(MensagemWhatsApp.telefone, func.max(MensagemWhatsApp.criado_em).label("ultima_em"),
                       func.sum(((MensagemWhatsApp.direcao == "entrada") & MensagemWhatsApp.lida.is_(False))
                                .cast(MensagemWhatsApp.id.type)).label("nao_lidas"))
                .group_by(MensagemWhatsApp.telefone).order_by(func.max(MensagemWhatsApp.criado_em).desc()).limit(200))
    termo = busca.strip()
    if termo:
        filtros = [MensagemWhatsApp.nome.ilike(f"%{termo}%"),
                   MensagemWhatsApp.telefone.in_(select(ContatoWhatsApp.telefone)
                                                 .where(ContatoWhatsApp.nome.ilike(f"%{termo}%")))]
        if util.so_digitos(termo):
            filtros.append(MensagemWhatsApp.telefone.like(f"%{util.so_digitos(termo)}%"))
        consulta = consulta.where(or_(*filtros))
    resultado = []
    escolhidos = _nomes_escolhidos(db)
    for telefone, _ultima_em, nao_lidas in db.execute(consulta).all():
        m = db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.telefone == telefone)
                       .order_by(MensagemWhatsApp.criado_em.desc(), MensagemWhatsApp.id.desc()).limit(1)).scalars().first()
        nome = escolhidos.get(m.telefone) or m.nome or db.execute(select(MensagemWhatsApp.nome).where(MensagemWhatsApp.telefone == m.telefone,
                                                                         MensagemWhatsApp.nome != "")
                                    .order_by(MensagemWhatsApp.id.desc()).limit(1)).scalar() or ""
        resultado.append({"telefone": m.telefone, "telefone_formatado": util.formatar_telefone(m.telefone),
                          "nome": nome, "ultima": m.texto[:120], "ultima_direcao": m.direcao,
                          "quando": _quando_curto(m.criado_em), "nao_lidas": int(nao_lidas or 0)})
    return JSONResponse({"conversas": resultado, "situacao": _situacao()})


def _quando_curto(momento) -> str:
    """Como no WhatsApp: hora (hoje), "Ontem" ou a data."""
    hoje = agora().date()
    if momento.date() == hoje:
        return momento.strftime("%H:%M")
    if (hoje - momento.date()).days == 1:
        return "Ontem"
    return momento.strftime("%d/%m/%y")


def _situacao() -> dict:
    s = whatsapp_leads.status()
    return {"disponivel": bool(s.get("disponivel")), "conectado": bool(s.get("conectado")), "erro": s.get("erro", "")}


@rotas.get("/conversas/api/conversa/{telefone}")
def conversa(telefone: str, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    _tela_vista(db)
    chave = _chave(telefone)
    mensagens = list(db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.telefone == chave)
                                .order_by(MensagemWhatsApp.criado_em.desc(), MensagemWhatsApp.id.desc())
                                .limit(300)).scalars())[::-1]
    for m in [m for m in mensagens if m.direcao == "entrada" and not m.lida]:
        m.lida = True
    db.commit()
    pendentes = db.execute(select(PonteWhatsApp).where(PonteWhatsApp.manual.is_(True),
                                                       PonteWhatsApp.status.in_(["aguardando", "retirada"]))
                           .order_by(PonteWhatsApp.id)).scalars().all()
    lead = sdr.lead_pelo_telefone(db, chave)
    escolhido = db.get(ContatoWhatsApp, chave)
    nome = (escolhido.nome if escolhido and escolhido.nome else "") \
        or next((m.nome for m in reversed(mensagens) if m.nome), "") or (lead.responsavel or lead.empresa if lead else "")
    return JSONResponse({
        "telefone": chave, "telefone_formatado": util.formatar_telefone(chave), "nome": nome,
        "mensagens": [{"direcao": m.direcao, "texto": m.texto, "status": m.status, "erro": m.erro, "origem": m.origem,
                       "quando": m.criado_em.strftime("%d/%m %H:%M"), "dia": m.criado_em.strftime("%Y-%m-%d"),
                       "hora": m.criado_em.strftime("%H:%M")} for m in mensagens],
        "enviando": [{"texto": p.texto, "quando": p.criado_em.strftime("%d/%m %H:%M"),
                      "dia": p.criado_em.strftime("%Y-%m-%d"), "hora": p.criado_em.strftime("%H:%M")} for p in pendentes
                     if _chave(p.telefone) == chave],
        "lead": {"id": lead.id, "empresa": lead.empresa, "status": lead.status, "opt_out": lead.opt_out} if lead else None,
        "situacao": _situacao(),
    })


@rotas.post("/conversas/api/enviar", dependencies=[Depends(verificar_csrf)])
async def enviar(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    dados = await request.json()
    texto = str(dados.get("texto", "")).strip()
    chave = util.normalizar_telefone(str(dados.get("telefone", "")))
    if not chave:
        return JSONResponse({"erro": "Digite um celular com DDD, por exemplo (81) 99999-0000."}, status_code=400)
    if not texto:
        return JSONResponse({"erro": "Escreva a mensagem."}, status_code=400)
    if not config.WHATSAPP_PONTE:
        return JSONResponse({"erro": "Neste computador, use a tela Conversas do próprio WhatsApp Leads."}, status_code=400)
    lead = sdr.lead_pelo_telefone(db, chave)
    if lead and lead.opt_out:
        return JSONResponse({"erro": "Este contato pediu para não receber mensagens (opt-out)."}, status_code=409)
    nome = str(dados.get("nome", "")).strip()[:200] or (lead.responsavel or lead.empresa if lead else "")
    try:
        whatsapp_leads.enviar("55" + chave, nome, texto, db=db, manual=True, usuario_id=usuario.id)
    except whatsapp_leads.ErroWhatsAppLeads as erro:
        return JSONResponse({"erro": str(erro)}, status_code=409)
    if lead:
        historico(db, lead.id, "whatsapp", f"Mensagem enviada pela tela Conversas: {texto[:300]}", usuario, canal="whatsapp")
    if str(dados.get("nome", "")).strip() and not db.get(ContatoWhatsApp, chave):
        _salvar_nome(db, chave, str(dados["nome"]), usuario)  # nome digitado na "Nova mensagem"
    db.commit()
    aviso = "" if whatsapp_leads.status().get("conectado") else "O celular está desconectado: a mensagem sai quando conectar."
    return {"ok": True, "telefone": chave, "aviso": aviso}


@rotas.post("/conversas/api/nome", dependencies=[Depends(verificar_csrf)])
async def editar_nome(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    """Editar o nome do contato (vale na tela Conversas e no WhatsApp Leads)."""
    dados = await request.json()
    chave = _chave(str(dados.get("telefone", "")))
    nome = str(dados.get("nome", "")).strip()
    if not chave:
        return JSONResponse({"erro": "Contato sem telefone."}, status_code=400)
    if not nome:
        return JSONResponse({"erro": "Digite o nome do contato."}, status_code=400)
    _salvar_nome(db, chave, nome, usuario)
    db.commit()
    return {"ok": True, "nome": nome[:200]}
