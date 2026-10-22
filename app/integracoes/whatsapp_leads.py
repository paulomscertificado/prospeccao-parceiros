"""WhatsApp conectado pelo sistema "WhatsApp Leads" (pasta whatsapp-leads, no mesmo computador).

O WhatsApp Leads é o dono da conexão (QR code ou modo teste), da fila com pausas anti-bloqueio,
do horário e do limite diário. Aqui só conversamos com a API local dele:
- status(): conectado? número? quantas mensagens hoje?
- enviar(): coloca UMA mensagem na fila dele (sempre por clique de uma pessoa, ou resposta a quem escreveu);
- novidades(): respostas dos parceiros, status dos envios e quem pediu para sair.

Configuração: nada, se as duas pastas estiverem lado a lado (o token é lido de
whatsapp-leads/dados/token_integracao.txt). Em outro servidor: WHATSAPP_LEADS_URL e WHATSAPP_LEADS_TOKEN no .env.

Sistema na nuvem ("ponte", config.WHATSAPP_PONTE): a nuvem não alcança o computador da MS. Então é o
WhatsApp Leads que chama a nuvem a cada 30 segundos (rotas /api/ponte/* em app/rotas/api.py):
- entrega o status do WhatsApp e leva as mensagens que estão esperando (tabela ponte_whatsapp);
- devolve o id de cada mensagem na fila de lá e as novidades (respostas, status, quem saiu).
Senha da ponte: WHATSAPP_PONTE_TOKEN aqui = PROSPECCAO_TOKEN no .env do WhatsApp Leads.
"""

import json
import logging
import time
from datetime import datetime

import httpx

from .. import config

log = logging.getLogger(__name__)
_cache = {"em": 0.0, "status": None}


class ErroWhatsAppLeads(Exception):
    pass


def token() -> str:
    if config.WHATSAPP_LEADS_TOKEN:
        return config.WHATSAPP_LEADS_TOKEN
    arquivo = config.WHATSAPP_LEADS_PASTA / "dados" / "token_integracao.txt"
    try:
        return arquivo.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def configurado() -> bool:
    if config.WHATSAPP_PONTE:
        return bool(config.WHATSAPP_PONTE_TOKEN)
    return bool(token())


SEGUNDOS_SEM_SINAL = 180  # o computador avisa a cada 30 s; 3 min sem aviso = desligado


def _status_da_ponte(db=None) -> dict:
    from ..banco import ler_config, sessao

    if db is not None:
        texto = ler_config(db, "wl_status")
    else:
        with sessao() as nova:
            texto = ler_config(nova, "wl_status")
    try:
        dados = json.loads(texto) if texto else {}
        visto = datetime.fromisoformat(dados.pop("visto_em"))
    except (ValueError, KeyError, TypeError):
        return {"disponivel": False, "conectado": False,
                "erro": "O computador com o WhatsApp Leads ainda não se conectou ao sistema na nuvem."}
    if (datetime.now() - visto).total_seconds() > SEGUNDOS_SEM_SINAL:
        return {"disponivel": False, "conectado": False,
                "erro": f"O computador com o WhatsApp Leads está desligado ou sem internet (último sinal: {visto:%d/%m %H:%M})."}
    return {"disponivel": True, **dados, "erro": ""}


def _pedir(metodo: str, caminho: str, **kw) -> dict:
    chave = token()
    if not chave:
        raise ErroWhatsAppLeads("O WhatsApp Leads ainda não foi ligado neste computador (abra o iniciar.bat dele uma vez).")
    try:
        r = httpx.request(metodo, config.WHATSAPP_LEADS_URL + caminho, headers={"x-token": chave}, timeout=10, **kw)
    except httpx.HTTPError:
        raise ErroWhatsAppLeads("O WhatsApp Leads está fechado. Abra o iniciar.bat dele e conecte o WhatsApp.") from None
    if r.status_code == 403:
        raise ErroWhatsAppLeads("O WhatsApp Leads recusou a conexão (token diferente). Veja docs/configuracao.md.")
    try:
        dados = r.json()
    except ValueError:
        raise ErroWhatsAppLeads(f"Resposta inesperada do WhatsApp Leads (erro {r.status_code}).") from None
    if r.status_code >= 400:
        raise ErroWhatsAppLeads(dados.get("erro", f"erro {r.status_code}").capitalize() + ".")
    return dados


def status(usar_cache: bool = True) -> dict:
    """{"disponivel", "conectado", "estado", "numero", "enviadas_hoje", "limite_diario", "erro"}."""
    if usar_cache and _cache["status"] is not None and time.monotonic() - _cache["em"] < 15:
        return _cache["status"]
    if not configurado():
        resultado = {"disponivel": False, "conectado": False, "erro": "WhatsApp Leads não encontrado neste computador."
                     if not config.WHATSAPP_PONTE else "Falta WHATSAPP_PONTE_TOKEN nas variáveis do sistema."}
    elif config.WHATSAPP_PONTE:
        resultado = _status_da_ponte()
    else:
        try:
            resultado = {"disponivel": True, **_pedir("GET", "/api/integracao/status"), "erro": ""}
        except ErroWhatsAppLeads as erro:
            resultado = {"disponivel": False, "conectado": False, "erro": str(erro)}
    _cache.update(em=time.monotonic(), status=resultado)
    return resultado


def enviar(telefone: str, nome: str, texto: str, resposta: bool = False, db=None) -> str:
    """Coloca a mensagem na fila do WhatsApp Leads. Devolve o id da mensagem lá
    (na ponte: "p" + id da espera aqui; vira o id de lá quando o computador confirmar)."""
    if config.WHATSAPP_PONTE:
        # db: a sessão de quem chamou (a mensagem entra na mesma transação do registro do envio)
        situacao = _status_da_ponte(db) if config.WHATSAPP_PONTE_TOKEN else status(usar_cache=False)
        if not situacao["disponivel"]:
            raise ErroWhatsAppLeads(situacao["erro"])
        from ..banco import sessao
        from ..modelos import PonteWhatsApp

        item = PonteWhatsApp(telefone=telefone, nome=nome[:200], texto=texto, resposta=resposta)
        if db is not None:
            db.add(item)
            db.flush()
            return f"p{item.id}"
        with sessao() as nova:
            nova.add(item)
            nova.flush()
            return f"p{item.id}"
    dados = _pedir("POST", "/api/integracao/enviar",
                   json={"telefone": telefone, "nome": nome, "texto": texto, "resposta": resposta})
    _cache["status"] = None
    return str(int(dados["id"]))


def novidades(desde_id: int) -> dict:
    return _pedir("GET", f"/api/integracao/novidades?desde={int(desde_id)}")
