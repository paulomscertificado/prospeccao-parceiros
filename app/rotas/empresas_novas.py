"""Tela Empresas novas: campanha diária de venda de certificado para empresas recém-abertas (API CNPJá)."""

import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import arquivo_env, empresas_novas, util
from ..banco import gravar_config, obter_db
from ..modelos import Tarefa, Usuario
from ..seguranca import exige, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()


@rotas.get("/empresas-novas")
def tela_empresas_novas(request: Request, usuario: Usuario = Depends(exige("campanhas.ver")),
                        db: Session = Depends(obter_db)):
    campanhas = empresas_novas.campanhas_recentes(db)
    contagem = dict(db.execute(select(Tarefa.campanha_id, func.count(func.distinct(Tarefa.lead_id)))
                               .where(Tarefa.campanha_id.in_([c.id for c in campanhas]))
                               .group_by(Tarefa.campanha_id)).all()) if campanhas else {}
    usuarios = db.execute(select(Usuario).where(Usuario.ativo.is_(True), Usuario.perfil != "parceiro")
                          .order_by(Usuario.nome)).scalars().all()
    return tela(request, "empresas_novas.html", {
        "cfg": {c: empresas_novas.cfg(db, c) for c in empresas_novas.PADRAO},
        "mensagens": empresas_novas.mensagens(db), "angulos": empresas_novas.ANGULOS,
        "tem_chave": bool(empresas_novas.chave_api()), "campanhas": campanhas, "empresas_por_campanha": contagem,
        "usuarios": usuarios, "dono": empresas_novas.dono(db), "hoje": date.today(),
        "ontem": date.today() - timedelta(days=1),
    })


@rotas.post("/empresas-novas/configurar", dependencies=[Depends(verificar_csrf)])
async def configurar(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                     db: Session = Depends(obter_db)):
    form = await request.form()
    chave = str(form.get("chave", "")).strip()
    if chave:
        arquivo_env.gravar({"CNPJA_API_KEY": chave})
    ufs = ",".join(u for u in (p.strip().upper() for p in str(form.get("ufs", "PE")).replace(";", ",").split(","))
                   if len(u) == 2) or "PE"
    canais = ",".join(c for c in ("whatsapp", "email") if form.get(f"canal_{c}"))
    if not canais:
        avisar(request, "Escolha pelo menos um canal (WhatsApp ou e-mail).", "erro")
        return voltar("/empresas-novas")
    maximo = max(1, min(500, util.para_int(form.get("maximo_dia")) or 60))
    hora = str(form.get("hora", "07:30"))[:5] or "07:30"
    dono_id = util.para_int(form.get("dono_id"))
    if dono_id and not db.get(Usuario, dono_id):
        dono_id = None
    for chave_cfg, valor in [("novas_ativo", "1" if form.get("ativo") else "0"), ("novas_ufs", ufs),
                             ("novas_canais", canais), ("novas_maximo_dia", str(maximo)), ("novas_hora", hora),
                             ("novas_sem_individual", "1" if form.get("sem_individual") else "0"),
                             ("novas_dono_id", str(dono_id or ""))]:
        gravar_config(db, chave_cfg, valor)
    registrar_log(db, usuario, "configurou_empresas_novas", "configuracao", None, request=request)
    db.commit()
    if form.get("ativo") and not empresas_novas.chave_api():
        avisar(request, "Configuração salva, mas falta a chave da API da CNPJá para a busca diária funcionar.", "erro")
    elif form.get("ativo") and not dono_id:
        avisar(request, "Configuração salva, mas escolha quem é o dono das campanhas diárias.", "erro")
    else:
        avisar(request, "Configuração salva." + (" A busca automática roda todo dia a partir das " + hora + "."
                                                 if form.get("ativo") else ""))
    return voltar("/empresas-novas")


@rotas.post("/empresas-novas/mensagens", dependencies=[Depends(verificar_csrf)])
async def salvar_mensagens(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                           db: Session = Depends(obter_db)):
    from .. import sdr

    form = await request.form()
    novas = {}
    for angulo in empresas_novas.ANGULOS:
        item = {campo: str(form.get(f"{angulo}_{campo}", "")).strip() for campo in ("assunto", "whatsapp", "email")}
        if not all(item.values()):
            avisar(request, "Preencha o assunto, o WhatsApp e o e-mail de todos os toques.", "erro")
            return voltar("/empresas-novas#mensagens")
        if not all(sdr.texto_sem_spam(v) for v in item.values()):
            avisar(request, "Tire as frases de spam (\"excelente oportunidade\", \"promoção\", \"não perca\"...).", "erro")
            return voltar("/empresas-novas#mensagens")
        novas[angulo] = item
    gravar_config(db, "novas_mensagens", json.dumps(novas, ensure_ascii=False))
    registrar_log(db, usuario, "editou_mensagens_empresas_novas", "configuracao", None, request=request)
    db.commit()
    avisar(request, "Mensagens salvas. Valem para as próximas campanhas diárias.")
    return voltar("/empresas-novas#mensagens")


@rotas.post("/empresas-novas/restaurar-mensagens", dependencies=[Depends(verificar_csrf)])
def restaurar_mensagens(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                        db: Session = Depends(obter_db)):
    gravar_config(db, "novas_mensagens", "")
    db.commit()
    avisar(request, "Mensagens voltaram ao texto inicial.")
    return voltar("/empresas-novas#mensagens")


@rotas.post("/empresas-novas/buscar", dependencies=[Depends(verificar_csrf)])
async def buscar_agora(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                       db: Session = Depends(obter_db)):
    form = await request.form()
    desde = util.para_data(form.get("desde")) or date.today()
    ate = util.para_data(form.get("ate")) or date.today()
    if desde > ate:
        desde, ate = ate, desde
    if (ate - desde).days > 7:
        avisar(request, "Busque no máximo 7 dias de uma vez (cada empresa encontrada gasta créditos da CNPJá).", "erro")
        return voltar("/empresas-novas")
    dono = empresas_novas.dono(db) or usuario
    try:
        r = empresas_novas.buscar_e_criar(db, dono, desde, ate)
    except empresas_novas.ErroCnpja as erro:
        texto = str(erro)
        avisar(request, f"A busca não deu certo: {texto[:1].upper()}{texto[1:]}.", "erro")
        return voltar("/empresas-novas")
    registrar_log(db, usuario, "buscou_empresas_novas", "campanha", r["campanha_id"],
                  f"{r['encontradas']} encontradas", request)
    db.commit()
    if r["campanha_id"]:
        avisar(request, f"{r['encontradas']} empresas abertas encontradas. A campanha está sendo montada e vai pedir "
                        "aprovação (leva alguns minutos).")
        return voltar(f"/campanhas/{r['campanha_id']}")
    avisar(request, f"{r['encontradas']} empresas encontradas, nenhuma nova para contatar nesse período.")
    return voltar("/empresas-novas")


@rotas.post("/empresas-novas/saldo", dependencies=[Depends(verificar_csrf)])
def ver_saldo(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar"))):
    try:
        s = empresas_novas.saldo()
    except empresas_novas.ErroCnpja as erro:
        texto = str(erro)
        avisar(request, f"{texto[:1].upper()}{texto[1:]}.", "erro")
        return voltar("/empresas-novas")
    total = (s.get("perpetual") or 0) + (s.get("transient") or 0)
    avisar(request, f"A chave da CNPJá funciona. Saldo: {total} créditos ({s.get('transient', 0)} do mês e "
                    f"{s.get('perpetual', 0)} acumulados). Cada 10 empresas encontradas gastam 1 crédito.")
    return voltar("/empresas-novas")
