"""E-mail comercial por SMTP, com o remetente do domínio da empresa (ex.: @mscertificados.com.br).

O domínio do mscertificados.com.br está no Google Workspace: servidor smtp.gmail.com, porta 587, e a
senha é uma SENHA DE APP do Google (não a senha normal). Configure em Configurações > E-mail.
"""

import hashlib
import hmac
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from .. import config


class ErroEmail(Exception):
    pass


class ErroDestinatario(ErroEmail):
    """O problema é o endereço do lead (inválido ou recusado), não a caixa de envio: só este e-mail não sai."""


ENDERECO_VALIDO = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


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
           lead_id: int | None = None, em_resposta_a: str = "", conta=None) -> str:
    """Envia e devolve o Message-ID. em_resposta_a: Message-ID do e-mail do lead (a resposta fica no mesmo fio).
    conta: ContaEmail por onde sai (app/contas_email.py); None = a principal da MS."""
    from .. import arquivo_env, contas_email

    principal = conta is None or conta.principal
    if principal:
        arquivo_env.carregar_do_banco(forcar=True)  # na nuvem: a senha salva há pouco já vale aqui
        problema = problema_de_configuracao()
        if problema:
            raise ErroEmail(problema)
    c = contas_email.credenciais(conta)
    if not principal:
        if not c.host or not c.endereco or not c.senha:
            raise ErroEmail(f"A conta {c.rotulo} está incompleta: falta a senha de app (tela E-mail).")
        if not dominio_permitido(c.endereco) and not contas_email.dominio_liberado(conta):
            raise ErroEmail(f"O remetente precisa ser um e-mail @{config.EMAIL_DOMINIO} (está {c.endereco}). "
                            "Outro domínio só para quem tem a permissão \"Enviar pelo próprio domínio\".")
    para = (para or "").strip()
    if not ENDERECO_VALIDO.match(para):
        raise ErroDestinatario(f"O e-mail \"{para}\" não é um endereço válido.")
    remetente = c.endereco
    nome = parseaddr(c.remetente)[0]
    msg = EmailMessage()
    msg["From"] = formataddr((nome, remetente)) if nome else remetente
    msg["To"] = para
    msg["Subject"] = assunto
    msg["Message-ID"] = make_msgid(domain=remetente.split("@")[-1])
    if em_resposta_a:
        msg["In-Reply-To"] = em_resposta_a
        msg["References"] = em_resposta_a
    link = link_descadastro(lead_id)
    unsubscribe = f"<mailto:{remetente}?subject=SAIR>"
    if link:
        unsubscribe = f"<{link}>, {unsubscribe}"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["List-Unsubscribe"] = unsubscribe
    responder = responder_para or c.responder_para
    if responder:
        msg["Reply-To"] = responder
    msg.set_content(corpo + (rodape(lead_id) if com_rodape else ""))
    usuario = c.login or remetente
    google = "gmail" in c.host or "google" in c.host
    onde = "Configurações > E-mail" if principal else "a tela E-mail"
    try:
        logado = False
        if c.porta == 465:
            with smtplib.SMTP_SSL(c.host, 465, context=ssl.create_default_context(), timeout=30) as s:
                s.login(usuario, c.senha)
                logado = True
                s.send_message(msg)
        else:
            with smtplib.SMTP(c.host, c.porta, timeout=30) as s:
                if c.tls:
                    s.starttls(context=ssl.create_default_context())
                s.login(usuario, c.senha)
                logado = True
                s.send_message(msg)
    except smtplib.SMTPServerDisconnected as erro:
        # O Google não responde "senha errada": ele fecha a conexão logo depois da senha.
        if not logado and google:
            raise ErroEmail(f"O Google recusou a senha da conta {usuario} (fechou a conexão ao conferir). "
                            "Confira: 1) a senha de app (16 letras) foi criada ESTANDO LOGADO nessa conta, em "
                            "myaccount.google.com/apppasswords; 2) se o e-mail de envio for um apelido (alias) ou grupo, "
                            "preencha \"Conta que faz o login\" com a conta dona dele. A senha normal não funciona.") from None
        raise ErroEmail(f"Não consegui enviar o e-mail ({erro}). Confira a internet e o servidor.") from None
    except smtplib.SMTPAuthenticationError:
        if google:
            raise ErroEmail(f"O Google recusou a senha de {usuario}. Use uma SENHA DE APP (16 letras) criada em "
                            "myaccount.google.com/apppasswords com a conta do e-mail de envio — a verificação em duas "
                            "etapas precisa estar ligada nessa conta.") from None
        raise ErroEmail(f"Usuário ou senha do e-mail recusados. Confira em {onde}.") from None
    except smtplib.SMTPRecipientsRefused as erro:
        detalhe = "; ".join(f"{cod} {m.decode(errors='replace') if isinstance(m, bytes) else m}"
                            for cod, m in erro.recipients.values())
        raise ErroDestinatario(f"O servidor recusou o endereço {para} ({detalhe[:150]}).") from None
    except smtplib.SMTPSenderRefused:
        raise ErroEmail(f"O servidor não aceitou enviar como {remetente}. O remetente deve ser o próprio e-mail "
                        "da conta (ou um alias dela).") from None
    except (smtplib.SMTPException, OSError) as erro:
        raise ErroEmail(f"Não consegui enviar o e-mail ({erro}). Confira a internet e o servidor.") from None
    return msg["Message-ID"]
