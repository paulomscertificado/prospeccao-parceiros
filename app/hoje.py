"""Quem precisa de mim hoje (auditoria de 11/11/2026, P1.7): uma lista de trabalho só, no topo do Painel.

- Respostas quentes esperando alguém assumir, com prazo de 2 horas úteis (horário de envio do sistema, dias úteis).
  Em 3 semanas a mediana até assumir foi de 18,6 h: o lead quente esfria.
- Respostas mornas para decidir (insistir ou descartar, com motivo).
- Tarefas de hoje e atrasadas da pessoa (reunião, ligação, follow-up; os toques de campanha ficam na Minha fila).
- Leads da pessoa em negociação sem movimento há dias e sem nada agendado ("esfriando").
- Parceiros sem venda há muito tempo.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from . import autorizacao, metricas
from .banco import agora, ler_config, ler_config_int
from .modelos import Historico, Lead, Oportunidade, Tarefa, Usuario

PRAZO_HORAS_UTEIS = 2
STATUS_COM_HUMANO = ["Respondeu", "Interessado", "Humano assumiu", "Reunião", "Negociação"]
MOSTRAR = 8  # itens por grupo (o resto fica no link "ver todos")


def _horario(db) -> tuple[time, time]:
    def ler(chave: str, padrao: str) -> time:
        try:
            return time.fromisoformat(ler_config(db, chave) or padrao)
        except ValueError:
            return time.fromisoformat(padrao)

    return ler("horario_envio_inicio", "08:30"), ler("horario_envio_fim", "18:00")


def somar_horas_uteis(inicio: datetime, horas: float, abre: time, fecha: time) -> datetime:
    """inicio + N horas contando só o horário de trabalho (segunda a sexta, de `abre` a `fecha`).
    Ex.: resposta às 17:30 com prazo de 2 h úteis (08:30–18:00) → 10:00 do dia útil seguinte."""
    restante = timedelta(hours=horas)
    atual = inicio
    for _ in range(30):  # no máximo algumas semanas de pulos (feriados não são considerados)
        if atual.weekday() >= 5:
            atual = datetime.combine(atual.date() + timedelta(days=7 - atual.weekday()), abre)
            continue
        if atual.time() < abre:
            atual = datetime.combine(atual.date(), abre)
        if atual.time() >= fecha:
            atual = datetime.combine(atual.date() + timedelta(days=1), abre)
            continue
        fim_do_dia = datetime.combine(atual.date(), fecha)
        if atual + restante <= fim_do_dia:
            return atual + restante
        restante -= fim_do_dia - atual
        atual = datetime.combine(atual.date() + timedelta(days=1), abre)
    return atual + restante


def prazo_para_assumir(db, criado_em: datetime) -> datetime:
    abre, fecha = _horario(db)
    return somar_horas_uteis(criado_em, PRAZO_HORAS_UTEIS, abre, fecha)


def _tempo(delta: timedelta) -> str:
    minutos = max(int(delta.total_seconds() // 60), 0)
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    return f"{horas} h" if horas < 48 else f"{horas // 24} dias"


def itens(db, usuario: Usuario) -> dict:
    """Tudo o que espera a pessoa agora, já em ordem de urgência."""
    momento = agora()
    resultado = {"quentes": [], "mornas": 0, "morna_mais_antiga": "", "tarefas": [], "esfriando": [],
                 "parceiros": [], "total": 0}

    if autorizacao.pode(usuario, "oportunidades.ver"):
        novas = db.execute(autorizacao.filtrar(
            select(Oportunidade).join(Lead, Oportunidade.lead_id == Lead.id).where(Oportunidade.status == "nova"),
            usuario, "oportunidades.ver", Lead.vendedor_id, sem_dono=True)
            .options(selectinload(Oportunidade.lead)).order_by(Oportunidade.criado_em)).scalars().all()
        for o in novas:
            if o.temperatura != "quente":
                continue
            prazo = prazo_para_assumir(db, o.criado_em)
            resultado["quentes"].append({"o": o, "prazo": prazo, "atrasada": momento > prazo,
                                         "espera": _tempo(momento - o.criado_em),
                                         "falta": _tempo(prazo - momento) if prazo > momento else "",
                                         "passou": _tempo(momento - prazo) if momento > prazo else ""})
        mornas = [o for o in novas if o.temperatura != "quente"]
        resultado["mornas"] = len(mornas)
        resultado["morna_mais_antiga"] = _tempo(momento - mornas[0].criado_em) if mornas else ""

    tarefas = db.execute(select(Tarefa).where(
        Tarefa.usuario_id == usuario.id, Tarefa.status == "pendente", Tarefa.tipo != "prospeccao",
        Tarefa.data <= date.today()).options(selectinload(Tarefa.lead))
        .order_by(Tarefa.data, Tarefa.hora).limit(50)).scalars().all()
    resultado["tarefas"] = [{"t": t, "atrasada": t.data < date.today(), "dias": (date.today() - t.data).days}
                            for t in tarefas]

    if autorizacao.pode(usuario, "leads.ver"):
        dias = ler_config_int(db, "dias_lead_parado", 7)
        meus = db.execute(select(Lead).where(
            Lead.status.in_(STATUS_COM_HUMANO), Lead.opt_out.is_(False), Lead.anonimizado.is_(False),
            or_(Lead.vendedor_id == usuario.id, Lead.humano_id == usuario.id))).scalars().all()
        ids = [l.id for l in meus]
        ultimo = dict(db.execute(select(Historico.lead_id, func.max(Historico.criado_em))
                                 .where(Historico.lead_id.in_(ids)).group_by(Historico.lead_id)).all()) if ids else {}
        agendados = set(db.execute(select(Tarefa.lead_id).where(
            Tarefa.lead_id.in_(ids), Tarefa.status == "pendente", Tarefa.data >= date.today())).scalars()) if ids else set()
        limite = momento - timedelta(days=dias)
        for lead in meus:
            movimento = max(filter(None, [ultimo.get(lead.id), lead.ultimo_contato, lead.criado_em]))
            if movimento < limite and lead.id not in agendados:
                resultado["esfriando"].append({"lead": lead, "dias": (momento - movimento).days})
        resultado["esfriando"].sort(key=lambda e: -e["dias"])

    if autorizacao.pode(usuario, "parceiros.ver"):
        resultado["parceiros"] = metricas.parceiros_parados(db, usuario)[:MOSTRAR]

    resultado["total"] = (len(resultado["quentes"]) + resultado["mornas"] + len(resultado["tarefas"])
                          + len(resultado["esfriando"]) + len(resultado["parceiros"]))
    resultado["atrasadas"] = sum(1 for q in resultado["quentes"] if q["atrasada"]) + sum(
        1 for t in resultado["tarefas"] if t["atrasada"])
    return resultado
