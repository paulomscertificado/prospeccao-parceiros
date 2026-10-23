"""E-mail comercial por SMTP, com o remetente do domínio da empresa (ex.: @mscertificados.com.br).

O domínio do mscertificados.com.br está no Google Workspace: servidor smtp.gmail.com, porta 587, e a
senha é uma SENHA DE APP do Google (não a senha normal). Configure em Configurações > E-mail.
"""

import hashlib
import hmac
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from .. import config


class ErroEmail(Exception):
    pass


def endereco_remetente() -> str:
    return parseaddr(config.SMTP_REMETENTE or config.SMTP_USUARIO)[1].lower()


def dominio_permitido(endereco: str) -> bool:
    return not config.EMAIL_DOMINIO or endereco.lower().endswith("@" + config.EMAIL_DOMINIO.lower())


def configurado() -> bool:
    return bool(config.SMTP_HOST and endereco_remetente()) and dominio_permitido(endereco_remetente())


def problema_de_configuracao() -> str:
    if not config.SMTP_HOST or not endereco_remetente():
        return "O e-mail de envio ainda não foi configurado (Configurações > E-mail)."
    if not dominio_permitido(endereco_remetente()):
        return f"O remetente precisa ser um e-mail @{config.EMAIL_DOMINIO} (está {endereco_remetente()})."
    return ""


# ---------------------------------------------------------------- Descadastro (opt-out)

def assinatura_descadastro(lead_id: int) -> str:
    return hmac.new(config.SECRET_KEY.encode(), f"descadastro:{lead_id}".encode(), hashlib.sha256).hexdigest()[:24]


def link_descadastro(lead_id: int | None) -> str:
    """Link de descadastro de 1 clique — só quando o sistema está publicado na internet (URL_PUBLICA)."""
    if not lead_id or any(x in config.URL_PUBLICA for x in ("localhost", "127.0.0.1")):
        return ""
    return f"{config.URL_PUBLICA}/descadastrar/{lead_id}/{assinatura_descadastro(lead_id)}"


def rodape(lead_id: int | None) -> str:
    link = link_descadastro(lead_id)
    if link:
        return f"\n\n--\nNão quer mais receber nossos e-mails? Descadastre-se em 1 clique: {link}"
    return ("\n\n--\nSe não quiser mais receber nossos e-mails, responda esta mensagem com a palavra SAIR "
            "e removeremos seu contato.")


RODAPE_OPT_OUT = rodape(None)


# ---------------------------------------------------------------- Envio

def enviar(para: str, assunto: str, corpo: str, responder_para: str = "", com_rodape: bool = True,
           lead_id: int | None = None) -> str:
    problema = problema_de_configuracao()
    if problema:
        raise ErroEmail(problema)
    remetente = endereco_remetente()
    nome = parseaddr(config.SMTP_REMETENTE)[0]
    msg = EmailMessage()
    msg["From"] = formataddr((nome, remetente)) if nome else remetente
    msg["To"] = para
    msg["Subject"] = assunto
    msg["Message-ID"] = make_msgid(domain=remetente.split("@")[-1])
    link = link_descadastro(lead_id)
    unsubscribe = f"<mailto:{remetente}?subject=SAIR>"
    if link:
        unsubscribe = f"<{link}>, {unsubscribe}"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["List-Unsubscribe"] = unsubscribe
    responder = responder_para or config.SMTP_RESPONDER_PARA
    if responder:
        msg["Reply-To"] = responder
    msg.set_content(corpo + (rodape(lead_id) if com_rodape else ""))
    usuario = config.SMTP_USUARIO or remetente
    try:
        logado = False
        if config.SMTP_PORTA == 465:
            with smtplib.SMTP_SSL(config.SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as s:
                s.login(usuario, config.SMTP_SENHA)
                logado = True
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORTA, timeout=30) as s:
                if config.SMTP_TLS:
                    s.starttls(context=ssl.create_default_context())
                s.login(usuario, config.SMTP_SENHA)
                logado = True
                s.send_message(msg)
    except smtplib.SMTPServerDisconnected as erro:
        # O Google não responde "senha errada": ele fecha a conexão logo depois da senha.
        if not logado and ("gmail" in config.SMTP_HOST or "google" in config.SMTP_HOST):
            raise ErroEmail("O Google recusou a senha (fechou a conexão ao conferir). Use uma SENHA DE APP de 16 letras "
                            "criada em myaccount.google.com/apppasswords com a conta do e-mail de envio — a senha normal "
                            "da conta não funciona. Cole a senha de app em Configurações > E-mail e salve.") from None
        raise ErroEmail(f"Não consegui enviar o e-mail ({erro}). Confira a internet e o servidor.") from None
    except smtplib.SMTPAuthenticationError:
        if "gmail" in config.SMTP_HOST or "google" in config.SMTP_HOST:
            raise ErroEmail("O Google recusou a senha. Use uma SENHA DE APP (16 letras) criada em "
                            "myaccount.google.com/apppasswords com a conta do e-mail de envio — a verificação em duas "
                            "etapas precisa estar ligada nessa conta.") from None
        raise ErroEmail("Usuário ou senha do e-mail recusados. Confira em Configurações > E-mail.") from None
    except smtplib.SMTPSenderRefused:
        raise ErroEmail(f"O servidor não aceitou enviar como {remetente}. O remetente deve ser o próprio e-mail "
                        "da conta (ou um alias dela).") from None
    except (smtplib.SMTPException, OSError) as erro:
        raise ErroEmail(f"Não consegui enviar o e-mail ({erro}). Confira a internet e o servidor.") from None
    return msg["Message-ID"]
