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


def responder_automaticamente(db, lead: Lead, canal: str, analise: dict, conexao: str | None = None,
                              em_resposta_a: str = "", assunto: str = "", conta_email=None) -> bool:
    """Envia a resposta da SDR (ex.: "vou passar para o time comercial") quando o canal permite.
    WhatsApp: só dentro da janela de 24 h aberta pela mensagem do lead (regra da Meta)."""
    from . import mensagens

    texto = analise.get("resposta_sugerida", "")
    if ler_config(db, "sdr_resposta_automatica") != "1" or not texto or not sdr.texto_seguro(texto):
        return False
    if sdr.com_humano(lead) or sdr.parceiro_do_lead(db, lead):
        return False  # alguém da equipe conduz a conversa: a IA não fala no meio
    from . import empresas_novas

    if empresas_novas.e_lead_de_venda(lead):
        return False  # venda para empresa nova: quem responde é o time, não a SDR de parcerias
    if canal == "email" and lead.email_invalido:
        return False  # e-mail que não existe: responder só gera outra devolução
    from datetime import timedelta

    from sqlalchemy import select

    from .banco import agora
    from .modelos import Mensagem

    if db.execute(select(Mensagem.id).where(Mensagem.lead_id == lead.id, Mensagem.angulo == "resposta",
                                            Mensagem.criado_em >= agora() - timedelta(hours=24)).limit(1)).first():
        return False  # a SDR responde 1 vez por dia, no máximo: nunca entra em conversa sem fim (ex.: com robô)
    try:
        if canal == "email" and lead.email and email_smtp.configurado():
            assunto = assunto.strip()
            assunto = assunto if assunto.lower().startswith("re:") else (f"Re: {assunto}" if assunto
                                                                          else "Re: parceria MS Certificação Digital")
            id_externo = email_smtp.enviar(lead.email, assunto[:200], texto, com_rodape=False, conta=conta_email,
                                           em_resposta_a="" if em_resposta_a.startswith("sem-id:") else em_resposta_a)
        elif canal == "whatsapp" and lead.whatsapp and whatsapp_cloud.configurado():
            id_externo = whatsapp_cloud.enviar_texto(lead.whatsapp, texto)
        elif canal == "whatsapp" and (lead.whatsapp or lead.telefone) and whatsapp_leads.configurado():
            # Resposta a quem acabou de escrever: sai na frente na fila do WhatsApp Leads, pelo mesmo número
            # em que o lead escreveu (ou pelo número do responsável pelo lead).
            from . import conexoes

            if not conexao:
                try:
                    conexao = conexoes.para_enviar(db, conexoes.responsavel(db, lead))
                except conexoes.SemNumero:
                    return False
            if mensagens.limite_do_numero(db, conexao):
                return False  # resposta automática também respeita o limite diário do número
            id_externo = str(whatsapp_leads.enviar(lead.whatsapp or lead.telefone, lead.responsavel or lead.empresa,
                                                   texto, resposta=True, db=db, conexao=conexao))
            msg = mensagens.registrar(db, lead.id, canal, texto, None, modo="whatsapp-leads", status="na_fila",
                                      id_externo=id_externo, categoria_id=lead.categoria_id, angulo="resposta")
            msg.conexao = conexao
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
    """Respostas por e-mail → IA SDR. Acha o lead pelo remetente ou pelo e-mail nosso que ele respondeu
    (In-Reply-To/References: vale quando um colega do lead responde de outro endereço)."""
    from datetime import datetime, timedelta

    from .banco import agora, gravar_config
    from .modelos import Mensagem

    from . import contas_email

    with sessao() as db:
        contas = [(c.id, max(c.criado_em, datetime(2000, 1, 1))) for c in contas_email.para_ler(db)]
    if not contas:
        return 0
    with sessao() as db:
        try:
            desde = datetime.fromisoformat(ler_config(db, "imap_ler_desde"))
        except ValueError:  # 1ª leitura neste formato: começa agora (as respostas antigas já foram tratadas)
            desde = agora().replace(microsecond=0)
            gravar_config(db, "imap_ler_desde", desde.isoformat())
        emails = _EmailsDeLeads()  # pergunta só pelos remetentes que chegaram (antes: todos os e-mails a cada 5 min)
        enviados = dict(db.execute(select(Mensagem.id_externo, Mensagem.lead_id).where(
            Mensagem.canal == "email", Mensagem.direcao == "saida", Mensagem.id_externo != "",
            Mensagem.lead_id.is_not(None), Mensagem.criado_em >= agora() - timedelta(days=120))).all())
        ja_processados = {i for (i,) in db.execute(select(Mensagem.id_externo).where(
            Mensagem.canal == "email", Mensagem.direcao == "entrada", Mensagem.id_externo != "",
            Mensagem.criado_em >= agora() - timedelta(days=email_imap.DIAS_DE_LEITURA + 7)))}
    total = 0
    for conta_id, criada_em in contas:
        with sessao() as db:
            conta = db.get(contas_email.ContaEmail, conta_id)
            if conta is not None:
                db.expunge(conta)  # usada fora desta sessão (só leitura dos dados de acesso)
        if conta is None:
            continue
        inicio = desde if conta.principal else max(desde, criada_em)  # conta nova: só o que chegou depois dela
        # Devoluções PRIMEIRO: o e-mail inexistente fica marcado (e a campanha para ele é cancelada) antes de
        # qualquer resposta ser tratada.
        try:
            _ler_devolucoes(conta, enviados)
        except Exception:  # noqa: BLE001 — devolução com problema não pode parar a leitura das respostas
            log.exception("Erro ao ler as devoluções de e-mail")
        total += _ler_caixa(conta, emails, enviados, ja_processados, inicio)
    return total


DIAS_DEVOLUCOES_1A_VEZ = 60  # na primeira leitura, pega também as devoluções antigas que já estão na caixa


def _ler_devolucoes(conta, enviados: dict) -> int:
    """"Endereço não encontrado" e afins → o e-mail do lead fica marcado como inexistente e sai da campanha."""
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from . import contas_email, email_validacao
    from .banco import agora, gravar_config

    marca = "devolucoes_lidas:" + contas_email.chave(conta)
    with sessao() as db:
        ja_leu = ler_config(db, marca)
    desde = agora() - timedelta(days=email_imap.DIAS_DE_LEITURA if ja_leu else DIAS_DEVOLUCOES_1A_VEZ)
    marcados = 0
    for d in email_imap.ler_devolucoes(desde, conta=conta):
        if not d["permanente"]:
            continue  # caixa cheia, servidor ocupado: o próximo envio pode dar certo
        with sessao() as db:
            leads = []
            if d["destinatarios"]:
                leads = list(db.execute(select(Lead).where(
                    func.lower(Lead.email).in_(d["destinatarios"]))).scalars())
            if not leads:
                ids = {enviados[i] for i in d["ids_originais"] if i in enviados}
                leads = [lead for lead in (db.get(Lead, i) for i in ids) if lead]
                if d["destinatarios"]:  # achou pelo e-mail enviado, mas o endereço citado é outro: não arrisca
                    leads = [lead for lead in leads if lead.email.lower() in d["destinatarios"]]
            for lead in leads:
                if lead.email_invalido and (lead.email_conferido or "") == lead.email:
                    continue
                email_validacao.marcar_invalido(db, lead, d["motivo"])
                marcados += 1
    with sessao() as db:
        gravar_config(db, marca, datetime.now().replace(microsecond=0).isoformat())
    if marcados:
        log.info("Devoluções: %s e-mails de leads marcados como inexistentes", marcados)
    return marcados


class _EmailsDeLeads:
    """"remetente in emails": o e-mail é de algum lead? Pergunta ao banco só pelos remetentes que aparecem na caixa
    (antes vinham todos os e-mails de leads a cada leitura: 3 milhões de linhas em 3 semanas, 14/11/2026)."""

    def __init__(self):
        self._sabidos: dict[str, bool] = {}

    def __contains__(self, email) -> bool:
        email = (email or "").strip().lower()
        if not email:
            return False
        if email not in self._sabidos:
            with sessao() as db:
                self._sabidos[email] = db.execute(
                    select(Lead.id).where(Lead.chave_email == email).limit(1)).first() is not None
        return self._sabidos[email]


def _ler_caixa(conta, emails, enviados: dict, ja_processados: set[str], desde) -> int:
    total = 0
    for item in email_imap.ler_respostas(emails, set(enviados), ja_processados, desde, conta=conta):
        ja_processados.add(item["message_id"])  # o mesmo e-mail em duas caixas é tratado uma vez só
        with sessao() as db:
            lead = db.execute(select(Lead).where(Lead.chave_email == item["de"])).scalars().first()
            if lead is None:
                lead_id = next((enviados[i] for i in item["responde_a"] if i in enviados), None)
                lead = db.get(Lead, lead_id) if lead_id else None
            if not lead:
                continue
            from . import email_validacao

            if email_validacao.texto_de_devolucao(item["texto"]):
                continue  # devolução ("Endereço não encontrado"): não é resposta (ver _ler_devolucoes)
            if not item["texto"]:
                # e-mail sem texto (só anexo): fica registrado (não volta na próxima leitura) e avisa quem cuida
                from . import mensagens

                entrada = mensagens.registrar(db, lead.id, "email", "[e-mail sem texto, só anexo]", None,
                                              status="recebida", id_externo=item["message_id"])
                entrada.direcao = "entrada"
                sdr.notificar(db, lead, f"{lead.empresa} mandou um e-mail sem texto (só anexo): confira na caixa "
                                        "de e-mail", f"/leads/{lead.id}")
                continue
            analise = sdr.processar_resposta(db, lead, item["texto"], "email", id_externo=item["message_id"])
            responder_automaticamente(db, lead, "email", analise, em_resposta_a=item["message_id"],
                                      assunto=item["assunto"], conta_email=conta)
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


def _passo(nome: str, funcao) -> None:
    """Roda uma parte da rodada. Erro numa parte não para as outras e conta para os avisos por e-mail
    (3 falhas seguidas = aviso; app/alertas.py)."""
    from . import alertas

    try:
        funcao()
    except Exception as erro:  # noqa: BLE001
        log.exception("Erro na %s", alertas.NOMES_ROTINAS.get(nome, nome))
        alertas.falhou(nome, erro)
    else:
        alertas.funcionou(nome)


def _fila_email() -> None:
    with sessao() as db:
        resultado = campanhas.processar_fila(db)
        if resultado["enviados"]:
            log.info("Fila: %s e-mails enviados", resultado["enviados"])


def _fila_whatsapp() -> None:
    with sessao() as db:
        r = campanhas.processar_fila_whatsapp(db)
        if r["enviados"]:
            log.info("Fila do WhatsApp: %s mensagens para contatos que já conversaram", r["enviados"])


def _sincronizar_whatsapp() -> None:
    with sessao() as db:
        r = sdr.sincronizar_whatsapp_conectado(db)
        if r["respostas"]:
            log.info("WhatsApp conectado: %s respostas de parceiros processadas", r["respostas"])


def _ler_emails() -> None:
    lidas = ler_respostas_por_email()
    if lidas:
        log.info("Respostas por e-mail processadas: %s", lidas)


def _empresas_novas() -> None:
    from . import empresas_novas

    r = empresas_novas.rodada_diaria()
    if r:
        log.info("Empresas novas: %s", r)


def _renovacao() -> None:
    from . import renovacao

    r = renovacao.rodada_diaria()
    if r:
        log.info("Renovação: %s", r)


def _rotina_hora() -> None:
    from . import renovacao, reservas
    from .vendas_servico import processar_vencimentos

    with sessao() as db:
        processar_vencimentos(db)
        renovacao.encerrar_toques(db)  # aviso de renovação de certificado vencido ou renovado não sai
        renovacao.limpar_artes(db)  # as artes do aviso ficam só uns dias (já foram no WhatsApp e no e-mail)
        campanhas.finalizar_cadencias(db)
    with sessao() as db:
        reservas.preencher_reservas_antigas(db)  # só na primeira vez
        liberadas = reservas.liberar_vencidas(db)
        if liberadas:
            log.info("Reservas: %s empresas voltaram para a base (60 dias sem mudança)", liberadas)
    from . import ars

    ars.preencher_novos()  # white label, Fase 1: linhas novas ganham a AR (só depois do migrar_ar.py aplicar)


def rodada(numero: int | None) -> None:
    """Uma rodada do relógio (chamado a cada minuto; na nuvem, pelo agendador em /api/cron)."""
    from . import alertas

    if numero is None:
        alertas.marcar_rodada()  # avisa se o agendador tinha ficado parado mais de 30 minutos
    _passo("fila_email", _fila_email)
    _passo("fila_whatsapp", _fila_whatsapp)
    _passo("sincronizar_whatsapp", _sincronizar_whatsapp)
    if _na_vez(numero, "ultima_leitura_email", 5):
        _passo("ler_emails", _ler_emails)
    if _na_vez(numero, "ultima_busca_empresas_novas", 15):
        _passo("empresas_novas", _empresas_novas)
    if _na_vez(numero, "ultima_rodada_renovacao", 15):
        _passo("renovacao", _renovacao)
    if _na_vez(numero, "ultima_rotina_hora", 60):
        _passo("rotina_hora", _rotina_hora)
    if alertas.ligado() and _na_vez(numero, "ultima_verificacao_alertas", 5):
        try:
            alertas.verificar()  # e-mail para os administradores quando algo para (e quando volta)
        except Exception:  # noqa: BLE001
            log.exception("Erro ao conferir os avisos")
