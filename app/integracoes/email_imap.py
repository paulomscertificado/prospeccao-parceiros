"""Leitura das RESPOSTAS por e-mail (IMAP): a IA SDR identifica quem respondeu e classifica.

Configure IMAP_HOST, IMAP_USUARIO e IMAP_SENHA no .env (a mesma caixa que envia os e-mails).
Só lê e-mails NÃO LIDOS de remetentes que são leads cadastrados; os demais ficam como estão.
"""

import email
import imaplib
import logging
import re
from email.header import decode_header, make_header

from .. import config

log = logging.getLogger(__name__)


def configurado() -> bool:
    return bool(config.IMAP_HOST and config.IMAP_USUARIO and config.IMAP_SENHA)


def _texto(msg) -> str:
    if msg.is_multipart():
        for parte in msg.walk():
            if parte.get_content_type() == "text/plain" and "attachment" not in str(parte.get("Content-Disposition")):
                return parte.get_payload(decode=True).decode(parte.get_content_charset() or "utf-8", "replace")
        for parte in msg.walk():
            if parte.get_content_type() == "text/html":
                html = parte.get_payload(decode=True).decode(parte.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", html)
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def sem_citacao(texto: str) -> str:
    """Corta o histórico citado ("Em ... escreveu:", linhas com ">") e deixa só a resposta nova."""
    linhas = []
    for linha in texto.splitlines():
        if re.match(r"^\s*>", linha) or re.match(r"^\s*(Em .+escreveu|On .+wrote|-----Original|De:\s)", linha):
            break
        # Gmail quebra "Em dom., 25 de out. de 2026 às 17:42, Fulano <\nemail> escreveu:" em duas linhas
        if re.match(r"^\s*(Em|On) .{0,80}\d{1,2}:\d{2}", linha):
            break
        linhas.append(linha)
    resposta = "\n".join(linhas).strip()
    # assinatura padrão sozinha no fim ("Atenciosamente,") não ajuda a entender a resposta
    return re.sub(r"\n+\s*(Atenciosamente|Att|Abraços|Obrigad[oa])[,.!]?\s*$", "", resposta, flags=re.I).strip()


def ler_respostas(emails_de_leads: set[str], maximo: int = 30) -> list[dict]:
    """Devolve [{"de", "assunto", "texto"}] dos e-mails não lidos vindos de leads (e marca como lidos)."""
    from .. import arquivo_env

    arquivo_env.carregar_do_banco(forcar=True)  # na nuvem: a senha salva há pouco já vale aqui
    if not configurado():
        return []
    achados = []
    try:
        with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORTA, timeout=30) as caixa:
            caixa.login(config.IMAP_USUARIO, config.IMAP_SENHA)
            caixa.select("INBOX")
            _, dados = caixa.search(None, "UNSEEN")
            for num in dados[0].split()[-200:]:
                _, cab = caixa.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
                remetente = email.utils.parseaddr(email.message_from_bytes(cab[0][1]).get("From", ""))[1].lower()
                if remetente not in emails_de_leads:
                    continue  # não é lead: continua "não lido" para a equipe
                _, conteudo = caixa.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(conteudo[0][1])
                achados.append({"de": remetente, "assunto": str(make_header(decode_header(msg.get("Subject", "")))),
                                "texto": sem_citacao(_texto(msg))[:4000]})
                if len(achados) >= maximo:
                    break
    except (imaplib.IMAP4.error, OSError) as erro:
        log.warning("Leitura IMAP falhou: %s", erro)
    return achados


def testar() -> str:
    """Entra na caixa e conta os e-mails não lidos. Devolve um texto para a tela (ou lança ErroImap)."""
    from .. import arquivo_env

    arquivo_env.carregar_do_banco(forcar=True)  # na nuvem: a senha salva há pouco já vale aqui
    if not configurado():
        raise ErroImap("A leitura das respostas não está configurada.")
    try:
        with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORTA, timeout=30) as caixa:
            caixa.login(config.IMAP_USUARIO, config.IMAP_SENHA)
            caixa.select("INBOX", readonly=True)
            _, dados = caixa.search(None, "UNSEEN")
            return f"Leitura funcionando: a caixa {config.IMAP_USUARIO} tem {len(dados[0].split())} e-mails não lidos."
    except imaplib.IMAP4.error:
        raise ErroImap("O servidor recusou o login de leitura. No Google, use a mesma SENHA DE APP do envio e "
                       "confira se o IMAP está ativado no Gmail (Configurações > Encaminhamento e POP/IMAP).") from None
    except OSError as erro:
        raise ErroImap(f"Não consegui conectar ao servidor de leitura ({erro}).") from None


class ErroImap(Exception):
    pass
