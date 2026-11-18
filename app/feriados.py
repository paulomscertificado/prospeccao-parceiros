"""Feriados de cada pessoa (pedido da Maria em 18/11/2026: "tem municípios que têm feriados, e isso impactaria nas
campanhas").

Os feriados de quem envia = os nacionais (automáticos: util.feriados_nacionais, com Carnaval, Sexta-feira Santa e
Corpus Christi) + os do ESTADO e da CIDADE onde a pessoa trabalha (cidade e UF no cadastro: Configurações > Usuários
ou Minha conta). Os do estado e da cidade são escritos por cada marca em Configurações > Feriados (chave
`feriados_locais` da AR: {"PE": "...", "PE/RECIFE": "..."}, uma data por linha, "16/07 Nossa Senhora do Carmo" todo
ano ou "20/11/2026 Ponto facultativo" só naquele ano).

Nos feriados da pessoa:
- as campanhas dela não marcam toques (campanhas._feriados → cadencias.dia_e_hora_futuros); antes, só a Renovação
  pulava feriados (as outras campanhas nem os nacionais);
- os toques já marcados para o dia mudam para o próximo dia de envio dela (remarcar: de hora em hora e ao salvar a
  cidade ou os feriados; as filas conferem de novo na hora de enviar: adiar_se_feriado);
- a Renovação não marca nem manda avisos (renovacao.dias_sem_envio(db, pessoa));
- não aparecem horários de reunião (agenda_horarios.horarios_livres).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from urllib.parse import quote_plus

from sqlalchemy import and_, or_, select

from . import util
from .banco import gravar_config, ler_config

log = logging.getLogger(__name__)

CHAVE = "feriados_locais"
UFS = {"AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
       "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
       "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
       "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
       "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
       "TO": "Tocantins"}
DIAS_REMARCAR = 120  # toques marcados até daqui a 4 meses mudam de dia quando caem num feriado de quem envia
_LINHA = re.compile(r"^\s*(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s*[-–:]?\s*(.*)$")
_SEM = object()


# ---------------------------------------------------------------- Local (UF e cidade)

def normalizar_uf(uf: str | None) -> str:
    uf = (uf or "").strip().upper()[:2]
    return uf if uf in UFS else ""


def normalizar_cidade(cidade: str | None) -> str:
    return re.sub(r"\s+", " ", (cidade or "").strip())[:120]


def chave_do_local(uf: str | None, cidade: str | None = "") -> str:
    """"PE" (o estado) ou "PE/RECIFE" (a cidade: maiúsculas, sem acento). Sem UF válida: ""."""
    uf = normalizar_uf(uf)
    if not uf:
        return ""
    cidade = util.chave_texto(cidade or "").upper()
    return f"{uf}/{cidade}" if cidade else uf


def nome_do_local(chave: str, exemplo: str = "") -> str:
    """Como o local aparece na tela: "Pernambuco (PE)" ou "Recife (PE)"."""
    uf, _, cidade = chave.partition("/")
    if not cidade:
        return f"{UFS.get(uf, uf)} ({uf})"
    return f"{exemplo or cidade.title()} ({uf})"


def link_de_busca(chave: str, ano: int, exemplo: str = "") -> str:
    """Pesquisa no Google pelos feriados do local (a tela mostra ao lado de cada quadro)."""
    uf, _, cidade = chave.partition("/")
    termo = (f"feriados municipais {exemplo or cidade.title()} {uf} {ano}" if cidade
             else f"feriados estaduais {UFS.get(uf, uf)} {ano}")
    return "https://www.google.com/search?q=" + quote_plus(termo)


# ---------------------------------------------------------------- Listas escritas na tela

def ler_lista(texto: str | None) -> tuple[list[tuple[int, int, int | None, str]], list[str]]:
    """Uma data por linha (ou separadas por ";"): "16/07 Nossa Senhora do Carmo" (todo ano) ou "20/11/2026 Ponto
    facultativo" (só naquele ano). Devolve ([(dia, mês, ano ou None, nome)], as linhas que não deu para entender)."""
    itens: list[tuple[int, int, int | None, str]] = []
    invalidas: list[str] = []
    for linha in re.split(r"[\n;]+", texto or ""):
        if not linha.strip():
            continue
        achou = _LINHA.match(linha)
        try:
            if not achou:
                raise ValueError(linha)
            dia, mes = int(achou.group(1)), int(achou.group(2))
            ano = int(achou.group(3)) if achou.group(3) else None
            date(ano or 2028, mes, dia)  # 2028 é bissexto: 29/02 sem ano vale
        except ValueError:
            invalidas.append(linha.strip()[:60])
            continue
        if any((d, m, a) == (dia, mes, ano) for d, m, a, _ in itens):
            continue
        itens.append((dia, mes, ano, achou.group(4).strip()[:80] or "Feriado"))
    return itens, invalidas


def texto_da_lista(itens: list[tuple[int, int, int | None, str]]) -> str:
    """O texto arrumado que fica gravado (em ordem de data)."""
    ordem = sorted(itens, key=lambda i: (i[2] or 0, i[1], i[0]))
    return "\n".join(f"{d:02d}/{m:02d}" + (f"/{a}" if a else "") + f" {n}" for d, m, a, n in ordem)


def _ler_da_ar(db, ar) -> str:
    """O valor gravado para a AR `ar` (None = o da plataforma), sem mexer na AR da sessão."""
    anterior = db.info.get("ar_config", _SEM)
    db.info["ar_config"] = ar
    try:
        return ler_config(db, CHAVE)
    finally:
        if anterior is _SEM:
            db.info.pop("ar_config", None)
        else:
            db.info["ar_config"] = anterior


def locais(db, ar=_SEM) -> dict[str, str]:
    """As listas de feriados da marca: {chave do local: texto}. Sem `ar`: a da tela (ou da rotina) de agora."""
    valor = ler_config(db, CHAVE) if ar is _SEM else _ler_da_ar(db, ar)
    try:
        dados = json.loads(valor or "{}")
    except ValueError:
        return {}
    if not isinstance(dados, dict):
        return {}
    return {k: v for k, v in dados.items() if isinstance(k, str) and isinstance(v, str) and v.strip()}


def gravar_locais(db, listas: dict[str, str]) -> None:
    """Grava as listas da marca da tela (só as que têm alguma data)."""
    gravar_config(db, CHAVE, json.dumps({k: v for k, v in sorted(listas.items()) if v.strip()}, ensure_ascii=False))
    db.info.pop("feriados_da_pessoa", None)


# ---------------------------------------------------------------- Feriados de uma pessoa

def _anos_padrao() -> tuple[int, ...]:
    hoje = date.today()
    return hoje.year, hoje.year + 1


def dias_de(db, ar, uf: str | None, cidade: str | None, anos: tuple[int, ...] | None = None) -> dict[date, str]:
    """Os feriados de um local: os nacionais + os do estado + os da cidade (listas da AR `ar`)."""
    anos = tuple(anos or _anos_padrao())
    dias: dict[date, str] = {}
    for ano in anos:
        dias.update(util.feriados_nacionais(ano))
    chave_uf = chave_do_local(uf)
    if not chave_uf:
        return dias
    listas = locais(db, ar)
    for chave in (chave_uf, chave_do_local(uf, cidade) if normalizar_cidade(cidade) else ""):
        for dia, mes, ano_fixo, nome in ler_lista(listas.get(chave, ""))[0] if chave else []:
            for ano in ([ano_fixo] if ano_fixo else anos):
                try:
                    dias.setdefault(date(ano, mes, dia), nome)
                except ValueError:  # 29/02 em ano que não é bissexto
                    pass
    return dias


def da_pessoa(db, pessoa, anos: tuple[int, ...] | None = None) -> dict[date, str]:
    """Os feriados de quem envia (ou de quem atende a reunião): nacionais + do estado + da cidade dela. Sem pessoa (ou
    sem UF no cadastro): só os nacionais."""
    if pessoa is None:
        return dias_de(db, None, "", "", anos)
    cache = db.info.setdefault("feriados_da_pessoa", {})
    chave = (pessoa.id, pessoa.tenant_id, pessoa.uf, pessoa.cidade, tuple(anos) if anos else None, date.today())
    if chave not in cache:
        cache[chave] = dias_de(db, pessoa.tenant_id, pessoa.uf, pessoa.cidade, anos)
    return cache[chave]


def dias_sem_envio(db, pessoa, anos: tuple[int, ...] | None = None) -> frozenset:
    return frozenset(da_pessoa(db, pessoa, anos))


def feriado_do_dia(db, pessoa, dia: date) -> str:
    """O nome do feriado, se `dia` é feriado para a pessoa ("" = dia normal)."""
    anos = None if dia.year in _anos_padrao() else (dia.year,)
    return da_pessoa(db, pessoa, anos).get(dia, "")


# ---------------------------------------------------------------- Toques marcados num feriado

def _responsavel(db, t):
    from . import conexoes

    return conexoes.responsavel(db, t.lead, None, t)


def _limite_da_renovacao(db, t):
    """Aviso de renovação: o dia do vencimento (o aviso não pode passar dele). None: não é renovação."""
    from .modelos import Campanha, Certificado

    camp = db.get(Campanha, t.campanha_id) if t.campanha_id else None
    if camp is None or camp.tipo != "renovacao" or not t.certificado_id:
        return None
    cert = db.get(Certificado, t.certificado_id)
    return cert.data_vencimento if cert is not None else None


def _horas_da_campanha(db, t) -> tuple[str, str]:
    from . import campanhas
    from .modelos import Campanha

    camp = db.get(Campanha, t.campanha_id) if t.campanha_id else None
    return (campanhas._hora_minima(db, camp), campanhas._hora_maxima(db, camp)) if camp is not None else ("", "")


def adiar_se_feriado(db, t, pessoa=None, hoje: date | None = None) -> str:
    """As filas, na hora de enviar: hoje é feriado de quem envia? O toque passa para o próximo dia de envio dela e a fila
    segue com os outros (devolve o nome do feriado; "" = pode enviar). Aviso de renovação que só caberia depois do
    vencimento sai assim mesmo (o cliente não pode ficar sem o aviso). Chamar com as configurações da AR da tarefa
    (usar_config_da_ar)."""
    from . import cadencias

    hoje = hoje or date.today()
    pessoa = pessoa if pessoa is not None else _responsavel(db, t)
    nome = feriado_do_dia(db, pessoa, hoje)
    if not nome:
        return ""
    minimo, maximo = _horas_da_campanha(db, t)
    data, hora = cadencias.dia_e_hora_futuros(db, hoje + timedelta(days=1), minimo=minimo, maximo=maximo,
                                              feriados=dias_sem_envio(db, pessoa))
    limite = _limite_da_renovacao(db, t)
    if limite is not None and data >= limite:
        return ""
    t.data, t.hora = data, hora
    return nome


def remarcar(db, hoje: date | None = None, pessoas: set[int] | None = None) -> int:
    """Toques em aberto (rascunho ou pendente) das campanhas e cadências que caem num feriado de quem envia passam para o
    próximo dia de envio dessa pessoa (um horário natural dentro do horário de envio), sem ficar antes do toque
    anterior da mesma empresa. A Renovação tem regras próprias (vencimento, 2 dias entre os avisos): ela usa
    renovacao.remarcar_feriados, com os feriados de quem é a campanha. `pessoas`: só os toques delas. Devolve quantos
    mudaram."""
    from sqlalchemy.orm import selectinload

    from . import cadencias, conexoes
    from .banco import usar_config_da_ar
    from .modelos import Campanha, Tarefa

    hoje = hoje or date.today()
    ate = hoje + timedelta(days=DIAS_REMARCAR)
    anos = tuple(sorted({hoje.year, ate.year}))
    candidatos = _dias_que_podem_ser_feriado(db, anos)
    candidatos = sorted(d for d in candidatos if hoje <= d <= ate)
    if not candidatos:
        return 0
    consulta = (select(Tarefa).outerjoin(Campanha, Tarefa.campanha_id == Campanha.id)
                .where(Tarefa.tipo == "prospeccao", Tarefa.status.in_(("rascunho", "pendente")),
                       Tarefa.data.in_(candidatos),
                       or_(Tarefa.campanha_id.is_(None),
                           and_(Campanha.tipo != "renovacao",
                                Campanha.status.in_(("aguardando_aprovacao", "ativa", "pausada")))))
                .options(selectinload(Tarefa.lead)))
    mudou = 0
    antes: dict[int, tuple] = {}  # id da tarefa -> (data, hora) de antes de mudar
    grupos: set[tuple] = set()
    for t in db.execute(consulta).scalars().all():
        pessoa = conexoes.responsavel(db, t.lead, None, t)
        if pessoas is not None and (pessoa is None or pessoa.id not in pessoas):
            continue
        if t.data not in da_pessoa(db, pessoa, anos):
            continue
        usar_config_da_ar(db, t.tenant_id)  # horário de envio e fim de semana da AR da tarefa
        minimo, maximo = _horas_da_campanha(db, t)
        antes[t.id] = (t.data, t.hora or "")
        t.data, t.hora = cadencias.dia_e_hora_futuros(db, t.data, minimo=minimo, maximo=maximo,
                                                      feriados=frozenset(da_pessoa(db, pessoa, anos)))
        grupos.add((t.campanha_id, t.lead_id))
        mudou += 1
    usar_config_da_ar(db, None)
    for campanha_id, lead_id in grupos:  # na ordem de antes, nenhum toque fica antes do anterior da mesma empresa
        if campanha_id is None or lead_id is None:
            continue
        da_empresa = db.execute(select(Tarefa).where(
            Tarefa.campanha_id == campanha_id, Tarefa.lead_id == lead_id, Tarefa.tipo == "prospeccao",
            Tarefa.status.in_(("rascunho", "pendente")))).scalars().all()
        maior = None
        for t in sorted(da_empresa, key=lambda x: (*antes.get(x.id, (x.data, x.hora or "")), x.id)):
            if maior is not None and (t.data, t.hora or "") < maior:
                t.data, t.hora = maior
                mudou += t.id not in antes
            maior = max(maior, (t.data, t.hora or "")) if maior is not None else (t.data, t.hora or "")
    if mudou:
        db.flush()
        log.info("Feriados: %s toques mudaram de dia (feriado de quem envia)", mudou)
    return mudou


def _dias_que_podem_ser_feriado(db, anos: tuple[int, ...]) -> set[date]:
    """Todos os dias que são feriado para alguém (os nacionais e os de todas as listas de todas as marcas): a consulta
    dos toques só olha esses dias."""
    from .modelos import Configuracao, ConfiguracaoAR

    dias: set[date] = set()
    for ano in anos:
        dias |= set(util.feriados_nacionais(ano))
    textos = [v for (v,) in db.execute(select(ConfiguracaoAR.valor).where(ConfiguracaoAR.chave == CHAVE)
                                       .execution_options(sem_filtro_de_ar=True)).all()]
    plataforma = db.get(Configuracao, CHAVE)
    if plataforma is not None:
        textos.append(plataforma.valor)
    for texto in textos:
        try:
            listas = json.loads(texto or "{}")
        except ValueError:
            continue
        for lista in (listas.values() if isinstance(listas, dict) else []):
            for dia, mes, ano_fixo, _ in ler_lista(lista if isinstance(lista, str) else "")[0]:
                for ano in ([ano_fixo] if ano_fixo else anos):
                    try:
                        dias.add(date(ano, mes, dia))
                    except ValueError:
                        pass
    return dias


# ---------------------------------------------------------------- Tela (Configurações > Feriados)

def painel(db) -> dict:
    """O que a tela mostra: os nacionais que faltam no ano (e o começo do próximo), as pessoas da marca com a cidade
    delas e um quadro para cada estado e cidade em uso (com o que já foi escrito)."""
    from .modelos import Usuario

    hoje = date.today()
    nacionais = sorted((d, n) for ano in (hoje.year, hoje.year + 1)
                       for d, n in util.feriados_nacionais(ano).items() if hoje <= d <= hoje + timedelta(days=365))
    pessoas = db.execute(select(Usuario).where(Usuario.ativo.is_(True), Usuario.perfil != "parceiro",
                                               Usuario.master.is_(False)).order_by(Usuario.nome)).scalars().all()
    listas = locais(db)
    quadros: dict[str, dict] = {}

    def quadro(chave: str, exemplo: str = "") -> dict:
        if chave not in quadros:
            quadros[chave] = {"chave": chave, "nome": nome_do_local(chave, exemplo), "texto": listas.get(chave, ""),
                              "pessoas": [], "busca": link_de_busca(chave, hoje.year, exemplo),
                              "cidade": "/" in chave}
        return quadros[chave]

    sem_local = []
    for p in pessoas:
        uf, cidade = normalizar_uf(p.uf), normalizar_cidade(p.cidade)
        if not uf:
            sem_local.append(p)
            continue
        quadro(chave_do_local(uf))["pessoas"].append(p.nome)
        if cidade:
            quadro(chave_do_local(uf, cidade), cidade)["pessoas"].append(p.nome)
    for chave in listas:
        if chave_do_local(*chave.split("/", 1)) == chave:
            quadro(chave)
    ordem = sorted(quadros.values(), key=lambda q: (q["chave"].split("/")[0], q["cidade"], q["nome"]))
    return {"nacionais": nacionais, "quadros": ordem, "pessoas": pessoas, "sem_local": sem_local, "ufs": UFS}
