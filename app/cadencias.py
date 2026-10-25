"""Cadências: transformam uma sequência (Dia 1 WhatsApp, Dia 2 ligação...) em tarefas na agenda."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, mensagens
from .banco import ler_config
from .leads_servico import historico
from .modelos import Cadencia, Lead, Tarefa, Usuario


def aplicar(db: Session, cadencia: Cadencia, leads: list[Lead], usuario: Usuario, inicio: date | None = None,
            campanha_id: int | None = None, mensagens_sdr: dict | None = None, canais: list[str] | None = None,
            status_tarefa: str = "pendente", cta: str = "", tom: str = "consultivo") -> dict:
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
            dia_anterior = data
            canal = passo.canal
            modelos = {}
            if passo.canal == "auto" or passo.angulo:
                canal = sdr.escolher_canal(db, lead, canais) if passo.canal == "auto" else passo.canal
                if da_ia and canal not in ("email", "whatsapp"):
                    if "whatsapp" not in (canais or ["whatsapp"]):
                        continue  # campanha só de e-mail e empresa sem e-mail: não entra
                    canal = "whatsapp"  # só fixo: WhatsApp a pesquisar (o time acha o número e cadastra na campanha)
                if lead.id not in mensagens_sdr:
                    mensagens_sdr[lead.id] = sdr.mensagens_por_regras(db, lead, responsavel, cta)
                msg = mensagens_sdr[lead.id].get(passo.angulo or "apresentacao") or {}
                assunto = msg.get("assunto", "") if canal == "email" else ""
                corpo = msg.get("email", "") if canal == "email" else msg.get("whatsapp", "")
                modelos = {"mensagem_whatsapp": msg.get("whatsapp", ""), "mensagem_email": msg.get("email", ""),
                           "assunto_email": (msg.get("assunto", "") or "")[:200]}
            elif da_ia and canal not in ("email", "whatsapp"):
                continue  # campanha da IA só manda e-mail e WhatsApp: ligação/LinkedIn o usuário faz por conta própria
            else:
                template = passo.template or mensagens.template_padrao(db, passo.canal)
                assunto, corpo = mensagens.montar(db, template, lead, responsavel)
            db.add(Tarefa(
                tipo="prospeccao", lead_id=lead.id, passo_id=passo.id, campanha_id=campanha_id,
                usuario_id=responsavel.id if responsavel else None, canal=canal, data=data,
                hora=passo.hora or "09:00", acao=passo.acao or f"Contato por {canal}",
                assunto=assunto, mensagem=corpo, angulo=passo.angulo or "", status=status_tarefa, **modelos,
            ))
            resultado["tarefas"] += 1
        if lead.vendedor_id is None and usuario.perfil in config.PERFIS_SO_PROPRIOS:
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
