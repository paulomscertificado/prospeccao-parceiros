"""E-mails que não existem: conferência antes de enviar e devoluções ("Endereço não encontrado").

Duas defesas, para a campanha não insistir em endereço morto (o que também prejudica a reputação do domínio
@mscertificados.com.br nos provedores):

1. ANTES de enviar: formato do endereço e se o domínio recebe e-mail (registro MX no DNS, pelo dns.google).
   Ex.: "jaci@jacicontabilpe.com.br" com domínio inexistente é barrado sem gastar envio.
2. DEPOIS de enviar: as mensagens de devolução que chegam na caixa (Gmail "Endereço não encontrado",
   Outlook "Undeliverable", "Mail delivery failed"...) são lidas e o e-mail do lead é marcado como inválido.
   Ex.: "leoi@terra.com.br" (domínio existe, a caixa não).

Lead com e-mail inválido: os toques de e-mail pendentes são cancelados, o e-mail deixa de contar como canal da
campanha e a ficha do lead mostra o aviso. Se corrigirem o endereço na ficha, a marca sai sozinha.
"""

import logging
import os
import re
from datetime import timedelta

import httpx
from sqlalchemy import select

log = logging.getLogger(__name__)

DIAS_PARA_CONFERIR_DE_NOVO = 30
_FORMATO = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                      r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
_cache_dominios: dict[str, tuple[bool | None, str]] = {}


def formato_valido(email: str) -> bool:
    email = (email or "").strip()
    return bool(_FORMATO.match(email)) and ".." not in email and len(email) <= 160


def _consulta_dns(nome: str, tipo: str) -> dict:
    r = httpx.get("https://dns.google/resolve", params={"name": nome, "type": tipo}, timeout=8)
    r.raise_for_status()
    return r.json()


def dominio_recebe_email(dominio: str) -> tuple[bool | None, str]:
    """(True/False/None, motivo). None = não deu para saber agora (sem internet): não barra o envio."""
    dominio = (dominio or "").strip().lower().rstrip(".")
    if os.environ.get("CONFERIR_DOMINIO_EMAIL", "1") == "0":
        return None, ""  # desligado (testes automáticos usam domínios de mentira)
    if dominio in _cache_dominios:
        return _cache_dominios[dominio]
    try:
        mx = _consulta_dns(dominio, "MX")
        if mx.get("Status") == 3:
            resultado = (False, f"o domínio {dominio} não existe")
        else:
            registros = [a.get("data", "") for a in mx.get("Answer", []) if a.get("type") == 15]
            if registros and all(r.strip().endswith(" .") or r.strip() == "0 ." for r in registros):
                resultado = (False, f"o domínio {dominio} não recebe e-mails")
            elif registros:
                resultado = (True, "")
            else:
                # sem MX, a norma manda tentar o próprio domínio (registro A)
                a = _consulta_dns(dominio, "A")
                tem_a = any(x.get("type") == 1 for x in a.get("Answer", []))
                resultado = (True, "") if tem_a else (False, f"o domínio {dominio} não recebe e-mails")
    except (httpx.HTTPError, ValueError) as erro:
        log.info("Não deu para conferir o domínio %s: %s", dominio, erro)
        return None, ""
    _cache_dominios[dominio] = resultado
    return resultado


def conferir(email: str) -> tuple[bool | None, str]:
    """(True/False/None, motivo) para um endereço."""
    email = (email or "").strip()
    if not email:
        return False, "sem e-mail"
    if not formato_valido(email):
        return False, "o endereço está escrito errado"
    return dominio_recebe_email(email.rsplit("@", 1)[1])


def marcar_invalido(db, lead, motivo: str, usuario=None) -> int:
    """Marca o e-mail do lead como inexistente e cancela os toques de e-mail pendentes. Devolve quantos cancelou."""
    from .banco import agora
    from .leads_servico import historico
    from .modelos import Tarefa

    motivo = (motivo or "o e-mail não existe")[:200]
    ja_estava = lead.email_invalido
    lead.email_invalido, lead.email_motivo, lead.email_verificado_em = True, motivo, agora()
    lead.email_conferido = lead.email or ""
    cancelados = 0
    for t in db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id, Tarefa.canal == "email",
                                             Tarefa.status.in_(["pendente", "rascunho"]))).scalars():
        t.status, t.concluida_em, t.resultado = "cancelada", agora(), f"E-mail não existe: {motivo}"[:500]
        cancelados += 1
    if not ja_estava:
        historico(db, lead.id, "sistema", f"E-mail {lead.email} marcado como inexistente: {motivo}. "
                                          "Os e-mails da campanha para ele foram cancelados.", usuario, "email")
    return cancelados


def utilizavel(db, lead, conferir_agora: bool = True) -> bool:
    """O e-mail do lead pode receber campanha? Confere o domínio (no máximo a cada 30 dias) e marca se não existir."""
    from .banco import agora

    if not lead.email:
        return False
    if (lead.email_conferido or "") != lead.email:
        # o endereço mudou (corrigido na ficha): a marca antiga não vale mais
        lead.email_invalido, lead.email_motivo, lead.email_verificado_em = False, "", None
        lead.email_conferido = lead.email
    if lead.email_invalido:
        return False
    if not conferir_agora:
        return True
    if lead.email_verificado_em and agora() - lead.email_verificado_em < timedelta(days=DIAS_PARA_CONFERIR_DE_NOVO):
        return True
    ok, motivo = conferir(lead.email)
    if ok is False:
        marcar_invalido(db, lead, motivo)
        return False
    if ok:
        lead.email_verificado_em = agora()
    return True


# ---------------------------------------------------------------- Devoluções

_REMETENTE_DEVOLUCAO = re.compile(r"mailer-daemon|postmaster|mail delivery|microsoftexchange|maildelivery", re.I)
_ASSUNTO_DEVOLUCAO = re.compile(
    r"delivery status notification|undeliver|n[ãa]o (foi )?entregue|endere[çc]o n[ãa]o encontrado|"
    r"mail delivery fail|returned mail|delivery failure|falha na entrega|n[ãa]o [ée] poss[íi]vel entregar|"
    r"mensagem n[ãa]o entregue|failure notice", re.I)
_PERMANENTE = re.compile(
    r"n[ãa]o (foi )?encontrad|does ?n[o']t exist|no such user|user unknown|unknown user|recipient rejected|"
    r"mailbox unavailable|address rejected|invalid recipient|not found|inexistente|no longer|disabled|"
    r"dom[íi]nio .{0,40}n[ãa]o|domain .{0,40}(not|couldn)|dns|nxdomain|unrouteable|account .{0,20}(disabled|inactive)",
    re.I)
_TEMPORARIO = re.compile(r"caixa .{0,15}cheia|mailbox (is )?full|over ?quota|quota exceeded|tente novamente|try again|"
                         r"temporar", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def parece_devolucao(remetente: str, assunto: str, tipo_conteudo: str = "") -> bool:
    if "report-type=delivery-status" in (tipo_conteudo or "").replace(" ", "").lower():
        return True
    return bool(_REMETENTE_DEVOLUCAO.search(remetente or "") and _ASSUNTO_DEVOLUCAO.search(assunto or "")) or \
        bool(_ASSUNTO_DEVOLUCAO.search(assunto or "") and re.search(r"daemon|postmaster|delivery", remetente or "", re.I))


def analisar_devolucao(msg) -> dict:
    """Lê uma mensagem de devolução (email.message.Message). Devolve
    {"destinatarios": [...], "permanente": bool, "motivo": str, "ids_originais": [...]}."""
    destinatarios, status, diagnostico, ids_originais, textos = [], "", "", [], []
    falhos = msg.get_all("X-Failed-Recipients") or []
    for f in falhos:
        destinatarios += _EMAIL.findall(f)
    for parte in msg.walk():
        tipo = parte.get_content_type()
        if tipo == "message/delivery-status":
            carga = parte.get_payload()
            blocos = carga if isinstance(carga, list) else []
            for bloco in blocos:
                for chave in ("Final-Recipient", "Original-Recipient"):
                    if bloco.get(chave):
                        destinatarios += _EMAIL.findall(bloco.get(chave))
                status = status or (bloco.get("Status") or "").strip()
                diagnostico = diagnostico or (bloco.get("Diagnostic-Code") or "").strip()
        elif tipo in ("text/rfc822-headers", "message/rfc822"):
            carga = parte.get_payload()
            texto = carga if isinstance(carga, str) else str(carga[0]) if isinstance(carga, list) and carga else ""
            ids_originais += re.findall(r"(?im)^message-id:\s*(<[^>\s]+>)", texto)
        elif tipo in ("text/plain", "text/html") and not parte.get_filename():
            try:
                bruto = parte.get_payload(decode=True) or b""
                textos.append(bruto.decode(parte.get_content_charset() or "utf-8", "replace"))
            except (LookupError, AttributeError):
                pass
    texto = re.sub(r"<[^>]+>", " ", " ".join(textos))
    if not destinatarios:
        # Gmail/Outlook em português: "Sua mensagem não foi entregue a fulano@x.com.br porque..."
        destinatarios = _EMAIL.findall(texto)
    referencias = re.findall(r"<[^<>\s]+>", (msg.get("In-Reply-To") or "") + " " + (msg.get("References") or ""))
    junto = f"{status} {diagnostico} {texto}"
    if status.startswith("4") or (not status.startswith("5") and _TEMPORARIO.search(junto)):
        permanente = False
    else:
        permanente = status.startswith("5") or bool(_PERMANENTE.search(junto))
    motivo = _motivo(status, diagnostico, texto, permanente)
    vistos = []
    for d in destinatarios:
        d = d.lower().strip(".")
        if d not in vistos and not _REMETENTE_DEVOLUCAO.search(d):
            vistos.append(d)
    return {"destinatarios": vistos, "permanente": permanente, "motivo": motivo,
            "ids_originais": [i[:120] for i in ids_originais + referencias]}


def _motivo(status: str, diagnostico: str, texto: str, permanente: bool) -> str:
    t = f"{diagnostico} {texto}".lower()
    if re.search(r"dom[íi]nio|domain|dns|nxdomain", t) and re.search(r"n[ãa]o|not|couldn|exist", t):
        return "o domínio do e-mail não existe (devolvido pelo servidor)"
    if not permanente:
        return "entrega temporariamente recusada (ex.: caixa cheia)"
    return "o endereço não existe (devolvido pelo servidor)"
