"""Painel do Admin Master (white label, Fase 3; docs/white-label.md).

Só o Admin Master (`Usuario.master`) enxerga: para qualquer outra pessoa, mesmo administradora, as rotas respondem 404.
- Lista das ARs com os números de cada uma (pessoas, leads, campanhas ativas, WhatsApps, administradores).
- Entrar numa AR: pede o motivo, grava em acessos_master e, até sair, a sessão do Admin Master enxerga só aquela AR
  (isolamento.ligar com `ar_entrada`), inclusive as configurações e os módulos dela. Uma faixa no topo avisa.
- Nova AR, suspender e reativar (pessoas de AR suspensa não entram: seguranca.usuario_logado).
- Módulos de cada AR: ligar e desligar por AR (configuracoes_ar; só o Admin Master muda).
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import autorizacao
from ..banco import agora, gravar_config, ler_config, obter_db, usar_config_da_ar
from ..modelos import AcessoMaster, Campanha, ConexaoWhatsApp, Lead, Tenant, Usuario
from ..seguranca import PRAZO_ENTRADA_SEG, diferencas, exige, fechar_entradas, registrar_log, verificar_csrf
from ..util import sem_acento
from ..web import avisar, tela, voltar

rotas = APIRouter()
PORTEIRO = exige("configuracoes.alterar")
SEM_FILTRO = {"sem_filtro_de_ar": True}
TAMANHO_DO_APELIDO = 39  # tenants.slug tem 40


def apelido_da_ar(texto: str) -> str:
    """O apelido da AR (vai virar o endereço dela) a partir do que a pessoa escreveu ou do nome: sem acento, minúsculo,
    e espaço ou símbolo vira hífen ("Certifica Recife" -> "certifica-recife"). Antes a tela recusava o apelido com
    espaço, acento ou maiúscula, e o navegador não avisava (o `pattern` com "-" no fim é inválido para ele)."""
    apelido = re.sub(r"[^a-z0-9]+", "-", sem_acento(texto or "").lower()).strip("-")
    return apelido[:TAMANHO_DO_APELIDO].rstrip("-")


def _so_master(usuario: Usuario) -> None:
    if not autorizacao.e_master(usuario):
        raise HTTPException(404)  # para os outros, o painel nem existe


def _por_ar(db: Session, consulta) -> dict:
    return dict(db.execute(consulta.execution_options(**SEM_FILTRO)).all())


def _fechar_entrada(db: Session, usuario: Usuario) -> None:
    fechar_entradas(db, usuario)


@rotas.get("/master")
def painel(request: Request, usuario: Usuario = Depends(PORTEIRO), db: Session = Depends(obter_db)):
    _so_master(usuario)
    ars = db.execute(select(Tenant).order_by(Tenant.id)).scalars().all()
    pessoas = _por_ar(db, select(Usuario.tenant_id, func.count(Usuario.id)).where(Usuario.ativo.is_(True))
                      .group_by(Usuario.tenant_id))
    leads = _por_ar(db, select(Lead.tenant_id, func.count(Lead.id)).group_by(Lead.tenant_id))
    campanhas = _por_ar(db, select(Campanha.tenant_id, func.count(Campanha.id)).where(Campanha.status == "ativa")
                        .group_by(Campanha.tenant_id))
    numeros = _por_ar(db, select(ConexaoWhatsApp.tenant_id, func.count(ConexaoWhatsApp.id))
                      .group_by(ConexaoWhatsApp.tenant_id))
    admins: dict[int, list[str]] = {}
    for ar, nome in db.execute(select(Usuario.tenant_id, Usuario.nome).where(
            Usuario.perfil == "admin", Usuario.ativo.is_(True), Usuario.master.is_(False))
            .execution_options(**SEM_FILTRO)).all():
        admins.setdefault(ar, []).append(nome)
    modulos: dict[int, dict[str, bool]] = {}
    anterior = db.info.pop("ar_config", None)
    for ar in ars:
        usar_config_da_ar(db, ar.id)
        modulos[ar.id] = {m: ler_config(db, chave) != "0" for m, (_, chave) in autorizacao.MODULOS.items()}
    usar_config_da_ar(db, anterior)
    acessos = db.execute(select(AcessoMaster).order_by(AcessoMaster.id.desc()).limit(20)).scalars().all()
    return tela(request, "master.html", {
        "ars": ars, "pessoas": pessoas, "leads": leads, "campanhas": campanhas, "numeros": numeros,
        "admins": admins, "modulos": modulos, "nomes_modulos": {m: n for m, (n, _) in autorizacao.MODULOS.items()},
        "acessos": acessos, "nome_ar": {a.id: a.nome for a in ars},
        "dentro": request.session.get("ar_entrada")})


@rotas.post("/master/entrar/{tid:int}", dependencies=[Depends(verificar_csrf)])
def entrar(request: Request, tid: int, motivo: str = Form(""), usuario: Usuario = Depends(PORTEIRO),
           db: Session = Depends(obter_db)):
    _so_master(usuario)
    ar = db.get(Tenant, tid)
    if ar is None:
        raise HTTPException(404)
    motivo = motivo.strip()
    if len(motivo) < 5:
        avisar(request, "Escreva o motivo de entrar na AR (fica registrado).", "erro")
        return voltar("/master")
    _fechar_entrada(db, usuario)
    db.add(AcessoMaster(usuario_id=usuario.id, tenant_id=ar.id, motivo=motivo[:300]))
    request.session["ar_entrada"], request.session["ar_entrada_nome"] = ar.id, ar.nome
    request.session["ar_entrada_ate"] = int(time.time()) + PRAZO_ENTRADA_SEG  # por até 2 horas
    registrar_log(db, usuario, "entrou_na_ar", "tenant", ar.id, f"{ar.nome}: {motivo[:200]}", request)
    db.commit()
    avisar(request, f"Você entrou na {ar.nome}: por até 2 horas (ou até sair), vê e mexe só no que é dela.")
    return voltar("/")


@rotas.post("/master/sair", dependencies=[Depends(verificar_csrf)])
def sair(request: Request, usuario: Usuario = Depends(PORTEIRO), db: Session = Depends(obter_db)):
    _so_master(usuario)
    nome = request.session.pop("ar_entrada_nome", "")
    request.session.pop("ar_entrada", None)
    request.session.pop("ar_entrada_ate", None)
    _fechar_entrada(db, usuario)
    registrar_log(db, usuario, "saiu_da_ar", "tenant", None, nome, request)
    db.commit()
    avisar(request, "Você saiu da AR: voltou a ver a plataforma toda.")
    return voltar("/master")


@rotas.post("/master/ar/nova", dependencies=[Depends(verificar_csrf)])
def nova_ar(request: Request, nome: str = Form(""), slug: str = Form(""), cnpj: str = Form(""),
            usuario: Usuario = Depends(PORTEIRO), db: Session = Depends(obter_db)):
    _so_master(usuario)
    nome = re.sub(r"\s+", " ", nome).strip()[:120]
    apelido = apelido_da_ar(slug) or apelido_da_ar(nome)  # sem apelido: sai do nome
    if not nome:
        avisar(request, "Escreva o nome da AR.", "erro")
        return voltar("/master")
    if len(apelido) < 2:
        avisar(request, "O apelido da AR precisa ter pelo menos 2 letras ou números (ex.: certifica-recife).", "erro")
        return voltar("/master")
    if db.execute(select(Tenant.id).where(Tenant.slug == apelido)).first():
        avisar(request, f"Já existe uma AR com o apelido \"{apelido}\". Escreva outro apelido.", "erro")
        return voltar("/master")
    ar = Tenant(nome=nome, slug=apelido, cnpj=cnpj.strip()[:20])
    db.add(ar)
    db.flush()
    registrar_log(db, usuario, "criou_ar", "tenant", ar.id, f"{nome} ({apelido})", request)
    db.commit()
    avisar(request, f"AR {nome} criada (apelido {apelido}). Para colocar a marca dela: clique em Entrar na AR e vá em "
                    "Configurações > Marca (nome, logo e cores) e em Configurações > Usuários (o administrador dela).")
    return voltar("/master")


@rotas.post("/master/ar/{tid:int}/situacao", dependencies=[Depends(verificar_csrf)])
def situacao(request: Request, tid: int, acao: str = Form(""), usuario: Usuario = Depends(PORTEIRO),
             db: Session = Depends(obter_db)):
    _so_master(usuario)
    ar = db.get(Tenant, tid)
    if ar is None or acao not in ("suspender", "reativar"):
        raise HTTPException(404)
    ar.situacao = "suspensa" if acao == "suspender" else "ativa"
    registrar_log(db, usuario, f"{acao}_ar", "tenant", ar.id, ar.nome, request)
    db.commit()
    avisar(request, f"AR {ar.nome}: " + ("suspensa (as pessoas dela não entram até reativar)." if acao == "suspender"
                                          else "reativada."))
    return voltar("/master")


@rotas.post("/master/ar/{tid:int}/modulos", dependencies=[Depends(verificar_csrf)])
async def modulos_da_ar(request: Request, tid: int, usuario: Usuario = Depends(PORTEIRO),
                        db: Session = Depends(obter_db)):
    _so_master(usuario)
    ar = db.get(Tenant, tid)
    if ar is None:
        raise HTTPException(404)
    form = await request.form()
    anterior = db.info.pop("ar_config", None)
    usar_config_da_ar(db, ar.id)
    ligados = []
    antes = {nome: "ligado" if ler_config(db, chave) == "1" else "desligado"
             for nome, chave in autorizacao.MODULOS.values()}
    for codigo, (nome, chave) in autorizacao.MODULOS.items():
        ligado = form.get(f"m__{codigo}") == "on"
        gravar_config(db, chave, "1" if ligado else "0")
        if ligado:
            ligados.append(nome)
    usar_config_da_ar(db, anterior)
    depois = {nome: "ligado" if nome in ligados else "desligado" for nome, _ in autorizacao.MODULOS.values()}
    registrar_log(db, usuario, "salvou_modulos_da_ar", "tenant", ar.id, ", ".join(ligados)[:200], request,
                  modulo="Módulos", mudancas=diferencas(antes, depois))
    db.commit()
    avisar(request, f"Módulos da {ar.nome} salvos.")
    return voltar("/master")
