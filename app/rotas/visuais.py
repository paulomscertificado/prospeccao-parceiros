"""Campanhas > Visuais: cadastro do HTML do e-mail e da imagem do WhatsApp usados nas campanhas (app/visual.py)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import visual as vis
from ..banco import obter_db
from ..modelos import ArquivoVisual, Campanha, Usuario, VisualCampanha
from ..seguranca import exige, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()


def _visual(db: Session, vid: int) -> VisualCampanha:
    v = db.get(VisualCampanha, vid)
    if v is None:
        raise HTTPException(404)
    return v


def _campanhas_que_usam(db: Session, vid: int) -> int:
    return db.execute(select(func.count(Campanha.id)).where(Campanha.visual_id == vid)).scalar() or 0


async def _ler_arquivo(campo) -> tuple[bytes, str]:
    if campo is None or not getattr(campo, "filename", ""):
        return b"", ""
    return await campo.read(vis.LIMITE_IMAGEM + 1), campo.filename


def _dados_do_form(form) -> dict:
    return {"nome": str(form.get("nome") or "").strip()[:120],
            "descricao": str(form.get("descricao") or "").strip()[:1000],
            "usar_em": ",".join(s for s in vis.SECOES if form.get(f"usar_{s}")),
            "html": str(form.get("html") or "")}


@rotas.get("/visuais")
def lista(request: Request, usuario: Usuario = Depends(exige("templates.ver")), db: Session = Depends(obter_db)):
    visuais = db.execute(select(VisualCampanha).order_by(VisualCampanha.ativo.desc(), VisualCampanha.nome)).scalars().all()
    uso = dict(db.execute(select(Campanha.visual_id, func.count(Campanha.id)).where(Campanha.visual_id.is_not(None))
                          .group_by(Campanha.visual_id)).all())
    return tela(request, "visuais.html", {"visuais": visuais, "uso": uso, "SECOES": vis.SECOES})


@rotas.post("/visuais/novo", dependencies=[Depends(verificar_csrf)])
async def criar(request: Request, usuario: Usuario = Depends(exige("templates.editar")), db: Session = Depends(obter_db)):
    form = await request.form()
    dados = _dados_do_form(form)
    if not dados["nome"]:
        avisar(request, "Dê um nome para o visual (ex.: Folheto da parceria).", "erro")
        return voltar("/visuais")
    if len(dados["html"]) > vis.LIMITE_HTML:
        avisar(request, "O HTML passou de 200 mil caracteres: e-mail grande demais é cortado pelo Gmail.", "erro")
        return voltar("/visuais")
    v = VisualCampanha(nome=dados["nome"], descricao=dados["descricao"], usar_em=dados["usar_em"] or "sdr,empresas_novas",
                       html=vis.limpar_html(dados["html"]), usuario_id=usuario.id)
    conteudo, nome_arquivo = await _ler_arquivo(form.get("imagem"))
    if conteudo:
        problema = vis.problema_na_imagem(conteudo)
        if problema:
            avisar(request, f"Imagem do WhatsApp: {problema}", "erro")
            return voltar("/visuais")
        vis.guardar_imagem(v, conteudo, nome_arquivo)
    db.add(v)
    db.flush()
    registrar_log(db, usuario, "criou_visual", "visual", v.id, v.nome, request)
    db.commit()
    avisar(request, f"Visual \"{v.nome}\" criado. Agora ele aparece para escolher nas campanhas.")
    return voltar(f"/visuais/{v.id}")


@rotas.get("/visuais/{vid:int}")
def ver(request: Request, vid: int, usuario: Usuario = Depends(exige("templates.ver")), db: Session = Depends(obter_db)):
    v = _visual(db, vid)
    return tela(request, "visual.html", {
        "v": v, "previa": vis.previa(v) if (v.html or "").strip() else "", "SECOES": vis.SECOES,
        "arquivos": [(a, vis.url_arquivo(a)) for a in v.arquivos], "campanhas": _campanhas_que_usam(db, vid),
        "LIMITE_KB": vis.LIMITE_IMAGEM // 1000,
    })


@rotas.post("/visuais/{vid:int}", dependencies=[Depends(verificar_csrf)])
async def salvar(request: Request, vid: int, usuario: Usuario = Depends(exige("templates.editar")),
                 db: Session = Depends(obter_db)):
    v = _visual(db, vid)
    form = await request.form()
    dados = _dados_do_form(form)
    if not dados["nome"]:
        avisar(request, "O visual precisa de um nome.", "erro")
        return voltar(f"/visuais/{vid}")
    if len(dados["html"]) > vis.LIMITE_HTML:
        avisar(request, "O HTML passou de 200 mil caracteres: e-mail grande demais é cortado pelo Gmail.", "erro")
        return voltar(f"/visuais/{vid}")
    v.nome, v.descricao, v.html = dados["nome"], dados["descricao"], vis.limpar_html(dados["html"])
    v.usar_em, v.ativo = dados["usar_em"], bool(form.get("ativo"))
    conteudo, nome_arquivo = await _ler_arquivo(form.get("imagem"))
    if conteudo:
        problema = vis.problema_na_imagem(conteudo)
        if problema:
            avisar(request, f"Imagem do WhatsApp: {problema}", "erro")
            return voltar(f"/visuais/{vid}")
        vis.guardar_imagem(v, conteudo, nome_arquivo)
    elif form.get("tirar_imagem"):
        v.imagem, v.imagem_tipo, v.imagem_nome, v.imagem_hash = None, "", "", ""
    registrar_log(db, usuario, "alterou_visual", "visual", v.id, v.nome, request)
    db.commit()
    avisar(request, "Visual salvo. Vale para os próximos envios das campanhas que usam ele.")
    return voltar(f"/visuais/{vid}")


@rotas.get("/visuais/{vid:int}/imagem")
def imagem(vid: int, usuario: Usuario = Depends(exige("templates.ver")), db: Session = Depends(obter_db)):
    v = _visual(db, vid)
    if not v.imagem:
        raise HTTPException(404)
    return Response(v.imagem, media_type=v.imagem_tipo or "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=60"})


@rotas.post("/visuais/{vid:int}/arquivos", dependencies=[Depends(verificar_csrf)])
async def enviar_arquivos(request: Request, vid: int, usuario: Usuario = Depends(exige("templates.editar")),
                          db: Session = Depends(obter_db)):
    v = _visual(db, vid)
    form = await request.form()
    guardados, problemas = 0, []
    for campo in form.getlist("arquivos"):
        conteudo, nome_arquivo = await _ler_arquivo(campo)
        if not conteudo:
            continue
        problema = vis.problema_na_imagem(conteudo)
        if problema:
            problemas.append(f"{nome_arquivo}: {problema}")
            continue
        db.add(ArquivoVisual(visual_id=v.id, nome=vis.nome_seguro(nome_arquivo), tipo=vis.tipo_da_imagem(conteudo),
                             tamanho=len(conteudo), dados=conteudo))
        guardados += 1
    db.commit()
    if guardados:
        avisar(request, f"{guardados} imagem(ns) guardada(s). Copie o endereço de cada uma e use no HTML (<img src=\"...\">).")
    if problemas:
        avisar(request, "Não guardei: " + "; ".join(problemas), "erro")
    return voltar(f"/visuais/{vid}#arquivos")


@rotas.post("/visuais/{vid:int}/arquivos/{aid:int}/apagar", dependencies=[Depends(verificar_csrf)])
def apagar_arquivo(request: Request, vid: int, aid: int, usuario: Usuario = Depends(exige("templates.editar")),
                   db: Session = Depends(obter_db)):
    a = db.get(ArquivoVisual, aid)
    if a is None or a.visual_id != vid:
        raise HTTPException(404)
    db.delete(a)
    db.commit()
    avisar(request, "Imagem apagada. Se o HTML ainda usava o endereço dela, a imagem some do e-mail.")
    return voltar(f"/visuais/{vid}#arquivos")


@rotas.post("/visuais/{vid:int}/apagar", dependencies=[Depends(verificar_csrf)])
def apagar(request: Request, vid: int, usuario: Usuario = Depends(exige("templates.editar")),
           db: Session = Depends(obter_db)):
    v = _visual(db, vid)
    if _campanhas_que_usam(db, vid):
        v.ativo = False  # campanha que usa continua achando o visual; só não aparece mais para escolher
        avisar(request, f"\"{v.nome}\" está em campanhas, então foi só desativado (não aparece mais para escolher).")
    else:
        db.delete(v)
        avisar(request, f"Visual \"{v.nome}\" apagado.")
    registrar_log(db, usuario, "apagou_visual", "visual", vid, v.nome, request)
    db.commit()
    return voltar("/visuais")


@rotas.post("/visuais/{vid:int}/teste-email", dependencies=[Depends(verificar_csrf)])
def teste_email(request: Request, vid: int, usuario: Usuario = Depends(exige("templates.ver")),
                db: Session = Depends(obter_db)):
    """Manda o visual com o texto de exemplo para o e-mail de quem pediu."""
    from .. import contas_email
    from ..integracoes import email_smtp

    v = _visual(db, vid)
    if not (v.html or "").strip():
        avisar(request, "Este visual ainda não tem HTML de e-mail.", "erro")
        return voltar(f"/visuais/{vid}")
    try:
        conta = contas_email.para_enviar(db, usuario)
        email_smtp.enviar(usuario.email, f"[TESTE] Visual \"{v.nome}\"", vis.TEXTO_EXEMPLO, com_rodape=False,
                          conta=conta, html=vis.previa(v))
    except (contas_email.SemConta, email_smtp.ErroEmail) as erro:
        avisar(request, f"O e-mail de teste não saiu: {erro}", "erro")
        return voltar(f"/visuais/{vid}")
    avisar(request, f"E-mail de teste enviado para {usuario.email}. Confira no computador e no celular.")
    return voltar(f"/visuais/{vid}")


@rotas.get("/visual/arquivo/{aid:int}/{nome}")
def arquivo_publico(aid: int, nome: str, db: Session = Depends(obter_db)):
    """Imagem usada dentro do HTML do e-mail: pública (o programa de e-mail do lead precisa abrir). Só imagens."""
    a = db.get(ArquivoVisual, aid)
    if a is None or a.nome != nome or not vis.tipo_da_imagem(a.dados[:16]):
        raise HTTPException(404)
    return Response(a.dados, media_type=a.tipo, headers={"Cache-Control": "public, max-age=86400",
                                                         "Content-Disposition": f'inline; filename="{a.nome}"'})
