"""Reserva do lead: quando um usuário coloca a empresa numa campanha, ela fica TRAVADA com ele.

- Enquanto estiver reservada, a campanha de outro usuário não pega essa empresa.
- A reserva vale 60 dias e é renovada a cada mudança de status do lead (respondeu, interessado, reunião...).
- Passados 60 dias sem nenhuma mudança de status, a empresa volta sozinha para a base (rotina de hora em hora).
- O dono da reserva (ou o administrador/gestor) pode liberar antes, pelo botão na ficha do lead.

Ao voltar para a base: o vendedor da ficha sai, os envios de campanha pendentes são cancelados e, se a empresa nunca
respondeu (Contatado, Aguardando resposta ou Perdido por "Sem resposta"), o status volta para "Novo", para outra
pessoa poder fazer campanha. Quem respondeu, pediu para sair ou disse que não tem interesse não volta a ser
procurado (as regras de opt-out e de perda continuam valendo).
"""

import logging
from datetime import timedelta

from sqlalchemy import select

from .banco import agora, gravar_config, ler_config
from .modelos import Campanha, Lead, Tarefa, Usuario

log = logging.getLogger(__name__)

DIAS_DE_RESERVA = 60
STATUS_QUE_VOLTAM_A_NOVO = {"Novo", "Pesquisando", "Abordagem criada", "Contatado", "Aguardando resposta"}
CAMPANHAS_EM_ANDAMENTO = ("gerando", "aguardando_aprovacao", "ativa", "pausada")


def ativa(lead: Lead) -> bool:
    return bool(lead.reservado_por_id and lead.reservado_ate and lead.reservado_ate > agora())


def de_outro(lead: Lead, usuario_id: int | None) -> bool:
    """A empresa está travada com OUTRA pessoa (não pode entrar na campanha de usuario_id)."""
    return ativa(lead) and lead.reservado_por_id != usuario_id


def reservar(db, lead: Lead, usuario: Usuario, motivo: str = "") -> None:
    """Trava a empresa com o usuário por 60 dias (ou renova, se já era dele)."""
    from .leads_servico import historico

    renovando = lead.reservado_por_id == usuario.id and ativa(lead)
    lead.reservado_por_id = usuario.id
    if not renovando:
        lead.reservado_em = agora()
    lead.reservado_ate = agora() + timedelta(days=DIAS_DE_RESERVA)
    if not renovando:
        historico(db, lead.id, "sistema", f"Empresa reservada para {usuario.nome} por {DIAS_DE_RESERVA} dias"
                                          + (f" ({motivo})" if motivo else "") + ".", usuario)


def renovar_por_status(lead: Lead) -> None:
    """Mudou o status: a contagem dos 60 dias recomeça (chamado por leads_servico.mudar_status)."""
    if lead.reservado_por_id:
        lead.reservado_ate = agora() + timedelta(days=DIAS_DE_RESERVA)


def pode_liberar(usuario: Usuario, lead: Lead) -> bool:
    from . import autorizacao

    return bool(lead.reservado_por_id) and (lead.reservado_por_id == usuario.id
                                            or autorizacao.ve_tudo(usuario, "leads.ver"))


def liberar(db, lead: Lead, usuario: Usuario | None, motivo: str) -> int:
    """Devolve a empresa para a base. Devolve quantos envios pendentes foram cancelados."""
    from .leads_servico import historico

    dono_id = lead.reservado_por_id
    dono = db.get(Usuario, dono_id) if dono_id else None
    cancelados = 0
    pendentes = db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id, Tarefa.tipo == "prospeccao",
                                                Tarefa.status.in_(["pendente", "rascunho"]))).scalars()
    for t in pendentes:
        t.status, t.concluida_em, t.resultado = "cancelada", agora(), f"Empresa liberada para a base: {motivo}"[:500]
        cancelados += 1
    if lead.vendedor_id and lead.vendedor_id == dono_id:
        lead.vendedor_id = None
    lead.reservado_por_id = lead.reservado_em = lead.reservado_ate = None
    voltou_a_novo = (lead.status in STATUS_QUE_VOLTAM_A_NOVO
                     or (lead.perdido and (lead.motivo_perda or "") == "Sem resposta"))
    if voltou_a_novo and not lead.opt_out:
        lead.status, lead.motivo_perda = "Novo", ""
    historico(db, lead.id, "sistema", f"Empresa liberada para a base ({motivo})"
                                      + (f"; estava com {dono.nome}" if dono else "")
                                      + ("; status voltou para Novo" if voltou_a_novo else "")
                                      + (f"; {cancelados} envio(s) pendente(s) cancelado(s)" if cancelados else "")
                                      + ".", usuario)
    return cancelados


def liberar_vencidas(db, maximo: int = 500) -> int:
    """Rotina: reservas com 60 dias sem mudança de status voltam para a base."""
    vencidas = db.execute(select(Lead).where(Lead.reservado_por_id.is_not(None), Lead.reservado_ate <= agora())
                          .limit(maximo)).scalars().all()
    for lead in vencidas:
        if _em_campanha_andando(db, lead.id):
            lead.reservado_ate = agora() + timedelta(days=1)  # ainda tem campanha rodando: espera ela acabar
            continue
        liberar(db, lead, None, f"{DIAS_DE_RESERVA} dias sem mudança de status")
    return len(vencidas)


def _em_campanha_andando(db, lead_id: int) -> bool:
    return db.execute(select(Tarefa.id).join(Campanha, Tarefa.campanha_id == Campanha.id).where(
        Tarefa.lead_id == lead_id, Tarefa.status.in_(["pendente", "rascunho"]),
        Campanha.status.in_(CAMPANHAS_EM_ANDAMENTO)).limit(1)).first() is not None


def preencher_reservas_antigas(db) -> int:
    """Uma vez só: empresas que já estão em campanhas ficam reservadas para quem criou a campanha mais recente
    delas, contando os 60 dias a partir da criação da campanha (no mínimo até amanhã)."""
    if ler_config(db, "reservas_preenchidas") == "1":
        return 0
    linhas = db.execute(select(Tarefa.lead_id, Campanha.usuario_id, Campanha.criado_em)
                        .join(Campanha, Tarefa.campanha_id == Campanha.id)
                        .where(Tarefa.lead_id.is_not(None), Campanha.usuario_id.is_not(None),
                               Campanha.status.not_in(["cancelada", "erro"]))
                        .order_by(Campanha.criado_em)).all()
    mais_recente = {}
    for lead_id, usuario_id, criado_em in linhas:
        mais_recente[lead_id] = (usuario_id, criado_em)
    feitos = 0
    for lead_id, (usuario_id, criado_em) in mais_recente.items():
        lead = db.get(Lead, lead_id)
        if lead is None or lead.reservado_por_id:
            continue
        lead.reservado_por_id, lead.reservado_em = usuario_id, criado_em
        lead.reservado_ate = max(criado_em + timedelta(days=DIAS_DE_RESERVA), agora() + timedelta(days=1))
        feitos += 1
    gravar_config(db, "reservas_preenchidas", "1")
    log.info("Reservas: %s empresas de campanhas existentes ficaram reservadas", feitos)
    return feitos
