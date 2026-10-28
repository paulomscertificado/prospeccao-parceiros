"""Mensagens: variáveis dos templates, opt-out, limite diário e controle de frequência.

Regra de ouro: o sistema NÃO dispara mensagens em massa. Cada mensagem é enviada por uma pessoa
(copiando, abrindo o WhatsApp ou clicando em "Enviar pela API" num contato por vez).
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import util
from .banco import agora, ler_config, ler_config_int
from .modelos import Lead, Mensagem, Template, Usuario

VARIAVEIS = {
    "nome": "Primeiro nome do responsável",
    "empresa": "Nome do escritório",
    "cidade": "Cidade do lead",
    "estado": "UF do lead",
    "especialidade": "Especialidade do escritório",
    "vendedor": "Seu nome",
    "comissao": "Texto da comissão (Configurações)",
    "link_parceria": "Link da página de parceria (Configurações)",
}


def valores_variaveis(db: Session, lead: Lead | None, usuario: Usuario | None) -> dict[str, str]:
    vendedor = usuario.nome if usuario and usuario.perfil != "parceiro" else ""
    if lead and lead.vendedor_id and (not usuario or usuario.id != lead.vendedor_id):
        dono = db.get(Usuario, lead.vendedor_id)
        vendedor = vendedor or (dono.nome if dono else "")
    return {
        "nome": util.primeiro_nome(lead.responsavel) if lead else "",
        "empresa": (lead.empresa if lead else "") or "seu escritório",
        "cidade": (lead.cidade if lead else "") or "sua região",
        "estado": lead.estado if lead else "",
        "especialidade": (lead.especialidade if lead else "").lower(),
        "vendedor": util.primeiro_nome(vendedor) or "a equipe",
        "comissao": ler_config(db, "texto_comissao"),
        "link_parceria": ler_config(db, "link_parceria"),
    }


def aplicar_variaveis(texto: str, valores: dict[str, str]) -> str:
    resultado = re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: valores.get(m.group(1), ""), texto or "")
    # "Olá, !" quando não sabemos o nome → "Olá!"
    resultado = re.sub(r"[ \t]*,[ \t]*([!?.])", r"\1", resultado)
    resultado = re.sub(r"(Olá|Oi|Bom dia|Boa tarde)[ \t]*,[ \t]*,", r"\1,", resultado)  # "Olá, , tudo bem?" → "Olá, tudo bem?"
    return re.sub(r"[ \t]{2,}", " ", resultado).strip()


def montar(db: Session, template: Template | None, lead: Lead | None, usuario: Usuario | None) -> tuple[str, str]:
    """(assunto, corpo) do template com as variáveis do lead."""
    if not template:
        return "", ""
    valores = valores_variaveis(db, lead, usuario)
    return aplicar_variaveis(template.assunto, valores), aplicar_variaveis(template.corpo, valores)


def template_padrao(db: Session, canal: str) -> Template | None:
    return db.execute(select(Template).where(Template.canal == canal, Template.ativo.is_(True))
                      .order_by(Template.id).limit(1)).scalars().first()


# ---------------------------------------------------------------- Regras de envio

ENVIADAS = ["copiada", "na_fila", "enviada", "entregue", "lida"]  # na_fila: na fila do WhatsApp conectado


def _contar_saida(db: Session, desde: datetime, *condicoes) -> int:
    return db.execute(select(func.count(Mensagem.id)).where(
        Mensagem.direcao == "saida", Mensagem.criado_em >= desde, Mensagem.status.in_(ENVIADAS), *condicoes,
    )).scalar() or 0


def enviadas_hoje(db: Session, canal: str) -> int:
    return _contar_saida(db, datetime.combine(agora().date(), datetime.min.time()), Mensagem.canal == canal)


def enviadas_na_hora(db: Session, canal: str) -> int:
    return _contar_saida(db, agora() - timedelta(hours=1), Mensagem.canal == canal)


def enviadas_hoje_campanha(db: Session, campanha_id: int) -> int:
    return _contar_saida(db, datetime.combine(agora().date(), datetime.min.time()), Mensagem.campanha_id == campanha_id)


def enviadas_hoje_dominio(db: Session, dominio_email: str) -> int:
    from .modelos import Lead as _Lead

    inicio = datetime.combine(agora().date(), datetime.min.time())
    return db.execute(select(func.count(Mensagem.id)).join(_Lead, Mensagem.lead_id == _Lead.id).where(
        Mensagem.direcao == "saida", Mensagem.criado_em >= inicio, Mensagem.status.in_(ENVIADAS),
        Mensagem.canal == "email", _Lead.chave_dominio == dominio_email)).scalar() or 0


def dentro_do_horario(db: Session, momento: datetime | None = None) -> bool:
    """Envio automático só em dia útil, dentro do horário configurado."""
    momento = momento or agora()
    if momento.weekday() >= 5:
        return False
    inicio = ler_config(db, "horario_envio_inicio") or "08:30"
    fim = ler_config(db, "horario_envio_fim") or "18:00"
    return inicio <= momento.strftime("%H:%M") < fim


def limite_diario(db: Session, canal: str) -> int:
    chave = {"whatsapp": "limite_diario_whatsapp", "email": "limite_diario_email"}.get(canal)
    return ler_config_int(db, chave, 0) if chave else 0


def ultimo_envio(db: Session, lead_id: int, canal: str | None = None) -> datetime | None:
    consulta = select(func.max(Mensagem.criado_em)).where(
        Mensagem.lead_id == lead_id, Mensagem.direcao == "saida", Mensagem.angulo != "resposta",
        Mensagem.status.in_(ENVIADAS))
    if canal:
        consulta = consulta.where(Mensagem.canal == canal)
    return db.execute(consulta).scalar()


def horas_entre_contatos(db: Session, canal: str) -> int:
    """Intervalo mínimo por canal (WhatsApp e e-mail separados); vazio = usa o geral (horas_entre_contatos)."""
    chave = {"email": "horas_entre_contatos_email", "whatsapp": "horas_entre_contatos_whatsapp"}.get(canal)
    valor = str(ler_config(db, chave) or "").strip() if chave else ""
    return util.para_int(valor) if valor else ler_config_int(db, "horas_entre_contatos", 20)


def bloqueio_de_envio(db: Session, lead: Lead | None, canal: str, campanha_id: int | None = None) -> str:
    """Motivo para NÃO contatar agora (vazio = pode). Vale para envio manual, pela API e pela fila.
    Limites: por contato (intervalo), por dia e por hora (canal), por campanha e por domínio (e-mail)."""
    if lead is not None:
        if lead.opt_out:
            return "Este contato pediu para não receber mensagens (opt-out)."
        if lead.anonimizado:
            return "Este lead foi anonimizado pela política de retenção."
        if lead.perdido and lead.motivo_perda == "Contato inválido" and canal in ("whatsapp", "ligacao"):
            return "O número deste lead foi marcado como inválido."
        horas = horas_entre_contatos(db, canal)
        ultimo = ultimo_envio(db, lead.id, canal)  # cada canal tem o seu controle: e-mail não segura WhatsApp
        nome = {"email": "e-mail", "whatsapp": "WhatsApp"}.get(canal, canal)
        if horas and ultimo and agora() - ultimo < timedelta(hours=horas):
            return (f"Já houve um {nome} para este lead há menos de {horas} horas (controle de frequência do {nome}). "
                    "Tente mais tarde ou use o outro canal.")
    limite = limite_diario(db, canal)
    if limite and enviadas_hoje(db, canal) >= limite:
        return f"O limite diário de {limite} mensagens de {canal} foi atingido. Ajuste em Configurações."
    por_hora = ler_config_int(db, {"email": "limite_hora_email", "whatsapp": "limite_hora_whatsapp"}.get(canal, ""), 0)
    if por_hora and enviadas_na_hora(db, canal) >= por_hora:
        return f"O limite de {por_hora} mensagens de {canal} por hora foi atingido. A fila continua na próxima hora."
    if campanha_id:
        por_campanha = ler_config_int(db, "limite_diario_campanha", 0)
        if por_campanha and enviadas_hoje_campanha(db, campanha_id) >= por_campanha:
            return f"O limite diário de {por_campanha} mensagens desta campanha foi atingido."
    if canal == "email" and lead is not None and lead.chave_dominio:
        por_dominio = ler_config_int(db, "limite_diario_dominio", 0)
        if por_dominio and enviadas_hoje_dominio(db, lead.chave_dominio) >= por_dominio:
            return f"Já saíram {por_dominio} e-mails hoje para o domínio {lead.chave_dominio}."
    return ""


def registrar(db: Session, lead_id: int | None, canal: str, corpo: str, usuario: Usuario | None,
              modo: str = "manual", status: str = "copiada", assunto: str = "", tarefa_id: int | None = None,
              id_externo: str = "", erro: str = "", campanha_id: int | None = None, angulo: str = "",
              categoria_id: int | None = None) -> Mensagem:
    msg = Mensagem(lead_id=lead_id, canal=canal, corpo=corpo, assunto=assunto, modo=modo, status=status,
                   usuario_id=usuario.id if usuario else None, tarefa_id=tarefa_id, id_externo=id_externo,
                   erro=erro, criado_em=agora(), campanha_id=campanha_id, angulo=angulo, categoria_id=categoria_id)
    db.add(msg)
    return msg


PALAVRAS_SAIR = {"sair", "parar", "pare", "cancelar", "descadastrar", "remover", "stop",
                 "nao quero receber", "não me mande mais"}


# Pedidos para parar no meio do texto (comparados sem acento e em minúsculas)
FRASES_SAIR = [
    "nao enviem mais", "nao envie mais", "nao mandem mais", "nao mande mais", "parem de enviar", "pare de enviar",
    "parem de mandar", "pare de mandar", "nao quero receber", "nao quero mais receber", "nao desejo receber",
    "nao autorizo", "nao entre em contato", "nao entrem em contato", "nao entrem mais em contato",
    "nao me procure", "nao nos procure", "remova meu numero", "remover meu numero", "remova nosso numero",
    "tirem meu numero", "tire meu numero", "retire meu numero", "retirem meu numero", "me tira da lista",
    "me tire da lista", "nao me chame mais", "nao chamem mais",
]


def pede_opt_out(texto: str) -> bool:
    t = util.chave_texto(texto)
    return (any(t == p or t.startswith(p + " ") for p in map(util.chave_texto, PALAVRAS_SAIR)) or "descadastr" in t
            or any(f in t for f in FRASES_SAIR))
