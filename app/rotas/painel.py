"""Dashboard, relatórios, IA Comercial e exportações."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, ia, metricas, planilhas, util
from ..banco import obter_db
from ..leads_servico import filtrar_por_usuario
from ..modelos import Certificado, Cliente, Lead, Parceiro, Usuario, Venda
from ..seguranca import equipe, registrar_log, ve_tudo, verificar_csrf
from ..vendas_servico import receita_renovacao_estimada
from ..web import TIPOS_ARQUIVO, arquivo, tela

rotas = APIRouter()


def _rotulo(texto: str, tamanho: int = 18) -> str:
    texto = texto.replace(" [DEMO]", "")
    return texto if len(texto) <= tamanho else texto[: tamanho - 1] + "…"


def _vendedores(db: Session):
    return list(db.execute(select(Usuario).where(Usuario.perfil.in_(["vendedor", "gestor", "admin"]),
                                                 Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars())


@rotas.get("/")
def dashboard(request: Request, periodo: str = "30d", vendedor: int | None = None,
              usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    p = metricas.periodo(periodo)
    vendedor = vendedor if ve_tudo(usuario) else None
    ind = metricas.indicadores(db, usuario, p, vendedor)
    ranking = sorted(metricas.ranking_parceiros(db, usuario, p, vendedor), key=lambda r: (-r["certificados"], -r["faturamento"]))
    top = [r for r in ranking if r["certificados"]][:10]
    regioes = metricas.por_grupo(db, usuario, p, "estado", vendedor)[:10]
    vendedores = metricas.por_vendedor(db, usuario, p) if ve_tudo(usuario) else []
    graficos = {
        "tempo": metricas.leads_por_tempo(db, usuario, vendedor),
        "funil": metricas.funil(ind),
        "parceiros": [["Ativos", ind["parceiros_ativos"]], ["Em ativação", ind["parceiros_ativacao"]],
                      ["Inativos/bloqueados", ind["parceiros_inativos"]]],
        "certificados": [[_rotulo(r["nome"]), r["certificados"]] for r in top],
        "receita": [[_rotulo(r["nome"]), round(r["faturamento"], 2)] for r in sorted(top, key=lambda r: -r["faturamento"])],
        "regioes": [[g["nome"], g["leads"], g["parceiros"]] for g in regioes],
        "vendedores": [[g["nome"], g["taxa_resposta"], g["taxa_conversao"]] for g in vendedores],
    }
    hoje = date.today()
    vencendo = db.execute(select(Certificado).where(
        Certificado.status.in_(["Ativo", "Em renovação"]),
        Certificado.data_vencimento <= hoje + timedelta(days=30)).order_by(Certificado.data_vencimento).limit(8)).scalars().all()
    return tela(request, "dashboard.html", {
        "ind": ind, "p": p, "periodo": periodo, "graficos": graficos, "ranking": ranking[:5], "regioes": regioes,
        "vendedores_perf": vendedores, "vendedores": _vendedores(db) if ve_tudo(usuario) else [],
        "vendedor_sel": vendedor, "followups": metricas.contar_followups_hoje(db, usuario),
        "parados": metricas.parceiros_parados(db, usuario), "vencendo": vencendo,
    })


# ---------------------------------------------------------------- Relatórios

def _dados_relatorio(db: Session, usuario: Usuario, p: metricas.Periodo):
    ind = metricas.indicadores(db, usuario, p)
    qtd90, valor90 = receita_renovacao_estimada(db, 90)
    metr = [
        ("Leads gerados", ind["leads_encontrados"]), ("Leads contatados", ind["leads_contatados"]),
        ("Taxa de contato", util.porcentagem(ind["taxa_contato"])), ("Taxa de resposta", util.porcentagem(ind["taxa_resposta"])),
        ("Taxa de interesse", util.porcentagem(ind["taxa_interesse"])), ("Taxa de reunião", util.porcentagem(ind["taxa_reuniao"])),
        ("Taxa de conversão", util.porcentagem(ind["taxa_conversao"])),
        ("Custo por lead", util.moeda(ind["custo_por_lead"])), ("Custo por parceiro", util.moeda(ind["custo_por_parceiro"])),
        ("Receita por parceiro", util.moeda(ind["receita_por_parceiro"])), ("Ticket médio", util.moeda(ind["ticket_medio"])),
        ("Certificados por parceiro", str(ind["certificados_por_parceiro"]).replace(".", ",")),
        ("Comissão média", util.moeda(ind["comissao_media"])), ("LTV do parceiro (lucro realizado)", util.moeda(ind["ltv_parceiro"])),
        ("Taxa de renovação", util.porcentagem(ind["taxa_renovacao"])), ("Churn de parceiros", util.porcentagem(ind["churn_parceiros"])),
        ("Certificados vendidos", ind["certificados_vendidos"]), ("Receita", util.moeda(ind["receita"])),
        ("Comissão gerada", util.moeda(ind["comissao"])), ("Lucro bruto", util.moeda(ind["lucro_bruto"])),
        ("Renovações previstas (90 dias)", f"{qtd90} certificados · {util.moeda(valor90)}"),
    ]
    return {
        "ind": ind, "metricas": metr, "funil": metricas.funil(ind),
        "vendedores": metricas.por_vendedor(db, usuario, p) if ve_tudo(usuario) else [],
        "estados": metricas.por_grupo(db, usuario, p, "estado"),
        "cidades": metricas.por_grupo(db, usuario, p, "cidade")[:20],
        "origens": metricas.por_grupo(db, usuario, p, "origem"),
        "especialidades": metricas.por_grupo(db, usuario, p, "especialidade"),
        "ranking": sorted(metricas.ranking_parceiros(db, usuario, p), key=lambda r: -r["faturamento"])[:20],
        "parados": metricas.parceiros_parados(db, usuario),
    }


@rotas.get("/relatorios")
def relatorios(request: Request, periodo: str = "30d", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    p = metricas.periodo(periodo)
    return tela(request, "relatorios.html", {"p": p, "periodo": periodo, **_dados_relatorio(db, usuario, p)})


def _tabela_grupo(titulo, linhas):
    return (titulo, ["Grupo", "Leads", "Contatados", "Responderam", "Parceiros", "Taxa resposta", "Conversão"],
            [[g["nome"], g["leads"], g["contatados"], g["responderam"], g["parceiros"],
              util.porcentagem(g["taxa_resposta"]), util.porcentagem(g["taxa_conversao"])] for g in linhas])


@rotas.get("/relatorios/exportar.{formato}")
def relatorio_exportar(request: Request, formato: str, periodo: str = "30d", usuario: Usuario = Depends(equipe),
                       db: Session = Depends(obter_db)):
    if formato not in TIPOS_ARQUIVO:
        raise HTTPException(404)
    p = metricas.periodo(periodo)
    d = _dados_relatorio(db, usuario, p)
    secoes = [
        ("Métricas", ["Indicador", "Valor"], [[a, b] for a, b in d["metricas"]]),
        ("Funil", ["Etapa", "Quantidade"], [[a, b] for a, b in d["funil"]]),
        _tabela_grupo("Por estado", d["estados"]),
        _tabela_grupo("Por cidade", d["cidades"]),
        _tabela_grupo("Por origem", d["origens"]),
        _tabela_grupo("Por especialidade", d["especialidades"]),
        ("Ranking de parceiros", ["Parceiro", "Indicados", "Certificados", "Faturamento", "Comissão", "Última venda"],
         [[r["nome"], r["indicados"], r["certificados"], util.moeda(r["faturamento"]), util.moeda(r["comissao"]),
           util.so_data_br(r["ultima_venda"])] for r in d["ranking"]]),
    ]
    if d["vendedores"]:
        secoes.insert(2, ("Por vendedor", ["Vendedor", "Leads", "Contatados", "Taxa resposta", "Parceiros", "Conversão", "Receita"],
                          [[g["nome"], g["leads"], g["contatados"], util.porcentagem(g["taxa_resposta"]), g["parceiros"],
                            util.porcentagem(g["taxa_conversao"]), util.moeda(g["receita"])] for g in d["vendedores"]]))
    registrar_log(db, usuario, "exportou", "relatorio", None, f"{formato} {p.nome}", request)
    db.commit()
    nome = f"relatorio_comercial_{date.today():%Y-%m-%d}.{formato}"
    if formato == "pdf":
        return arquivo(planilhas.gerar_pdf(f"Relatório comercial – {p.nome}", secoes), nome, TIPOS_ARQUIVO["pdf"])
    # CSV/Excel: uma tabela única com a coluna "Seção"
    linhas = [[titulo] + linha for titulo, _, ls in secoes for linha in ls]
    colunas = ["Seção", "Item", "Valor 1", "Valor 2", "Valor 3", "Valor 4", "Valor 5", "Valor 6"]
    linhas = [l + [""] * (len(colunas) - len(l)) for l in linhas]
    if formato == "csv":
        return arquivo(planilhas.gerar_csv(colunas, linhas), nome, TIPOS_ARQUIVO["csv"])
    return arquivo(planilhas.gerar_xlsx("Relatório", colunas, linhas), nome, TIPOS_ARQUIVO["xlsx"])


# ---------------------------------------------------------------- Exportações gerais

def _export_leads(db, usuario):
    leads = db.execute(filtrar_por_usuario(select(Lead).where(Lead.anonimizado.is_(False)), usuario)
                       .order_by(Lead.score.desc())).scalars().all()
    colunas = ["Empresa", "CNPJ", "Responsável", "Cargo", "Telefone", "WhatsApp", "E-mail", "Site", "Instagram",
               "LinkedIn", "Cidade", "UF", "Especialidade", "Status", "Score", "Potencial", "Origem", "Fonte",
               "Vendedor", "Cadastro", "Último contato", "Próximo contato", "Opt-out"]
    linhas = [[l.empresa, l.cnpj, l.responsavel, l.cargo, l.telefone, l.whatsapp, l.email, l.site, l.instagram,
               l.linkedin, l.cidade, l.estado, l.especialidade, l.status, l.score, l.potencial, l.origem, l.fonte_url,
               l.vendedor.nome if l.vendedor else "", l.criado_em, l.ultimo_contato, l.proximo_contato, l.opt_out]
              for l in leads]
    return "Leads", colunas, linhas


def _export_parceiros(db, usuario):
    ranking = metricas.ranking_parceiros(db, usuario)
    colunas = ["Escritório", "Responsável", "CNPJ", "Telefone", "E-mail", "Cidade", "UF", "Entrada", "Status",
               "Indicados", "Certificados", "Receita", "Comissão acumulada", "Última venda"]
    linhas = [[r["parceiro"].escritorio, r["parceiro"].responsavel, r["parceiro"].cnpj, r["parceiro"].telefone,
               r["parceiro"].email, r["cidade"], r["estado"], r["parceiro"].data_entrada, r["status"], r["indicados"],
               r["certificados"], r["faturamento"], r["comissao"], r["ultima_venda"]] for r in ranking]
    return "Parceiros", colunas, linhas


def _export_clientes(db, usuario):
    consulta = select(Cliente).order_by(Cliente.nome)
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.join(Parceiro, Cliente.parceiro_id == Parceiro.id).where(Parceiro.vendedor_id == usuario.id)
    clientes = db.execute(consulta).scalars().all()
    return "Clientes", ["Cliente", "CNPJ/CPF", "Contato", "Telefone", "E-mail", "Parceiro", "Status", "Cadastro"], [
        [c.nome, c.cnpj, c.contato, c.telefone, c.email, c.parceiro.escritorio if c.parceiro else "", c.status, c.criado_em]
        for c in clientes]


def _export_vendas(db, usuario, so_comissao=False):
    consulta = select(Venda).order_by(Venda.data.desc())
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where(Venda.vendedor_id == usuario.id)
    if so_comissao:
        consulta = consulta.where(Venda.comissao > 0)
    vendas = db.execute(consulta).scalars().all()
    colunas = ["Data", "Cliente", "Produto", "Tipo", "Parceiro", "Vendedor", "Valor", "Custo", "Comissão",
               "Comissão paga", "Lucro bruto"]
    linhas = [[v.data, v.cliente.nome, v.produto.nome if v.produto else "", "Renovação" if v.tipo == "renovacao" else "Nova",
               v.parceiro.escritorio if v.parceiro else "", v.vendedor.nome if v.vendedor else "", v.valor, v.custo,
               v.comissao, v.comissao_paga, v.valor - v.custo - v.comissao] for v in vendas]
    return ("Comissões" if so_comissao else "Vendas"), colunas, linhas


def _export_vencimentos(db, usuario):
    certs = db.execute(select(Certificado).order_by(Certificado.data_vencimento)).scalars().all()
    hoje = date.today()
    return "Vencimentos", ["Cliente", "CNPJ/CPF", "Tipo", "Emissão", "Vencimento", "Dias", "Parceiro", "Status"], [
        [c.cliente_nome, c.cnpj, c.tipo, c.data_emissao, c.data_vencimento, (c.data_vencimento - hoje).days,
         c.parceiro.escritorio if c.parceiro else "", c.status] for c in certs]


EXPORTADORES = {
    "leads": _export_leads, "parceiros": _export_parceiros, "clientes": _export_clientes,
    "vendas": _export_vendas, "comissoes": lambda db, u: _export_vendas(db, u, True),
    "vencimentos": _export_vencimentos,
}


@rotas.get("/exportar/{tipo}.{formato}")
def exportar(request: Request, tipo: str, formato: str, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    if tipo not in EXPORTADORES or formato not in TIPOS_ARQUIVO:
        raise HTTPException(404)
    titulo, colunas, linhas = EXPORTADORES[tipo](db, usuario)
    registrar_log(db, usuario, "exportou", tipo, None, f"{formato}, {len(linhas)} linhas", request)
    db.commit()
    nome = f"{tipo}_{date.today():%Y-%m-%d}.{formato}"
    if formato == "csv":
        return arquivo(planilhas.gerar_csv(colunas, linhas), nome, TIPOS_ARQUIVO["csv"])
    if formato == "xlsx":
        return arquivo(planilhas.gerar_xlsx(titulo, colunas, linhas), nome, TIPOS_ARQUIVO["xlsx"])
    # PDF: até 12 colunas para caber na página
    return arquivo(planilhas.gerar_pdf(titulo, [("", colunas[:12], [l[:12] for l in linhas])]), nome, TIPOS_ARQUIVO["pdf"])


# ---------------------------------------------------------------- IA Comercial

@rotas.get("/ia")
def ia_comercial(request: Request, pergunta: str = "", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    resposta = metricas.responder_pronta(db, usuario, pergunta) if pergunta else None
    titulo = dict(metricas.PERGUNTAS).get(pergunta, "")
    return tela(request, "ia.html", {"perguntas": metricas.PERGUNTAS, "resposta": resposta, "titulo_pergunta": titulo,
                                     "pergunta_sel": pergunta, "ia_ligada": ia.disponivel()})


@rotas.post("/ia", dependencies=[Depends(verificar_csrf)])
def ia_pergunta_livre(request: Request, texto: str = Form(...), usuario: Usuario = Depends(equipe),
                      db: Session = Depends(obter_db)):
    resposta_ia, erro = "", ""
    try:
        resposta_ia = ia.responder_pergunta(db, texto, metricas.resumo_para_ia(db, usuario))
        registrar_log(db, usuario, "ia_comercial", "", None, texto[:300], request)
        db.commit()
    except ia.ErroDaIA as e:
        erro = str(e)
    return tela(request, "ia.html", {"perguntas": metricas.PERGUNTAS, "resposta": None, "texto": texto,
                                     "resposta_ia": resposta_ia, "erro_ia": erro, "ia_ligada": ia.disponivel()})
