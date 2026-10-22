"""WhatsApp Cloud API (oficial da Meta).

Regras da Meta: para iniciar conversa com quem não falou com você nas últimas 24 horas, só é permitido
enviar TEMPLATES aprovados no Gerenciador do WhatsApp. Por isso o envio usa o "nome_meta" do template.
O sistema envia UMA mensagem por clique (nunca em massa) e respeita opt-out, limite diário e frequência.
"""

import hashlib
import hmac

import httpx

from .. import config, util


class ErroWhatsApp(Exception):
    pass


def configurado() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def enviar_template(telefone: str, nome_template: str, parametros: list[str], idioma: str = "pt_BR") -> str:
    """Envia um template aprovado. Devolve o id da mensagem na Meta."""
    if not configurado():
        raise ErroWhatsApp("A API oficial do WhatsApp não está configurada (veja docs/configuracao.md).")
    numero = util.normalizar_telefone(telefone)
    if not numero:
        raise ErroWhatsApp("Telefone inválido para WhatsApp.")
    if not nome_template:
        raise ErroWhatsApp("Este template não tem o nome do template aprovado na Meta. Preencha em Cadências > Templates.")
    corpo = {
        "messaging_product": "whatsapp", "to": "55" + numero, "type": "template",
        "template": {"name": nome_template, "language": {"code": idioma}},
    }
    if parametros:
        corpo["template"]["components"] = [{"type": "body", "parameters": [
            {"type": "text", "text": p or "-"} for p in parametros]}]
    url = f"https://graph.facebook.com/{config.WHATSAPP_API_VERSAO}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    try:
        r = httpx.post(url, json=corpo, timeout=30, headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"})
    except httpx.HTTPError:
        raise ErroWhatsApp("Sem conexão com a API do WhatsApp. Confira a internet.") from None
    if r.status_code >= 400:
        try:
            detalhe = r.json().get("error", {}).get("message", "")
        except ValueError:
            detalhe = r.text[:200]
        raise ErroWhatsApp(f"A Meta recusou o envio: {detalhe}")
    return (r.json().get("messages") or [{}])[0].get("id", "")


def enviar_texto(telefone: str, texto: str) -> str:
    """Mensagem livre: a Meta só permite dentro de 24 h depois que o contato escreveu (janela de atendimento)."""
    if not configurado():
        raise ErroWhatsApp("A API oficial do WhatsApp não está configurada.")
    numero = util.normalizar_telefone(telefone)
    url = f"https://graph.facebook.com/{config.WHATSAPP_API_VERSAO}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    try:
        r = httpx.post(url, timeout=30, headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
                       json={"messaging_product": "whatsapp", "to": "55" + numero, "type": "text",
                             "text": {"body": texto[:4000]}})
    except httpx.HTTPError:
        raise ErroWhatsApp("Sem conexão com a API do WhatsApp.") from None
    if r.status_code >= 400:
        raise ErroWhatsApp(f"A Meta recusou o envio: {r.text[:200]}")
    return (r.json().get("messages") or [{}])[0].get("id", "")


def assinatura_valida(corpo: bytes, assinatura: str) -> bool:
    """Confere o cabeçalho X-Hub-Signature-256 dos webhooks (exige WHATSAPP_APP_SECRET)."""
    if not config.WHATSAPP_APP_SECRET:
        return False
    esperado = "sha256=" + hmac.new(config.WHATSAPP_APP_SECRET.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, assinatura or "")


def ler_webhook(dados: dict) -> tuple[list[dict], list[dict]]:
    """Separa (mensagens recebidas, atualizações de status) do JSON do webhook."""
    recebidas, status = [], []
    for entrada in dados.get("entry", []):
        for mudanca in entrada.get("changes", []):
            valor = mudanca.get("value", {})
            for m in valor.get("messages", []):
                texto = (m.get("text") or {}).get("body") or (m.get("button") or {}).get("text") or f"[{m.get('type')}]"
                recebidas.append({"de": m.get("from", ""), "texto": texto, "id": m.get("id", "")})
            for s in valor.get("statuses", []):
                status.append({"id": s.get("id", ""), "status": s.get("status", "")})
    return recebidas, status
