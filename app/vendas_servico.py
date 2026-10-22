"""Vendas, comissões e vencimentos (renovação)."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import util
from .banco import agora, ler_config
from .leads_servico import historico
from .modelos import Certificado, Cliente, Lead, Parceiro, Produto, Tarefa, Usuario, Venda


# ---------------------------------------------------------------- Calculadora de comissão

def calcular(preco: float, custo: float, comissao_tipo: str, comissao_valor: float) -> dict:
    preco, custo, comissao_valor = float(preco or 0), float(custo or 0), float(comissao_valor or 0)
    comissao = preco * comissao_valor / 100 if comissao_tipo == "percentual" else comissao_valor
    comissao = round(comissao, 2)
    lucro = round(preco - custo - comissao, 2)
    return {
        "receita": round(preco, 2), "custo": round(custo, 2), "comissao": comissao, "lucro_bruto": lucro,
        "margem": round(100 * lucro / preco, 1) if preco else 0.0,
    }


def regra_de_comissao(produto: Produto | None, parceiro: Parceiro | None) -> tuple[str, float]:
    if parceiro and parceiro.comissao_tipo in ("percentual", "fixo"):
        return parceiro.comissao_tipo, parceiro.comissao_valor
    if produto:
        return produto.comissao_tipo, produto.comissao_valor
    return "percentual", 0.0


def descrever_regra(tipo: str, valor: float) -> str:
    if tipo == "fixo":
        return f"{util.moeda(valor)} por certificado"
    return f"{util.porcentagem(valor, 0 if float(valor).is_integer() else 1)} do valor da venda"


# ---------------------------------------------------------------- Venda

def registrar_venda(db: Session, *, cliente: Cliente, produto: Produto | None, parceiro: Parceiro | None,
                    valor: float | None, data: date, tipo: str, vendedor: Usuario | None,
                    certificado_anterior: Certificado | None = None, observacoes: str = "",
                    custo: float | None = None) -> Venda:
    preco = valor if valor not in (None, 0) else (produto.preco if produto else 0)
    custo = custo if custo is not None else (produto.custo if produto else 0)
    tipo_comissao, valor_comissao = regra_de_comissao(produto, parceiro)
    conta = calcular(preco, custo, tipo_comissao, valor_comissao) if parceiro else calcular(preco, custo, "fixo", 0)
    venda = Venda(cliente_id=cliente.id, produto_id=produto.id if produto else None,
                  parceiro_id=parceiro.id if parceiro else None, vendedor_id=vendedor.id if vendedor else None,
                  data=data, tipo=tipo, valor=conta["receita"], custo=conta["custo"], comissao=conta["comissao"],
                  observacoes=observacoes)
    db.add(venda)
    db.flush()
    cliente.status = "Emitido"
    # Certificado novo entra no controle de vencimentos.
    meses = produto.validade_meses if produto else 12
    db.add(Certificado(
        cliente_id=cliente.id, cliente_nome=cliente.nome, cnpj=cliente.cnpj,
        tipo=produto.nome if produto else "Certificado digital", data_emissao=data,
        data_vencimento=util.somar_meses(data, meses), parceiro_id=parceiro.id if parceiro else None,
        venda_id=venda.id, status="Ativo",
    ))
    if certificado_anterior:
        certificado_anterior.status = "Renovado"
        for t in db.execute(select(Tarefa).where(Tarefa.certificado_id == certificado_anterior.id,
                                                 Tarefa.status == "pendente")).scalars():
            t.status, t.concluida_em, t.resultado = "feita", agora(), f"Renovado (venda nº {venda.id})"
    if parceiro:
        ativar_parceiro_na_primeira_venda(db, parceiro, vendedor)
    return venda


def ativar_parceiro_na_primeira_venda(db: Session, parceiro: Parceiro, usuario: Usuario | None):
    if parceiro.status != "EM ATIVAÇÃO":
        return
    parceiro.status = "ATIVO"
    if parceiro.lead_id:
        lead = db.get(Lead, parceiro.lead_id)
        if lead and lead.status != "Parceiro ativo":
            from .leads_servico import mudar_status

            mudar_status(db, lead, "Parceiro ativo", usuario, "primeira venda do parceiro")


# ---------------------------------------------------------------- Vencimentos e renovação

def niveis_alerta(db: Session) -> list[int]:
    try:
        niveis = sorted({int(x) for x in ler_config(db, "alertas_vencimento").split(",") if x.strip()}, reverse=True)
    except ValueError:
        niveis = [90, 60, 30, 15, 7]
    return niveis or [90, 60, 30, 15, 7]


def responsavel_padrao(db: Session, parceiro: Parceiro | None) -> int | None:
    if parceiro and parceiro.vendedor_id:
        return parceiro.vendedor_id
    admin = db.execute(select(Usuario.id).where(Usuario.perfil == "admin", Usuario.ativo.is_(True))
                       .order_by(Usuario.id).limit(1)).scalar()
    return admin


def processar_vencimentos(db: Session, hoje: date | None = None) -> int:
    """Gera (ou atualiza) a tarefa de renovação quando o certificado entra em cada faixa de alerta
    (90, 60, 30, 15 e 7 dias) e marca como vencidos os que passaram da data."""
    hoje = hoje or date.today()
    niveis = niveis_alerta(db)
    criadas = 0
    ativos = db.execute(select(Certificado).where(Certificado.status.in_(["Ativo", "Em renovação"]))).scalars().all()
    for cert in ativos:
        dias = (cert.data_vencimento - hoje).days
        if dias < 0:
            cert.status = "Vencido"
            continue
        alcancados = [n for n in niveis if dias <= n]
        if not alcancados:
            continue
        nivel = min(alcancados)
        if cert.ultimo_alerta is not None and cert.ultimo_alerta <= nivel:
            continue
        cert.ultimo_alerta = nivel
        parceiro = db.get(Parceiro, cert.parceiro_id) if cert.parceiro_id else None
        acao = f"Certificado de {cert.cliente_nome} vence em {dias} dias ({cert.data_vencimento:%d/%m/%Y}). CONTATAR CLIENTE"
        tarefa = db.execute(select(Tarefa).where(Tarefa.certificado_id == cert.id, Tarefa.status == "pendente")
                            .limit(1)).scalars().first()
        if tarefa:
            tarefa.acao, tarefa.data = acao, hoje
        else:
            telefone = cert.cliente.telefone if cert.cliente else ""
            db.add(Tarefa(
                tipo="renovacao", certificado_id=cert.id, cliente_id=cert.cliente_id,
                parceiro_id=cert.parceiro_id, usuario_id=responsavel_padrao(db, parceiro),
                canal="whatsapp" if telefone else "ligacao", data=hoje, hora="09:00", acao=acao,
                mensagem=(f"Olá! O certificado digital ({cert.tipo}) de {cert.cliente_nome} vence em "
                          f"{cert.data_vencimento:%d/%m/%Y}. Podemos já agendar a renovação para não ficar sem "
                          f"o certificado?" + (f" Atendimento em parceria com {parceiro.escritorio}." if parceiro else "")),
            ))
            criadas += 1
    return criadas


def receita_renovacao_estimada(db: Session, dias: int = 90) -> tuple[int, float]:
    """(quantidade, valor) dos certificados que vencem nos próximos N dias, pelo preço atual do produto."""
    hoje = date.today()
    certs = db.execute(select(Certificado).where(
        Certificado.status.in_(["Ativo", "Em renovação"]),
        Certificado.data_vencimento >= hoje, Certificado.data_vencimento <= hoje + timedelta(days=dias),
    )).scalars().all()
    precos = {p.nome: p.preco for p in db.execute(select(Produto)).scalars()}
    vendas_valores = [v for (v,) in db.execute(select(Venda.valor))]
    ticket = sum(vendas_valores) / len(vendas_valores) if vendas_valores else 0
    total = sum(precos.get(c.tipo, ticket) for c in certs)
    return len(certs), round(total, 2)
