"""Login (senha + código do celular para admin/gestor), primeiro acesso, sair e troca de senha."""

import math
import re
import secrets
import time

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, dois_fatores
from ..banco import agora, ler_config, obter_db
from ..modelos import Usuario
from ..seguranca import (MINUTOS_DA_TRAVA, TENTATIVAS_ERRADAS, entrar, existe_usuario, ip_de, marcar_login,
                         problema_na_senha, registrar_log, registrar_tentativa_errada, resumir_senha, senha_confere,
                         trava_de_entrada, usuario_logado, verificar_csrf, zerar_tentativas)
from ..util import email_valido
from ..web import avisar, tela, voltar

rotas = APIRouter()


def _inicio(usuario: Usuario) -> str:
    return "/portal" if usuario.perfil == "parceiro" else "/"


MINUTOS_PARA_O_CODIGO = 10


def _aguardar_codigo(request: Request, usuario: Usuario) -> None:
    """Senha certa, falta o código: a sessão guarda só quem está entrando (sem acesso ao sistema)."""
    request.session.clear()
    request.session.update({"pendente_2fa": usuario.id, "pendente_versao": usuario.versao_sessao,
                            "pendente_desde": int(time.time()), "csrf": secrets.token_urlsafe(32)})


def _pendente(request: Request, db: Session) -> Usuario | None:
    uid = request.session.get("pendente_2fa")
    if not uid or time.time() - request.session.get("pendente_desde", 0) > MINUTOS_PARA_O_CODIGO * 60:
        return None
    usuario = db.get(Usuario, uid)
    if not usuario or not usuario.ativo or usuario.versao_sessao != request.session.get("pendente_versao"):
        return None
    return usuario


def _concluir_login(request: Request, db: Session, usuario: Usuario, destino: str = ""):
    entrar(request, usuario)
    marcar_login(db, usuario)
    registrar_log(db, usuario, "login", "usuario", usuario.id, request=request)
    db.commit()
    return voltar(destino or _inicio(usuario))


# ---------------------------------------------------------------- trava da entrada (seguranca.trava_de_entrada)
# Pedido da Maria em 26/11/2026: a Thamires errou a senha, a entrada travou e nem ela nem a Maria sabiam da trava. A
# tela agora avisa quantas tentativas restam e, travada, até que horas, o que fazer e o contato do suporte.
TRAVA_DA_SENHA = f"foram {TENTATIVAS_ERRADAS} tentativas com e-mail ou senha errados"
TRAVA_DO_CODIGO = f"foram {TENTATIVAS_ERRADAS} códigos errados"
DEPOIS_DO_CODIGO = ", entrando de novo com e-mail e senha,"


def contato_do_suporte(db: Session) -> str:
    """O contato do suporte da plataforma (Configurações > Marca, do Admin Master fora das ARs); "" = sem contato."""
    return re.sub(r"\s+", " ", ler_config(db, "plataforma_suporte") or "").strip()


def _fale_com_o_suporte(db: Session) -> str:
    contato = contato_do_suporte(db)
    return f"fale com o suporte da plataforma: {contato}" if contato else "fale com o suporte da plataforma"


def ainda_restam(restam: int) -> str:
    """O aviso depois de um erro, antes da trava."""
    if restam == 1:
        return (f"Atenção: resta só 1 tentativa. Se errar de novo, a entrada fica travada por {MINUTOS_DA_TRAVA} "
                "minutos, por segurança.")
    return (f"Você ainda tem {restam} tentativas. Depois de {TENTATIVAS_ERRADAS} erros seguidos, a entrada fica "
            f"travada por {MINUTOS_DA_TRAVA} minutos, por segurança.")


def mensagem_da_trava(db: Session, ate, motivo: str, depois: str = "") -> str:
    """A entrada travou: o motivo, a partir de que horas tentar de novo e com quem falar."""
    minutos = max(1, math.ceil((ate - agora()).total_seconds() / 60))
    return (f"Entrada travada por segurança: {motivo}. Tente de novo a partir das {ate:%H:%M} (daqui a {minutos} "
            f"{'minuto' if minutos == 1 else 'minutos'}){depois} ou {_fale_com_o_suporte(db)}.")


def _tela_de_entrada(request: Request, db: Session, contexto: dict | None = None, status_code: int = 200):
    return tela(request, "login.html", {"suporte": contato_do_suporte(db), "tentativas": TENTATIVAS_ERRADAS,
                                        "minutos_trava": MINUTOS_DA_TRAVA, **(contexto or {})}, status_code=status_code)


@rotas.get("/login")
def login_tela(request: Request, db: Session = Depends(obter_db)):
    if not existe_usuario(db):
        return voltar("/primeiro-acesso")
    return _tela_de_entrada(request, db)


@rotas.post("/login", dependencies=[Depends(verificar_csrf)])
def login(request: Request, email: str = Form(...), senha: str = Form(...), db: Session = Depends(obter_db)):
    chave = f"{ip_de(request)}|{email.strip().lower()}"
    _, travada_ate = trava_de_entrada(db, chave)
    if travada_ate:  # travada vale também para a senha certa: é a proteção contra quem tenta adivinhar
        return _tela_de_entrada(request, db, {"erro": mensagem_da_trava(db, travada_ate, TRAVA_DA_SENHA),
                                              "email": email}, status_code=429)
    usuario = db.execute(select(Usuario).where(Usuario.email == email.strip().lower())).scalars().first()
    if not usuario or not usuario.ativo or not senha_confere(senha, usuario.senha_hash):
        registrar_tentativa_errada(db, chave)
        registrar_log(db, None, "login_falhou", "usuario", None, f"e-mail: {email.strip().lower()}", request)
        db.commit()
        restam, travada_ate = trava_de_entrada(db, chave)
        if travada_ate:
            return _tela_de_entrada(request, db, {"erro": mensagem_da_trava(db, travada_ate, TRAVA_DA_SENHA),
                                                  "email": email}, status_code=429)
        return _tela_de_entrada(request, db, {"erro": "E-mail ou senha incorretos. " + ainda_restam(restam),
                                              "email": email}, status_code=401)
    zerar_tentativas(db, chave)
    if dois_fatores.precisa(usuario) and not (usuario.totp_ativo and dois_fatores.aparelho_confiavel(request, usuario)):
        db.commit()
        _aguardar_codigo(request, usuario)
        return voltar("/login/codigo" if usuario.totp_ativo else "/login/ativar-codigo")
    return _concluir_login(request, db, usuario)


def _sem_pendente(request: Request):
    avisar(request, "O tempo para digitar o código acabou. Entre de novo com e-mail e senha.", "alerta")
    return voltar("/login")


@rotas.get("/login/ativar-codigo")
def ativar_codigo_tela(request: Request, db: Session = Depends(obter_db)):
    usuario = _pendente(request, db)
    if usuario is None:
        return _sem_pendente(request)
    if usuario.totp_ativo:
        return voltar("/login/codigo")
    segredo = request.session.get("segredo_novo") or dois_fatores.novo_segredo()
    request.session["segredo_novo"] = segredo  # só a própria pessoa vê (é o que ela digita no app)
    emissor = dois_fatores.emissor(db)
    return tela(request, "dois_fatores_ativar.html", {
        "qr": dois_fatores.qr_svg(dois_fatores.link_do_app(segredo, usuario.email, emissor)),
        "chave": dois_fatores.segredo_em_grupos(segredo), "pessoa": usuario, "emissor": emissor})


@rotas.post("/login/ativar-codigo", dependencies=[Depends(verificar_csrf)])
def ativar_codigo(request: Request, codigo: str = Form(""), db: Session = Depends(obter_db)):
    usuario = _pendente(request, db)
    segredo = request.session.get("segredo_novo", "")
    if usuario is None or not segredo:
        return _sem_pendente(request)
    chave = f"2fa|{usuario.id}"
    _, travada_ate = trava_de_entrada(db, chave)
    if travada_ate:
        avisar(request, mensagem_da_trava(db, travada_ate, TRAVA_DO_CODIGO, DEPOIS_DO_CODIGO), "erro")
        return voltar("/login/ativar-codigo")
    passo = dois_fatores.conferir(segredo, codigo)
    if passo is None:
        registrar_tentativa_errada(db, chave)
        db.commit()
        restam, travada_ate = trava_de_entrada(db, chave)
        avisar(request, mensagem_da_trava(db, travada_ate, TRAVA_DO_CODIGO, DEPOIS_DO_CODIGO) if travada_ate else
               "Código errado. Confira se leu o QR code desta tela e digite os 6 números que o app mostra agora (eles "
               "mudam a cada 30 segundos). " + ainda_restam(restam), "erro")
        return voltar("/login/ativar-codigo")
    zerar_tentativas(db, chave)
    codigos = dois_fatores.ativar(usuario, segredo, passo)
    registrar_log(db, usuario, "ativou_2fa", "usuario", usuario.id, request=request)
    entrar(request, usuario)
    marcar_login(db, usuario)
    db.commit()
    return tela(request, "dois_fatores_codigos.html", {"codigos": codigos, "destino": _inicio(usuario)})


@rotas.get("/login/codigo")
def codigo_tela(request: Request, db: Session = Depends(obter_db)):
    usuario = _pendente(request, db)
    if usuario is None:
        return _sem_pendente(request)
    if not usuario.totp_ativo:
        return voltar("/login/ativar-codigo")
    return tela(request, "dois_fatores_codigo.html", {"pessoa": usuario})


@rotas.post("/login/codigo", dependencies=[Depends(verificar_csrf)])
def codigo_login(request: Request, codigo: str = Form(""), lembrar: str = Form(""), db: Session = Depends(obter_db)):
    usuario = _pendente(request, db)
    if usuario is None or not usuario.totp_ativo:
        return _sem_pendente(request)
    chave = f"2fa|{usuario.id}"
    _, travada_ate = trava_de_entrada(db, chave)
    if travada_ate:
        return tela(request, "dois_fatores_codigo.html", {"pessoa": usuario, "erro": mensagem_da_trava(
            db, travada_ate, TRAVA_DO_CODIGO, DEPOIS_DO_CODIGO)}, status_code=429)
    recuperacao = False
    passo = dois_fatores.conferir(dois_fatores.segredo_de(usuario), codigo, usuario.totp_ultimo_passo)
    if passo is not None:
        usuario.totp_ultimo_passo = passo
    elif dois_fatores.usar_codigo_de_recuperacao(usuario, codigo):
        recuperacao = True
    else:
        registrar_tentativa_errada(db, chave)
        registrar_log(db, usuario, "codigo_2fa_errado", "usuario", usuario.id, request=request)
        db.commit()
        restam, travada_ate = trava_de_entrada(db, chave)
        if travada_ate:
            return tela(request, "dois_fatores_codigo.html", {"pessoa": usuario, "erro": mensagem_da_trava(
                db, travada_ate, TRAVA_DO_CODIGO, DEPOIS_DO_CODIGO)}, status_code=429)
        return tela(request, "dois_fatores_codigo.html", {"pessoa": usuario, "erro": "Código errado ou já usado. "
                    "Digite os 6 números que o app mostra agora. " + ainda_restam(restam)}, status_code=401)
    zerar_tentativas(db, chave)
    if recuperacao:
        registrar_log(db, usuario, "usou_codigo_recuperacao", "usuario", usuario.id,
                      f"restam {dois_fatores.codigos_restantes(usuario)}", request)
    resposta = _concluir_login(request, db, usuario)
    if recuperacao:
        avisar(request, f"Você entrou com um código de recuperação (restam {dois_fatores.codigos_restantes(usuario)}). "
                        "Se perdeu o celular, peça ao administrador para zerar a verificação em 2 etapas e configure de "
                        "novo.", "alerta")
    if lembrar == "on":
        resposta.set_cookie(dois_fatores.COOKIE_APARELHO, dois_fatores.marca_do_aparelho(usuario),
                            max_age=dois_fatores.DIAS_APARELHO * 24 * 3600, httponly=True, samesite="lax",
                            secure=config.PRODUCAO)
    return resposta


@rotas.get("/primeiro-acesso")
def primeiro_acesso_tela(request: Request, db: Session = Depends(obter_db)):
    if existe_usuario(db):
        return voltar("/login")
    return tela(request, "primeiro_acesso.html")


@rotas.post("/primeiro-acesso", dependencies=[Depends(verificar_csrf)])
def primeiro_acesso(request: Request, nome: str = Form(...), email: str = Form(...), senha: str = Form(...),
                    senha2: str = Form(...), db: Session = Depends(obter_db)):
    if existe_usuario(db):
        return voltar("/login")
    erro = ""
    if not nome.strip() or not email_valido(email):
        erro = "Preencha seu nome e um e-mail válido."
    elif senha != senha2:
        erro = "As duas senhas não são iguais."
    else:
        erro = problema_na_senha(senha)
    if erro:
        return tela(request, "primeiro_acesso.html", {"erro": erro, "nome": nome, "email": email})
    usuario = Usuario(nome=nome.strip(), email=email.strip().lower(), senha_hash=resumir_senha(senha), perfil="admin",
                      master=True)  # quem cria o sistema é o admin master (dono da plataforma)
    db.add(usuario)
    db.flush()
    registrar_log(db, usuario, "primeiro_acesso", "usuario", usuario.id, request=request)
    db.commit()
    if dois_fatores.precisa(usuario):
        _aguardar_codigo(request, usuario)
        avisar(request, "Conta de administrador criada. Falta só ligar a verificação em 2 etapas.")
        return voltar("/login/ativar-codigo")
    entrar(request, usuario)
    avisar(request, "Conta de administrador criada. Bem-vinda!")
    return voltar("/")


@rotas.get("/descadastrar/{lead_id:int}/{assinatura}")
@rotas.post("/descadastrar/{lead_id:int}/{assinatura}")
def descadastrar(request: Request, lead_id: int, assinatura: str, db: Session = Depends(obter_db)):
    """Link do rodapé dos e-mails (e "List-Unsubscribe" de 1 clique): registra o opt-out."""
    import hmac as _hmac

    from ..integracoes import email_smtp
    from ..leads_servico import registrar_opt_out
    from ..modelos import Lead

    lead = db.get(Lead, lead_id)
    if not lead or not _hmac.compare_digest(email_smtp.assinatura_descadastro(lead_id), assinatura):
        return tela(request, "erro.html", {"titulo": "Link inválido", "mensagem": "Este link de descadastro não é válido."},
                    status_code=404)
    from .. import marca

    da_ar = marca.da_ar(db, lead.tenant_id or marca.ar_padrao(db))  # a empresa que mandou o e-mail (a AR do lead)
    if request.method == "GET":  # abrir o link só pergunta (antivírus "abrem" links sozinhos)
        return tela(request, "descadastro.html", {"caminho_form": request.url.path, "marca": da_ar})
    registrar_opt_out(db, lead, None, "pediu descadastro pelo e-mail")
    db.commit()
    return tela(request, "erro.html", {"titulo": "Pronto!", "marca": da_ar,
                                       "mensagem": "Seu contato foi removido. Você não receberá mais mensagens "
                                       f"{marca.frase(da_ar, 'de', nome=True)}."})


@rotas.get("/sair")
def sair(request: Request):
    request.session.clear()
    return voltar("/login")


@rotas.get("/minha-conta")
def minha_conta(request: Request, usuario: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    from .. import marca

    from datetime import date

    from .. import feriados

    hoje = date.today()
    proximos = sorted((d, n) for d, n in feriados.da_pessoa(db, usuario).items() if d >= hoje and d.weekday() < 5)[:6]
    return tela(request, "minha_conta.html", {"restam_codigos": dois_fatores.codigos_restantes(usuario),
                                              "ufs": feriados.UFS, "proximos_feriados": proximos,
                                              "exige_2fa": dois_fatores.precisa(usuario),
                                              # sem "empresa que eu represento", as mensagens saem pela marca da AR
                                              "marca_padrao": marca.da_ar(db, usuario.tenant_id or marca.ar_padrao(db)),
                                              "quem_fala": marca.da_pessoa(usuario, db=db)})


@rotas.post("/minha-conta/empresa", dependencies=[Depends(verificar_csrf)])
async def salvar_empresa(request: Request, usuario: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    """Empresa que o usuário representa nas mensagens (app/marca.py)."""
    form = await request.form()
    usuario = db.get(Usuario, usuario.id)
    limites = {"nome": 160, "site": 160, "descricao": 80}
    for campo, tamanho in limites.items():
        valor = str(form.get(campo, "")).strip()
        if campo == "site":
            valor = valor.removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
        if campo == "descricao":
            valor = valor.rstrip(".;,: ")
        setattr(usuario, f"empresa_{campo}", valor[:tamanho])
    registrar_log(db, usuario, "configurou_empresa_representada", "usuario", usuario.id, request=request)
    db.commit()
    from .. import marca

    avisar(request, f"Pronto: suas próximas campanhas e mensagens falam em nome de {marca.da_pessoa(usuario)['nome']}.")
    return voltar("/minha-conta#empresa")


@rotas.post("/minha-conta/cidade", dependencies=[Depends(verificar_csrf)])
def salvar_cidade(request: Request, cidade: str = Form(""), uf: str = Form(""),
                  usuario: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    """Onde a pessoa trabalha: nos feriados do estado e da cidade dela (e nos nacionais) as campanhas dela não enviam
    e a agenda não oferece reunião (app/feriados.py, pedido da Maria em 18/11/2026)."""
    from .. import feriados
    from .admin import _remarcar_feriados

    usuario = db.get(Usuario, usuario.id)
    antes = (usuario.cidade or "", usuario.uf or "")
    if feriados.normalizar_cidade(cidade) and not feriados.normalizar_uf(uf):
        avisar(request, "Escolha também a UF da sua cidade.", "erro")
        return voltar("/minha-conta#cidade")
    usuario.uf = feriados.normalizar_uf(uf)
    usuario.cidade, aviso_cidade = feriados.conferir_cidade(usuario.uf, cidade)  # o nome como o IBGE escreve
    movidos = 0
    if (usuario.cidade, usuario.uf) != antes:
        registrar_log(db, usuario, "mudou_cidade", "usuario", usuario.id,
                      f"{usuario.cidade or '—'} ({usuario.uf or '—'})", request)
        movidos = _remarcar_feriados(db, {usuario.id})
    db.commit()
    avisar(request, "Cidade salva." + (f" {movidos} toque(s) seus que caíam num feriado mudaram de dia." if movidos else ""))
    if aviso_cidade:
        avisar(request, aviso_cidade, "alerta")
    return voltar("/minha-conta#cidade")


@rotas.post("/minha-conta/senha", dependencies=[Depends(verificar_csrf)])
def trocar_senha(request: Request, atual: str = Form(...), nova: str = Form(...), nova2: str = Form(...),
                 usuario: Usuario = Depends(usuario_logado), db: Session = Depends(obter_db)):
    usuario = db.get(Usuario, usuario.id)
    if not senha_confere(atual, usuario.senha_hash):
        avisar(request, "A senha atual está errada.", "erro")
    elif nova != nova2:
        avisar(request, "As duas senhas novas não são iguais.", "erro")
    elif problema := problema_na_senha(nova):
        avisar(request, problema, "erro")
    else:
        usuario.senha_hash = resumir_senha(nova)
        usuario.versao_sessao += 1
        registrar_log(db, usuario, "trocou_senha", "usuario", usuario.id, request=request)
        db.commit()
        entrar(request, usuario)
        avisar(request, "Senha trocada. As outras sessões abertas foram encerradas.")
    return voltar("/minha-conta")
