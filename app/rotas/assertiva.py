"""Consultas da Assertiva (app/assertiva.py, docs/assertiva.md): a tela "Consulta Assertiva", o resultado de cada
consulta, o uso na ficha do lead e as credenciais da marca em Configurações > Integrações (pedido da Maria em
18/11/2026: cada marca com a sua chave)."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import assertiva, autorizacao, marca, util
from ..banco import obter_db
from ..modelos import ConsultaAssertiva, ContaAssertiva, Lead, Usuario
from ..seguranca import exige, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()
INTEGRACOES = "/configuracoes?aba=integracoes#assertiva"


def _conta_da_tela(request: Request, usuario: Usuario, db: Session) -> tuple[ContaAssertiva | None, str]:
    """A conta da marca da tela, ou o motivo de não dar (Admin Master fora de uma marca)."""
    if marca.ar_da_tela(request, usuario) is None:
        return None, ("Entre numa marca (painel do Admin Master > Entrar na AR) para usar ou configurar a Assertiva "
                      "dela: cada marca tem as próprias credenciais.")
    return assertiva.da_ar(db), ""


def painel(request: Request, usuario: Usuario, db: Session) -> dict:
    """O quadro da Assertiva em Configurações > Integrações."""
    conta, motivo = _conta_da_tela(request, usuario, db)
    return {"motivo": motivo, "configurada": assertiva.configurada(conta), "id_mascarado": assertiva.id_mascarado(conta),
            "situacao": assertiva.situacao(conta), "testado_em": conta.testado_em if conta else None,
            "finalidade": conta.finalidade if conta else 5, "finalidades": assertiva.FINALIDADES}


@rotas.get("/assertiva")
def tela_assertiva(request: Request, tipo: str = "cnpj", usuario: Usuario = Depends(exige("assertiva.consultar")),
                   db: Session = Depends(obter_db)):
    conta, motivo = _conta_da_tela(request, usuario, db)
    ultimas = [] if motivo else db.execute(select(ConsultaAssertiva).order_by(ConsultaAssertiva.id.desc())
                                           .limit(30)).scalars().all()
    pessoas = {u.id: u.nome for u in db.execute(select(Usuario)).scalars()} if ultimas else {}
    return tela(request, "assertiva.html", {
        "motivo": motivo, "configurada": assertiva.configurada(conta), "tipos": assertiva.TIPOS,
        "tipo": tipo if tipo in assertiva.TIPOS else "cnpj", "buscar_por": assertiva.BUSCAR_POR, "ufs": assertiva.UFS,
        "finalidade": assertiva.FINALIDADES.get(conta.finalidade if conta else 5, ""), "ultimas": ultimas,
        "pessoas": pessoas, "mascarar": assertiva.mascarar, "dias_guarda": assertiva.DIAS_GUARDA})


@rotas.post("/assertiva/consultar", dependencies=[Depends(verificar_csrf)])
async def consultar(request: Request, usuario: Usuario = Depends(exige("assertiva.consultar")),
                    db: Session = Depends(obter_db)):
    form = await request.form()
    tipo = str(form.get("tipo") or "")
    conta, motivo = _conta_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/assertiva")
    filtros = {c: str(form.get(c) or "") for c in ("nome", "buscar_por", "uf", "cidade")}
    try:
        consulta, reaproveitada = assertiva.consultar(db, conta, usuario, tipo, str(form.get("valor") or ""),
                                                      filtros=filtros, de_novo=bool(form.get("de_novo")))
    except assertiva.ErroAssertiva as erro:
        avisar(request, str(erro), "erro")
        return voltar(f"/assertiva?tipo={tipo if tipo in assertiva.TIPOS else 'cnpj'}")
    db.commit()
    if reaproveitada:
        avisar(request, f"Esta consulta já tinha sido feita em {consulta.criado_em:%d/%m/%Y às %H:%M}: o resultado "
                        "guardado aparece de novo, sem cobrar. Para buscar dados novos, use \"Consultar de novo\".",
               "alerta")
    return voltar(f"/assertiva/consulta/{consulta.id}")


@rotas.get("/assertiva/consulta/{cid:int}")
def ver_consulta(request: Request, cid: int, lead: int = 0, usuario: Usuario = Depends(exige("assertiva.consultar")),
                 db: Session = Depends(obter_db)):
    consulta = db.get(ConsultaAssertiva, cid)  # a sessão da tela só enxerga a marca da pessoa (app/isolamento.py)
    if consulta is None:
        raise HTTPException(404)
    do_lead = db.get(Lead, lead) if lead else None
    if do_lead is not None and not autorizacao.pode(usuario, "leads.editar", do_lead):
        do_lead = None
    partes = consulta.chave.split("|") if consulta.tipo == "nome" else []
    return tela(request, "assertiva_consulta.html", {
        "c": consulta, "r": assertiva.resumo(consulta), "lead": do_lead,
        "quem": db.get(Usuario, consulta.usuario_id) if consulta.usuario_id else None,
        "finalidade": assertiva.FINALIDADES.get(consulta.finalidade, str(consulta.finalidade)),
        "mascarar": assertiva.mascarar, "dias_guarda": assertiva.DIAS_GUARDA,
        "de_novo_nome": dict(zip(("buscar_por", "nome", "uf", "cidade"), partes)) if len(partes) == 4 else {}})


@rotas.post("/leads/{lead_id:int}/assertiva", dependencies=[Depends(verificar_csrf)])
def consultar_do_lead(request: Request, lead_id: int, de_novo: str = Form(""),
                      usuario: Usuario = Depends(exige("leads.editar", "assertiva.consultar")),
                      db: Session = Depends(obter_db)):
    lead = autorizacao.garantir(usuario, "leads.editar", db.get(Lead, lead_id))
    conta, motivo = _conta_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar(f"/leads/{lead_id}")
    if not util.cnpj_valido(lead.cnpj):
        avisar(request, "Este lead não tem um CNPJ válido: preencha o CNPJ em Editar para consultar na Assertiva.",
               "alerta")
        return voltar(f"/leads/{lead_id}")
    try:
        consulta, reaproveitada = assertiva.consultar(db, conta, usuario, "cnpj", lead.cnpj, lead=lead,
                                                      de_novo=bool(de_novo))
    except assertiva.ErroAssertiva as erro:
        avisar(request, str(erro), "erro")
        return voltar(f"/leads/{lead_id}")
    db.commit()
    if reaproveitada:
        avisar(request, f"Este CNPJ já tinha sido consultado em {consulta.criado_em:%d/%m/%Y}: o resultado guardado "
                        "aparece de novo, sem cobrar.", "alerta")
    return voltar(f"/assertiva/consulta/{consulta.id}?lead={lead_id}")


@rotas.post("/leads/{lead_id:int}/assertiva/usar", dependencies=[Depends(verificar_csrf)])
def usar_no_lead(request: Request, lead_id: int, consulta: int = Form(...), campo: str = Form(...),
                 valor: str = Form(""), usuario: Usuario = Depends(exige("leads.editar", "assertiva.consultar")),
                 db: Session = Depends(obter_db)):
    lead = autorizacao.garantir(usuario, "leads.editar", db.get(Lead, lead_id))
    c = db.get(ConsultaAssertiva, consulta)
    if c is None:
        raise HTTPException(404)
    try:
        texto = assertiva.usar_no_lead(db, lead, c, campo, valor, usuario)
    except assertiva.ErroAssertiva as erro:
        avisar(request, str(erro), "erro")
        return voltar(f"/assertiva/consulta/{c.id}?lead={lead_id}")
    registrar_log(db, usuario, "usou_dado_assertiva", "lead", lead.id,
                  f"{assertiva.CAMPOS_DO_LEAD[campo]} vindo da consulta {c.id}", request, modulo="assertiva")
    db.commit()
    avisar(request, texto)
    return voltar(f"/assertiva/consulta/{c.id}?lead={lead_id}")


# ---------------------------------------------------------------- Configurações > Integrações

@rotas.post("/configuracoes/assertiva", dependencies=[Depends(verificar_csrf)])
async def salvar_credenciais(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")),
                             db: Session = Depends(obter_db)):
    form = await request.form()
    conta, motivo = _conta_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar(INTEGRACOES)
    conta, problemas = assertiva.salvar(db, conta, {c: str(form.get(c) or "")
                                                    for c in ("client_id", "segredo", "finalidade")})
    if problemas:
        db.rollback()
        avisar(request, " ".join(problemas), "erro")
        return voltar(INTEGRACOES)
    registrar_log(db, usuario, "salvou_credenciais_assertiva", "configuracao", None,
                  f"finalidade {conta.finalidade}", request, modulo="assertiva")  # as credenciais não vão no registro
    db.commit()
    avisar(request, "Credenciais da Assertiva salvas para esta marca. Clique em \"Testar as credenciais\" para "
                    "conferir (não gasta consulta).")
    return voltar(INTEGRACOES)


@rotas.post("/configuracoes/assertiva/testar", dependencies=[Depends(verificar_csrf)])
def testar_credenciais(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")),
                       db: Session = Depends(obter_db)):
    conta, motivo = _conta_da_tela(request, usuario, db)
    if motivo or not assertiva.configurada(conta):
        avisar(request, motivo or "Salve primeiro o Client ID e o Client Secret da Assertiva.", "erro")
        return voltar(INTEGRACOES)
    try:
        texto = assertiva.testar(db, conta)
    except assertiva.ErroAssertiva as erro:
        db.commit()  # guarda que o teste falhou (aparece no quadro)
        avisar(request, str(erro), "erro")
        return voltar(INTEGRACOES)
    db.commit()
    avisar(request, texto)
    return voltar(INTEGRACOES)


@rotas.post("/configuracoes/assertiva/apagar", dependencies=[Depends(verificar_csrf)])
def apagar_credenciais(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")),
                       db: Session = Depends(obter_db)):
    conta, motivo = _conta_da_tela(request, usuario, db)
    if motivo or conta is None:
        avisar(request, motivo or "Esta marca não tem credenciais da Assertiva salvas.", "erro")
        return voltar(INTEGRACOES)
    db.delete(conta)
    registrar_log(db, usuario, "apagou_credenciais_assertiva", "configuracao", None, "", request, modulo="assertiva")
    db.commit()
    avisar(request, "Credenciais da Assertiva apagadas desta marca. As consultas ficam paradas até salvar outras.")
    return voltar(INTEGRACOES)
