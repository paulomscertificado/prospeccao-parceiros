"""Tela Minha fila: os disparos da pessoa num lugar só. O que está na fila do WhatsApp agora, o que ainda vai sair
(e por que ainda não saiu), o que saiu ou falhou e o registro (log) dos disparos. Cada um vê os próprios; admin e
gestor podem ver a fila de outra pessoa ou da equipe toda."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import campanhas, config, mensagens, sdr, util
from ..banco import agora, ler_config, obter_db
from ..modelos import Campanha, Lead, LogAuditoria, Mensagem, Tarefa, Usuario
from ..seguranca import equipe, ve_tudo
from ..web import tela
from .envios import STATUS_ENVIO

rotas = APIRouter()


def _motivo_pendente(db, t: Tarefa, hoje: date, no_horario: bool, liberados: dict[int, bool]) -> str:
    """Por que o toque ainda não saiu, em linguagem simples."""
    lead = t.lead
    if t.data > hoje:
        return f"Programado para {t.data:%d/%m}"
    if not lead or not sdr.automacao_ativa(lead):
        return "Automação parada para este lead (respondeu, opt-out ou está com alguém)"
    if t.canal == "email":
        if not lead.email:
            return "Sem e-mail cadastrado"
        if ler_config(db, "enviar_email_automatico") != "1":
            return "Envio automático de e-mail desligado: use Disparar campanha e-mail"
        return "Aguardando o horário de envio" if not no_horario else "Sai na próxima rodada da fila (a cada minuto)"
    if not (lead.whatsapp or campanhas.celular_do_lead(lead)):
        return "Sem WhatsApp: pesquise o número na campanha"
    if lead.id not in liberados:
        liberados[lead.id] = campanhas.whatsapp_liberado(db, lead)
    if liberados[lead.id] and ler_config(db, "enviar_whatsapp_automatico") == "1":
        return "Sai sozinho (contato já conversou com a MS)" if no_horario else "Aguardando o horário de envio"
    return "Aguardando seu clique (WhatsApp de hoje ou Disparar campanha WhatsApp)"


@rotas.get("/fila")
def minha_fila(request: Request, de: str = "", canal: str = "", usuario: Usuario = Depends(equipe),
               db: Session = Depends(obter_db)):
    hoje = date.today()
    alvo_id = usuario.id
    if ve_tudo(usuario) and de:
        alvo_id = None if de == "todos" else (util.para_int(de) or usuario.id)

    def do_alvo_tarefa(q):
        if alvo_id is None:
            return q
        return q.where(or_(Campanha.usuario_id == alvo_id, Lead.vendedor_id == alvo_id))

    def do_alvo_mensagem(q):
        if alvo_id is None:
            return q
        return q.where(or_(Mensagem.usuario_id == alvo_id, Lead.vendedor_id == alvo_id, Campanha.usuario_id == alvo_id))

    canais = [canal] if canal in ("email", "whatsapp") else ["email", "whatsapp"]

    # 1) Pendentes: toques das campanhas ativas que ainda não saíram (atrasados, hoje e próximos 7 dias)
    pend_q = (select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id).outerjoin(Lead, Tarefa.lead_id == Lead.id)
              .where(Tarefa.status == "pendente", Tarefa.canal.in_(canais), Campanha.status == "ativa",
                     Tarefa.data <= hoje + timedelta(days=7)))
    pendentes = db.execute(do_alvo_tarefa(pend_q).order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(300)).scalars().all()
    no_horario = mensagens.dentro_do_horario(db)
    liberados: dict[int, bool] = {}
    pendentes = [{"t": t, "motivo": _motivo_pendente(db, t, hoje, no_horario, liberados),
                  "atrasado": t.data < hoje} for t in pendentes]

    # 2) Na fila do WhatsApp agora e 3) histórico (últimos 7 dias): saiu, falhou, foi lida...
    desde = agora().replace(hour=0, minute=0, second=0) - timedelta(days=7)
    msg_q = (select(Mensagem).outerjoin(Lead, Mensagem.lead_id == Lead.id)
             .outerjoin(Campanha, Mensagem.campanha_id == Campanha.id)
             .where(Mensagem.canal.in_(canais), Mensagem.status != "recebida", Mensagem.criado_em >= desde))
    envios = db.execute(do_alvo_mensagem(msg_q).order_by(Mensagem.criado_em.desc(), Mensagem.id.desc())
                        .limit(300)).scalars().all()
    na_fila = [m for m in envios if m.status == "na_fila"]
    historico = [m for m in envios if m.status != "na_fila"]

    # 4) Log dos disparos e testes feitos pela pessoa
    log_q = select(LogAuditoria).where(or_(LogAuditoria.acao.like("disparou_campanha%"),
                                           LogAuditoria.acao == "testou_campanha"),
                                       LogAuditoria.criado_em >= agora() - timedelta(days=30))
    if alvo_id is not None:
        log_q = log_q.where(LogAuditoria.usuario_id == alvo_id)
    logs = db.execute(log_q.order_by(LogAuditoria.criado_em.desc()).limit(50)).scalars().all()

    inicio_hoje = agora().replace(hour=0, minute=0, second=0)
    resumo = {
        "hoje": sum(1 for p in pendentes if p["t"].data <= hoje),
        "atrasados": sum(1 for p in pendentes if p["atrasado"]),
        "na_fila": len(na_fila),
        "enviadas_hoje": sum(1 for m in historico if m.criado_em >= inicio_hoje and m.status != "falhou"),
        "falharam": sum(1 for m in historico if m.status == "falhou"),
        "email_hoje": mensagens.enviadas_hoje(db, "email"), "email_limite": mensagens.limite_diario(db, "email"),
        "whats_hoje": mensagens.enviadas_hoje(db, "whatsapp"), "whats_limite": mensagens.limite_diario(db, "whatsapp"),
    }
    ids = {m.lead_id for m in envios if m.lead_id}
    leads_por_id = {l.id: l for l in db.execute(select(Lead).where(Lead.id.in_(ids))).scalars()} if ids else {}
    nomes_camp = {c.id: c.nome for c in db.execute(select(Campanha)).scalars()}
    pessoas = db.execute(select(Usuario).where(Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars().all() \
        if ve_tudo(usuario) else []
    return tela(request, "fila.html", {
        "pendentes": pendentes, "na_fila": na_fila, "historico": historico, "logs": logs, "resumo": resumo,
        "leads_por_id": leads_por_id, "nomes_camp": nomes_camp, "STATUS_ENVIO": STATUS_ENVIO, "hoje": hoje,
        "no_horario": no_horario, "pessoas": pessoas, "filtro_de": "todos" if alvo_id is None else str(alvo_id),
        "filtro_canal": canal, "horario": (ler_config(db, "horario_envio_inicio"), ler_config(db, "horario_envio_fim")),
        "CANAIS": config.CANAIS,
    })
