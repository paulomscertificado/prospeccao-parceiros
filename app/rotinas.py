"""Rotinas automáticas (rodam sozinhas enquanto o sistema está aberto).

- a cada minuto: fila de e-mails das campanhas aprovadas (com horário e limites) e sincronização com o
  WhatsApp conectado (WhatsApp Leads): respostas dos parceiros, status dos envios e opt-outs;
- a cada 5 minutos: respostas por e-mail (IMAP) → IA SDR classifica e faz o handoff;
- a cada hora: alertas de vencimento e fim das cadências sem resposta.
"""

import logging

from sqlalchemy import select

from . import campanhas, sdr
from .banco import ler_config, sessao
from .integracoes import email_imap, email_smtp, whatsapp_cloud, whatsapp_leads
from .modelos import Lead

log = logging.getLogger(__name__)


def responder_automaticamente(db, lead: Lead, canal: str, analise: dict) -> bool:
    """Envia a resposta da SDR (ex.: "vou passar para o time comercial") quando o canal permite.
    WhatsApp: só dentro da janela de 24 h aberta pela mensagem do lead (regra da Meta)."""
    from . import mensagens

    texto = analise.get("resposta_sugerida", "")
    if ler_config(db, "sdr_resposta_automatica") != "1" or not texto or not sdr.texto_seguro(texto):
        return False
    try:
        if canal == "email" and lead.email and email_smtp.configurado():
            id_externo = email_smtp.enviar(lead.email, "Re: parceria MS Certificação Digital", texto, com_rodape=False)
        elif canal == "whatsapp" and lead.whatsapp and whatsapp_cloud.configurado():
            id_externo = whatsapp_cloud.enviar_texto(lead.whatsapp, texto)
        elif canal == "whatsapp" and (lead.whatsapp or lead.telefone) and whatsapp_leads.configurado():
            # Resposta a quem acabou de escrever: sai na frente na fila do WhatsApp Leads.
            id_externo = str(whatsapp_leads.enviar(lead.whatsapp or lead.telefone, lead.responsavel or lead.empresa,
                                                   texto, resposta=True, db=db))
            mensagens.registrar(db, lead.id, canal, texto, None, modo="whatsapp-leads", status="na_fila",
                                id_externo=id_externo, categoria_id=lead.categoria_id, angulo="resposta")
            return True
        else:
            return False
    except (email_smtp.ErroEmail, whatsapp_cloud.ErroWhatsApp, whatsapp_leads.ErroWhatsAppLeads) as erro:
        log.warning("Resposta automática falhou (%s): %s", lead.empresa, erro)
        return False
    mensagens.registrar(db, lead.id, canal, texto, None, modo="api", status="enviada", id_externo=id_externo,
                        categoria_id=lead.categoria_id, angulo="resposta")
    return True


def ler_respostas_por_email() -> int:
    if not email_imap.configurado():
        return 0
    with sessao() as db:
        emails = {e for (e,) in db.execute(select(Lead.chave_email).where(Lead.chave_email != "")) if e}
    total = 0
    for item in email_imap.ler_respostas(emails):
        with sessao() as db:
            lead = db.execute(select(Lead).where(Lead.chave_email == item["de"])).scalars().first()
            if not lead or not item["texto"]:
                continue
            analise = sdr.processar_resposta(db, lead, item["texto"], "email")
            responder_automaticamente(db, lead, "email", analise)
            total += 1
    return total


def _na_vez(numero: int | None, chave: str, minutos: int) -> bool:
    """Neste computador: conta as rodadas. Na nuvem (numero=None): compara com a última vez, gravada no banco,
    porque o agendador pode pular um minuto."""
    if numero is not None:
        return numero % minutos == 0
    from datetime import datetime, timedelta

    from .banco import gravar_config, ler_config

    with sessao() as db:
        try:
            ultima = datetime.fromisoformat(ler_config(db, chave))
        except ValueError:
            ultima = datetime(2000, 1, 1)
        if datetime.now() - ultima < timedelta(minutes=minutos, seconds=-20):
            return False
        gravar_config(db, chave, datetime.now().replace(microsecond=0).isoformat())
    return True


def rodada(numero: int | None) -> None:
    """Uma rodada do relógio (chamado a cada minuto; na nuvem, pelo agendador em /api/cron)."""
    try:
        with sessao() as db:
            resultado = campanhas.processar_fila(db)
            if resultado["enviados"]:
                log.info("Fila: %s e-mails enviados", resultado["enviados"])
    except Exception:  # noqa: BLE001
        log.exception("Erro na fila de envio")
    try:
        with sessao() as db:
            r = campanhas.processar_fila_whatsapp(db)
            if r["enviados"]:
                log.info("Fila do WhatsApp: %s mensagens para contatos que já conversaram", r["enviados"])
    except Exception:  # noqa: BLE001
        log.exception("Erro na fila de WhatsApp")
    try:
        with sessao() as db:
            r = sdr.sincronizar_whatsapp_conectado(db)
            if r["respostas"]:
                log.info("WhatsApp conectado: %s respostas de parceiros processadas", r["respostas"])
    except Exception:  # noqa: BLE001
        log.exception("Erro ao sincronizar com o WhatsApp Leads")
    if _na_vez(numero, "ultima_leitura_email", 5):
        try:
            lidas = ler_respostas_por_email()
            if lidas:
                log.info("Respostas por e-mail processadas: %s", lidas)
        except Exception:  # noqa: BLE001
            log.exception("Erro ao ler respostas por e-mail")
    if _na_vez(numero, "ultima_rotina_hora", 60):
        from .vendas_servico import processar_vencimentos

        try:
            with sessao() as db:
                processar_vencimentos(db)
                campanhas.finalizar_cadencias(db)
        except Exception:  # noqa: BLE001
            log.exception("Erro na rotina de hora em hora")
