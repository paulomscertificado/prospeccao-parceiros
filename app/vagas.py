"""Vagas de WhatsApp por número: quanto cabe por dia e por hora em cada número e uma agenda que não estoura.

Pedido da Maria em 23/11/2026: "se eu fizer muitas campanhas, essas campanhas vão acumular a quantidade de disparos
dentro de um único número ... quero que não fique gargalando, não fique acumulando e que eu não fique com as mensagens
atrasadas aqui na minha fila". No dia 23/11 havia 128 WhatsApps marcados para um dia em que cabiam uns 75: as campanhas
eram marcadas pelos dias da cadência sem olhar o que já estava marcado, o excesso atrasava e, com mais de 2 dias de
atraso, parava esperando um clique.

- Ritmo de cada número: um WhatsApp automático a cada 8 a 12 minutos (Configurações > Geral, intervalo_whatsapp_*; a
  fila dá a vez a cada número, campanhas.processar_fila_whatsapp) e no máximo limite_hora_whatsapp por hora: cabem uns
  6 por hora, no horário de envio da marca, fora do almoço (12:00-13:30) e com 20 minutos de folga no fim (as mesmas
  regras do cadencias.hora_natural).
- Ocupação: os WhatsApps já marcados nas campanhas ativas, por número, dia e hora, só de quem vai receber (campo
  WhatsApp preenchido, sem SAIR, sem pausa, sem resposta: sdr.automacao_ativa). Os da API oficial ficam de fora (fila
  própria). O número de cada toque é o fixado na campanha ou o do responsável pelo lead (cada pessoa tem o seu
  disparo: o próprio número ou um compartilhado com ela).
- planejar(): põe cada WhatsApp numa vaga do número: fica no horário marcado se a hora dele ainda tem vaga; senão vai
  para o primeiro dia com vaga, na hora mais vazia, mantendo o espaço da cadência entre os toques da mesma empresa. O
  e-mail do mesmo toque vai junto (na mesma hora, ou umas 2 h depois, como foi montado) e o toque só de e-mail anda o
  necessário para não passar na frente. Usado ao aprovar a campanha (campanhas.aprovar).
- replanejar(): de hora em hora (rotinas._rotina_hora), os atrasados de dias anteriores e os que estão numa hora já
  lotada do número nos próximos dias vão para as próximas vagas.
- resumo() / para_tela() / da_campanha(): as vagas dos próximos dias do número, para a Nova campanha, o Buscar agora
  das Empresas novas e a aprovação (templates/_vagas_whatsapp.html).
"""

import logging
import random
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, or_, select

from . import config, util
from .banco import agora, ler_config, ler_config_int, usar_config_da_ar
from .modelos import Campanha, Lead, Tarefa, Usuario

log = logging.getLogger(__name__)

ALMOCO = (12 * 60, 13 * 60 + 30)  # sem envio marcado no almoço (como cadencias.hora_natural)
FOLGA_FIM = 20                    # minutos antes do fim do horário de envio
FOLGA_AGORA = 15                  # envio marcado para hoje: pelo menos 15 minutos depois de agora
DIAS_DE_BUSCA = 60                # procura vaga em até 60 dias
DIAS_DA_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def por_hora(db) -> int:
    """Quantos WhatsApps automáticos cabem por hora em cada número: o ritmo da fila (8 a 12 minutos entre um e outro = 6
    por hora) e o limite por hora de Configurações > Geral, o menor dos dois."""
    from . import campanhas

    minimo, maximo = campanhas.intervalo_automatico(db, "whatsapp")
    ritmo = max(1, int(3600 // ((minimo + maximo) / 2)))
    limite = ler_config_int(db, "limite_hora_whatsapp", 0)
    return max(1, min(ritmo, limite) if limite > 0 else ritmo)


def _minutos(hhmm: str, padrao: int) -> int:
    texto = util.hora_hhmm(hhmm or "", "")
    if not texto:
        return padrao
    h, m = texto.split(":")
    return int(h) * 60 + int(m)


def vagas_por_hora(db, minimo: str = "", maximo: str = "") -> dict[int, tuple[int, int, int]]:
    """{hora: (vagas, primeiro minuto, último minuto)} no horário de envio da marca das configurações de agora (fora do
    almoço e da folga do fim; `minimo`/`maximo` = janela da campanha, como a da Renovação). Ex.: 07:30-20:00 e 6 por
    hora: 07h = 3 vagas (07:30-07:59), 08h-11h = 6, 12h = nenhuma, 13h = 3 (13:30-13:59), 14h-18h = 6, 19h = 4."""
    inicio = _minutos(ler_config(db, "horario_envio_inicio"), 8 * 60 + 30)
    fim = _minutos(ler_config(db, "horario_envio_fim"), 18 * 60)
    if minimo:
        inicio = max(inicio, _minutos(minimo, inicio))
    if maximo:
        fim = min(fim, _minutos(maximo, fim))
    fim -= FOLGA_FIM
    cabem = por_hora(db)
    horas: dict[int, tuple[int, int, int]] = {}
    for hora in range(inicio // 60, fim // 60 + 1):
        minutos = [m for m in range(max(inicio, hora * 60), min(fim, hora * 60 + 59) + 1)
                   if not ALMOCO[0] <= m < ALMOCO[1]]
        vagas = (cabem * len(minutos)) // 60
        if vagas:
            horas[hora] = (vagas, minutos[0], minutos[-1])
    return horas


def _recebe():
    """Condição do banco: o lead recebe WhatsApp automático (campo preenchido, sem SAIR, sem pausa, não perdido e sem
    resposta, como sdr.automacao_ativa). Os toques dos outros não saem e não ocupam vaga."""
    parados = [s for s, etapa in config.ETAPA_DO_STATUS.items() if etapa >= 2] + list(config.STATUS_PERDIDO)
    return and_(func.coalesce(Lead.whatsapp, "") != "", Lead.automacao_pausada.is_not(True), Lead.opt_out.is_not(True),
                Lead.anonimizado.is_not(True), func.coalesce(Lead.status, "").not_in(parados))


def recebe(lead: Lead | None) -> bool:
    """O mesmo que _recebe(), para um lead já carregado."""
    from . import sdr

    return bool(lead is not None and (lead.whatsapp or "").strip() and sdr.automacao_ativa(lead))


class Numeros:
    """O número de WhatsApp de cada envio, para contar as vagas: o fixado na campanha ou o do responsável pelo lead, o
    mesmo que a fila usa (conexoes.para_enviar: o próprio, se conectado, senão um compartilhado com ele e conectado).
    Ex.: quem dispara pelo número compartilhado de outra pessoa divide as vagas daquele número. Sem número conectado
    (ou o computador do WhatsApp Leads fora do ar): o próprio, senão o primeiro compartilhado. Guarda a resposta de
    cada pessoa."""

    def __init__(self, db):
        self.db = db
        self._da_pessoa: dict = {}

    def da_pessoa(self, usuario_id: int | None) -> str:
        if usuario_id in self._da_pessoa:
            return self._da_pessoa[usuario_id]
        from . import conexoes

        chave = f"pessoa:{usuario_id or 0}"
        pessoa = self.db.get(Usuario, usuario_id) if usuario_id else None
        if pessoa is not None:
            try:
                chave = conexoes.para_enviar(self.db, pessoa)
            except conexoes.SemNumero:
                proprio = conexoes.minha(self.db, pessoa)
                if proprio is not None:
                    chave = proprio.id
                else:
                    outros = sorted((c for c in conexoes.todas(self.db) if conexoes.pode_disparar(pessoa, c)),
                                    key=lambda c: (c.id != conexoes.PRINCIPAL, c.criado_em or datetime.min))
                    if outros:
                        chave = outros[0].id
        self._da_pessoa[usuario_id] = chave
        return chave

    def do_toque(self, conexao_fixa: str | None, vendedor_id: int | None, usuario_id: int | None) -> str:
        return conexao_fixa or self.da_pessoa(vendedor_id or usuario_id)


def _hora_de(hhmm: str | None) -> int:
    try:
        return int((hhmm or "")[:2])
    except ValueError:
        return 9


def ocupacao(db, desde: date, sem: set = frozenset(), numeros: Numeros | None = None) -> Counter:
    """WhatsApps já marcados por (número, dia, hora), a partir de `desde` (fora os ids de `sem`): os pendentes das
    campanhas ativas, de quem vai receber. A API oficial não conta (fila própria); rascunho de campanha que espera
    aprovação também não (pode nem ser aprovada: ao aprovar, ela entra nas vagas que sobraram)."""
    numeros = numeros or Numeros(db)
    linhas = db.execute(
        select(Tarefa.id, Tarefa.data, Tarefa.hora, Tarefa.usuario_id, Lead.vendedor_id, Campanha.conexao_id)
        .join(Lead, Tarefa.lead_id == Lead.id).join(Campanha, Tarefa.campanha_id == Campanha.id)
        .where(Tarefa.status == "pendente", Tarefa.canal == "whatsapp", Tarefa.tipo == "prospeccao",
               Tarefa.data >= desde, Campanha.status == "ativa", Campanha.envio_oficial.is_not(True), _recebe())
        .execution_options(sem_filtro_de_ar=True)).all()
    carga: Counter = Counter()
    for tid, dia, hora, uid, vid, fixa in linhas:
        if tid not in sem:
            carga[(numeros.do_toque(fixa, vid, uid), dia, _hora_de(hora))] += 1
    return carga


def _dia_de_envio(dia: date, pular_fds: bool, sem_envio: frozenset) -> date:
    """O próprio dia ou o próximo dia de envio (fora do fim de semana, se a marca pula, e dos feriados)."""
    for _ in range(DIAS_DE_BUSCA):
        if not ((pular_fds and dia.weekday() >= 5) or dia in sem_envio):
            return dia
        dia += timedelta(days=1)
    return dia


def _cabem_na_hora(vagas: int, de: int, ate: int, a_partir: int) -> int:
    """As vagas da hora a partir do minuto `a_partir` (hoje: só o que falta dela)."""
    if a_partir <= de:
        return vagas
    if a_partir > ate:
        return 0
    return (vagas * (ate - a_partir + 1)) // (ate - de + 1)


def _primeira_vaga(numero: str, alvo: date, carga: Counter, no_dia: Counter, horas: dict, pular_fds: bool,
                   sem_envio: frozenset, momento: datetime, atual: tuple | None = None) -> tuple[date, str] | None:
    """Dia e horário do WhatsApp no número. `atual` (dia, hora) marcado no dia `alvo` com vaga na hora dele: fica onde
    está (campanha que cabe não muda nada). Senão: o primeiro dia a partir de `alvo` com vaga, na hora mais vazia dele
    (espalha pelo dia), com os minutos espalhados dentro da hora (nunca redondos, como cadencias.hora_natural). Hoje:
    só o que falta do dia, e o que já venceu hoje e ainda não saiu também ocupa (`no_dia` = total por número e dia).
    None = nenhuma vaga em DIAS_DE_BUSCA dias."""
    hoje = momento.date()
    agora_min = momento.hour * 60 + momento.minute

    def dia_de_envio(dia: date) -> bool:
        return not ((pular_fds and dia.weekday() >= 5) or dia in sem_envio)

    def cabe_hoje(a_partir: int) -> bool:
        return no_dia[(numero, hoje)] < sum(_cabem_na_hora(v, de, ate, a_partir) for v, de, ate in horas.values())

    if atual is not None and atual[0] == alvo and atual[0] >= hoje and dia_de_envio(alvo):
        minuto = _minutos(atual[1] or "", -1)
        hora = minuto // 60
        if hora in horas and horas[hora][1] <= minuto <= horas[hora][2] and (alvo > hoje or minuto > agora_min):
            vagas, de, ate = horas[hora]
            a_partir = agora_min if alvo == hoje else -1
            if (carga[(numero, alvo, hora)] < _cabem_na_hora(vagas, de, ate, a_partir)
                    and (alvo > hoje or cabe_hoje(a_partir))):
                return atual
    dia = max(alvo, hoje)
    for _ in range(DIAS_DE_BUSCA):
        a_partir = agora_min + FOLGA_AGORA if dia == hoje else -1
        if dia_de_envio(dia) and (dia > hoje or cabe_hoje(a_partir)):
            livres = []
            for hora, (vagas, de, ate) in horas.items():
                cabem = _cabem_na_hora(vagas, de, ate, a_partir)
                usados = carga[(numero, dia, hora)]
                if usados < cabem:
                    livres.append((usados / cabem, hora, usados))
            if livres:
                _ocupado, hora, usados = min(livres)  # a hora mais vazia (empate: a mais cedo)
                vagas, de, ate = horas[hora]
                passo = max(1, (ate - de + 1) // vagas)
                minuto = max(de + usados * passo, a_partir)
                minuto = min(ate, minuto + random.randint(0, min(4, passo - 1)))
                if minuto % 5 == 0 and minuto < ate:
                    minuto += 1  # nada de 09:00, 10:15...
                return dia, f"{minuto // 60:02d}:{minuto % 60:02d}"
        dia += timedelta(days=1)
    return None


def _chave_do_passo(t: Tarefa):
    """O toque de cada tarefa: o passo da cadência (WhatsApp e e-mail do mesmo toque têm o mesmo) ou, sem passo, o dia."""
    return ("passo", t.passo_id) if t.passo_id else ("dia", t.data)


def planejar(db, tarefas: list[Tarefa], desde: date | None = None, ordem=None, minimo: str = "",
             maximo: str = "") -> dict:
    """Põe os WhatsApps de `tarefas` nas vagas do número de cada um (sem estourar nenhuma hora), a partir do dia marcado
    de cada um (nunca antes de `desde`, nem antes de hoje), mantendo entre os toques da mesma empresa pelo menos o
    espaço que eles tinham. O e-mail do mesmo toque vai junto: na mesma hora, se estava junto, ou umas 2 h depois do
    WhatsApp; toque só de e-mail anda o necessário para não passar na frente. E-mail de dia que já passou fica como
    está (a fila de e-mail solta os atrasados). `ordem`: a chave para escolher quem fica com as vagas (lista de tarefas
    de uma empresa -> valor); padrão: quem estava marcado antes. `minimo`/`maximo`: a janela da campanha. As
    configurações (horário, ritmo) são as de agora: quem chama liga as da AR (banco.usar_config_da_ar). Devolve
    {"movidos" (WhatsApps que mudaram de dia), "de", "ate" (os dias do primeiro WhatsApp de cada empresa), "empresas"}."""
    from . import cadencias, feriados

    momento = agora()
    hoje = momento.date()
    desde = max(desde or hoje, hoje)
    numeros = Numeros(db)
    carga = ocupacao(db, hoje, {t.id for t in tarefas if t.id}, numeros)
    no_dia: Counter = Counter()
    for (num, dia, _hora), n in carga.items():
        no_dia[(num, dia)] += n
    horas = vagas_por_hora(db, minimo, maximo)
    pular_fds = ler_config(db, "pular_fim_de_semana") == "1"
    grupos: dict[tuple, list[Tarefa]] = {}
    for t in tarefas:
        grupos.setdefault((t.campanha_id, t.lead_id), []).append(t)
    sem_envio_de: dict = {}
    feito = {"movidos": 0, "de": None, "ate": None, "empresas": 0}

    def padrao(lista):
        return min((t.data, t.hora or "", t.id or 0) for t in lista)

    for lista in sorted(grupos.values(), key=ordem or padrao):
        lead = lista[0].lead
        if not recebe(lead) or not horas:
            continue  # o WhatsApp não sai (campo em branco, SAIR, respondeu): nada a acomodar
        responsavel = lead.vendedor_id or lista[0].usuario_id
        if responsavel not in sem_envio_de:
            pessoa = db.get(Usuario, responsavel) if responsavel else None
            sem_envio_de[responsavel] = feriados.dias_sem_envio(db, pessoa) if pessoa else frozenset()
        sem_envio = sem_envio_de[responsavel]
        camp = db.get(Campanha, lista[0].campanha_id) if lista[0].campanha_id else None
        numero = numeros.do_toque(camp.conexao_id if camp else "", lead.vendedor_id, lista[0].usuario_id)
        passos: dict = {}
        for t in lista:
            passos.setdefault(_chave_do_passo(t), []).append(t)
        antes_ant = novo_ant = None
        zap_ant, primeiro = False, True
        for passo in sorted(passos.values(), key=lambda p: min((t.data, t.hora or "", t.id or 0) for t in p)):
            original = min(t.data for t in passo)
            zap = next((t for t in passo if t.canal == "whatsapp"), None)
            alvo = max(original, desde)
            if novo_ant is not None:
                espaco = (original - antes_ant).days
                if zap is not None and zap_ant:
                    espaco = max(1, espaco)  # dois WhatsApps para a mesma empresa nunca no mesmo dia
                alvo = max(alvo, novo_ant + timedelta(days=espaco))
            if zap is not None:
                zap_antes = (zap.data, zap.hora)
                vaga = _primeira_vaga(numero, alvo, carga, no_dia, horas, pular_fds, sem_envio, momento,
                                      atual=zap_antes)
                if vaga is not None:
                    zap.data, zap.hora = vaga
                    carga[(numero, zap.data, _hora_de(zap.hora))] += 1
                    no_dia[(numero, zap.data)] += 1
                    if zap.data != zap_antes[0]:
                        feito["movidos"] += 1
                for t in passo:
                    if ((zap.data, zap.hora) == zap_antes or t.canal != "email" or t.data < hoje
                            or (t.data, t.hora) == (zap.data, zap.hora)):
                        continue  # o WhatsApp ficou onde estava (o e-mail também fica)
                    if (t.data, t.hora) == zap_antes:  # estava junto com o WhatsApp: continua junto
                        t.data, t.hora = zap.data, zap.hora
                    elif t.data == zap_antes[0] and (t.hora or "") >= (zap_antes[1] or ""):  # depois dele, no dia
                        t.data, t.hora = cadencias.depois_de(db, zap.data, zap.hora or "09:00", pular_fds=pular_fds,
                                                             minimo=minimo, maximo=maximo, feriados=sem_envio)
                    elif zap.data != zap_antes[0]:  # em outro dia: anda os mesmos dias que o WhatsApp
                        t.data = _dia_de_envio(t.data + (zap.data - zap_antes[0]), pular_fds, sem_envio)
                novo = zap.data
                if primeiro:
                    feito["de"] = min(feito["de"] or zap.data, zap.data)
                    feito["ate"] = max(feito["ate"] or zap.data, zap.data)
                    feito["empresas"] += 1
                    primeiro = False
            else:  # toque só de e-mail: anda só o necessário para não passar na frente do anterior
                novo = original
                if alvo > original:
                    for t in passo:
                        if t.data >= hoje:
                            t.data = _dia_de_envio(t.data + (alvo - original), pular_fds, sem_envio)
                    novo = min(t.data for t in passo)
            antes_ant, novo_ant, zap_ant = original, novo, zap is not None
    return feito


def _ja_comecaram(db, pares: set) -> set:
    """Os (campanha, lead) de `pares` em que a empresa já recebeu algum toque (a conversa começou)."""
    if not pares:
        return set()
    linhas = db.execute(select(Tarefa.campanha_id, Tarefa.lead_id).where(
        Tarefa.campanha_id.in_({c for c, _ in pares}), Tarefa.status == "feita").distinct()
        .execution_options(sem_filtro_de_ar=True)).all()
    return {(c, l) for c, l in linhas if (c, l) in pares}


def replanejar(db, hoje: date | None = None, so_campanhas: set | None = None) -> int:
    """De hora em hora: os WhatsApps de campanha que sai sozinha que ficaram de dias anteriores (o número caiu, a fila
    não deu conta) e os que estão numa hora já lotada do número nos próximos dias (campanha marcada antes das vagas,
    número trocado, limite por hora diminuído) vão para as próximas vagas do número; os toques seguintes da mesma
    empresa andam junto para manter o espaço. Antes, com mais de 2 dias de atraso, eles paravam esperando um clique e a
    lista de Atrasados só crescia. Quem já começou a conversa fica com as vagas; anda o primeiro toque de quem ainda não
    recebeu nada. Ficam de fora a Renovação (tem prazo: renovacao.ajustar_a_etapa cuida dela), a API oficial (fila
    própria), as campanhas em que o contato frio espera o clique (o atraso delas é o clique) e os toques de hoje (a
    fila está mandando). `so_campanhas`: só estas campanhas (None = todas). Devolve quantos WhatsApps mudaram de dia."""
    from sqlalchemy.orm import selectinload

    from . import campanhas

    hoje = hoje or agora().date()
    consulta = (
        select(Tarefa.campanha_id, Tarefa.lead_id, Tarefa.data, Tarefa.hora, Tarefa.usuario_id, Lead.vendedor_id,
               Campanha.conexao_id, Campanha.tenant_id)
        .join(Campanha, Tarefa.campanha_id == Campanha.id).join(Lead, Tarefa.lead_id == Lead.id)
        .where(Tarefa.status == "pendente", Tarefa.canal == "whatsapp", Tarefa.tipo == "prospeccao",
               Tarefa.data != hoje, Campanha.status == "ativa", Campanha.aprovado_em.is_not(None),
               Campanha.tipo != "renovacao", Campanha.envio_oficial.is_not(True),
               or_(Campanha.tipo.in_(campanhas.TIPOS_QUE_SAEM_SOZINHOS), Campanha.whatsapp_sozinho.is_(True)),
               _recebe()))
    if so_campanhas is not None:
        consulta = consulta.where(Tarefa.campanha_id.in_(so_campanhas))
    candidatos = db.execute(consulta.execution_options(sem_filtro_de_ar=True)).all()
    if not candidatos:
        return 0
    numeros = Numeros(db)
    futuros = any(linha.data > hoje for linha in candidatos)
    carga = ocupacao(db, hoje + timedelta(days=1), numeros=numeros) if futuros else Counter()
    por_ar: dict = {}
    for linha in candidatos:
        por_ar.setdefault(linha.tenant_id, []).append(linha)
    movidos = 0
    anterior = db.info.get("ar_config")
    try:
        for ar, linhas in por_ar.items():
            usar_config_da_ar(db, ar)  # o horário e o ritmo da marca
            horas = vagas_por_hora(db)
            pares = set()
            for linha in linhas:
                if linha.data < hoje:
                    pares.add((linha.campanha_id, linha.lead_id))  # atrasado
                    continue
                hora = _hora_de(linha.hora)
                numero = numeros.do_toque(linha.conexao_id, linha.vendedor_id, linha.usuario_id)
                if hora in horas and carga[(numero, linha.data, hora)] > horas[hora][0]:
                    pares.add((linha.campanha_id, linha.lead_id))  # numa hora lotada do número
            if not pares:
                continue
            tarefas = [t for t in db.execute(select(Tarefa).where(
                Tarefa.campanha_id.in_({c for c, _ in pares}), Tarefa.status == "pendente",
                Tarefa.tipo == "prospeccao", Tarefa.canal.in_(("whatsapp", "email")))
                .options(selectinload(Tarefa.lead)).execution_options(sem_filtro_de_ar=True)).scalars()
                if (t.campanha_id, t.lead_id) in pares]
            comecou = _ja_comecaram(db, pares)

            def ordem(lista, comecou=comecou):
                return ((lista[0].campanha_id, lista[0].lead_id) not in comecou,
                        min((t.data, t.hora or "", t.id or 0) for t in lista))

            movidos += planejar(db, tarefas, hoje, ordem=ordem)["movidos"]
    finally:
        usar_config_da_ar(db, anterior)
    if movidos:
        log.info("Vagas: %s WhatsApps foram para as próximas vagas dos números (atrasados ou hora lotada)", movidos)
    return movidos


def _titulo(dia: date, hoje: date) -> str:
    if dia == hoje:
        return "hoje"
    if dia == hoje + timedelta(days=1):
        return "amanhã"
    return f"{DIAS_DA_SEMANA[dia.weekday()]} {dia:%d/%m}"


def resumo(db, pessoa: Usuario | None, dias: int = 5, conexao_fixa: str = "") -> dict:
    """As vagas de WhatsApp do número de `pessoa` (ou do fixado na campanha) nos próximos `dias` dias de envio, para as
    telas: {"numero", "dias": [{"dia", "titulo", "cabem", "marcados", "livres"}], "por_hora", "por_dia", "livres"}.
    Hoje: só as horas que faltam, e o que já venceu hoje e ainda não saiu conta como marcado."""
    from . import feriados

    momento = agora()
    hoje = momento.date()
    numeros = Numeros(db)
    numero = conexao_fixa or numeros.da_pessoa(pessoa.id if pessoa else None)
    carga = ocupacao(db, hoje, numeros=numeros)
    horas = vagas_por_hora(db)
    pular_fds = ler_config(db, "pular_fim_de_semana") == "1"
    sem_envio = feriados.dias_sem_envio(db, pessoa) if pessoa else frozenset()
    agora_min = momento.hour * 60 + momento.minute + FOLGA_AGORA
    lista, dia = [], hoje
    for _ in range(dias + 21):
        if len(lista) >= dias:
            break
        if not ((pular_fds and dia.weekday() >= 5) or dia in sem_envio):
            a_partir = agora_min if dia == hoje else -1
            cabem = sum(_cabem_na_hora(v, de, ate, a_partir) for v, de, ate in horas.values())
            marcados = sum(n for (num, d, _h), n in carga.items() if num == numero and d == dia)
            if dia != hoje or cabem or marcados:
                lista.append({"dia": dia, "titulo": _titulo(dia, hoje), "cabem": cabem, "marcados": marcados,
                              "livres": max(0, cabem - marcados)})
        dia += timedelta(days=1)
    return {"numero": numero, "dias": lista, "por_hora": por_hora(db),
            "por_dia": sum(v for v, _de, _ate in horas.values()), "livres": sum(d["livres"] for d in lista)}


def nome_do_numero(db, numero: str) -> str:
    """O nome do número para as telas ("" = a pessoa ainda não tem número)."""
    from . import conexoes

    if not numero or numero.startswith("pessoa:"):
        return ""
    c = db.get(conexoes.ConexaoWhatsApp, numero)
    return c.nome if c else numero


def para_tela(db, pessoa: Usuario | None, dias: int = 5, conexao_fixa: str = "") -> dict:
    """resumo() com o nome do número e o intervalo da fila, para o quadro _vagas_whatsapp.html."""
    from . import campanhas

    r = resumo(db, pessoa, dias, conexao_fixa)
    r["nome"] = nome_do_numero(db, r["numero"])
    r["intervalo"] = campanhas.texto_do_intervalo(db, "whatsapp")
    return r


def da_campanha(db, camp: Campanha, dias: int = 7) -> dict | None:
    """Para a aprovação: as vagas do número da campanha (o fixado nela ou o de quem é a campanha) e quanto ela pede
    (os WhatsApps dos rascunhos de quem vai receber). None = campanha sem WhatsApp pela fila do número (Renovação tem
    prazo e a API oficial tem fila própria)."""
    if camp.tipo == "renovacao" or camp.envio_oficial or "whatsapp" not in (camp.canais or ""):
        return None
    dono = db.get(Usuario, camp.usuario_id) if camp.usuario_id else None
    anterior = db.info.get("ar_config")
    usar_config_da_ar(db, camp.tenant_id)  # o horário e o ritmo da marca da campanha
    try:
        r = para_tela(db, dono, max(dias, 20), camp.conexao_id or "")  # 20 dias para a conta; a tela mostra `dias`
    finally:
        usar_config_da_ar(db, anterior)
    linhas = db.execute(select(Tarefa.lead_id, func.count(Tarefa.id), func.min(Tarefa.data))
                        .join(Lead, Tarefa.lead_id == Lead.id)
                        .where(Tarefa.campanha_id == camp.id, Tarefa.status == "rascunho", Tarefa.canal == "whatsapp",
                               _recebe())
                        .group_by(Tarefa.lead_id)).all()
    r["empresas"] = len(linhas)
    r["whatsapps"] = sum(n for _lead, n, _dia in linhas)
    inicio = min((dia for _lead, _n, dia in linhas), default=None)
    r["primeiros"] = quando_cabem(r, r["empresas"], inicio) if r["empresas"] else None
    r["dias"] = r["dias"][:dias]
    return r


def quando_cabem(resumo_: dict, quantidade: int, desde: date | None = None) -> dict | None:
    """Com as vagas livres de `resumo_` a partir de `desde` (o dia marcado da campanha: nada sai antes dele), entre que
    dias saem `quantidade` WhatsApps (o primeiro toque de cada empresa): {"de": dia do resumo, "ate": dia do resumo}.
    None = não cabem nos dias do resumo."""
    soma, primeiro = 0, None
    for item in resumo_["dias"]:
        if (desde and item["dia"] < desde) or not item["livres"]:
            continue
        primeiro = primeiro or item
        soma += item["livres"]
        if soma >= quantidade:
            return {"de": primeiro, "ate": item}
    return None
