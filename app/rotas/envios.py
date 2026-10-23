"""Tela Envios: o que já saiu (e-mail e WhatsApp), para quem, quando e como está; o que vai sair; e como funcionam
os disparos (com os limites de Configurações). Cada um vê os envios dos próprios leads; admin e gestor veem todos."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import config, mensagens, util
from ..banco import agora, ler_config, obter_db
from ..modelos import Campanha, Lead, Mensagem, Tarefa, Usuario
from ..seguranca import equipe
from ..web import tela

rotas = APIRouter()

STATUS_ENVIO = {"na_fila": ("Na fila", "selo-azul"), "enviada": ("Enviada", "selo-ok"), "entregue": ("Entregue", "selo-ok"),
                "lida": ("Lida", "selo-ok"), "falhou": ("Não saiu", "selo-erro"), "copiada": ("Copiada (envio manual)", ""),
                "recebida": ("Resposta recebida", "selo-alerta")}
PERIODOS = {"hoje": ("Hoje", 0), "7d": ("7 dias", 7), "30d": ("30 dias", 30), "90d": ("90 dias", 90)}


def _so_dele(consulta, usuario: Usuario):
    """Funcionário/vendedor: só os envios dos próprios leads (ou feitos por ele)."""
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        return consulta.where(or_(Lead.vendedor_id == usuario.id, Mensagem.usuario_id == usuario.id))
    return consulta


@rotas.get("/envios")
def tela_envios(request: Request, canal: str = "", status: str = "", campanha: str = "", periodo: str = "7d",
                lead: str = "", busca: str = "", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    hoje = date.today()
    dias = PERIODOS.get(periodo, PERIODOS["7d"])[1]
    desde = agora().replace(hour=0, minute=0, second=0) - timedelta(days=dias)
    consulta = (select(Mensagem).outerjoin(Lead, Mensagem.lead_id == Lead.id)
                .where(Mensagem.canal.in_(["email", "whatsapp"]), Mensagem.criado_em >= desde))
    consulta = _so_dele(consulta, usuario)
    if canal in ("email", "whatsapp"):
        consulta = consulta.where(Mensagem.canal == canal)
    if status == "respondeu":
        consulta = consulta.where(Mensagem.respondida.is_(True))
    elif status == "respostas":
        consulta = consulta.where(Mensagem.status == "recebida")
    elif status in STATUS_ENVIO:
        consulta = consulta.where(Mensagem.status == status)
    else:
        consulta = consulta.where(Mensagem.status != "recebida")  # padrão: só o que a MS mandou
    if util.para_int(campanha):
        consulta = consulta.where(Mensagem.campanha_id == util.para_int(campanha))
    if util.para_int(lead):
        consulta = consulta.where(Mensagem.lead_id == util.para_int(lead))
    if busca.strip():
        consulta = consulta.where(Lead.empresa.ilike(f"%{busca.strip()}%"))
    lista = db.execute(consulta.order_by(Mensagem.criado_em.desc(), Mensagem.id.desc()).limit(300)).scalars().all()

    # Próximos envios: o que está programado nas campanhas aprovadas
    proximos_q = (select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id).outerjoin(Lead, Tarefa.lead_id == Lead.id)
                  .where(Tarefa.status == "pendente", Tarefa.canal.in_(["email", "whatsapp"]),
                         Campanha.status == "ativa", Tarefa.data <= hoje + timedelta(days=3)))
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        proximos_q = proximos_q.where(or_(Lead.vendedor_id == usuario.id, Campanha.usuario_id == usuario.id))
    if canal in ("email", "whatsapp"):
        proximos_q = proximos_q.where(Tarefa.canal == canal)
    if busca.strip():
        proximos_q = proximos_q.where(Lead.empresa.ilike(f"%{busca.strip()}%"))
    if util.para_int(campanha):
        proximos_q = proximos_q.where(Tarefa.campanha_id == util.para_int(campanha))
    if util.para_int(lead):
        proximos_q = proximos_q.where(Tarefa.lead_id == util.para_int(lead))
    proximos = db.execute(proximos_q.order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(30)).scalars().all()

    def contar(q):
        return db.execute(_so_dele(q.outerjoin(Lead, Mensagem.lead_id == Lead.id), usuario)).scalar() or 0

    base = select(func.count(Mensagem.id)).where(Mensagem.criado_em >= desde)
    resumo = {
        "email_hoje": mensagens.enviadas_hoje(db, "email"), "email_limite": mensagens.limite_diario(db, "email"),
        "whats_hoje": mensagens.enviadas_hoje(db, "whatsapp"), "whats_limite": mensagens.limite_diario(db, "whatsapp"),
        "falharam": contar(base.where(Mensagem.status == "falhou")),
        "respostas": contar(base.where(Mensagem.status == "recebida")),
        "na_fila": contar(base.where(Mensagem.status == "na_fila")),
    }
    regras = {chave: ler_config(db, chave) for chave in (
        "limite_diario_email", "limite_hora_email", "limite_diario_whatsapp", "limite_hora_whatsapp",
        "limite_diario_campanha", "limite_diario_dominio", "horas_entre_contatos", "horario_envio_inicio",
        "horario_envio_fim", "enviar_email_automatico", "enviar_whatsapp_automatico", "dias_sem_resposta")}
    camp_q = select(Campanha).where(Campanha.arquivada.is_(False)).order_by(Campanha.criado_em.desc()).limit(100)
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        camp_q = camp_q.where(Campanha.usuario_id == usuario.id)
    lead_obj = db.get(Lead, util.para_int(lead)) if util.para_int(lead) else None
    pessoas = {u.id: u.nome for u in db.execute(select(Usuario)).scalars()}
    nomes_camp = {c.id: c.nome for c in db.execute(select(Campanha)).scalars()}
    return tela(request, "envios.html", {
        "lista": lista, "proximos": proximos, "resumo": resumo, "regras": regras, "STATUS_ENVIO": STATUS_ENVIO,
        "PERIODOS": PERIODOS, "filtros": {"canal": canal, "status": status, "campanha": campanha, "periodo": periodo,
                                          "lead": lead, "busca": busca},
        "campanhas": db.execute(camp_q).scalars().all(), "lead_filtro": lead_obj, "pessoas": pessoas,
        "nomes_camp": nomes_camp, "hoje": hoje,
    })
