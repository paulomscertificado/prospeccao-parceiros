"""Contas de e-mail das campanhas: a principal da MS (Configurações > E-mail) e a de cada pessoa da equipe.

Funciona como os números de WhatsApp (app/conexoes.py):
- cada pessoa cadastra o PRÓPRIO e-mail @mscertificados.com.br (tela E-mail); quem tem email.outro_dominio
  (gestor e admin) pode usar o próprio domínio e servidor (Google, Microsoft 365 ou outro SMTP/IMAP);
- o dono, o administrador e o gestor compartilham uma conta com toda a equipe ou com pessoas escolhidas;
- o e-mail de um lead sai pela conta do responsável; sem conta própria, por uma que compartilharam com ele (da mesma
  AR; pedido da Maria em 18/11/2026, como no WhatsApp). A principal da MS só vale para os disparos do dono dela:
  compartilhada, ela aparece para a pessoa, mas os disparos dela não saem por ali (para_enviar).
Os limites de envio (por hora, dia e domínio) continuam valendo para a MS inteira: todas as contas são do mesmo
domínio e dividem a mesma reputação.
"""

import json
from dataclasses import dataclass
from email.utils import formataddr, parseaddr

from sqlalchemy import select
from sqlalchemy.orm import object_session

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


def dominio_da_equipe(db, usuario: Usuario | None) -> str:
    """O domínio dos e-mails da equipe da AR da pessoa (Configurações > Marca; white label, Fase 5). Vazio = a AR ainda
    não informou: vale qualquer domínio de empresa (nunca Gmail, Hotmail... pessoal)."""
    from . import marca

    return marca.da_pessoa(usuario, db=db)["dominio_email"] if usuario is not None else config.EMAIL_DOMINIO


def dominio_ok(conta: ContaEmail | None, endereco: str) -> bool:
    """Na hora de enviar: o e-mail é do domínio da AR do dono da conta (ou a conta tem o domínio liberado)."""
    if conta is None or conta.principal:
        return not config.EMAIL_DOMINIO or endereco.lower().endswith("@" + config.EMAIL_DOMINIO.lower())
    if dominio_liberado(conta):
        return True
    from . import marca

    if not conta.tenant_id:
        return not config.EMAIL_DOMINIO or endereco.lower().endswith("@" + config.EMAIL_DOMINIO.lower())
    dominio = marca.da_pessoa(None, conta.tenant_id, db=object_session(conta))["dominio_email"]
    return not dominio or endereco.lower().endswith("@" + dominio)


def dominio_liberado(conta: ContaEmail | None) -> bool:
    """A conta pode enviar fora do domínio da AR: foi salva assim e o dono AINDA tem email.outro_dominio."""
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
    # sem o filtro da AR (white label, Fase 2): a principal é da AR MS e existe uma vez só; numa tela de outra AR ela
    # fica escondida, mas não pode ser criada de novo
    sem_filtro = {"sem_filtro_de_ar": True}
    c = db.execute(select(ContaEmail).where(ContaEmail.principal.is_(True)).limit(1)
                   .execution_options(**sem_filtro)).scalars().first()
    if c is None or c.dono_id is None:
        # a principal é do cadastro do primeiro administrador (regra de 13/11/2026: cada pessoa dispara só pelo
        # próprio e-mail; criada antes de existir um administrador, ganha o dono depois)
        dono = db.execute(select(Usuario).where(Usuario.perfil == "admin").order_by(Usuario.id)
                          .execution_options(**sem_filtro)).scalars().first()
        if c is None:
            c = ContaEmail(principal=True, nome="E-mail principal da MS", dono_id=dono.id if dono else None,
                           compartilhada_todos=True)
            db.add(c)
        elif dono is not None:
            c.dono_id = dono.id
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


def _ar_da_conta(db, c: ContaEmail):
    """AR da conta: a gravada nela ou, se ainda vazia, a do dono."""
    if c.tenant_id:
        return c.tenant_id
    dono = db.get(Usuario, c.dono_id) if c.dono_id else None
    return dono.tenant_id if dono is not None else None


def compartilhadas_para_disparo(db, quem: Usuario) -> list[ContaEmail]:
    """Contas de outras pessoas que valem para os disparos de `quem`: o dono (ou o administrador/gestor) compartilhou
    com ele ou com toda a equipe, a conta está ligada e é da mesma AR. Nunca a principal. Primeiro as compartilhadas
    com a pessoa pelo nome, depois as de toda a equipe; entre elas, a mais antiga. As filas rodam sem o filtro da AR
    (white label): por isso a AR é conferida aqui, senão o "toda a equipe" de uma AR valeria para as outras."""
    ar = getattr(quem, "tenant_id", None)
    if not ar:
        return []
    contas = db.execute(select(ContaEmail).where(ContaEmail.principal.is_(False), ContaEmail.ativa.is_(True))
                        .order_by(ContaEmail.criado_em, ContaEmail.id)).scalars().all()
    escolhidas = [c for c in contas if c.dono_id != quem.id and (c.compartilhada_todos or quem.id in compartilhada_com(c))
                  and _ar_da_conta(db, c) == ar]
    return sorted(escolhidas, key=lambda c: quem.id not in compartilhada_com(c))  # sorted é estável: mantém a idade


def para_enviar(db, quem: Usuario | None) -> ContaEmail:
    """Conta por onde sai o e-mail de `quem` (campanhas, filas, Minha fila, envio pela ficha do lead):
    1. a do cadastro dele (a principal da MS conta como do cadastro de quem é dono dela);
    2. sem conta própria, uma conta de outra pessoa compartilhada com ele (compartilhadas_para_disparo). Pedido da Maria
       em 18/11/2026 ("Sim, liberar"), como já era no WhatsApp: a Thamires compartilhou o e-mail dela com a Maria
       Eduarda e os e-mails da campanha da Maria Eduarda continuavam parados.
    Continua valendo a regra de 13/11/2026 ("cada usuário tem seu disparo, nunca misture os disparos de um usuário com
    outro"): ninguém dispara pelo e-mail de outra pessoa sem que ela (ou o administrador/gestor) compartilhe, e ser
    administrador não basta. A principal nunca vale para os disparos de outra pessoa: ela é compartilhada com toda a
    equipe, e os e-mails de todo mundo sem conta passariam a sair por ela. Conta própria pausada: os disparos esperam
    (não troca para uma compartilhada). Sem conta: o disparo espera e a pessoa é avisada. Sem responsável (envio do
    sistema): a principal."""
    principal = garantir_principal(db)
    if quem is None:
        return principal
    proprio = minha(db, quem)
    if proprio is not None:
        if proprio.ativa:
            return proprio
        raise SemConta(f"O e-mail de {quem.nome} está pausado em Contas de e-mail: os disparos de {quem.nome} esperam até "
                       "ligar de novo (quem tem e-mail próprio dispara só por ele).")
    if principal.dono_id == quem.id:
        return principal
    compartilhadas = compartilhadas_para_disparo(db, quem)
    if compartilhadas:
        return compartilhadas[0]
    raise SemConta(f"{quem.nome} não tem e-mail próprio cadastrado nem um e-mail compartilhado: cadastre o seu em Contas de "
                   "e-mail ou peça a quem tem um para compartilhar. Pela regra do sistema, os disparos de cada pessoa saem "
                   "só pelo e-mail dela ou por um que compartilharam com ela (nunca pelo principal).")


def para_ler(db) -> list[ContaEmail]:
    """Contas cujas caixas a IA SDR lê (respostas dos leads)."""
    from .integracoes import email_imap

    return [c for c in todas(db) if (c.principal and email_imap.configurado())
            or (not c.principal and c.ativa and c.ler_respostas)]
