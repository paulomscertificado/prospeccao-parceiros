"""Parceiros, clientes, vendas, comissões (com calculadora) e vencimentos."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import config, metricas, planilhas, util
from ..banco import agora, ler_config_int, obter_db
from ..modelos import Certificado, Cliente, Lead, Parceiro, Produto, Tarefa, Usuario, Venda
from ..seguranca import (admin, criptografar, descriptografar, equipe, gestao, registrar_log, ve_tudo,
                         verificar_csrf)
from ..vendas_servico import calcular, descrever_regra, processar_vencimentos, registrar_venda
from ..web import avisar, tela, voltar

rotas = APIRouter()


def _vendedores(db):
    return list(db.execute(select(Usuario).where(Usuario.perfil.in_(["vendedor", "gestor", "admin"]),
                                                 Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars())


def _parceiros_visiveis(db: Session, usuario: Usuario):
    consulta = select(Parceiro).order_by(Parceiro.escritorio)
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where(Parceiro.vendedor_id == usuario.id)
    return list(db.execute(consulta).scalars())


def _parceiro(db: Session, pid: int, usuario: Usuario) -> Parceiro:
    p = db.get(Parceiro, pid)
    if not p or (usuario.perfil in config.PERFIS_SO_PROPRIOS and p.vendedor_id != usuario.id):
        raise HTTPException(404)
    return p


# ---------------------------------------------------------------- Parceiros

@rotas.get("/parceiros")
def parceiros(request: Request, status: str = "", q: str = "", aba: str = "lista", usuario: Usuario = Depends(equipe),
              db: Session = Depends(obter_db)):
    ranking = metricas.ranking_parceiros(db, usuario)
    if status:
        ranking = [r for r in ranking if r["status"] == status]
    if q:
        termo = util.chave_texto(q)
        ranking = [r for r in ranking if termo in util.chave_texto(r["nome"]) or termo in util.chave_texto(r["cidade"])]
    return tela(request, "parceiros.html", {
        "linhas": sorted(ranking, key=lambda r: r["nome"].lower()), "status": status, "q": q, "aba": aba,
        "mais_venderam": sorted([r for r in ranking if r["certificados"]], key=lambda r: -r["certificados"])[:10],
        "mais_indicaram": sorted([r for r in ranking if r["indicados"]], key=lambda r: -r["indicados"])[:10],
        "maior_faturamento": sorted([r for r in ranking if r["faturamento"]], key=lambda r: -r["faturamento"])[:10],
        "parados": metricas.parceiros_parados(db, usuario),
        "dias_parado": ler_config_int(db, "dias_parceiro_parado", 30),
    })


@rotas.get("/parceiros/{pid:int}")
def parceiro_ficha(request: Request, pid: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    if pid == 0:
        p = Parceiro(escritorio="", status="EM ATIVAÇÃO", data_entrada=date.today(), comissao_tipo="", comissao_valor=0)
        return tela(request, "parceiro.html", {"p": p, "novo": True, "vendedores": _vendedores(db)})
    p = _parceiro(db, pid, usuario)
    clientes = db.execute(select(Cliente).where(Cliente.parceiro_id == p.id).order_by(Cliente.criado_em.desc())).scalars().all()
    vendas = db.execute(select(Venda).where(Venda.parceiro_id == p.id).order_by(Venda.data.desc())).scalars().all()
    certificados = db.execute(select(Certificado).where(Certificado.parceiro_id == p.id)
                              .order_by(Certificado.data_vencimento)).scalars().all()
    tipo, valor = (p.comissao_tipo, p.comissao_valor) if p.comissao_tipo else ("", 0)
    acesso = db.execute(select(Usuario).where(Usuario.parceiro_id == p.id)).scalars().first()
    return tela(request, "parceiro.html", {
        "p": p, "novo": False, "clientes": clientes, "vendas": vendas, "certificados": certificados,
        "vendedores": _vendedores(db), "chave_pix": descriptografar(p.chave_pix_cripto) if ve_tudo(usuario) else "",
        "regra": descrever_regra(tipo, valor) if tipo else "Regra padrão de cada produto",
        "totais": {"indicados": len(clientes), "vendidos": len(vendas), "receita": sum(v.valor for v in vendas),
                   "comissao": sum(v.comissao for v in vendas),
                   "a_pagar": sum(v.comissao for v in vendas if not v.comissao_paga),
                   "ultima_venda": vendas[0].data if vendas else None},
        "acesso": acesso, "lead": db.get(Lead, p.lead_id) if p.lead_id else None,
    })


@rotas.post("/parceiros/{pid:int}", dependencies=[Depends(verificar_csrf)])
async def parceiro_salvar(request: Request, pid: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    form = await request.form()
    p = Parceiro() if pid == 0 else _parceiro(db, pid, usuario)
    p.escritorio = str(form.get("escritorio", "")).strip()
    if not p.escritorio:
        avisar(request, "Informe o nome do escritório.", "erro")
        return voltar(f"/parceiros/{pid}")
    cnpj = str(form.get("cnpj", ""))
    if cnpj and not util.cnpj_valido(cnpj):
        avisar(request, "CNPJ inválido. Confira os números.", "erro")
        return voltar(f"/parceiros/{pid}")
    p.cnpj = util.formatar_cnpj(cnpj) if cnpj else ""
    for campo in ("responsavel", "email", "cidade", "observacoes"):
        setattr(p, campo, str(form.get(campo, "")).strip())
    p.telefone = util.formatar_telefone(str(form.get("telefone", "")))
    p.estado = str(form.get("estado", "")).upper()[:2]
    p.data_entrada = util.para_data(form.get("data_entrada")) or p.data_entrada or date.today()
    if form.get("status") in config.STATUS_PARCEIRO:
        p.status = form.get("status")
    if ve_tudo(usuario):
        p.vendedor_id = util.para_int(form.get("vendedor_id"))
        tipo = str(form.get("comissao_tipo", ""))
        p.comissao_tipo = tipo if tipo in ("percentual", "fixo") else ""
        p.comissao_valor = util.para_float(form.get("comissao_valor")) if p.comissao_tipo else 0
        pix = str(form.get("chave_pix", "")).strip()
        if pix != descriptografar(p.chave_pix_cripto):
            p.chave_pix_cripto = criptografar(pix)
    elif pid == 0:
        p.vendedor_id = usuario.id
    if pid == 0:
        db.add(p)
    db.flush()
    registrar_log(db, usuario, "salvou_parceiro", "parceiro", p.id, p.escritorio, request)
    db.commit()
    avisar(request, "Parceiro salvo.")
    return voltar(f"/parceiros/{p.id}")


# ---------------------------------------------------------------- Clientes

@rotas.get("/clientes")
def clientes(request: Request, q: str = "", parceiro: int | None = None, status: str = "",
             usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    consulta = select(Cliente).order_by(Cliente.criado_em.desc())
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        ids = [p.id for p in _parceiros_visiveis(db, usuario)]
        consulta = consulta.where(Cliente.parceiro_id.in_(ids))
    if q:
        consulta = consulta.where(or_(Cliente.nome.ilike(f"%{q}%"), Cliente.cnpj.ilike(f"%{q}%")))
    if parceiro:
        consulta = consulta.where(Cliente.parceiro_id == parceiro)
    if status:
        consulta = consulta.where(Cliente.status == status)
    return tela(request, "clientes.html", {"clientes": db.execute(consulta.limit(500)).scalars().all(), "q": q,
                                           "parceiro": parceiro, "status": status,
                                           "parceiros": _parceiros_visiveis(db, usuario)})


@rotas.post("/clientes/{cid:int}", dependencies=[Depends(verificar_csrf)])
async def cliente_salvar(request: Request, cid: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    form = await request.form()
    c = Cliente(origem="Direto") if cid == 0 else db.get(Cliente, cid)
    if c is None:
        raise HTTPException(404)
    c.nome = str(form.get("nome", "")).strip()
    if not c.nome:
        avisar(request, "Informe o nome do cliente.", "erro")
        return voltar("/clientes")
    c.cnpj = util.formatar_cnpj(str(form.get("cnpj", "")))
    c.contato = str(form.get("contato", "")).strip()
    c.telefone = util.formatar_telefone(str(form.get("telefone", "")))
    c.email = str(form.get("email", "")).strip().lower()
    c.parceiro_id = util.para_int(form.get("parceiro_id"))
    if c.parceiro_id and cid == 0:
        c.origem = "Indicação"
    if form.get("status") in config.STATUS_CLIENTE:
        c.status = form.get("status")
    c.observacoes = str(form.get("observacoes", ""))
    if cid == 0:
        db.add(c)
    db.commit()
    avisar(request, "Cliente salvo.")
    return voltar(str(form.get("voltar_para") or "/clientes"))


# ---------------------------------------------------------------- Vendas

@rotas.get("/vendas")
def vendas(request: Request, periodo: str = "90d", parceiro: int | None = None, cliente: int | None = None,
           renovar: int | None = None, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    p = metricas.periodo(periodo)
    consulta = select(Venda).where(Venda.data >= p.inicio).order_by(Venda.data.desc(), Venda.id.desc())
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where(Venda.vendedor_id == usuario.id)
    if parceiro:
        consulta = consulta.where(Venda.parceiro_id == parceiro)
    lista = db.execute(consulta.limit(500)).scalars().all()
    cert_renovar = db.get(Certificado, renovar) if renovar else None
    return tela(request, "vendas.html", {
        "vendas": lista, "periodo": periodo, "p": p, "parceiro": parceiro,
        "totais": {"qtd": len(lista), "receita": sum(v.valor for v in lista), "comissao": sum(v.comissao for v in lista),
                   "lucro": sum(v.valor - v.custo - v.comissao for v in lista)},
        "produtos": db.execute(select(Produto).where(Produto.ativo.is_(True)).order_by(Produto.nome)).scalars().all(),
        "parceiros": _parceiros_visiveis(db, usuario) if usuario.perfil in config.PERFIS_SO_PROPRIOS else
        db.execute(select(Parceiro).where(Parceiro.status != "BLOQUEADO").order_by(Parceiro.escritorio)).scalars().all(),
        "clientes": db.execute(select(Cliente).order_by(Cliente.nome).limit(1000)).scalars().all(),
        "cliente_sel": cliente, "renovar": cert_renovar, "vendedores": _vendedores(db),
    })


@rotas.post("/vendas/nova", dependencies=[Depends(verificar_csrf)])
async def venda_nova(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    form = await request.form()
    cliente = db.get(Cliente, util.para_int(form.get("cliente_id")) or 0)
    parceiro = db.get(Parceiro, util.para_int(form.get("parceiro_id")) or 0)
    if not cliente:
        nome = str(form.get("cliente_nome", "")).strip()
        if not nome:
            avisar(request, "Escolha um cliente ou digite o nome de um cliente novo.", "erro")
            return voltar("/vendas")
        cliente = Cliente(nome=nome, cnpj=util.formatar_cnpj(str(form.get("cliente_cnpj", ""))),
                          telefone=util.formatar_telefone(str(form.get("cliente_telefone", ""))),
                          parceiro_id=parceiro.id if parceiro else None, origem="Indicação" if parceiro else "Direto")
        db.add(cliente)
        db.flush()
    if parceiro is None and cliente.parceiro_id:
        parceiro = db.get(Parceiro, cliente.parceiro_id)
    if parceiro and parceiro.status == "BLOQUEADO":
        avisar(request, "Este parceiro está BLOQUEADO e não pode receber comissão.", "erro")
        return voltar("/vendas")
    produto = db.get(Produto, util.para_int(form.get("produto_id")) or 0)
    vendedor = db.get(Usuario, util.para_int(form.get("vendedor_id")) or 0) if ve_tudo(usuario) else usuario
    anterior = db.get(Certificado, util.para_int(form.get("certificado_id")) or 0) if form.get("certificado_id") else None
    venda = registrar_venda(
        db, cliente=cliente, produto=produto, parceiro=parceiro, valor=util.para_float(form.get("valor")) or None,
        data=util.para_data(form.get("data")) or date.today(),
        tipo="renovacao" if form.get("tipo") == "renovacao" or anterior else "nova",
        vendedor=vendedor or usuario, certificado_anterior=anterior, observacoes=str(form.get("observacoes", "")))
    registrar_log(db, usuario, "registrou_venda", "venda", venda.id, f"{cliente.nome} {util.moeda(venda.valor)}", request)
    db.commit()
    avisar(request, f"Venda registrada: {util.moeda(venda.valor)}"
                    + (f", comissão de {util.moeda(venda.comissao)} para {parceiro.escritorio}." if parceiro else ".")
                    + " O certificado já entrou no controle de vencimentos.")
    return voltar("/vendas")


@rotas.post("/vendas/{vid:int}/excluir", dependencies=[Depends(verificar_csrf)])
def venda_excluir(request: Request, vid: int, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    v = db.get(Venda, vid)
    if not v:
        raise HTTPException(404)
    for c in db.execute(select(Certificado).where(Certificado.venda_id == v.id)).scalars():
        db.delete(c)
    registrar_log(db, usuario, "excluiu_venda", "venda", v.id, f"{v.cliente.nome} {util.moeda(v.valor)}", request)
    db.delete(v)
    db.commit()
    avisar(request, "Venda excluída (o certificado dela saiu do controle de vencimentos).")
    return voltar("/vendas")


# ---------------------------------------------------------------- Comissões e calculadora

@rotas.get("/comissoes")
def comissoes(request: Request, situacao: str = "a_pagar", parceiro: int | None = None,
              usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    consulta = select(Venda).where(Venda.comissao > 0).order_by(Venda.data.desc())
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where(Venda.vendedor_id == usuario.id)
    if situacao == "a_pagar":
        consulta = consulta.where(Venda.comissao_paga.is_(False))
    elif situacao == "pagas":
        consulta = consulta.where(Venda.comissao_paga.is_(True))
    if parceiro:
        consulta = consulta.where(Venda.parceiro_id == parceiro)
    lista = db.execute(consulta.limit(1000)).scalars().all()
    por_parceiro = {}
    for v in lista:
        item = por_parceiro.setdefault(v.parceiro_id, {"parceiro": v.parceiro, "qtd": 0, "total": 0.0})
        item["qtd"] += 1
        item["total"] += v.comissao
    produtos = db.execute(select(Produto).order_by(Produto.nome)).scalars().all()
    calculos = {pr.id: calcular(pr.preco, pr.custo, pr.comissao_tipo, pr.comissao_valor) for pr in produtos}
    return tela(request, "comissoes.html", {
        "vendas": lista, "situacao": situacao, "parceiro": parceiro, "por_parceiro": list(por_parceiro.values()),
        "total": sum(v.comissao for v in lista), "produtos": produtos, "calculos": calculos,
        "parceiros": _parceiros_visiveis(db, usuario),
        "regras_especiais": db.execute(select(Parceiro).where(Parceiro.comissao_tipo != "")).scalars().all(),
        "descrever_regra": descrever_regra,
    })


@rotas.post("/comissoes/pagar", dependencies=[Depends(verificar_csrf)])
async def comissoes_pagar(request: Request, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    vendas = db.execute(select(Venda).where(Venda.id.in_(ids), Venda.comissao_paga.is_(False))).scalars().all()
    for v in vendas:
        v.comissao_paga, v.comissao_paga_em = True, date.today()
    registrar_log(db, usuario, "pagou_comissoes", "venda", None,
                  f"{len(vendas)} comissões, total {util.moeda(sum(v.comissao for v in vendas))}", request)
    db.commit()
    avisar(request, f"{len(vendas)} comissões marcadas como pagas ({util.moeda(sum(v.comissao for v in vendas))}).")
    return voltar("/comissoes")


@rotas.post("/produtos/{pid:int}", dependencies=[Depends(verificar_csrf)])
async def produto_salvar(request: Request, pid: int, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    form = await request.form()
    pr = Produto() if pid == 0 else db.get(Produto, pid)
    if pr is None:
        raise HTTPException(404)
    pr.nome = str(form.get("nome", "")).strip() or "Produto"
    pr.preco = util.para_float(form.get("preco"))
    pr.custo = util.para_float(form.get("custo"))
    pr.comissao_tipo = "fixo" if form.get("comissao_tipo") == "fixo" else "percentual"
    pr.comissao_valor = util.para_float(form.get("comissao_valor"))
    pr.validade_meses = util.para_int(form.get("validade_meses")) or 12
    pr.ativo = form.get("ativo") == "on"
    if pid == 0:
        db.add(pr)
    registrar_log(db, usuario, "salvou_produto", "produto", pr.id, pr.nome, request)
    db.commit()
    avisar(request, "Produto salvo.")
    return voltar("/comissoes#produtos")


# ---------------------------------------------------------------- Vencimentos

@rotas.get("/vencimentos")
def vencimentos(request: Request, janela: str = "30", parceiro: int | None = None, usuario: Usuario = Depends(equipe),
                db: Session = Depends(obter_db)):
    processar_vencimentos(db)
    db.commit()
    hoje = date.today()
    consulta = select(Certificado).order_by(Certificado.data_vencimento)
    if janela == "vencidos":
        consulta = consulta.where(Certificado.status == "Vencido")
    elif janela == "todos":
        pass
    else:
        dias = util.para_int(janela) or 30
        consulta = consulta.where(Certificado.status.in_(["Ativo", "Em renovação"]),
                                  Certificado.data_vencimento <= hoje + timedelta(days=dias))
    if parceiro:
        consulta = consulta.where(Certificado.parceiro_id == parceiro)
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        ids = [p.id for p in _parceiros_visiveis(db, usuario)]
        consulta = consulta.where(or_(Certificado.parceiro_id.in_(ids), Certificado.parceiro_id.is_(None)))
    certs = db.execute(consulta.limit(1000)).scalars().all()
    faixas = {}
    for dias in (7, 15, 30, 60, 90):
        faixas[dias] = sum(1 for c in db.execute(select(Certificado.data_vencimento).where(
            Certificado.status.in_(["Ativo", "Em renovação"]), Certificado.data_vencimento >= hoje,
            Certificado.data_vencimento <= hoje + timedelta(days=dias))).all())
    return tela(request, "vencimentos.html", {
        "certs": certs, "janela": janela, "parceiro": parceiro, "faixas": faixas,
        "parceiros": _parceiros_visiveis(db, usuario), "hoje": hoje,
        "tarefas": {t.certificado_id: t for t in db.execute(select(Tarefa).where(
            Tarefa.certificado_id.is_not(None), Tarefa.status == "pendente")).scalars()},
    })


@rotas.post("/vencimentos/{cid:int}/status", dependencies=[Depends(verificar_csrf)])
def vencimento_status(request: Request, cid: int, status: str = Form(...), usuario: Usuario = Depends(equipe),
                      db: Session = Depends(obter_db)):
    c = db.get(Certificado, cid)
    if not c or status not in config.STATUS_CERTIFICADO:
        raise HTTPException(404)
    c.status = status
    if status in ("Não renovará", "Renovado"):
        for t in db.execute(select(Tarefa).where(Tarefa.certificado_id == c.id, Tarefa.status == "pendente")).scalars():
            t.status, t.concluida_em, t.resultado = "feita", agora(), status
    db.commit()
    avisar(request, f"Certificado de {c.cliente_nome}: {status}.")
    return voltar("/vencimentos")


@rotas.post("/vencimentos/importar", dependencies=[Depends(verificar_csrf)])
async def vencimentos_importar(request: Request, arquivo: UploadFile = File(...), usuario: Usuario = Depends(gestao),
                               db: Session = Depends(obter_db)):
    conteudo = await arquivo.read()
    try:
        linhas = planilhas.ler_linhas(arquivo.filename, conteudo)
    except planilhas.ErroPlanilha as erro:
        avisar(request, str(erro), "erro")
        return voltar("/vencimentos")
    parceiros = list(db.execute(select(Parceiro)).scalars())
    por_nome = {util.chave_texto(p.escritorio): p for p in parceiros}
    por_cnpj = {util.normalizar_cnpj(p.cnpj): p for p in parceiros if p.cnpj}
    importados, erros, duplicados = 0, [], 0
    for numero, linha in enumerate(linhas, start=2):
        d = planilhas.mapear(linha, planilhas.SINONIMOS_CERTIFICADO)
        vencimento = util.para_data(d.get("data_vencimento"))
        if not d.get("cliente") or not vencimento:
            erros.append(f"linha {numero}: falta o cliente ou a data de vencimento")
            continue
        documento = util.formatar_cnpj(d.get("cnpj", ""))
        ja_existe = db.execute(select(Certificado.id).where(
            Certificado.cliente_nome == d["cliente"], Certificado.data_vencimento == vencimento)).first()
        if ja_existe:
            duplicados += 1
            continue
        parceiro = por_cnpj.get(util.normalizar_cnpj(d.get("parceiro", ""))) or por_nome.get(util.chave_texto(d.get("parceiro", "")))
        cliente = db.execute(select(Cliente).where(Cliente.nome == d["cliente"])).scalars().first()
        if not cliente:
            cliente = Cliente(nome=d["cliente"], cnpj=documento, telefone=util.formatar_telefone(d.get("telefone", "")),
                              email=d.get("email", ""), parceiro_id=parceiro.id if parceiro else None,
                              status="Emitido", origem="Importação")
            db.add(cliente)
            db.flush()
        db.add(Certificado(cliente_id=cliente.id, cliente_nome=d["cliente"], cnpj=documento, tipo=d.get("tipo", ""),
                           data_emissao=util.para_data(d.get("data_emissao")), data_vencimento=vencimento,
                           parceiro_id=parceiro.id if parceiro else None,
                           status="Vencido" if vencimento < date.today() else "Ativo"))
        importados += 1
    processar_vencimentos(db)
    registrar_log(db, usuario, "importou_vencimentos", "certificado", None, f"{importados} importados", request)
    db.commit()
    texto = f"{importados} certificados importados, {duplicados} já existiam."
    if erros:
        texto += " Problemas: " + "; ".join(erros[:10]) + ("..." if len(erros) > 10 else "")
    avisar(request, texto, "alerta" if erros else "ok")
    return voltar("/vencimentos")
