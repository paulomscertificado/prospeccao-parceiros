"""Login (senha + código do celular para admin/gestor), primeiro acesso, sair e troca de senha."""

import secrets
import time

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, dois_fatores
from ..banco import obter_db
from ..modelos import Usuario
from ..seguranca import (entrar, existe_usuario, ip_de, limite_login, marcar_login, problema_na_senha,
                         registrar_log, resumir_senha, senha_confere, usuario_logado, verificar_csrf)
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


@rotas.get("/login")
def login_tela(request: Request, db: Session = Depends(obter_db)):
    if not existe_usuario(db):
        return voltar("/primeiro-acesso")
    return tela(request, "login.html")


@rotas.post("/login", dependencies=[Depends(verificar_csrf)])
def login(request: Request, email: str = Form(...), senha: str = Form(...), db: Session = Depends(obter_db)):
    chave = f"{ip_de(request)}|{email.strip().lower()}"
    if limite_login.bloqueado(chave):
        return tela(request, "login.html", {"erro": "Muitas tentativas erradas. Espere 15 minutos e tente de novo.",
                                            "email": email}, status_code=429)
    usuario = db.execute(select(Usuario).where(Usuario.email == email.strip().lower())).scalars().first()
    if not usuario or not usuario.ativo or not senha_confere(senha, usuario.senha_hash):
        limite_login.registrar(chave)
        registrar_log(db, None, "login_falhou", "usuario", None, f"e-mail: {email.strip().lower()}", request)
        db.commit()
        return tela(request, "login.html", {"erro": "E-mail ou senha incorretos.", "email": email}, status_code=401)
    limite_login.zerar(chave)
    if dois_fatores.precisa(usuario) and not (usuario.totp_ativo and dois_fatores.aparelho_confiavel(request, usuario)):
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
    return tela(request, "dois_fatores_ativar.html", {
        "qr": dois_fatores.qr_svg(dois_fatores.link_do_app(segredo, usuario.email)),
        "chave": dois_fatores.segredo_em_grupos(segredo), "pessoa": usuario})


@rotas.post("/login/ativar-codigo", dependencies=[Depends(verificar_csrf)])
def ativar_codigo(request: Request, codigo: str = Form(""), db: Session = Depends(obter_db)):
    usuario = _pendente(request, db)
    segredo = request.session.get("segredo_novo", "")
    if usuario is None or not segredo:
        return _sem_pendente(request)
    chave = f"2fa|{usuario.id}"
    if limite_login.bloqueado(chave):
        avisar(request, "Muitas tentativas erradas. Espere 15 minutos e tente de novo.", "erro")
        return voltar("/login/ativar-codigo")
    passo = dois_fatores.conferir(segredo, codigo)
    if passo is None:
        limite_login.registrar(chave)
        avisar(request, "Código errado. Confira se leu o QR code desta tela e digite os 6 números que o app mostra "
                        "agora (eles mudam a cada 30 segundos).", "erro")
        return voltar("/login/ativar-codigo")
    limite_login.zerar(chave)
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
    if limite_login.bloqueado(chave):
        return tela(request, "dois_fatores_codigo.html", {"pessoa": usuario, "erro": "Muitas tentativas erradas. "
                    "Espere 15 minutos e tente de novo."}, status_code=429)
    recuperacao = False
    passo = dois_fatores.conferir(dois_fatores.segredo_de(usuario), codigo, usuario.totp_ultimo_passo)
    if passo is not None:
        usuario.totp_ultimo_passo = passo
    elif dois_fatores.usar_codigo_de_recuperacao(usuario, codigo):
        recuperacao = True
    else:
        limite_login.registrar(chave)
        registrar_log(db, usuario, "codigo_2fa_errado", "usuario", usuario.id, request=request)
        db.commit()
        return tela(request, "dois_fatores_codigo.html", {"pessoa": usuario, "erro": "Código errado ou já usado. "
                    "Digite os 6 números que o app mostra agora."}, status_code=401)
    limite_login.zerar(chave)
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
    usuario = Usuario(nome=nome.strip(), email=email.strip().lower(), senha_hash=resumir_senha(senha), perfil="admin")
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
    if request.method == "GET":  # abrir o link só pergunta (antivírus "abrem" links sozinhos)
        return tela(request, "descadastro.html", {"caminho_form": request.url.path})
    registrar_opt_out(db, lead, None, "pediu descadastro pelo e-mail")
    db.commit()
    return tela(request, "erro.html", {"titulo": "Pronto!", "mensagem": "Seu contato foi removido. Você não receberá "
                                       "mais mensagens da MS Certificação Digital."})


@rotas.get("/sair")
def sair(request: Request):
    request.session.clear()
    return voltar("/login")


@rotas.get("/minha-conta")
def minha_conta(request: Request, usuario: Usuario = Depends(usuario_logado)):
    return tela(request, "minha_conta.html", {"restam_codigos": dois_fatores.codigos_restantes(usuario),
                                              "exige_2fa": dois_fatores.precisa(usuario)})


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
