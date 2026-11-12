"""Cadências: transformam uma sequência (Dia 1 WhatsApp, Dia 2 ligação...) em tarefas na agenda."""

import random
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import autorizacao, mensagens
from .banco import ler_config
from .leads_servico import historico
from .modelos import Cadencia, Lead, Tarefa, Usuario


def _minutos(hhmm: str, padrao: int) -> int:
    try:
        h, m = hhmm.strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return padrao


FOLGA_MINUTOS = 15  # toque marcado para hoje: pelo menos 15 minutos depois de agora


def hora_natural(db: Session, dia: date | None = None) -> str | None:
    """Horário "quebrado" e diferente para cada mensagem de campanha (ex.: 09:47, 14:13), dentro do horário de envio
    e fora do almoço (12:00–13:30): mensagens em horário redondo, todas juntas, parecem disparo automático.
    dia = hoje: só horários que ainda não passaram; None se o horário de envio de hoje já acabou."""
    from .banco import agora

    inicio = _minutos(ler_config(db, "horario_envio_inicio") or "08:30", 8 * 60 + 30)
    fim = _minutos(ler_config(db, "horario_envio_fim") or "18:00", 18 * 60) - 20  # folga para sair antes do fim
    if fim <= inicio:
        fim = inicio + 60
    if dia is not None and dia <= agora().date():
        if dia < agora().date():
            return None  # dia que já passou
        minimo = agora().hour * 60 + agora().minute + FOLGA_MINUTOS
        if minimo > fim:
            return None  # o horário de envio de hoje já acabou
        if 12 * 60 <= minimo < 13 * 60 + 30 and fim < 13 * 60 + 30:
            return None
        inicio = max(inicio, minimo)
    for _ in range(20):
        minuto = random.randint(inicio, fim)
        if minuto % 5 == 0:
            minuto += random.randint(1, 4)  # nada de 09:00, 10:15, 14:30...
        if not (12 * 60 <= minuto < 13 * 60 + 30) and minuto <= fim + 4:
            return f"{minuto // 60:02d}:{minuto % 60:02d}"
    minuto = inicio + 7 if not (12 * 60 <= inicio + 7 < 13 * 60 + 30) else 13 * 60 + 37
    return f"{minuto // 60:02d}:{minuto % 60:02d}"


def dia_e_hora_futuros(db: Session, dia: date, pular_fds: bool | None = None) -> tuple[date, str]:
    """O dia pedido (ou o próximo, se o horário de envio dele já passou) e um horário natural que ainda não passou."""
    from .banco import agora

    if pular_fds is None:
        pular_fds = ler_config(db, "pular_fim_de_semana") == "1"
    dia = max(dia, agora().date())
    for _ in range(15):
        if pular_fds and dia.weekday() >= 5:
            dia += timedelta(days=1)
            continue
        hora = hora_natural(db, dia)
        if hora:
            return dia, hora
        dia += timedelta(days=1)
    return dia, hora_natural(db) or "09:07"


def aplicar(db: Session, cadencia: Cadencia, leads: list[Lead], usuario: Usuario, inicio: date | None = None,
            campanha_id: int | None = None, mensagens_sdr: dict | None = None, canais: list[str] | None = None,
            status_tarefa: str = "pendente", cta: str = "", tom: str = "consultivo",
            foco_whatsapp: bool = False) -> dict:
    """Cria as tarefas da cadência para cada lead. Pula quem tem opt-out, está encerrado, foi assumido
    por um humano ou já tem uma cadência em andamento.

    Passos com canal "auto" (cadência da IA SDR): o canal sai da prioridade configurada e a mensagem é a
    do ângulo do passo (mensagens_sdr[lead_id][angulo], ou geradas na hora). status_tarefa="rascunho"
    deixa tudo esperando a aprovação da campanha."""
    # Campanha da IA SDR: só e-mail e WhatsApp (ligação é o usuário quem faz, por conta própria)
    da_ia = bool(campanha_id) and mensagens_sdr is not None
    from . import sdr

    mensagens_sdr = mensagens_sdr or {}
    inicio = inicio or date.today()
    pular_fds = ler_config(db, "pular_fim_de_semana") == "1"
    resultado = {"leads": 0, "tarefas": 0, "pulados": []}
    for lead in leads:
        if lead.opt_out or lead.anonimizado:
            resultado["pulados"].append(f"{lead.empresa}: pediu para não ser contatado")
            continue
        if lead.perdido or lead.etapa >= 2:
            resultado["pulados"].append(f"{lead.empresa}: já respondeu ou foi encerrado ({lead.status})")
            continue
        if lead.automacao_pausada:
            resultado["pulados"].append(f"{lead.empresa}: atendimento assumido por uma pessoa")
            continue
        em_andamento = db.execute(select(Tarefa.id).where(
            Tarefa.lead_id == lead.id, Tarefa.tipo == "prospeccao",
            Tarefa.status.in_(["pendente", "rascunho"])).limit(1)).first()
        if em_andamento:
            resultado["pulados"].append(f"{lead.empresa}: já está em uma cadência")
            continue
        responsavel = db.get(Usuario, lead.vendedor_id) if lead.vendedor_id else usuario
        dia_anterior = None
        for passo in cadencia.passos:
            data = inicio + timedelta(days=passo.dia - 1)
            if pular_fds:
                while data.weekday() >= 5 or (dia_anterior and data <= dia_anterior):
                    data += timedelta(days=1)
            if dia_anterior and data < dia_anterior:
                data = dia_anterior  # o toque anterior pulou para outro dia: este não fica antes dele
            hora = passo.hora or "09:00"
            if campanha_id:
                # nunca num horário que já passou: hoje, só daqui a 15 min em diante; sem tempo hoje, amanhã
                data, hora = dia_e_hora_futuros(db, data, pular_fds)
            dia_anterior = data
            canal = passo.canal
            modelos = {}
            canal_extra = ""  # o outro canal do mesmo toque (e-mail E WhatsApp)
            if passo.canal == "auto" or passo.angulo:
                canal = sdr.escolher_canal(db, lead, canais) if passo.canal == "auto" else passo.canal
                if foco_whatsapp and passo.canal == "auto" and lead.whatsapp and "whatsapp" in (canais or []):
                    canal = "whatsapp"  # Empresas novas: o foco é sempre o WhatsApp; e-mail só para quem não tem
                if da_ia and canal not in ("email", "whatsapp"):
                    if "whatsapp" not in (canais or ["whatsapp"]):
                        continue  # campanha só de e-mail e empresa sem e-mail: não entra
                    canal = "whatsapp"  # só fixo: WhatsApp a pesquisar (o time acha o número e cadastra na campanha)
                if lead.id not in mensagens_sdr:
                    mensagens_sdr[lead.id] = sdr.mensagens_por_regras(db, lead, responsavel, cta, tom)
                msg = mensagens_sdr[lead.id].get(passo.angulo or "apresentacao") or {}
                if not msg:  # toque que a IA não escreveu (ex.: pergunta rápida): sai das regras do tom
                    msg = sdr.mensagens_por_regras(db, lead, responsavel, cta, tom).get(passo.angulo) or {}
                assunto = msg.get("assunto", "") if canal == "email" else ""
                corpo = msg.get("email", "") if canal == "email" else msg.get("whatsapp", "")
                modelos = {"mensagem_whatsapp": msg.get("whatsapp", ""), "mensagem_email": msg.get("email", ""),
                           "assunto_email": (msg.get("assunto", "") or "")[:200]}
                # pedido da Maria: campanha com WhatsApp cria a mensagem de WhatsApp para todas as empresas; quem está
                # com o campo WhatsApp em branco fica com ela pronta, esperando cadastrarem o número (não sai antes)
                if (da_ia and canal != "whatsapp" and "whatsapp" in (canais or [])
                        and not (lead.whatsapp or "").strip() and (msg.get("whatsapp") or "").strip()):
                    canal_extra = "whatsapp"
                # pedido da Maria: quem tem WhatsApp e e-mail recebe os dois em cada toque (Empresas novas: só WhatsApp)
                elif (da_ia and canal == "whatsapp" and not foco_whatsapp and "email" in (canais or [])
                        and lead.email and not lead.email_invalido and (msg.get("email") or "").strip()):
                    canal_extra = "email"
            elif da_ia and canal not in ("email", "whatsapp"):
                continue  # campanha da IA só manda e-mail e WhatsApp: ligação/LinkedIn o usuário faz por conta própria
            else:
                template = passo.template or mensagens.template_padrao(db, passo.canal)
                assunto, corpo = mensagens.montar(db, template, lead, responsavel)
            from . import marca

            assunto, corpo = marca.aplicar(assunto, responsavel), marca.aplicar(corpo, responsavel)
            modelos = {k: marca.aplicar(v, responsavel) for k, v in modelos.items()}
            if canal_extra:
                # cada mensagem fica num canal só (sem reserva do outro), para o mesmo toque nunca sair duas vezes
                if canal_extra == "whatsapp":
                    extra = {"assunto": "", "mensagem": modelos["mensagem_whatsapp"],
                             "mensagem_whatsapp": modelos["mensagem_whatsapp"]}
                    modelos["mensagem_whatsapp"] = ""
                else:
                    extra = {"assunto": modelos["assunto_email"], "mensagem": modelos["mensagem_email"],
                             "mensagem_email": modelos["mensagem_email"], "assunto_email": modelos["assunto_email"]}
                    modelos["mensagem_email"] = modelos["assunto_email"] = ""
                db.add(Tarefa(
                    tipo="prospeccao", lead_id=lead.id, passo_id=passo.id, campanha_id=campanha_id,
                    usuario_id=responsavel.id if responsavel else None, canal=canal_extra, data=data,
                    hora=hora, acao=f"Contato por {canal_extra}", angulo=passo.angulo or "", status=status_tarefa,
                    **extra,
                ))
                resultado["tarefas"] += 1
            db.add(Tarefa(
                tipo="prospeccao", lead_id=lead.id, passo_id=passo.id, campanha_id=campanha_id,
                usuario_id=responsavel.id if responsavel else None, canal=canal, data=data,
                hora=hora, acao=passo.acao or f"Contato por {canal}",
                assunto=assunto, mensagem=corpo, angulo=passo.angulo or "", status=status_tarefa, **modelos,
            ))
            resultado["tarefas"] += 1
        if lead.vendedor_id is None and usuario.perfil != "parceiro" and not autorizacao.ve_tudo(usuario, "leads.ver"):
            lead.vendedor_id = usuario.id
        if lead.status in ("Novo", "Pesquisando"):
            lead.status = "Abordagem criada"
        lead.proximo_contato = inicio
        texto = "preparada (aguardando aprovação)" if status_tarefa == "rascunho" else f"iniciada em {inicio:%d/%m/%Y}"
        historico(db, lead.id, "sistema", f"Cadência \"{cadencia.nome}\" {texto}.", usuario)
        resultado["leads"] += 1
    return resultado


def atualizar_proximo_contato(db: Session, lead: Lead) -> None:
    proxima = db.execute(select(Tarefa.data).where(
        Tarefa.lead_id == lead.id, Tarefa.status == "pendente").order_by(Tarefa.data).limit(1)).scalar()
    lead.proximo_contato = proxima
