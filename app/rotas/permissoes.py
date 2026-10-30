"""Tela Permissões (administrador): papéis, permissões de cada papel, exceções por usuário, equipes e módulos.
As regras ficam em app/autorizacao.py; aqui só se guardam as escolhas (sempre com registro de atividade)."""

import re
from itertools import groupby

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import autorizacao, util
from ..autorizacao import CATALOGO, ESCOPOS, MODULOS, POR_CODIGO
from ..banco import gravar_config, obter_db
from ..modelos import Equipe, ExcecaoPermissao, Papel, PermissaoPapel, Usuario
from ..seguranca import exige, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()
GERENCIAR = exige("permissoes.gerenciar")
DESTINO = "/permissoes"
# Papéis que podem servir de modelo para um papel novo (admin tem tudo; parceiro é só o portal)
BASES_COPIAVEIS = ("gestor", "funcionario", "vendedor")


def _papeis(db: Session) -> list[Papel]:
    ordem = {c: i for i, c in enumerate(autorizacao.PERFIS_BASE)}
    return sorted(db.execute(select(Papel)).scalars(), key=lambda p: (ordem.get(p.codigo, 9), p.nome))


def _grupos(permissoes) -> list[tuple[str, list]]:
    return [(g, list(itens)) for g, itens in groupby(permissoes, key=lambda p: p.grupo)]


@rotas.get("/permissoes")
def tela_permissoes(request: Request, aba: str = "papeis", papel: str = "", pessoa: int | None = None,
                    usuario: Usuario = Depends(GERENCIAR), db: Session = Depends(obter_db)):
    papeis = _papeis(db)
    escolhido = next((p for p in papeis if p.codigo == papel), papeis[0] if papeis else None)
    do_papel = {}
    if escolhido is not None:
        do_papel = {r.permissao: r.escopo for r in db.execute(
            select(PermissaoPapel).where(PermissaoPapel.papel_id == escolhido.id)).scalars()}
    usuarios = list(db.execute(select(Usuario).order_by(Usuario.ativo.desc(), Usuario.nome)).scalars())
    alvo = db.get(Usuario, pessoa) if pessoa else None
    contagem = dict(db.execute(select(Usuario.papel_id, func.count()).group_by(Usuario.papel_id)).all())
    por_perfil = dict(db.execute(select(Usuario.perfil, func.count()).where(Usuario.papel_id.is_(None))
                                 .group_by(Usuario.perfil)).all())
    return tela(request, "permissoes.html", {
        "aba": aba, "papeis": papeis, "papel": escolhido, "do_papel": do_papel,
        "grupos": _grupos([p for p in CATALOGO if escolhido is None
                           or autorizacao.permitidas_no_perfil(escolhido.base, p)]),
        "todas": CATALOGO, "todas_por_codigo": POR_CODIGO, "escopos": ESCOPOS, "modulos_info": MODULOS,
        "modulos": autorizacao.modulos_ligados(db),
        "usuarios": usuarios, "alvo": alvo,
        "papel_do_alvo": autorizacao.papel_de(db, alvo) if alvo else None,
        "acesso": _grupos_explicados(db, alvo) if alvo else [],
        "excecoes": list(db.execute(select(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == alvo.id)
                                    .order_by(ExcecaoPermissao.id)).scalars()) if alvo else [],
        "nomes": {u.id: u.nome for u in usuarios},
        "equipes": list(db.execute(select(Equipe).order_by(Equipe.nome)).scalars()),
        "membros": dict(db.execute(select(Usuario.equipe_id, func.count()).group_by(Usuario.equipe_id)).all()),
        "usuarios_no_papel": lambda p: contagem.get(p.id, 0) if not p.sistema else por_perfil.get(p.codigo, 0),
        "bases_copiaveis": [p for p in papeis if p.base in BASES_COPIAVEIS],
        "nao_negaveis": autorizacao.NAO_NEGAVEIS,
    })


def _grupos_explicados(db: Session, alvo: Usuario):
    linhas = autorizacao.explicar(db, alvo)
    return [(g, list(itens)) for g, itens in groupby(linhas, key=lambda l: l["p"].grupo)]


# ---------------------------------------------------------------- Papéis

@rotas.post("/permissoes/papel/{pid:int}", dependencies=[Depends(verificar_csrf)])
async def salvar_papel(request: Request, pid: int, usuario: Usuario = Depends(GERENCIAR), db: Session = Depends(obter_db)):
    papel = db.get(Papel, pid)
    if papel is None:
        raise HTTPException(404)
    destino = f"{DESTINO}?papel={papel.codigo}"
    if papel.codigo == "admin":
        avisar(request, "O papel Administrador tem sempre acesso a tudo (assim o sistema nunca fica sem quem cuide dele).",
               "alerta")
        return voltar(destino)
    form = await request.form()
    nome = str(form.get("nome", "")).strip()
    if nome and not papel.sistema:
        papel.nome = nome[:120]
    escolhas = []
    for p in CATALOGO:
        if not autorizacao.permitidas_no_perfil(papel.base, p):
            continue
        valor = str(form.get(f"p__{p.codigo}", ""))
        if not valor:
            continue
        if p.com_escopo and valor not in ESCOPOS:
            continue
        escolhas.append((p.codigo, valor if p.com_escopo else autorizacao.TUDO))
    antes = {r.permissao: r.escopo for r in db.execute(
        select(PermissaoPapel).where(PermissaoPapel.papel_id == papel.id)).scalars()}
    db.execute(delete(PermissaoPapel).where(PermissaoPapel.papel_id == papel.id))
    for codigo, escopo in escolhas:
        db.add(PermissaoPapel(papel_id=papel.id, permissao=codigo, escopo=escopo))
    depois = dict(escolhas)
    mudancas = [f"+{c}({e})" for c, e in depois.items() if antes.get(c) != e] + [f"-{c}" for c in antes if c not in depois]
    registrar_log(db, usuario, "alterou_papel", "papel", papel.id, f"{papel.nome}: " + (" ".join(mudancas) or "sem mudança"),
                  request)
    db.commit()
    avisar(request, f"Permissões do papel {papel.nome} salvas." if mudancas else "Nada mudou.")
    return voltar(destino)


@rotas.post("/permissoes/papel/novo", dependencies=[Depends(verificar_csrf)])
def novo_papel(request: Request, nome: str = Form(...), copiar_de: str = Form(...), usuario: Usuario = Depends(GERENCIAR),
               db: Session = Depends(obter_db)):
    modelo = db.execute(select(Papel).where(Papel.codigo == copiar_de)).scalars().first()
    nome = nome.strip()[:120]
    if not nome or modelo is None or modelo.base not in BASES_COPIAVEIS:
        avisar(request, "Informe o nome e escolha de qual papel copiar (Gestor, Funcionário MS, Vendedor ou um papel "
                        "criado a partir deles).", "erro")
        return voltar(DESTINO)
    base = re.sub(r"[^a-z0-9]+", "_", util.chave_texto(nome)).strip("_")
    codigo, n = f"p_{base or 'papel'}"[:36], 2
    while db.execute(select(Papel.id).where(Papel.codigo == codigo)).first():
        codigo, n = f"p_{base}"[:33] + f"_{n}", n + 1
    papel = Papel(codigo=codigo, nome=nome, base=modelo.base, sistema=False,
                  descricao=f"Criado a partir de {modelo.nome}", permissoes_conhecidas=modelo.permissoes_conhecidas)
    db.add(papel)
    db.flush()
    for r in db.execute(select(PermissaoPapel).where(PermissaoPapel.papel_id == modelo.id)).scalars():
        db.add(PermissaoPapel(papel_id=papel.id, permissao=r.permissao, escopo=r.escopo))
    registrar_log(db, usuario, "criou_papel", "papel", papel.id, f"{nome} (cópia de {modelo.nome})", request)
    db.commit()
    avisar(request, f"Papel {nome} criado com as mesmas permissões de {modelo.nome}. Ajuste abaixo e salve.")
    return voltar(f"{DESTINO}?papel={codigo}")


@rotas.post("/permissoes/papel/{pid:int}/excluir", dependencies=[Depends(verificar_csrf)])
def excluir_papel(request: Request, pid: int, usuario: Usuario = Depends(GERENCIAR), db: Session = Depends(obter_db)):
    papel = db.get(Papel, pid)
    if papel is None:
        raise HTTPException(404)
    if papel.sistema:
        avisar(request, "Os 5 papéis do sistema não podem ser excluídos.", "erro")
        return voltar(DESTINO)
    if db.execute(select(Usuario.id).where(Usuario.papel_id == papel.id)).first():
        avisar(request, "Ainda há usuários com este papel. Troque o papel deles em Configurações > Usuários antes.", "erro")
        return voltar(f"{DESTINO}?papel={papel.codigo}")
    db.execute(delete(PermissaoPapel).where(PermissaoPapel.papel_id == papel.id))
    registrar_log(db, usuario, "excluiu_papel", "papel", papel.id, papel.nome, request)
    db.delete(papel)
    db.commit()
    avisar(request, "Papel excluído.")
    return voltar(DESTINO)


# ---------------------------------------------------------------- Exceções por usuário

@rotas.post("/permissoes/excecao", dependencies=[Depends(verificar_csrf)])
def nova_excecao(request: Request, usuario_id: int = Form(...), permissao: str = Form(...), efeito: str = Form(...),
                 escopo: str = Form(""), ate: str = Form(""), motivo: str = Form(""),
                 usuario: Usuario = Depends(GERENCIAR), db: Session = Depends(obter_db)):
    alvo = db.get(Usuario, usuario_id)
    destino = f"{DESTINO}?aba=usuarios&pessoa={usuario_id}"
    p = POR_CODIGO.get(permissao)
    if alvo is None or p is None or efeito not in ("permitir", "negar"):
        avisar(request, "Escolha a pessoa, a permissão e se é PERMITIR ou NEGAR.", "erro")
        return voltar(destino)
    if not autorizacao.permitidas_no_perfil(alvo.perfil, p):
        avisar(request, "Essa permissão não vale para este tipo de usuário (o parceiro só usa o portal).", "erro")
        return voltar(destino)
    if efeito == "negar" and permissao in autorizacao.NAO_NEGAVEIS:
        avisar(request, "Essa permissão não pode ser negada por exceção (o sistema ficaria sem quem cuide das "
                        "permissões). Troque o papel da pessoa, se for o caso.", "erro")
        return voltar(destino)
    escopo = escopo if (p.com_escopo and efeito == "permitir" and escopo in ESCOPOS) else ""
    data_fim = util.para_data(ate) if ate else None
    db.execute(delete(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == alvo.id,
                                              ExcecaoPermissao.permissao == permissao))  # uma regra por permissão
    db.add(ExcecaoPermissao(usuario_id=alvo.id, permissao=permissao, efeito=efeito, escopo=escopo, ate=data_fim,
                            motivo=motivo.strip()[:300], criado_por_id=usuario.id))
    registrar_log(db, usuario, "excecao_permissao", "usuario", alvo.id,
                  f"{efeito.upper()} {permissao}" + (f" ({escopo})" if escopo else "")
                  + (f" até {data_fim:%d/%m/%Y}" if data_fim else "") + (f" – {motivo.strip()}" if motivo.strip() else ""),
                  request)
    db.commit()
    avisar(request, f"Exceção salva: {efeito.upper()} \"{p.nome}\" para {alvo.nome}.")
    return voltar(destino)


@rotas.post("/permissoes/excecao/{eid:int}/remover", dependencies=[Depends(verificar_csrf)])
def remover_excecao(request: Request, eid: int, usuario: Usuario = Depends(GERENCIAR), db: Session = Depends(obter_db)):
    e = db.get(ExcecaoPermissao, eid)
    if e is None:
        raise HTTPException(404)
    registrar_log(db, usuario, "removeu_excecao", "usuario", e.usuario_id, f"{e.efeito.upper()} {e.permissao}", request)
    destino = f"{DESTINO}?aba=usuarios&pessoa={e.usuario_id}"
    db.delete(e)
    db.commit()
    avisar(request, "Exceção removida: vale de novo o que o papel da pessoa permite.")
    return voltar(destino)


# ---------------------------------------------------------------- Equipes

@rotas.post("/permissoes/equipes/{eid:int}", dependencies=[Depends(verificar_csrf)])
def salvar_equipe(request: Request, eid: int, nome: str = Form(""), excluir: str = Form(""),
                  usuario: Usuario = Depends(GERENCIAR), db: Session = Depends(obter_db)):
    destino = f"{DESTINO}?aba=equipes"
    equipe = Equipe() if eid == 0 else db.get(Equipe, eid)
    if equipe is None:
        raise HTTPException(404)
    if excluir and eid:
        for u in db.execute(select(Usuario).where(Usuario.equipe_id == equipe.id)).scalars():
            u.equipe_id = None
        registrar_log(db, usuario, "excluiu_equipe", "equipe", equipe.id, equipe.nome, request)
        db.delete(equipe)
        db.commit()
        avisar(request, "Equipe excluída. As pessoas dela ficaram sem equipe.")
        return voltar(destino)
    nome = nome.strip()[:120]
    if not nome:
        avisar(request, "Informe o nome da equipe.", "erro")
        return voltar(destino)
    if db.execute(select(Equipe.id).where(Equipe.nome == nome, Equipe.id != (equipe.id or 0))).first():
        avisar(request, "Já existe uma equipe com esse nome.", "erro")
        return voltar(destino)
    equipe.nome = nome
    if eid == 0:
        db.add(equipe)
    db.flush()
    registrar_log(db, usuario, "salvou_equipe", "equipe", equipe.id, nome, request)
    db.commit()
    avisar(request, "Equipe salva. Escolha quem faz parte dela em Configurações > Usuários.")
    return voltar(destino)


# ---------------------------------------------------------------- Módulos

@rotas.post("/permissoes/modulos", dependencies=[Depends(verificar_csrf)])
async def salvar_modulos(request: Request, usuario: Usuario = Depends(GERENCIAR), db: Session = Depends(obter_db)):
    form = await request.form()
    ligados = []
    for codigo, (nome, chave) in MODULOS.items():
        ligado = form.get(f"m__{codigo}") == "on"
        gravar_config(db, chave, "1" if ligado else "0")
        if ligado:
            ligados.append(nome)
    registrar_log(db, usuario, "salvou_modulos", "configuracao", None, "ligados: " + (", ".join(ligados) or "nenhum"),
                  request)
    db.commit()
    avisar(request, "Módulos salvos. O que foi desligado some do menu e fica bloqueado para todos.")
    return voltar(f"{DESTINO}?aba=modulos")
