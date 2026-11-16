"""WhatsApp Cloud API (oficial da Meta, Plataforma do WhatsApp Business).

Regras da Meta: para iniciar conversa com quem não falou com você nas últimas 24 horas, só é permitido
enviar MODELOS (templates) aprovados no Gerenciador do WhatsApp. Texto livre só dentro da janela de 24 h depois da
última mensagem do contato.

Duas formas de usar:
- por AR (app/whatsapp_oficial.py, tela Configurações > WhatsApp > "API oficial da Meta"): as funções com
  `phone_number_id` e `token` explícitos (consultar_numero, enviar_modelo, enviar_texto_por);
- a antiga, por variável (WHATSAPP_TOKEN e WHATSAPP_PHONE_NUMBER_ID): configurado(), enviar_template(),
  enviar_texto() — botão "Enviar pela API" da ficha do lead.
"""

import hashlib
import hmac

import httpx

from .. import config, util


class ErroWhatsApp(Exception):
    pass


CAMPOS_DO_NUMERO = "display_phone_number,verified_name,quality_rating,whatsapp_business_manager_messaging_limit,name_status"


def _url(caminho: str, versao: str | None = None) -> str:
    return f"https://graph.facebook.com/{versao or config.WHATSAPP_API_VERSAO}/{caminho}"


def _destino(telefone: str) -> str:
    """Telefone brasileiro como a Meta pede: 55 + DDD + número, celular sempre com o 9 da frente."""
    numero = util.com_nono_digito(telefone or "")
    if not numero:
        raise ErroWhatsApp("Telefone inválido para WhatsApp (digite com DDD, ex.: 81 99999-0000).")
    return "55" + numero


def _erro_da_meta(r: httpx.Response) -> str:
    try:
        erro = r.json().get("error") or {}
    except ValueError:
        return r.text[:200]
    detalhe = (erro.get("error_data") or {}).get("details") or ""
    return " ".join(x for x in (erro.get("message", ""), detalhe) if x)[:400] or f"erro {r.status_code}"


def _pedir(metodo: str, caminho: str, token: str, versao: str | None = None, **kw) -> dict:
    if not token:
        raise ErroWhatsApp("Falta o token da API oficial (Configurações > WhatsApp > API oficial da Meta).")
    try:
        r = httpx.request(metodo, _url(caminho, versao), timeout=30, headers={"Authorization": f"Bearer {token}"}, **kw)
    except httpx.HTTPError:
        raise ErroWhatsApp("Sem conexão com a API do WhatsApp. Confira a internet.") from None
    if r.status_code >= 400:
        raise ErroWhatsApp(f"A Meta recusou: {_erro_da_meta(r)}")
    try:
        return r.json()
    except ValueError:
        return {}


def consultar_numero(phone_number_id: str, token: str, versao: str | None = None) -> dict:
    """Dados do número na Meta: número, nome verificado, qualidade e limite de mensagens (teste de conexão)."""
    return _pedir("GET", phone_number_id, token, versao, params={"fields": CAMPOS_DO_NUMERO})


def contas_do_token(token: str, versao: str | None = None) -> list[str]:
    """IDs das contas do WhatsApp Business que o token alcança (as permissões granulares do próprio token): assim a
    pessoa não precisa procurar o ID da conta na Meta."""
    dados = _pedir("GET", "debug_token", token, versao, params={"input_token": token})
    ids: list[str] = []
    for escopo in (dados.get("data") or {}).get("granular_scopes") or []:
        if escopo.get("scope") in ("whatsapp_business_management", "whatsapp_business_messaging"):
            ids += [str(i) for i in escopo.get("target_ids") or [] if str(i) not in ids]
    return ids


def inscrever_app(waba_id: str, token: str, versao: str | None = None) -> bool:
    """Liga o app do token à conta do WhatsApp Business (o que o "Início rápido" da Meta faria): sem isso, as
    respostas e a situação das mensagens da conta não chegam ao webhook do app."""
    dados = _pedir("POST", f"{waba_id}/subscribed_apps", token, versao)
    return bool(dados.get("success", True))


def enviar_modelo(phone_number_id: str, token: str, telefone: str, nome_modelo: str, idioma: str = "pt_BR",
                  parametros: list[str] | None = None, versao: str | None = None) -> str:
    """Envia um modelo aprovado. Devolve o id da mensagem na Meta (wamid)."""
    if not nome_modelo:
        raise ErroWhatsApp("Falta o nome do modelo aprovado na Meta.")
    corpo = {"messaging_product": "whatsapp", "to": _destino(telefone), "type": "template",
             "template": {"name": nome_modelo, "language": {"code": idioma or "pt_BR"}}}
    if parametros:
        corpo["template"]["components"] = [{"type": "body", "parameters": [
            {"type": "text", "text": p or "-"} for p in parametros]}]
    dados = _pedir("POST", f"{phone_number_id}/messages", token, versao, json=corpo)
    return (dados.get("messages") or [{}])[0].get("id", "")


def enviar_texto_por(phone_number_id: str, token: str, telefone: str, texto: str, versao: str | None = None) -> str:
    """Mensagem livre: a Meta só permite dentro de 24 h depois que o contato escreveu (janela de atendimento)."""
    dados = _pedir("POST", f"{phone_number_id}/messages", token, versao,
                   json={"messaging_product": "whatsapp", "to": _destino(telefone), "type": "text",
                         "text": {"body": texto[:4000]}})
    return (dados.get("messages") or [{}])[0].get("id", "")


# ---------------------------------------------------------------- forma antiga (variáveis WHATSAPP_*)

def configurado() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def enviar_template(telefone: str, nome_template: str, parametros: list[str], idioma: str = "pt_BR") -> str:
    """Envia um template aprovado pelo número das variáveis. Devolve o id da mensagem na Meta."""
    if not configurado():
        raise ErroWhatsApp("A API oficial do WhatsApp não está configurada (veja docs/configuracao.md).")
    if not util.normalizar_telefone(telefone):
        raise ErroWhatsApp("Telefone inválido para WhatsApp.")
    if not nome_template:
        raise ErroWhatsApp("Este template não tem o nome do template aprovado na Meta. Preencha em Cadências > Templates.")
    return enviar_modelo(config.WHATSAPP_PHONE_NUMBER_ID, config.WHATSAPP_TOKEN, telefone, nome_template, idioma,
                         parametros)


def enviar_texto(telefone: str, texto: str) -> str:
    if not configurado():
        raise ErroWhatsApp("A API oficial do WhatsApp não está configurada.")
    return enviar_texto_por(config.WHATSAPP_PHONE_NUMBER_ID, config.WHATSAPP_TOKEN, telefone, texto)


# ---------------------------------------------------------------- webhook

def assinatura_confere(corpo: bytes, assinatura: str, segredo: str) -> bool:
    """Confere o cabeçalho X-Hub-Signature-256 dos webhooks com a chave secreta do app."""
    if not segredo:
        return False
    esperado = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, assinatura or "")


def assinatura_valida(corpo: bytes, assinatura: str) -> bool:
    """Forma antiga: confere com WHATSAPP_APP_SECRET."""
    return assinatura_confere(corpo, assinatura, config.WHATSAPP_APP_SECRET)


def numeros_do_webhook(dados: dict) -> set[str]:
    """As "Identificações do número de telefone" (phone_number_id) que aparecem no webhook: dizem de qual AR ele é."""
    return {str(((m.get("value") or {}).get("metadata") or {}).get("phone_number_id") or "")
            for e in dados.get("entry", []) for m in e.get("changes", [])} - {""}


def ler_webhook(dados: dict) -> tuple[list[dict], list[dict]]:
    """Separa (mensagens recebidas, atualizações de status) do JSON do webhook. Cada item leva o `numero_id`
    (phone_number_id) do número que recebeu ou mandou; a recebida leva também o nome do contato."""
    recebidas, status = [], []
    for entrada in dados.get("entry", []):
        for mudanca in entrada.get("changes", []):
            valor = mudanca.get("value", {})
            numero_id = str((valor.get("metadata") or {}).get("phone_number_id") or "")
            nomes = {c.get("wa_id", ""): (c.get("profile") or {}).get("name", "") for c in valor.get("contacts", [])}
            for m in valor.get("messages", []):
                texto = ((m.get("text") or {}).get("body") or (m.get("button") or {}).get("text")
                         or ((m.get("interactive") or {}).get("button_reply") or {}).get("title") or f"[{m.get('type')}]")
                recebidas.append({"de": m.get("from", ""), "texto": texto, "id": m.get("id", ""), "numero_id": numero_id,
                                  "nome": nomes.get(m.get("from", ""), "")})
            for s in valor.get("statuses", []):
                erros = s.get("errors") or [{}]
                status.append({"id": s.get("id", ""), "status": s.get("status", ""), "numero_id": numero_id,
                               "erro": (erros[0].get("title") or erros[0].get("message") or "")[:300]})
    return recebidas, status
