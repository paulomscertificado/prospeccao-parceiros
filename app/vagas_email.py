"""Vagas de e-mail: quanto cabe por hora e por dia e uma agenda que não estoura.

Pedido da Maria em 25/11/2026, sobre o quadro Vagas de WhatsApp no número (app/vagas.py): "gostei muito disso aqui e
agora desenvolva a mesma coisa para os emails!". O mesmo que o WhatsApp tem, com as regras do e-mail:

- Ritmo: a fila de e-mail (campanhas.processar_fila) manda um e-mail por vez, a cada 3 a 4 minutos
  (campanhas.INTERVALO_AUTOMATICO_SEG; o relógio roda a cada minuto), no máximo limite_hora_email por hora e
  limite_diario_email por dia (Configurações > Geral > E-mail): uns 17 por hora e 80 num dia.
- As vagas são da MARCA: os limites de e-mail valem para a marca inteira, somando todas as contas de e-mail dela (são
  do mesmo domínio e dividem a mesma reputação: app/contas_email.py). O quadro mostra também a conta por onde os e-mails
  saem: a da pessoa ou uma compartilhada com ela, nunca a de outra pessoa (contas_email.para_enviar).
- Horário: o de envio da marca, de segunda a sexta (a fila de e-mail não manda no sábado nem no domingo:
  mensagens.dentro_do_horario), fora do almoço e com 20 minutos de folga no fim, como o WhatsApp (vagas.vagas_por_hora),
  e fora dos feriados de quem envia (app/feriados.py).
- Ocupação: os e-mails pendentes das campanhas ativas, de quem vai receber (e-mail preenchido e não marcado como
  inexistente; sem SAIR, pausa, resposta ou perda) e que têm conta para sair (sem conta, o e-mail espera e não ocupa
  vaga). Os da Renovação ocupam (gastam o limite da marca), mas não mudam de dia (têm prazo). Hoje também contam os
  que já saíram (o limite é do dia) e os atrasados (a fila manda primeiro).
- planejar(): na aprovação (campanhas.aprovar, depois das vagas do WhatsApp), cada e-mail fica no horário marcado se a
  hora e o dia ainda têm vaga; senão vai para a hora mais vazia do primeiro dia com vaga. Nunca anda para trás: o e-mail
  continua depois do WhatsApp do mesmo toque (Empresas novas: umas 2 h depois, campanhas.TIPOS_WHATSAPP_PRIMEIRO) e dois
  e-mails para a mesma empresa ficam a pelo menos 20 h um do outro (campanhas.horas_minimas_automatico), com o espaço
  da cadência entre os toques.
- replanejar(): de hora em hora (rotinas._rotina_hora), os e-mails atrasados de dias anteriores e os que estão numa hora
  ou num dia já lotado da marca vão para as próximas vagas. O atrasado de Empresas novas cuja empresa ainda tem WhatsApp
  por sair fica como está: sai sem esperar o WhatsApp (pedido da Maria em 17/11/2026, "soltar os e-mails").
- resumo() / para_tela() / da_campanha(): o quadro templates/_vagas_email.html na Nova campanha, no Buscar agora das
  Empresas novas e na aprovação, ao lado das vagas de WhatsApp.
"""

import logging
import math
import random
from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, func, or_, select

from . import config, vagas
from .banco import agora, ler_config, ler_config_int, usar_config_da_ar
from .modelos import Campanha, Lead, Mensagem, Tarefa, Tenant, Usuario

log = logging.getLogger(__name__)

ESPERA_DO_RELOGIO_SEG = 30  # o relógio roda a cada minuto: o e-mail liberado sai, em média, meio minuto depois
TOLERANCIA_FIM = 4  # minutos: o horário natural (cadencias.hora_natural/depois_de) vai até 4 min depois da folga do fim


def ritmo_por_hora(db) -> int:
    """Quantos e-mails a fila consegue mandar numa hora: um a cada 3 a 4 minutos, uns 17."""
    from . import campanhas

    minimo, maximo = campanhas.intervalo_automatico(db, "email")
    return max(1, int(3600 // ((minimo + maximo) / 2 + ESPERA_DO_RELOGIO_SEG)))


def por_hora(db) -> int:
    """Quantos e-mails automáticos cabem por hora na marca: o ritmo da fila e o limite por hora de Configurações >
    Geral > E-mail, o menor dos dois."""
    ritmo = ritmo_por_hora(db)
    limite = ler_config_int(db, "limite_hora_email", 0)
    return max(1, min(ritmo, limite) if limite > 0 else ritmo)


def vagas_por_hora(db, minimo: str = "", maximo: str = "") -> dict[int, tuple[int, int, int]]:
    """{hora: (vagas, primeiro minuto, último minuto)}: as mesmas horas do WhatsApp (horário de envio da marca, fora do
    almoço e da folga do fim), com o ritmo do e-mail."""
    return vagas.vagas_por_hora(db, minimo, maximo, cabem=por_hora(db))


def por_dia(db, horas: dict | None = None) -> int:
    """Quantos e-mails cabem num dia inteiro na marca: o limite por dia de Configurações (0 = sem limite) ou o que as
    horas comportam, o menor dos dois."""
    horas = vagas_por_hora(db) if horas is None else horas
    total = sum(v for v, _de, _ate in horas.values())
    limite = ler_config_int(db, "limite_diario_email", 0)
    return min(total, limite) if limite > 0 else total


def texto_do_intervalo(db) -> str:
    """"3 a 4 minutos": o intervalo da fila de e-mail como ele acontece (o relógio roda a cada minuto)."""
    from . import campanhas

    minimo, maximo = (max(1, math.ceil(s / 60)) for s in campanhas.intervalo_automatico(db, "email"))
    return f"{minimo} minutos" if minimo == maximo else f"{minimo} a {maximo} minutos"


def _recebe():
    """Condição do banco: o lead recebe o e-mail automático (campo preenchido e não marcado como inexistente, sem SAIR,
    pausa, resposta ou perda, como sdr.automacao_ativa e email_validacao.utilizavel). Os e-mails dos outros não saem e
    não ocupam vaga."""
    parados = [s for s, etapa in config.ETAPA_DO_STATUS.items() if etapa >= 2] + list(config.STATUS_PERDIDO)
    return and_(func.coalesce(Lead.email, "") != "",
                or_(Lead.email_invalido.is_not(True), func.coalesce(Lead.email_conferido, "") != Lead.email),
                Lead.automacao_pausada.is_not(True), Lead.opt_out.is_not(True), Lead.anonimizado.is_not(True),
                func.coalesce(Lead.status, "").not_in(parados))


def recebe(lead: Lead | None) -> bool:
    """O mesmo que _recebe(), para um lead já carregado."""
    from . import sdr

    if lead is None or not (lead.email or "").strip() or not sdr.automacao_ativa(lead):
        return False
    return not (lead.email_invalido and (lead.email_conferido or "") == lead.email)


def chave_da_marca(ar) -> str:
    """A chave das vagas: a marca (os limites de e-mail são dela, somando as contas)."""
    return f"marca:{ar or 0}"


class Contas:
    """A conta de e-mail por onde sai cada envio, a mesma da fila (campanhas.conta_do_toque): a do responsável pelo
    lead ou, sem ela, uma compartilhada com ele; a principal só para o dono dela. Sem conta (contas_email.SemConta), o
    e-mail espera e a fila avisa a pessoa: ele não ocupa vaga. Guarda a resposta de cada pessoa."""

    def __init__(self, db):
        self.db = db
        self._contas: dict = {}
        self._dono_principal: int | None = None

    def da_pessoa(self, usuario_id: int | None):
        """A conta (ContaEmail) por onde saem os e-mails da pessoa; None = sem conta."""
        if usuario_id not in self._contas:
            from . import contas_email

            pessoa = self.db.get(Usuario, usuario_id) if usuario_id else None
            try:
                self._contas[usuario_id] = contas_email.para_enviar(self.db, pessoa) if pessoa is not None else None
            except contas_email.SemConta:
                self._contas[usuario_id] = None
        return self._contas[usuario_id]

    def responsavel(self, vendedor_id: int | None, usuario_id: int | None, dono_da_campanha: int | None) -> int | None:
        """De quem é o envio (conexoes.responsavel): o responsável pelo lead; senão quem recebeu o toque, o dono da
        campanha e, por último, o dono do e-mail principal."""
        uid = vendedor_id or usuario_id or dono_da_campanha
        if uid:
            return uid
        if self._dono_principal is None:
            from . import contas_email

            self._dono_principal = contas_email.garantir_principal(self.db).dono_id or 0
        return self._dono_principal or None

    def chave(self, ar, vendedor_id: int | None, usuario_id: int | None, dono_da_campanha: int | None) -> str | None:
        """A chave das vagas do envio (a marca). None = sem conta para sair."""
        if self.da_pessoa(self.responsavel(vendedor_id, usuario_id, dono_da_campanha)) is None:
            return None
        return chave_da_marca(ar)


def ocupacao(db, desde: date, sem: set = frozenset(), contas: Contas | None = None,
             ars: set | None = None) -> tuple[Counter, Counter]:
    """E-mails já marcados, fora os ids de `sem`: (por (chave, dia, hora) a partir de `desde`, atrasados de antes de
    `desde` por chave). Só os pendentes das campanhas ativas, de quem vai receber e com conta para sair. Rascunho de
    campanha que espera aprovação não conta (pode nem ser aprovada: ao aprovar, ela entra nas vagas que sobraram). `ars`:
    só estas marcas (None = todas)."""
    contas = contas or Contas(db)
    consulta = (select(Tarefa.id, Tarefa.data, Tarefa.hora, Tarefa.tenant_id, Lead.vendedor_id, Tarefa.usuario_id,
                       Campanha.usuario_id.label("dono_da_campanha"))
                .join(Lead, Tarefa.lead_id == Lead.id).join(Campanha, Tarefa.campanha_id == Campanha.id)
                .where(Tarefa.status == "pendente", Tarefa.canal == "email", Tarefa.tipo == "prospeccao",
                       Campanha.status == "ativa", Campanha.aprovado_em.is_not(None), _recebe()))
    if ars is not None:
        consulta = consulta.where(Tarefa.tenant_id.in_(ars))
    carga: Counter = Counter()
    atrasados: Counter = Counter()
    for tid, dia, hora, ar, vid, uid, dono in db.execute(consulta.execution_options(sem_filtro_de_ar=True)).all():
        if tid in sem:
            continue
        chave = contas.chave(ar, vid, uid, dono)
        if chave is None:
            continue  # sem conta: espera e não ocupa vaga
        if dia < desde:
            atrasados[chave] += 1
        else:
            carga[(chave, dia, vagas._hora_de(hora))] += 1
    return carga, atrasados


def enviados_hoje(db, ars: set | None = None) -> Counter:
    """E-mails que já saíram hoje, por chave (marca): contam no limite do dia (a mesma conta de
    mensagens.enviadas_hoje, que a fila usa)."""
    from . import mensagens

    inicio = datetime.combine(agora().date(), time.min)
    consulta = (select(Mensagem.tenant_id, func.count(Mensagem.id))
                .where(Mensagem.direcao == "saida", Mensagem.canal == "email", Mensagem.criado_em >= inicio,
                       Mensagem.status.in_(mensagens.ENVIADAS))
                .group_by(Mensagem.tenant_id))
    if ars is not None:
        consulta = consulta.where(Mensagem.tenant_id.in_(ars))
    return Counter({chave_da_marca(ar): n for ar, n in db.execute(consulta.execution_options(sem_filtro_de_ar=True))})


def _dia_de_envio(dia: date, sem_envio: frozenset) -> bool:
    """A fila de e-mail só manda de segunda a sexta (mensagens.dentro_do_horario) e fora dos feriados de quem envia."""
    return dia.weekday() < 5 and dia not in sem_envio


def _quando(dia: date, hora: str | None) -> datetime:
    minuto = vagas._minutos(hora or "", 9 * 60)
    return datetime.combine(dia, time(minuto // 60 % 24, minuto % 60))


class _Agenda:
    """As vagas de uma marca enquanto se planeja: o que já está marcado por hora e por dia, quanto cabe e o que já saiu
    hoje."""

    def __init__(self, horas: dict, teto: int, carga: Counter, atrasados: Counter, saidos: Counter, momento: datetime):
        self.horas, self.teto, self.carga, self.saidos, self.momento = horas, teto, carga, saidos, momento
        self.hoje = momento.date()
        self.agora_min = momento.hour * 60 + momento.minute
        self.no_dia: Counter = Counter()
        for (chave, dia, _hora), n in carga.items():
            self.no_dia[(chave, dia)] += n
        for chave, n in atrasados.items():
            self.no_dia[(chave, self.hoje)] += n  # a fila manda os atrasados primeiro: ocupam hoje

    def cabem_no_dia(self, chave: str, dia: date) -> int:
        """Quantos cabem no dia: o limite do dia e as horas; hoje, só o que falta do dia e do limite (os que já saíram
        contam)."""
        if dia == self.hoje:
            a_partir = self.agora_min + vagas.FOLGA_AGORA
            nas_horas = sum(vagas._cabem_na_hora(v, de, ate, a_partir) for v, de, ate in self.horas.values())
            return max(0, min(nas_horas, self.teto - self.saidos[chave]))
        return min(self.teto, sum(v for v, _de, _ate in self.horas.values()))

    def tem_vaga_no_dia(self, chave: str, dia: date) -> bool:
        return self.no_dia[(chave, dia)] < self.cabem_no_dia(chave, dia)

    def ocupar(self, chave: str, dia: date, hora: str) -> None:
        self.carga[(chave, dia, vagas._hora_de(hora))] += 1
        self.no_dia[(chave, dia)] += 1

    def fica_onde_esta(self, chave: str, atual: tuple, a_partir_de: datetime, sem_envio: frozenset) -> bool:
        """O e-mail marcado em `atual` (dia, hora) pode ficar: dia de envio, não antes do limite, dentro do horário e com
        vaga na hora e no dia (campanha que cabe não muda nada)."""
        dia, hora_txt = atual
        minuto = vagas._minutos(hora_txt or "", -1)
        hora = minuto // 60
        if minuto < 0 or dia < self.hoje or not _dia_de_envio(dia, sem_envio) or _quando(dia, hora_txt) < a_partir_de:
            return False
        if hora not in self.horas or not self.horas[hora][1] <= minuto <= self.horas[hora][2] + TOLERANCIA_FIM:
            return False
        if dia == self.hoje and minuto <= self.agora_min:
            return False
        vagas_h, de, ate = self.horas[hora]
        a_partir = self.agora_min if dia == self.hoje else -1
        return (self.carga[(chave, dia, hora)] < vagas._cabem_na_hora(vagas_h, de, ate, a_partir)
                and self.tem_vaga_no_dia(chave, dia))

    def primeira_vaga(self, chave: str, a_partir_de: datetime, sem_envio: frozenset) -> tuple[date, str] | None:
        """O primeiro dia de envio com vaga a partir de `a_partir_de`, na hora mais vazia dele (espalha pelo dia), com os
        minutos espalhados dentro da hora (nunca redondos, como cadencias.hora_natural). None = nenhuma vaga em
        vagas.DIAS_DE_BUSCA dias."""
        dia = max(a_partir_de.date(), self.hoje)
        for _ in range(vagas.DIAS_DE_BUSCA):
            if _dia_de_envio(dia, sem_envio) and self.tem_vaga_no_dia(chave, dia):
                a_partir = -1
                if dia == a_partir_de.date():
                    a_partir = a_partir_de.hour * 60 + a_partir_de.minute
                if dia == self.hoje:
                    a_partir = max(a_partir, self.agora_min + vagas.FOLGA_AGORA)
                livres = []
                for hora, (vagas_h, de, ate) in self.horas.items():
                    cabem = vagas._cabem_na_hora(vagas_h, de, ate, a_partir)
                    usados = self.carga[(chave, dia, hora)]
                    if usados < cabem:
                        livres.append((usados / cabem, hora, usados))
                if livres:
                    _ocupado, hora, usados = min(livres)  # a hora mais vazia (empate: a mais cedo)
                    vagas_h, de, ate = self.horas[hora]
                    passo = max(1, (ate - de + 1) // vagas_h)
                    minuto = max(de + usados * passo, a_partir)
                    minuto = min(ate, minuto + random.randint(0, min(4, passo - 1)))
                    if minuto % 5 == 0 and minuto < ate:
                        minuto += 1  # nada de 09:00, 10:15...
                    return dia, f"{minuto // 60:02d}:{minuto % 60:02d}"
            dia += timedelta(days=1)
        return None


def _agenda(db, ars: set | None, sem: set, contas: Contas, horas: dict) -> _Agenda:
    momento = agora()
    carga, atrasados = ocupacao(db, momento.date(), sem, contas, ars)
    return _Agenda(horas, por_dia(db, horas), carga, atrasados, enviados_hoje(db, ars), momento)


def planejar(db, tarefas: list[Tarefa], desde: date | None = None, ordem=None, minimo: str = "",
             maximo: str = "") -> dict:
    """Põe os e-mails de `tarefas` nas vagas da marca (sem estourar nenhuma hora nem o limite do dia), a partir do dia e
    do horário marcados de cada um (nunca antes de `desde`, nem antes de agora). Entre dois e-mails da mesma empresa
    ficam pelo menos 20 h (campanhas.horas_minimas_automatico) e o espaço que a cadência tinha. Só mexe nos e-mails: o
    WhatsApp tem as vagas dele (app/vagas.py) e é planejado antes; como o e-mail nunca vai para antes de onde estava, ele
    continua depois do WhatsApp do mesmo toque. `ordem`: quem fica com as vagas primeiro (lista de tarefas de uma
    empresa -> valor); padrão: quem estava marcado antes. `minimo`/`maximo`: a janela da campanha. As configurações
    (horário, limites) são as de agora: quem chama liga as da AR (banco.usar_config_da_ar). Devolve {"movidos" (e-mails
    que mudaram de dia), "de", "ate" (os dias do primeiro e-mail de cada empresa), "empresas"}."""
    from . import campanhas, feriados

    feito = {"movidos": 0, "de": None, "ate": None, "empresas": 0}
    emails = [t for t in tarefas if t.canal == "email"]
    horas = vagas_por_hora(db, minimo, maximo)
    if not emails or not horas:
        return feito
    contas = Contas(db)
    ars = {t.tenant_id for t in emails}
    agenda = _agenda(db, None if None in ars else ars, {t.id for t in emails if t.id}, contas, horas)
    hoje = agenda.hoje
    comeco = datetime.combine(max(desde or hoje, hoje), time.min)
    horas_minimas = campanhas.horas_minimas_automatico(db, "email")
    grupos: dict[tuple, list[Tarefa]] = {}
    for t in emails:
        grupos.setdefault((t.campanha_id, t.lead_id), []).append(t)
    sem_envio_de: dict = {}

    def padrao(lista):
        return min((t.data, t.hora or "", t.id or 0) for t in lista)

    for lista in sorted(grupos.values(), key=ordem or padrao):
        lead = lista[0].lead
        if not recebe(lead):
            continue  # o e-mail não sai (campo em branco, endereço inexistente, SAIR, respondeu): nada a acomodar
        camp = db.get(Campanha, lista[0].campanha_id) if lista[0].campanha_id else None
        responsavel = contas.responsavel(lead.vendedor_id, lista[0].usuario_id, camp.usuario_id if camp else None)
        chave = contas.chave(lista[0].tenant_id, lead.vendedor_id, lista[0].usuario_id,
                             camp.usuario_id if camp else None)
        if chave is None:
            continue  # sem conta de e-mail: espera (a fila avisa a pessoa) e não ocupa vaga
        if responsavel not in sem_envio_de:
            pessoa = db.get(Usuario, responsavel) if responsavel else None
            sem_envio_de[responsavel] = feriados.dias_sem_envio(db, pessoa) if pessoa else frozenset()
        sem_envio = sem_envio_de[responsavel]
        anterior = None  # (marcado antes, marcado agora) do e-mail anterior da empresa
        for posicao, t in enumerate(sorted(lista, key=lambda t: (t.data, t.hora or "", t.id or 0))):
            original = _quando(t.data, t.hora)
            limite = max(original, comeco)
            if anterior is not None:
                original_ant, novo_ant = anterior
                espaco = (original.date() - original_ant.date()).days  # o espaço da cadência entre os dois e-mails
                limite = max(limite, novo_ant + timedelta(hours=horas_minimas),
                             datetime.combine(novo_ant.date() + timedelta(days=max(0, espaco)), time.min))
            antes = (t.data, t.hora)
            if not agenda.fica_onde_esta(chave, antes, limite, sem_envio):
                vaga = agenda.primeira_vaga(chave, limite, sem_envio)
                if vaga is not None:
                    t.data, t.hora = vaga
            agenda.ocupar(chave, t.data, t.hora)
            if t.data != antes[0]:
                feito["movidos"] += 1
            if posicao == 0:
                feito["de"] = min(feito["de"] or t.data, t.data)
                feito["ate"] = max(feito["ate"] or t.data, t.data)
                feito["empresas"] += 1
            anterior = (original, _quando(t.data, t.hora))
    return feito


def _ainda_tem_whatsapp(db, pares: set, hoje: date) -> set:
    """Dos (campanha, lead) de `pares`, os em que a empresa ainda tem WhatsApp da campanha por sair (pendente, com o
    campo preenchido e sem atraso grande: o mesmo de campanhas._whatsapp_da_empresa_pendente)."""
    from . import campanhas

    if not pares:
        return set()
    linhas = db.execute(select(Tarefa.campanha_id, Tarefa.lead_id).join(Lead, Lead.id == Tarefa.lead_id).where(
        Tarefa.campanha_id.in_({c for c, _ in pares}), Tarefa.lead_id.in_({l for _, l in pares}),
        Tarefa.canal == "whatsapp", Tarefa.status == "pendente",
        Tarefa.data >= hoje - timedelta(days=campanhas.DIAS_ATRASO_AUTOMATICO),
        func.trim(func.coalesce(Lead.whatsapp, "")) != "").distinct().execution_options(sem_filtro_de_ar=True)).all()
    return {(c, l) for c, l in linhas if (c, l) in pares}


def replanejar(db, hoje: date | None = None, so_campanhas: set | None = None) -> int:
    """De hora em hora: os e-mails que ficaram de dias anteriores (a conta deu erro, a fila não deu conta) e os que
    estão numa hora ou num dia já lotado da marca nos próximos dias (campanha marcada antes das vagas, limite diminuído)
    vão para as próximas vagas; os e-mails seguintes da mesma empresa andam junto para manter o espaço. Quem já começou
    a conversa fica com as vagas; anda o primeiro toque de quem ainda não recebeu nada. Ficam de fora a Renovação (tem
    prazo: renovacao.ajustar_a_etapa cuida dela), a marca com o envio automático de e-mail desligado (o atraso é o
    clique), o e-mail sem conta para sair (espera a conta), o atrasado de campanha em que o WhatsApp vai primeiro cuja
    empresa ainda tem WhatsApp por sair (sai sem esperar o WhatsApp: regra de 17/11/2026) e os e-mails de hoje (a fila
    está mandando). `so_campanhas`: só estas campanhas (None = todas). Devolve quantos e-mails mudaram de dia."""
    from sqlalchemy.orm import selectinload

    from . import campanhas

    hoje = hoje or agora().date()
    consulta = (
        select(Tarefa.campanha_id, Tarefa.lead_id, Tarefa.data, Tarefa.hora, Tarefa.tenant_id, Tarefa.usuario_id,
               Lead.vendedor_id, Campanha.usuario_id.label("dono_da_campanha"), Campanha.tipo.label("tipo"))
        .join(Campanha, Tarefa.campanha_id == Campanha.id).join(Lead, Tarefa.lead_id == Lead.id)
        .where(Tarefa.status == "pendente", Tarefa.canal == "email", Tarefa.tipo == "prospeccao",
               Tarefa.data != hoje, Campanha.status == "ativa", Campanha.aprovado_em.is_not(None),
               Campanha.tipo != "renovacao", _recebe()))
    if so_campanhas is not None:
        consulta = consulta.where(Tarefa.campanha_id.in_(so_campanhas))
    candidatos = db.execute(consulta.execution_options(sem_filtro_de_ar=True)).all()
    if not candidatos:
        return 0
    contas = Contas(db)
    por_ar: dict = {}
    for linha in candidatos:
        por_ar.setdefault(linha.tenant_id, []).append(linha)
    movidos = 0
    anterior = db.info.get("ar_config")
    try:
        for ar, linhas in por_ar.items():
            usar_config_da_ar(db, ar)  # o horário e os limites da marca
            if ler_config(db, "enviar_email_automatico") != "1":
                continue  # os e-mails desta marca esperam o clique: o atraso é o clique
            horas = vagas_por_hora(db)
            if not horas:
                continue
            teto = por_dia(db, horas)
            if any(linha.data > hoje for linha in linhas):
                carga, _atrasados = ocupacao(db, hoje + timedelta(days=1), contas=contas, ars={ar})
            else:
                carga = Counter()
            no_dia: Counter = Counter()
            for (chave, dia, _hora), n in carga.items():
                no_dia[(chave, dia)] += n
            atrasados_que_esperam = {(l.campanha_id, l.lead_id) for l in linhas
                                     if l.data < hoje and l.tipo in campanhas.TIPOS_WHATSAPP_PRIMEIRO}
            ficam = _ainda_tem_whatsapp(db, atrasados_que_esperam, hoje)  # saem sem esperar o WhatsApp (17/11/2026)
            pares = set()
            for linha in linhas:
                par = (linha.campanha_id, linha.lead_id)
                chave = contas.chave(ar, linha.vendedor_id, linha.usuario_id, linha.dono_da_campanha)
                if chave is None or par in ficam:
                    continue  # sem conta (espera a conta) ou atrasado que sai sem esperar o WhatsApp
                if linha.data < hoje:
                    pares.add(par)  # atrasado
                    continue
                hora = vagas._hora_de(linha.hora)
                if (hora in horas and carga[(chave, linha.data, hora)] > horas[hora][0]) or no_dia[(chave, linha.data)] > teto:
                    pares.add(par)  # numa hora ou num dia já lotado da marca
            if not pares:
                continue
            tarefas = [t for t in db.execute(select(Tarefa).where(
                Tarefa.campanha_id.in_({c for c, _ in pares}), Tarefa.status == "pendente",
                Tarefa.tipo == "prospeccao", Tarefa.canal == "email")
                .options(selectinload(Tarefa.lead)).execution_options(sem_filtro_de_ar=True)).scalars()
                if (t.campanha_id, t.lead_id) in pares]
            comecou = vagas._ja_comecaram(db, pares)

            def ordem(lista, comecou=comecou):
                return ((lista[0].campanha_id, lista[0].lead_id) not in comecou,
                        min((t.data, t.hora or "", t.id or 0) for t in lista))

            movidos += planejar(db, tarefas, hoje, ordem=ordem)["movidos"]
    finally:
        usar_config_da_ar(db, anterior)
    if movidos:
        log.info("Vagas de e-mail: %s e-mails foram para as próximas vagas da marca (atrasados ou hora/dia lotado)",
                 movidos)
    return movidos


# ---------------------------------------------------------------- Telas

def _ar_da_marca(db, pessoa: Usuario | None) -> int | None:
    """A marca das vagas nas telas: a de quem está vendo (a campanha nasce na marca da tela, como o isolamento faz com
    as linhas novas); fora de uma marca (Admin Master), a da pessoa ou a AR MS."""
    from . import ars, isolamento

    return (isolamento.ar_da_sessao(db) or (pessoa.tenant_id if pessoa is not None else None)
            or db.execute(select(Tenant.id).where(Tenant.slug == ars.AR_MS)
                          .execution_options(sem_filtro_de_ar=True)).scalar())


def nome_da_conta(conta) -> str:
    """O endereço da conta, para as telas ("" = sem conta)."""
    if conta is None:
        return ""
    if conta.principal:
        from email.utils import parseaddr

        return parseaddr(config.SMTP_REMETENTE or config.SMTP_USUARIO)[1].lower() or conta.nome or "e-mail principal"
    return conta.endereco or conta.nome


def resumo(db, pessoa: Usuario | None, dias: int = 5, ar: int | None = None) -> dict:
    """As vagas de e-mail da marca de `pessoa` (ou da marca `ar`) nos próximos `dias` dias de envio, para as telas:
    {"conta" (por onde saem os e-mails da pessoa; None = sem conta), "dias": [{"dia", "titulo", "cabem", "marcados",
    "livres"}], "por_hora", "por_dia", "livres"}. Hoje: só o que falta do dia e do limite do dia (os que já saíram
    contam), e os atrasados contam como marcados."""
    from . import feriados

    contas = Contas(db)
    ar = ar or _ar_da_marca(db, pessoa)
    chave = chave_da_marca(ar)
    horas = vagas_por_hora(db)
    agenda = _agenda(db, {ar}, set(), contas, horas)
    sem_envio = feriados.dias_sem_envio(db, pessoa) if pessoa else frozenset()
    lista, dia = [], agenda.hoje
    for _ in range(dias + 21):
        if len(lista) >= dias:
            break
        if _dia_de_envio(dia, sem_envio):
            cabem = agenda.cabem_no_dia(chave, dia)
            marcados = agenda.no_dia[(chave, dia)]
            if dia != agenda.hoje or cabem or marcados:
                lista.append({"dia": dia, "titulo": vagas._titulo(dia, agenda.hoje), "cabem": cabem,
                              "marcados": marcados, "livres": max(0, cabem - marcados)})
        dia += timedelta(days=1)
    conta = contas.da_pessoa(pessoa.id) if pessoa else None
    # white label: a conta de outra marca não aparece (as Empresas novas são da plataforma: quem envia pode ser de outra
    # marca que a de quem está vendo)
    outra_marca = conta is not None and (_ar_da_conta(db, conta) or ar) != ar
    return {"conta": None if outra_marca else conta, "outra_marca": outra_marca, "ar": ar, "dias": lista,
            "por_hora": por_hora(db), "por_dia": agenda.teto, "livres": sum(d["livres"] for d in lista)}


def _ar_da_conta(db, conta):
    from . import contas_email

    return contas_email._ar_da_conta(db, conta)


def para_tela(db, pessoa: Usuario | None, dias: int = 5, ar: int | None = None) -> dict:
    """resumo() com o endereço da conta, o intervalo da fila e os limites, para o quadro _vagas_email.html."""
    r = resumo(db, pessoa, dias, ar)
    r["nome"] = nome_da_conta(r["conta"])
    r["intervalo"] = texto_do_intervalo(db)
    r["limite_dia"] = ler_config_int(db, "limite_diario_email", 0)
    r["limite_hora"] = ler_config_int(db, "limite_hora_email", 0)
    return r


def da_campanha(db, camp: Campanha, dias: int = 7) -> dict | None:
    """Para a aprovação: as vagas de e-mail da marca da campanha (com a conta de quem é a campanha) e quanto ela pede
    (os e-mails dos rascunhos de quem vai receber). None = campanha sem e-mail pela fila de vagas (a Renovação tem
    prazo: as datas são as do vencimento)."""
    if camp.tipo == "renovacao" or "email" not in (camp.canais or ""):
        return None
    dono = db.get(Usuario, camp.usuario_id) if camp.usuario_id else None
    anterior = db.info.get("ar_config")
    usar_config_da_ar(db, camp.tenant_id)  # o horário e os limites da marca da campanha
    try:
        r = para_tela(db, dono, max(dias, 20), camp.tenant_id)  # 20 dias para a conta; a tela mostra `dias`
    finally:
        usar_config_da_ar(db, anterior)
    linhas = db.execute(select(Tarefa.lead_id, func.count(Tarefa.id), func.min(Tarefa.data))
                        .join(Lead, Tarefa.lead_id == Lead.id)
                        .where(Tarefa.campanha_id == camp.id, Tarefa.status == "rascunho", Tarefa.canal == "email",
                               _recebe())
                        .group_by(Tarefa.lead_id)).all()
    r["empresas"] = len(linhas)
    r["emails"] = sum(n for _lead, n, _dia in linhas)
    inicio = min((dia for _lead, _n, dia in linhas), default=None)
    r["primeiros"] = vagas.quando_cabem(r, r["empresas"], inicio) if r["empresas"] else None
    r["dias"] = r["dias"][:dias]
    return r
