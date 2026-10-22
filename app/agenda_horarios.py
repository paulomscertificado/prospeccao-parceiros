"""Calendar: horários livres de verdade para reuniões.

Os horários saem do EXPEDIENTE cadastrado de cada pessoa (Configurações > Usuários, ex.:
"seg-sex 09:00-12:00,14:00-18:00") menos as reuniões já marcadas na agenda do sistema.
Nunca inventa horário. (Integração com Google Calendar: ver docs/configuracao.md.)
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from .banco import agora
from .leads_servico import historico, mudar_status
from .modelos import Lead, Tarefa, Usuario

DIAS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "sáb": 5, "dom": 6}
NOMES_DIA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def ler_expediente(texto: str) -> tuple[set[int], list[tuple[time, time]]]:
    """"seg-sex 09:00-12:00,14:00-18:00" → ({0..4}, [(9h,12h), (14h,18h)]). Inválido → vazio."""
    try:
        dias_txt, horas_txt = (texto or "").strip().split(" ", 1)
        dias: set[int] = set()
        for parte in dias_txt.lower().split(","):
            if "-" in parte:
                ini, fim = (DIAS[x] for x in parte.split("-"))
                dias |= set(range(ini, fim + 1))
            else:
                dias.add(DIAS[parte])
        faixas = []
        for faixa in horas_txt.replace(" ", "").split(","):
            ini, fim = faixa.split("-")
            faixas.append((time.fromisoformat(ini), time.fromisoformat(fim)))
        return dias, faixas
    except (ValueError, KeyError):
        return set(), []


def ocupados(db, usuario_id: int, inicio: date, fim: date) -> list[datetime]:
    linhas = db.execute(select(Tarefa.data, Tarefa.hora).where(
        Tarefa.usuario_id == usuario_id, Tarefa.tipo == "reuniao", Tarefa.status == "pendente",
        Tarefa.data >= inicio, Tarefa.data <= fim)).all()
    resultado = []
    for d, h in linhas:
        try:
            resultado.append(datetime.combine(d, time.fromisoformat(h or "09:00")))
        except ValueError:
            continue
    return resultado


def horarios_livres(db, usuario: Usuario, dias: int = 7, quantidade: int = 6,
                    antecedencia_horas: int = 2) -> list[datetime]:
    dias_semana, faixas = ler_expediente(usuario.expediente)
    if not dias_semana or not faixas:
        return []
    duracao = timedelta(minutes=max(15, usuario.duracao_reuniao or 30))
    minimo = agora() + timedelta(hours=antecedencia_horas)
    hoje = agora().date()
    marcados = ocupados(db, usuario.id, hoje, hoje + timedelta(days=dias))
    livres = []
    for n in range(dias + 1):
        dia = hoje + timedelta(days=n)
        if dia.weekday() not in dias_semana:
            continue
        for ini, fim in faixas:
            inicio = datetime.combine(dia, ini)
            while inicio + duracao <= datetime.combine(dia, fim):
                conflito = any(abs((m - inicio).total_seconds()) < duracao.total_seconds() for m in marcados)
                if inicio >= minimo and not conflito:
                    livres.append(inicio)
                    if len(livres) >= quantidade:
                        return livres
                inicio += duracao
    return livres


def texto_horarios(horarios: list[datetime]) -> str:
    return ", ".join(f"{NOMES_DIA[h.weekday()]} {h:%d/%m} às {h:%H:%M}" for h in horarios)


class HorarioIndisponivel(ValueError):
    pass


def agendar(db, lead: Lead, responsavel: Usuario, quando: datetime, canal: str, quem_marcou: Usuario | None,
            pauta: str = "") -> Tarefa:
    """Marca a reunião se o horário ainda estiver livre no expediente do responsável."""
    livres = horarios_livres(db, responsavel, dias=max(1, (quando.date() - agora().date()).days + 1), quantidade=500,
                             antecedencia_horas=0)
    if quando not in livres:
        raise HorarioIndisponivel("Esse horário não está mais livre na agenda do responsável. Escolha outro.")
    tarefa = Tarefa(tipo="reuniao", lead_id=lead.id, usuario_id=responsavel.id, canal=canal, data=quando.date(),
                    hora=quando.strftime("%H:%M"),
                    acao=pauta or f"Reunião de parceria · {lead.categoria.nome if lead.categoria else 'sem categoria'} · "
                                  f"score {lead.score}")
    db.add(tarefa)
    if lead.etapa < 5 and not lead.perdido:
        mudar_status(db, lead, "Reunião", quem_marcou)
    lead.proximo_contato = quando.date()
    historico(db, lead.id, "reuniao",
              f"Reunião marcada · Data: {quando:%d/%m/%Y} · Hora: {quando:%H:%M} · Canal: {canal} · "
              f"Responsável: {responsavel.nome} · Lead: {lead.empresa} · Categoria: "
              f"{lead.categoria.nome if lead.categoria else '-'} · Score: {lead.score}", quem_marcou)
    return tarefa
