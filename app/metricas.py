"""Indicadores do dashboard, relatórios e respostas prontas da IA Comercial.

As contas são feitas em Python sobre colunas enxutas: funcionam igual no SQLite e no PostgreSQL.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, util
from .banco import ler_config_int
from .modelos import Certificado, Cliente, Lead, Parceiro, Tarefa, Usuario, Venda
from .util import taxa


@dataclass
class Periodo:
    inicio: date
    fim: date
    nome: str

    @property
    def dias(self) -> int:
        return (self.fim - self.inicio).days + 1


def periodo(codigo: str) -> Periodo:
    hoje = date.today()
    opcoes = {"7d": (7, "Últimos 7 dias"), "30d": (30, "Últimos 30 dias"), "90d": (90, "Últimos 90 dias"),
              "12m": (365, "Últimos 12 meses")}
    if codigo == "tudo":
        return Periodo(date(2000, 1, 1), hoje, "Todo o período")
    dias, nome = opcoes.get(codigo, opcoes["30d"])
    return Periodo(hoje - timedelta(days=dias - 1), hoje, nome)


def _no_periodo(valor, p: Periodo) -> bool:
    if valor is None:
        return False
    d = valor.date() if isinstance(valor, datetime) else valor
    return p.inicio <= d <= p.fim


def _escopo_leads(consulta, usuario: Usuario, vendedor_id: int | None):
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        return consulta.where(Lead.vendedor_id == usuario.id)
    if vendedor_id:
        return consulta.where(Lead.vendedor_id == vendedor_id)
    return consulta


def _escopo_vendas(consulta, usuario: Usuario, vendedor_id: int | None):
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        return consulta.where(Venda.vendedor_id == usuario.id)
    if vendedor_id:
        return consulta.where(Venda.vendedor_id == vendedor_id)
    return consulta


def _leads(db: Session, usuario: Usuario, vendedor_id=None):
    consulta = select(Lead.id, Lead.criado_em, Lead.status, Lead.estado, Lead.cidade, Lead.vendedor_id,
                      Lead.origem, Lead.especialidade, Lead.tipo_empresa, Lead.score, Lead.contatado_em,
                      Lead.respondeu_em, Lead.interessado_em, Lead.reuniao_em, Lead.proposta_em, Lead.convertido_em,
                      Lead.anonimizado)
    return db.execute(_escopo_leads(consulta, usuario, vendedor_id)).all()


def _vendas(db: Session, usuario: Usuario, vendedor_id=None):
    consulta = select(Venda.id, Venda.data, Venda.valor, Venda.custo, Venda.comissao, Venda.parceiro_id,
                      Venda.vendedor_id, Venda.tipo, Venda.comissao_paga)
    return db.execute(_escopo_vendas(consulta, usuario, vendedor_id)).all()


def _parceiros(db: Session, usuario: Usuario, vendedor_id=None):
    consulta = select(Parceiro)
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where(Parceiro.vendedor_id == usuario.id)
    elif vendedor_id:
        consulta = consulta.where(Parceiro.vendedor_id == vendedor_id)
    return list(db.execute(consulta).scalars())


# ---------------------------------------------------------------- Indicadores principais

def indicadores(db: Session, usuario: Usuario, p: Periodo, vendedor_id: int | None = None) -> dict:
    leads = _leads(db, usuario, vendedor_id)
    do_periodo = [l for l in leads if _no_periodo(l.criado_em, p)]
    contatados = [l for l in leads if _no_periodo(l.contatado_em, p)]
    responderam = [l for l in leads if _no_periodo(l.respondeu_em, p)]
    interessados = [l for l in leads if _no_periodo(l.interessado_em, p)]
    reunioes = [l for l in leads if _no_periodo(l.reuniao_em, p)]
    propostas = [l for l in leads if _no_periodo(l.proposta_em, p)]
    convertidos = [l for l in leads if _no_periodo(l.convertido_em, p)]
    vendas = [v for v in _vendas(db, usuario, vendedor_id) if _no_periodo(v.data, p)]
    parceiros = _parceiros(db, usuario, vendedor_id)
    status_parc = Counter(x.status for x in parceiros)
    receita = sum(v.valor for v in vendas)
    custo = sum(v.custo for v in vendas)
    comissao = sum(v.comissao for v in vendas)
    parceiros_com_venda = {v.parceiro_id for v in vendas if v.parceiro_id}
    meses = max(p.dias / 30.0, 1) if p.nome != "Todo o período" else max(
        ((p.fim - (min((l.criado_em.date() for l in leads), default=p.fim))).days + 1) / 30.0, 1)
    custo_prospeccao = ler_config_int(db, "custo_mensal_prospeccao", 0) * meses
    agendadas = db.execute(_escopo_tarefas(select(func.count(Tarefa.id)).where(
        Tarefa.tipo == "reuniao", Tarefa.status == "pendente"), usuario)).scalar() or 0
    ind = {
        "leads_encontrados": len(do_periodo),
        "leads_novos": sum(1 for l in do_periodo if l.status in ("Novo", "Pesquisando", "Abordagem criada")),
        "leads_contatados": len(contatados),
        "leads_responderam": len(responderam),
        "leads_interessados": len(interessados),
        "reunioes_agendadas": agendadas,
        "reunioes_periodo": len(reunioes),
        "propostas_enviadas": len(propostas),
        "parceiros_convertidos": len(convertidos),
        "parceiros_cadastrados": len(parceiros),
        "parceiros_ativos": status_parc.get("ATIVO", 0),
        "parceiros_inativos": status_parc.get("INATIVO", 0) + status_parc.get("BLOQUEADO", 0),
        "parceiros_ativacao": status_parc.get("EM ATIVAÇÃO", 0),
        "certificados_vendidos": len(vendas),
        "receita": receita, "custo": custo, "comissao": comissao, "lucro_bruto": receita - custo - comissao,
        "taxa_contato": taxa(len(contatados), len(do_periodo)),
        "taxa_resposta": taxa(len(responderam), len(contatados)),
        "taxa_interesse": taxa(len(interessados), len(contatados)),
        "taxa_reuniao": taxa(len(reunioes), len(contatados)),
        "taxa_conversao": taxa(len(convertidos), len(do_periodo)),
        "custo_por_lead": custo_prospeccao / len(do_periodo) if do_periodo else 0,
        "custo_por_parceiro": (custo_prospeccao + 0) / len(convertidos) if convertidos else 0,
        "custo_prospeccao": custo_prospeccao,
        "receita_por_parceiro": receita / len(parceiros_com_venda) if parceiros_com_venda else 0,
        "ticket_medio": receita / len(vendas) if vendas else 0,
        "certificados_por_parceiro": round(len(vendas) / len(parceiros_com_venda), 1) if parceiros_com_venda else 0,
        "comissao_media": comissao / len(vendas) if vendas else 0,
    }
    # LTV (realizado): lucro bruto médio por parceiro desde a entrada.
    todas = _vendas(db, usuario, vendedor_id)
    lucro_total = sum(v.valor - v.custo - v.comissao for v in todas)
    ind["ltv_parceiro"] = lucro_total / len(parceiros) if parceiros else 0
    ind["churn_parceiros"] = taxa(ind["parceiros_inativos"], len(parceiros))
    ind["taxa_renovacao"] = taxa_renovacao(db, p)
    return ind


def _escopo_tarefas(consulta, usuario: Usuario):
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        return consulta.where(Tarefa.usuario_id == usuario.id)
    return consulta


def taxa_renovacao(db: Session, p: Periodo) -> float:
    """Dos certificados que venceram no período, quantos foram renovados."""
    certs = db.execute(select(Certificado.status, Certificado.data_vencimento).where(
        Certificado.data_vencimento >= p.inicio, Certificado.data_vencimento <= min(p.fim, date.today()))).all()
    finalizados = [c for c in certs if c.status in ("Renovado", "Vencido", "Não renovará")]
    return taxa(sum(1 for c in finalizados if c.status == "Renovado"), len(finalizados))


def funil(ind: dict) -> list[tuple[str, int]]:
    return [("Leads encontrados", ind["leads_encontrados"]), ("Contatados", ind["leads_contatados"]),
            ("Responderam", ind["leads_responderam"]), ("Interessados", ind["leads_interessados"]),
            ("Reuniões", ind["reunioes_periodo"]), ("Propostas", ind["propostas_enviadas"]),
            ("Parceiros", ind["parceiros_convertidos"])]


# ---------------------------------------------------------------- Séries para gráficos

def leads_por_tempo(db: Session, usuario: Usuario, vendedor_id=None) -> dict:
    hoje = date.today()
    datas = [l.criado_em.date() for l in _leads(db, usuario, vendedor_id)]
    contagem = Counter(datas)
    dias = [hoje - timedelta(days=i) for i in range(29, -1, -1)]
    semanas = [hoje - timedelta(days=hoje.weekday()) - timedelta(weeks=i) for i in range(11, -1, -1)]
    por_semana = Counter(d - timedelta(days=d.weekday()) for d in datas)
    meses = []
    ano, mes = hoje.year, hoje.month
    for _ in range(12):
        meses.append((ano, mes))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    meses.reverse()
    por_mes = Counter((d.year, d.month) for d in datas)
    nomes_mes = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    return {
        "dia": {"rotulos": [d.strftime("%d/%m") for d in dias], "valores": [contagem.get(d, 0) for d in dias]},
        "semana": {"rotulos": [d.strftime("%d/%m") for d in semanas], "valores": [por_semana.get(d, 0) for d in semanas]},
        "mes": {"rotulos": [f"{nomes_mes[m - 1]}/{str(a)[2:]}" for a, m in meses],
                "valores": [por_mes.get(x, 0) for x in meses]},
    }


def ranking_parceiros(db: Session, usuario: Usuario | None = None, p: Periodo | None = None,
                      vendedor_id=None) -> list[dict]:
    parceiros = _parceiros(db, usuario, vendedor_id) if usuario else list(db.execute(select(Parceiro)).scalars())
    vendas = db.execute(select(Venda.parceiro_id, Venda.valor, Venda.comissao, Venda.data)
                        .where(Venda.parceiro_id.is_not(None))).all()
    indicados = Counter(pid for (pid,) in db.execute(select(Cliente.parceiro_id).where(Cliente.parceiro_id.is_not(None))))
    por_parceiro = defaultdict(lambda: {"certificados": 0, "faturamento": 0.0, "comissao": 0.0, "ultima_venda": None})
    for v in vendas:
        if p and not _no_periodo(v.data, p):
            continue
        item = por_parceiro[v.parceiro_id]
        item["certificados"] += 1
        item["faturamento"] += v.valor
        item["comissao"] += v.comissao
        if not item["ultima_venda"] or v.data > item["ultima_venda"]:
            item["ultima_venda"] = v.data
    ultima_geral = {}
    for v in vendas:
        if v.parceiro_id not in ultima_geral or v.data > ultima_geral[v.parceiro_id]:
            ultima_geral[v.parceiro_id] = v.data
    linhas = []
    for parc in parceiros:
        dados = por_parceiro[parc.id]
        linhas.append({"parceiro": parc, "id": parc.id, "nome": parc.escritorio, "status": parc.status,
                       "cidade": parc.cidade, "estado": parc.estado,
                       "indicados": indicados.get(parc.id, 0), "certificados": dados["certificados"],
                       "faturamento": dados["faturamento"], "comissao": dados["comissao"],
                       "ultima_venda": ultima_geral.get(parc.id)})
    return linhas


def parceiros_parados(db: Session, usuario: Usuario | None = None, dias: int | None = None) -> list[dict]:
    dias = dias or ler_config_int(db, "dias_parceiro_parado", 30)
    limite = date.today() - timedelta(days=dias)
    return [r for r in ranking_parceiros(db, usuario)
            if r["status"] in ("ATIVO", "EM ATIVAÇÃO") and r["parceiro"].data_entrada <= limite
            and (r["ultima_venda"] is None or r["ultima_venda"] < limite)]


def por_vendedor(db: Session, usuario: Usuario, p: Periodo) -> list[dict]:
    leads = _leads(db, usuario)
    vendas = [v for v in _vendas(db, usuario) if _no_periodo(v.data, p)]
    nomes = {u.id: u.nome for u in db.execute(select(Usuario)).scalars()}
    grupos = defaultdict(lambda: {"leads": 0, "contatados": 0, "responderam": 0, "parceiros": 0, "vendas": 0, "receita": 0.0})
    for l in leads:
        g = grupos[l.vendedor_id]
        g["leads"] += _no_periodo(l.criado_em, p)
        g["contatados"] += _no_periodo(l.contatado_em, p)
        g["responderam"] += _no_periodo(l.respondeu_em, p)
        g["parceiros"] += _no_periodo(l.convertido_em, p)
    for v in vendas:
        grupos[v.vendedor_id]["vendas"] += 1
        grupos[v.vendedor_id]["receita"] += v.valor
    linhas = []
    for vid, g in grupos.items():
        if not any((g["leads"], g["contatados"], g["vendas"])):
            continue
        linhas.append({"nome": nomes.get(vid, "Sem vendedor"), **g,
                       "taxa_resposta": taxa(g["responderam"], g["contatados"]),
                       "taxa_conversao": taxa(g["parceiros"], g["leads"])})
    return sorted(linhas, key=lambda x: (-x["taxa_conversao"], -x["parceiros"]))


def por_grupo(db: Session, usuario: Usuario, p: Periodo, campo: str, vendedor_id=None) -> list[dict]:
    """Desempenho agrupado por estado, cidade, origem, especialidade ou tipo de empresa."""
    grupos = defaultdict(lambda: {"leads": 0, "contatados": 0, "responderam": 0, "parceiros": 0})
    for l in _leads(db, usuario, vendedor_id):
        if l.anonimizado:
            continue
        chave = getattr(l, campo) or "(não informado)"
        if campo == "cidade" and l.estado:
            chave = f"{chave}/{l.estado}"
        g = grupos[chave]
        g["leads"] += _no_periodo(l.criado_em, p)
        g["contatados"] += _no_periodo(l.contatado_em, p)
        g["responderam"] += _no_periodo(l.respondeu_em, p)
        g["parceiros"] += _no_periodo(l.convertido_em, p)
    linhas = [{"nome": k, **g, "taxa_resposta": taxa(g["responderam"], g["contatados"]),
               "taxa_conversao": taxa(g["parceiros"], g["leads"])}
              for k, g in grupos.items() if g["leads"] or g["contatados"] or g["parceiros"]]
    return sorted(linhas, key=lambda x: (-x["parceiros"], -x["leads"]))


def leads_parados(db: Session, usuario: Usuario, dias: int | None = None) -> list[Lead]:
    dias = dias or ler_config_int(db, "dias_lead_parado", 7)
    limite = datetime.now() - timedelta(days=dias)
    consulta = select(Lead).where(
        Lead.status.in_(["Contatado", "Aguardando resposta", "Respondeu", "Interessado", "Humano assumiu",
                         "Reunião", "Negociação"]),
        Lead.opt_out.is_(False), Lead.atualizado_em < limite).order_by(Lead.score.desc())
    consulta = _escopo_leads(consulta, usuario, None)
    sem_tarefa = []
    for lead in db.execute(consulta.limit(300)).scalars():
        pendente = db.execute(select(Tarefa.id).where(Tarefa.lead_id == lead.id, Tarefa.status == "pendente").limit(1)).first()
        if not pendente:
            sem_tarefa.append(lead)
    return sem_tarefa


def contar_followups_hoje(db: Session, usuario: Usuario) -> int:
    consulta = select(func.count(Tarefa.id)).where(Tarefa.status == "pendente", Tarefa.data <= date.today())
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where(Tarefa.usuario_id == usuario.id)
    return db.execute(consulta).scalar() or 0


# ---------------------------------------------------------------- IA Comercial: perguntas prontas

PERGUNTAS = [
    ("melhores_leads", "Quais são meus 20 melhores leads?"),
    ("contatar_hoje", "Quem devo contatar hoje?"),
    ("leads_parados", "Quais leads estão parados?"),
    ("parceiros_inativos", "Quais parceiros estão inativos ou parados?"),
    ("cidade_conversao", "Qual cidade possui melhor conversão?"),
    ("vendedor_performance", "Qual vendedor possui melhor performance?"),
    ("tipo_converte", "Qual tipo de escritório converte mais?"),
    ("custo_parceiro", "Quanto estou pagando para adquirir cada parceiro?"),
    ("parceiro_receita", "Qual parceiro gera mais receita?"),
    ("clientes_renovar", "Quais clientes precisam renovar?"),
    ("receita_renovacao", "Qual será minha receita estimada de renovação?"),
]


def responder_pronta(db: Session, usuario: Usuario, codigo: str) -> dict:
    """Devolve {"texto": ..., "colunas": [...], "linhas": [...], "links": [...]} para a pergunta pronta."""
    p = periodo("90d")
    if codigo == "melhores_leads":
        consulta = _escopo_leads(select(Lead).where(Lead.status.not_in(config.STATUS_PERDIDO + ["Parceiro", "Parceiro ativo"]),
                                                    Lead.opt_out.is_(False), Lead.anonimizado.is_(False))
                                 .order_by(Lead.score.desc(), Lead.criado_em.desc()).limit(20), usuario, None)
        leads = list(db.execute(consulta).scalars())
        return {"texto": f"Seus {len(leads)} leads em aberto com maior score:",
                "colunas": ["Lead", "Cidade", "Score", "Potencial", "Status"],
                "linhas": [[l.empresa, f"{l.cidade}/{l.estado}", l.score, l.potencial, l.status] for l in leads],
                "links": [f"/leads/{l.id}" for l in leads]}
    if codigo == "contatar_hoje":
        consulta = select(Tarefa).where(Tarefa.status == "pendente", Tarefa.data <= date.today()).order_by(Tarefa.data, Tarefa.hora)
        consulta = _escopo_tarefas(consulta, usuario)
        tarefas = list(db.execute(consulta.limit(50)).scalars())
        return {"texto": f"Hoje você possui {contar_followups_hoje(db, usuario)} follow-ups pendentes. Os primeiros:",
                "colunas": ["Quando", "Lead/cliente", "Canal", "Ação"],
                "linhas": [[f"{util.so_data_br(t.data)} {t.hora}", (t.lead.empresa if t.lead else (t.cliente.nome if t.cliente else "-")),
                            config.CANAIS.get(t.canal, t.canal), t.acao] for t in tarefas],
                "links": ["/agenda"] * len(tarefas)}
    if codigo == "leads_parados":
        leads = leads_parados(db, usuario)[:50]
        return {"texto": f"{len(leads)} leads em negociação sem movimento há mais de "
                         f"{ler_config_int(db, 'dias_lead_parado', 7)} dias e sem tarefa agendada:",
                "colunas": ["Lead", "Status", "Último contato", "Score"],
                "linhas": [[l.empresa, l.status, util.data_br(l.ultimo_contato) or "-", l.score] for l in leads],
                "links": [f"/leads/{l.id}" for l in leads]}
    if codigo == "parceiros_inativos":
        parados = parceiros_parados(db, usuario)
        inativos = [r for r in ranking_parceiros(db, usuario) if r["status"] in ("INATIVO", "BLOQUEADO")]
        dias = ler_config_int(db, "dias_parceiro_parado", 30)
        linhas = [[r["nome"], r["status"], util.so_data_br(r["ultima_venda"]) or "nunca vendeu", r["certificados"]]
                  for r in parados + inativos]
        return {"texto": f"{len(parados)} parceiros não geraram nenhuma venda nos últimos {dias} dias "
                         f"e {len(inativos)} estão inativos/bloqueados.",
                "colunas": ["Parceiro", "Status", "Última venda", "Certificados"], "linhas": linhas,
                "links": [f"/parceiros/{r['id']}" for r in parados + inativos]}
    if codigo == "cidade_conversao":
        linhas = [g for g in por_grupo(db, usuario, periodo("tudo"), "cidade") if g["leads"] >= 3][:15]
        linhas.sort(key=lambda g: -g["taxa_conversao"])
        melhor = linhas[0]["nome"] if linhas else "-"
        return {"texto": f"Melhor conversão (cidades com 3+ leads): {melhor}.",
                "colunas": ["Cidade", "Leads", "Responderam", "Parceiros", "Conversão"],
                "linhas": [[g["nome"], g["leads"], g["responderam"], g["parceiros"], util.porcentagem(g["taxa_conversao"])] for g in linhas]}
    if codigo == "vendedor_performance":
        linhas = por_vendedor(db, usuario, p)
        return {"texto": ("Melhor performance nos últimos 90 dias: " + linhas[0]["nome"]) if linhas else "Ainda sem dados.",
                "colunas": ["Vendedor", "Leads", "Contatados", "Taxa resposta", "Parceiros", "Conversão", "Receita"],
                "linhas": [[g["nome"], g["leads"], g["contatados"], util.porcentagem(g["taxa_resposta"]), g["parceiros"],
                            util.porcentagem(g["taxa_conversao"]), util.moeda(g["receita"])] for g in linhas]}
    if codigo == "tipo_converte":
        linhas = por_grupo(db, usuario, periodo("tudo"), "especialidade")
        linhas.sort(key=lambda g: (-g["taxa_conversao"], -g["leads"]))
        return {"texto": "Conversão por especialidade do escritório (todo o período):",
                "colunas": ["Especialidade", "Leads", "Parceiros", "Conversão"],
                "linhas": [[g["nome"], g["leads"], g["parceiros"], util.porcentagem(g["taxa_conversao"])] for g in linhas[:15]]}
    if codigo == "custo_parceiro":
        ind = indicadores(db, usuario, p)
        custo_mes = ler_config_int(db, "custo_mensal_prospeccao", 0)
        if not custo_mes:
            return {"texto": "Informe o custo mensal da prospecção (salários, ferramentas, anúncios) em "
                             "Configurações para calcular o custo por parceiro.", "colunas": [], "linhas": []}
        return {"texto": f"Nos últimos 90 dias: custo de prospecção {util.moeda(ind['custo_prospeccao'])}, "
                         f"{ind['parceiros_convertidos']} parceiros adquiridos → "
                         f"{util.moeda(ind['custo_por_parceiro'])} por parceiro e {util.moeda(ind['custo_por_lead'])} por lead.",
                "colunas": [], "linhas": []}
    if codigo == "parceiro_receita":
        linhas = sorted(ranking_parceiros(db, usuario), key=lambda r: -r["faturamento"])[:15]
        return {"texto": ("Parceiro que mais gera receita: " + linhas[0]["nome"]) if linhas and linhas[0]["faturamento"] else "Ainda sem vendas.",
                "colunas": ["Parceiro", "Certificados", "Faturamento", "Comissão"],
                "linhas": [[r["nome"], r["certificados"], util.moeda(r["faturamento"]), util.moeda(r["comissao"])] for r in linhas],
                "links": [f"/parceiros/{r['id']}" for r in linhas]}
    if codigo == "clientes_renovar":
        hoje = date.today()
        certs = list(db.execute(select(Certificado).where(
            Certificado.status.in_(["Ativo", "Em renovação"]), Certificado.data_vencimento <= hoje + timedelta(days=30))
            .order_by(Certificado.data_vencimento)).scalars())
        return {"texto": f"{len(certs)} certificados vencem nos próximos 30 dias:",
                "colunas": ["Cliente", "Tipo", "Vencimento", "Dias", "Parceiro"],
                "linhas": [[c.cliente_nome, c.tipo, util.so_data_br(c.data_vencimento), (c.data_vencimento - hoje).days,
                            c.parceiro.escritorio if c.parceiro else "-"] for c in certs],
                "links": ["/vencimentos"] * len(certs)}
    if codigo == "receita_renovacao":
        from .vendas_servico import receita_renovacao_estimada

        linhas = []
        for dias in (30, 60, 90, 180, 365):
            qtd, valor = receita_renovacao_estimada(db, dias)
            linhas.append([f"Próximos {dias} dias", qtd, util.moeda(valor)])
        return {"texto": "Receita estimada se todos os certificados forem renovados pelo preço atual da tabela:",
                "colunas": ["Período", "Certificados", "Receita estimada"], "linhas": linhas}
    return {"texto": "Pergunta não reconhecida.", "colunas": [], "linhas": []}


def resumo_para_ia(db: Session, usuario: Usuario) -> str:
    """Retrato do negócio (números e nomes de empresas, sem contatos pessoais) para a IA Comercial."""
    partes = []
    for nome_p in ("30d", "90d"):
        ind = indicadores(db, usuario, periodo(nome_p))
        partes.append(f"[{periodo(nome_p).nome}] " + "; ".join(
            f"{k}={round(v, 1) if isinstance(v, float) else v}" for k, v in ind.items()))
    for codigo, pergunta in PERGUNTAS:
        r = responder_pronta(db, usuario, codigo)
        tabela = "\n".join(" | ".join(str(c) for c in linha) for linha in r["linhas"][:20])
        partes.append(f"## {pergunta}\n{r['texto']}\n{' | '.join(r['colunas'])}\n{tabela}")
    return "\n\n".join(partes)[:60_000]


# ---------------------------------------------------------------- Inteligência de Prospecção (IA SDR)

MINIMO_AMOSTRA = 15  # comparações só com pelo menos 15 contatos (evita conclusões com poucos dados)


def inteligencia(db: Session, usuario: Usuario, p: Periodo) -> dict:
    from .modelos import Campanha, Categoria, Mensagem, Oportunidade

    cats = {c.id: c for c in db.execute(select(Categoria)).scalars()}
    leads = db.execute(_escopo_leads(select(
        Lead.id, Lead.categoria_id, Lead.criado_em, Lead.score, Lead.fit, Lead.contatado_em, Lead.respondeu_em,
        Lead.interessado_em, Lead.reuniao_em, Lead.convertido_em, Lead.parceiro_id), usuario, None)).all()
    msgs = db.execute(select(Mensagem.canal, Mensagem.angulo, Mensagem.campanha_id, Mensagem.categoria_id,
                             Mensagem.status, Mensagem.respondida, Mensagem.direcao, Mensagem.criado_em,
                             Mensagem.modo)).all()
    msgs = [m for m in msgs if _no_periodo(m.criado_em, p)]
    saidas = [m for m in msgs if m.direcao == "saida" and m.angulo != "resposta"]
    receita_parceiro = defaultdict(float)
    receita_periodo = defaultdict(float)
    for v in db.execute(select(Venda.parceiro_id, Venda.valor, Venda.data)).all():
        if v.parceiro_id:
            receita_parceiro[v.parceiro_id] += v.valor
            if _no_periodo(v.data, p):
                receita_periodo[v.parceiro_id] += v.valor
    ops = db.execute(select(Oportunidade.temperatura, Oportunidade.criado_em)).all()

    do_periodo = [l for l in leads if _no_periodo(l.criado_em, p)]
    contatados = [l for l in leads if _no_periodo(l.contatado_em, p)]
    tentativas = [m for m in saidas if m.modo == "api"]
    entregues = [m for m in tentativas if m.status in ("enviada", "entregue", "lida")]
    ind = {
        "leads_encontrados": len(do_periodo),
        "leads_qualificados": sum(1 for l in do_periodo if l.fit in ("Muito alto potencial", "Alto potencial")),
        "leads_contatados": len(contatados),
        "mensagens_enviadas": len(saidas),
        "taxa_entrega": taxa(len(entregues), len(tentativas)) if tentativas else None,
        "taxa_resposta": taxa(sum(1 for l in leads if _no_periodo(l.respondeu_em, p)), len(contatados)),
        "taxa_interesse": taxa(sum(1 for l in leads if _no_periodo(l.interessado_em, p)), len(contatados)),
        "reunioes": sum(1 for l in leads if _no_periodo(l.reuniao_em, p)),
        "oportunidades_quentes": sum(1 for o in ops if o.temperatura == "quente" and _no_periodo(o.criado_em, p)),
        "parceiros": sum(1 for l in leads if _no_periodo(l.convertido_em, p)),
        "receita": sum(receita_periodo[l.parceiro_id] for l in leads if l.parceiro_id),
    }
    ind["conversao"] = taxa(ind["parceiros"], len(do_periodo))

    grupos = defaultdict(lambda: defaultdict(float))
    for l in leads:
        g = grupos[l.categoria_id]
        g["leads"] += _no_periodo(l.criado_em, p)
        g["contatados"] += _no_periodo(l.contatado_em, p)
        g["responderam"] += _no_periodo(l.respondeu_em, p)
        g["interessados"] += _no_periodo(l.interessado_em, p)
        g["reunioes"] += _no_periodo(l.reuniao_em, p)
        g["parceiros"] += _no_periodo(l.convertido_em, p)
        g["score_soma"] += l.score or 0
        g["total"] += 1
        if l.parceiro_id:
            g["receita"] += receita_periodo[l.parceiro_id]
            g["receita_total"] += receita_parceiro[l.parceiro_id]
            g["parceiros_total"] += 1
    segmentos = []
    for cid, g in grupos.items():
        if not (g["leads"] or g["contatados"] or g["parceiros"]):
            continue
        cat = cats.get(cid)
        linha = {k: int(v) for k, v in g.items() if k not in ("receita", "receita_total")}
        linha.update({
            "nome": cat.nome if cat else "Sem categoria", "codigo": cat.codigo if cat else "",
            "aderencia": cat.aderencia if cat else 0, "receita": g["receita"],
            "ltv": g["receita_total"] / g["parceiros_total"] if g["parceiros_total"] else 0,
            "score_medio": round(g["score_soma"] / g["total"]) if g["total"] else 0,
            "taxa_resposta": taxa(g["responderam"], g["contatados"]),
            "taxa_interesse": taxa(g["interessados"], g["contatados"]),
            "conversao": taxa(g["parceiros"], g["leads"]),
        })
        segmentos.append(linha)
    segmentos.sort(key=lambda s: (-s["parceiros"], -s["taxa_resposta"], -s["leads"]))

    def agrupar_msgs(chave, nomes=None):
        resultado = defaultdict(lambda: {"enviadas": 0, "respondidas": 0})
        for m in saidas:
            k = getattr(m, chave) or "—"
            resultado[k]["enviadas"] += 1
            resultado[k]["respondidas"] += bool(m.respondida)
        linhas = [{"nome": (nomes or {}).get(k, k), "chave": k, **v,
                   "taxa_resposta": taxa(v["respondidas"], v["enviadas"])} for k, v in resultado.items()]
        return sorted(linhas, key=lambda x: (-x["taxa_resposta"], -x["enviadas"]))

    nomes_camp = {c.id: c.nome for c in db.execute(select(Campanha)).scalars()}
    por_canal = agrupar_msgs("canal", config.CANAIS)
    por_angulo = agrupar_msgs("angulo", config.ANGULOS)
    por_campanha = agrupar_msgs("campanha_id", nomes_camp)

    com_amostra = [s for s in segmentos if s["contatados"] >= MINIMO_AMOSTRA]
    rankings = {}
    melhor = max(com_amostra, key=lambda s: s["taxa_resposta"], default=None)
    if melhor:
        rankings["resposta"] = melhor
    for chave in ("reunioes", "parceiros", "receita"):
        melhor = max(segmentos, key=lambda s: s[chave], default=None)
        if melhor and melhor[chave]:
            rankings[chave] = melhor
    return {"ind": ind, "segmentos": segmentos, "por_canal": por_canal, "por_angulo": por_angulo,
            "por_campanha": por_campanha, "rankings": rankings,
            "sugestoes": sugestoes(segmentos, por_canal, por_angulo)}


def sugestoes(segmentos: list[dict], por_canal: list[dict], por_angulo: list[dict]) -> list[str]:
    """Descoberta de segmentos e estratégias, com base só nos números (mínimo de amostra)."""
    dicas = []
    validos = [s for s in segmentos if s["contatados"] >= MINIMO_AMOSTRA]
    if len(validos) >= 2:
        melhor = max(validos, key=lambda s: s["taxa_resposta"])
        pior = min(validos, key=lambda s: s["taxa_resposta"])
        if pior["taxa_resposta"] and melhor["taxa_resposta"] > pior["taxa_resposta"] * 1.2:
            dif = round(100 * (melhor["taxa_resposta"] / pior["taxa_resposta"] - 1))
            dicas.append(f"{melhor['nome']} têm taxa de resposta {dif}% maior que {pior['nome']} "
                         f"({util.porcentagem(melhor['taxa_resposta'])} x {util.porcentagem(pior['taxa_resposta'])}). "
                         f"Sugestão: priorizar {melhor['nome']}.")
        media = sum(s["taxa_resposta"] for s in validos) / len(validos)
        canal = next((c for c in por_canal if c["enviadas"] >= MINIMO_AMOSTRA), None)
        for s in validos:
            if (s["score_medio"] >= 61 or s["aderencia"] >= 20) and s["taxa_resposta"] < media * 0.6:
                dicas.append(f"{s['nome']} têm alto potencial, mas baixa taxa de resposta "
                             f"({util.porcentagem(s['taxa_resposta'])}). Sugestão: mudar a estratégia"
                             + (f" — testar o canal {canal['nome']}, que responde melhor" if canal else "")
                             + " e um CTA pedindo o responsável por parcerias.")
    canais = [c for c in por_canal if c["enviadas"] >= MINIMO_AMOSTRA]
    if len(canais) >= 2:
        dicas.append(f"Canal com melhor resposta: {canais[0]['nome']} ({util.porcentagem(canais[0]['taxa_resposta'])}).")
    angulos = [a for a in por_angulo if a["enviadas"] >= MINIMO_AMOSTRA]
    if len(angulos) >= 2:
        dicas.append(f"Abordagem que mais gera resposta: {angulos[0]['nome']} "
                     f"({util.porcentagem(angulos[0]['taxa_resposta'])}).")
    if not dicas:
        dicas.append(f"Ainda não há dados suficientes para comparar (mínimo de {MINIMO_AMOSTRA} contatos por grupo). "
                     "As sugestões aparecem sozinhas conforme as campanhas rodarem.")
    return dicas


def oportunidades_de_parceria(db: Session, uf: str = "", cidade: str = "") -> list[dict]:
    """'Encontrar novas oportunidades de parceria': categoria, motivo, potencial, quantidade, estratégia."""
    from . import base_receita
    from .modelos import Categoria

    contagem = base_receita.contar(db, uf, cidade)
    linhas = []
    for c in db.execute(select(Categoria).where(Categoria.ativa.is_(True)).order_by(Categoria.prioridade)).scalars():
        if c.codigo == "outros":
            continue
        potencial = "Alto" if c.aderencia >= 20 else ("Médio" if c.aderencia >= 12 else "Baixo")
        linhas.append({"categoria": c, "motivo": c.motivo, "potencial": potencial,
                       "quantidade": contagem.get(c.codigo, 0), "estrategia": c.estrategia})
    ordem = {"Alto": 0, "Médio": 1, "Baixo": 2}
    return sorted(linhas, key=lambda x: (ordem[x["potencial"]], -x["quantidade"]))
