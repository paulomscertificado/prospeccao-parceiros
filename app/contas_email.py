"""Contas de e-mail das campanhas: a principal da MS (Configurações > E-mail) e a de cada pessoa da equipe.

Funciona como os números de WhatsApp (app/conexoes.py):
- cada pessoa cadastra o PRÓPRIO e-mail @mscertificados.com.br (tela E-mail); quem tem email.outro_dominio
  (gestor e admin) pode usar o próprio domínio e servidor (Google, Microsoft 365 ou outro SMTP/IMAP);
- o dono, o administrador e o gestor compartilham uma conta com toda a equipe ou com pessoas escolhidas;
- o e-mail de um lead sai pela conta do responsável; sem conta própria, por uma compartilhada com ele; por último
  pela principal, se ela estiver liberada para ele (começa liberada para toda a equipe).
Os limites de envio (por hora, dia e domínio) continuam valendo para a MS inteira: todas as contas são do mesmo
domínio e dividem a mesma reputação.
"""

import json
from dataclasses import dataclass
from email.utils import formataddr, parseaddr

from sqlalchemy import select

from . import autorizacao, config
from .modelos import ContaEmail, Usuario

GOOGLE = {"smtp_host": "smtp.gmail.com", "smtp_porta": 587, "imap_host": "imap.gmail.com", "imap_porta": 993}


class SemConta(Exception):
    """Motivo pronto para a tela: a pessoa não tem conta de e-mail para enviar."""


@dataclass
class Credenciais:
    host: str
    porta: int
    tls: bool
    login: str
    senha: str
    remetente: str          # "Nome <endereco>"
    endereco: str
    responder_para: str
    imap_host: str
    imap_porta: int
    rotulo: str             # para mensagens de erro e registros ("principal" ou o e-mail da pessoa)


def credenciais(conta: ContaEmail | None) -> Credenciais:
    """Dados de acesso da conta. None ou a principal: os de Configurações > E-mail."""
    if conta is None or conta.principal:
        endereco = parseaddr(config.SMTP_REMETENTE or config.SMTP_USUARIO)[1].lower()
        return Credenciais(config.SMTP_HOST, config.SMTP_PORTA, config.SMTP_TLS, config.SMTP_USUARIO or endereco,
                           config.SMTP_SENHA, config.SMTP_REMETENTE or endereco, endereco, config.SMTP_RESPONDER_PARA,
                           config.IMAP_HOST if config.IMAP_USUARIO else "", config.IMAP_PORTA, "principal")
    from .seguranca import descriptografar

    senha = descriptografar(conta.senha_cripto or "")
    if senha.startswith("(não foi possível"):
        senha = ""
    return Credenciais(conta.smtp_host, conta.smtp_porta, conta.smtp_porta != 465, conta.login or conta.endereco, senha,
                       formataddr((conta.nome_remetente, conta.endereco)) if conta.nome_remetente else conta.endereco,
                       conta.endereco, "", conta.imap_host if conta.ler_respostas else "", conta.imap_porta,
                       conta.endereco)


def dominio_liberado(conta: ContaEmail | None) -> bool:
    """A conta pode enviar fora do domínio da MS: foi salva assim e o dono AINDA tem email.outro_dominio."""
    if conta is None or conta.principal or not conta.dominio_livre or not conta.dono_id:
        return False
    from sqlalchemy.orm import object_session

    db = object_session(conta)
    dono = db.get(Usuario, conta.dono_id) if db is not None else None
    return bool(dono and dono.ativo and autorizacao.pode(dono, "email.outro_dominio"))


def chave(conta: ContaEmail | None) -> str:
    """Como a conta aparece em Mensagem.conexao."""
    return "email:principal" if conta is None or conta.principal else f"email:{conta.id}"


# ---------------------------------------------------------------- Quem pode o quê

def compartilhada_com(c: ContaEmail) -> list[int]:
    try:
        return [int(i) for i in json.loads(c.compartilhada_com or "[]")]
    except (ValueError, TypeError):
        return []


def pode_gerenciar(usuario: Usuario, c: ContaEmail) -> bool:
    """Trocar senha, pausar, remover: o dono e o administrador (a principal: só o administrador)."""
    return (not c.principal and c.dono_id == usuario.id) or autorizacao.pode(usuario, "email.gerenciar_todas")


def pode_compartilhar(usuario: Usuario, c: ContaEmail) -> bool:
    """Escolher com quem a conta é compartilhada: o dono, o administrador e o gestor."""
    return pode_gerenciar(usuario, c) or autorizacao.pode(usuario, "email.compartilhar_todas")


def pode_usar(usuario: Usuario, c: ContaEmail) -> bool:
    return (not c.principal and c.dono_id == usuario.id) or c.compartilhada_todos or usuario.id in compartilhada_com(c)


# ---------------------------------------------------------------- Contas

def garantir_principal(db) -> ContaEmail:
    c = db.execute(select(ContaEmail).where(ContaEmail.principal.is_(True)).limit(1)).scalars().first()
    if c is None:
        dono = db.execute(select(Usuario).where(Usuario.perfil == "admin").order_by(Usuario.id)).scalars().first()
        c = ContaEmail(principal=True, nome="E-mail principal da MS", dono_id=dono.id if dono else None,
                       compartilhada_todos=True)
        db.add(c)
        db.flush()
    return c


def todas(db) -> list[ContaEmail]:
    garantir_principal(db)
    return list(db.execute(select(ContaEmail).order_by(ContaEmail.principal.desc(), ContaEmail.criado_em)).scalars())


def visiveis(db, usuario: Usuario) -> list[ContaEmail]:
    """Na tela E-mail: admin e gestor veem todas (para compartilhar); os outros, as que podem usar."""
    ve_todas = autorizacao.pode(usuario, "email.compartilhar_todas") or autorizacao.pode(usuario, "email.gerenciar_todas")
    return [c for c in todas(db) if ve_todas or pode_usar(usuario, c)]


def minha(db, usuario: Usuario) -> ContaEmail | None:
    return db.execute(select(ContaEmail).where(ContaEmail.dono_id == usuario.id, ContaEmail.principal.is_(False))
                      .limit(1)).scalars().first()


def principal_pronta() -> bool:
    from .integracoes import email_smtp

    return email_smtp.configurado()


def para_enviar(db, quem: Usuario | None) -> ContaEmail:
    """Conta por onde sai o e-mail de `quem`: a própria (ligada); senão uma compartilhada com ele; senão a principal,
    se estiver liberada para ele (principal sem configuração: o envio avisa)."""
    principal = garantir_principal(db)
    if quem is None:
        return principal
    proprio = minha(db, quem)
    if proprio and proprio.ativa:
        return proprio
    for c in todas(db):
        if not c.principal and c.ativa and c.id != (proprio.id if proprio else 0) and pode_usar(quem, c):
            return c
    if pode_usar(quem, principal):
        return principal
    raise SemConta(f"{quem.nome} não tem e-mail para enviar: cadastre o seu na tela E-mail ou peça para o "
                   "administrador ou o gestor compartilhar um.")


def para_ler(db) -> list[ContaEmail]:
    """Contas cujas caixas a IA SDR lê (respostas dos leads)."""
    from .integracoes import email_imap

    return [c for c in todas(db) if (c.principal and email_imap.configurado())
            or (not c.principal and c.ativa and c.ler_respostas)]
