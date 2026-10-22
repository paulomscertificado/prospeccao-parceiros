"""Login, primeiro acesso, sair e troca de senha."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..banco import obter_db
from ..modelos import Usuario
from ..seguranca import (entrar, existe_usuario, ip_de, limite_login, marcar_login, problema_na_senha,
                         registrar_log, resumir_senha, senha_confere, usuario_logado, verificar_csrf)
from ..util import email_valido
from ..web import avisar, tela, voltar

rotas = APIRouter()


def _inicio(usuario: Usuario) -> str:
    return "/portal" if usuario.perfil == "parceiro" else "/"


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
    entrar(request, usuario)
    marcar_login(db, usuario)
    registrar_log(db, usuario, "login", "usuario", usuario.id, request=request)
    db.commit()
    return voltar(_inicio(usuario))


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
    return tela(request, "minha_conta.html")


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
