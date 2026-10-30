"""Leitura das RESPOSTAS por e-mail (IMAP): a IA SDR identifica quem respondeu e classifica.

Configure IMAP_HOST, IMAP_USUARIO e IMAP_SENHA no .env (a mesma caixa que envia os e-mails).
Lê os e-mails dos últimos dias (lidos ou não, sem marcar nada como lido) que vieram de um lead cadastrado ou que
respondem a um e-mail enviado pelo sistema (In-Reply-To/References). Cada e-mail é processado uma vez só: o
Message-ID fica guardado na mensagem recebida.
"""

import email
import hashlib
import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

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


DIAS_DE_LEITURA = 3
_MESES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FUSO_BRASILIA = timezone(timedelta(hours=-3))


def _data_imap(d: datetime) -> str:
    return f"{d.day:02d}-{_MESES[d.month - 1]}-{d.year}"  # o IMAP só aceita o mês em inglês


def _ids(valor: str) -> list[str]:
    return re.findall(r"<[^<>\s]+>", valor or "")


def id_da_mensagem(cab) -> str:
    """Message-ID (até 120 letras, o tamanho do campo). Sem ele: uma marca feita do remetente, data e assunto."""
    ids = _ids(cab.get("Message-ID", ""))
    if ids:
        return ids[0][:120]
    base = f"{cab.get('From', '')}|{cab.get('Date', '')}|{cab.get('Subject', '')}"
    return "sem-id:" + hashlib.sha1(base.encode("utf-8", "replace")).hexdigest()[:24]


def _quando(cab) -> datetime | None:
    try:
        d = parsedate_to_datetime(cab.get("Date", ""))
    except (TypeError, ValueError, IndexError):
        return None
    if d.tzinfo is None:
        return d
    return d.astimezone(FUSO_BRASILIA).replace(tzinfo=None)


def _acesso(conta) -> tuple[str, int, str, str]:
    """(servidor, porta, login, senha) da caixa: None = a principal (Configurações > E-mail)."""
    if conta is None or conta.principal:
        return config.IMAP_HOST, config.IMAP_PORTA, config.IMAP_USUARIO, config.IMAP_SENHA
    from .. import contas_email

    c = contas_email.credenciais(conta)
    return c.imap_host, c.imap_porta, c.login, c.senha


def ler_respostas(emails_de_leads: set[str], enviados: set[str] | None = None, ja_processados: set[str] | None = None,
                  desde: datetime | None = None, maximo: int = 30, conta=None) -> list[dict]:
    """[{"de", "assunto", "texto", "message_id", "responde_a"}] dos e-mails recentes de leads (ou que respondem a um
    e-mail enviado pelo sistema) ainda não processados. Não marca nada como lido: a caixa fica como a equipe deixou.
    enviados: Message-IDs dos e-mails que o sistema mandou; ja_processados: Message-IDs já tratados;
    desde: ignora e-mails mais antigos (a 1ª leitura não reprocessa respostas já tratadas)."""
    from .. import arquivo_env

    arquivo_env.carregar_do_banco(forcar=True)  # na nuvem: a senha salva há pouco já vale aqui
    servidor, porta, login, senha = _acesso(conta)
    if not (servidor and login and senha):
        return []
    enviados, ja_processados = enviados or set(), ja_processados or set()
    inicio = datetime.now(FUSO_BRASILIA).replace(tzinfo=None) - timedelta(days=DIAS_DE_LEITURA)
    if desde and desde > inicio:
        inicio = desde
    achados = []
    try:
        with imaplib.IMAP4_SSL(servidor, porta, timeout=30) as caixa:
            caixa.login(login, senha)
            caixa.select("INBOX", readonly=True)  # só leitura: nada fica marcado como lido
            _, dados = caixa.search(None, "SINCE", _data_imap(inicio))
            for num in dados[0].split()[-300:]:
                _, cab_bruto = caixa.fetch(
                    num, "(BODY.PEEK[HEADER.FIELDS (FROM DATE SUBJECT MESSAGE-ID IN-REPLY-TO REFERENCES)])")
                cab = email.message_from_bytes(cab_bruto[0][1])
                message_id = id_da_mensagem(cab)
                if message_id in ja_processados:
                    continue
                quando = _quando(cab)
                if quando and quando < inicio:
                    continue
                remetente = email.utils.parseaddr(cab.get("From", ""))[1].lower()
                responde_a = [i[:120] for i in _ids(cab.get("In-Reply-To", "")) + _ids(cab.get("References", ""))]
                if remetente not in emails_de_leads and not any(i in enviados for i in responde_a):
                    continue  # não é de lead nem responde a um e-mail nosso
                _, conteudo = caixa.fetch(num, "(BODY.PEEK[])")
                msg = email.message_from_bytes(conteudo[0][1])
                achados.append({"de": remetente, "assunto": str(make_header(decode_header(msg.get("Subject", "")))),
                                "texto": sem_citacao(_texto(msg))[:4000], "message_id": message_id,
                                "responde_a": responde_a})
                if len(achados) >= maximo:
                    break
    except (imaplib.IMAP4.error, OSError) as erro:
        log.warning("Leitura IMAP falhou (%s): %s", login, erro)
    return achados


def testar(conta=None) -> str:
    """Entra na caixa e conta os e-mails não lidos. Devolve um texto para a tela (ou lança ErroImap).
    conta: ContaEmail (None = a principal)."""
    from .. import arquivo_env

    arquivo_env.carregar_do_banco(forcar=True)  # na nuvem: a senha salva há pouco já vale aqui
    servidor, porta, login, senha = _acesso(conta)
    if not (servidor and login and senha):
        raise ErroImap("A leitura das respostas não está configurada.")
    try:
        with imaplib.IMAP4_SSL(servidor, porta, timeout=30) as caixa:
            caixa.login(login, senha)
            caixa.select("INBOX", readonly=True)
            _, dados = caixa.search(None, "UNSEEN")
            return f"Leitura funcionando: a caixa {login} tem {len(dados[0].split())} e-mails não lidos."
    except imaplib.IMAP4.error:
        raise ErroImap("O servidor recusou o login de leitura. No Google, use a mesma SENHA DE APP do envio e "
                       "confira se o IMAP está ativado no Gmail (Configurações > Encaminhamento e POP/IMAP).") from None
    except OSError as erro:
        raise ErroImap(f"Não consegui conectar ao servidor de leitura ({erro}).") from None


class ErroImap(Exception):
    pass
