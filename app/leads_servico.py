"""Regras dos leads: deduplicação, cadastro, mudança de status (com histórico), opt-out,
conversão em parceiro e política de retenção (LGPD)."""

from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import config, score, util
from .banco import agora, ler_config_int
from .modelos import Historico, Lead, Parceiro, Tarefa, Usuario

CAMPOS_TEXTO = ["empresa", "cnpj", "responsavel", "cargo", "telefone", "whatsapp", "email", "site",
                "instagram", "linkedin", "cidade", "estado", "endereco", "especialidade", "tipo_empresa",
                "socios", "porte", "regime", "origem", "fonte_url", "observacoes", "base_legal"]
CAMPOS_NUMERO = ["qtd_clientes_estimada", "funcionarios"]
CAMPOS_MARCA = ["equipe_comercial", "multiplos_socios", "atende_empresas", "presenca_digital_forte",
                "demonstrou_interesse", "consentimento"]


def limpar_campos(lead: Lead) -> None:
    """Padroniza os campos e recalcula as chaves de deduplicação."""
    lead.empresa = (lead.empresa or "").strip()[:200]
    lead.estado = (lead.estado or "").strip().upper()[:2]
    lead.cnpj = util.formatar_cnpj(lead.cnpj) if util.normalizar_cnpj(lead.cnpj) else ""
    lead.telefone = util.formatar_telefone(lead.telefone) if lead.telefone else ""
    lead.whatsapp = util.formatar_telefone(lead.whatsapp) if lead.whatsapp else ""
    lead.email = (lead.email or "").strip().lower()
    lead.site = util.normalizar_site(lead.site)
    lead.instagram = util.normalizar_instagram(lead.instagram)
    lead.linkedin = util.normalizar_link(lead.linkedin)
    lead.chave_cnpj = util.normalizar_cnpj(lead.cnpj) if len(util.normalizar_cnpj(lead.cnpj)) == 14 else ""
    lead.chave_dominio = util.dominio_proprio(lead.site) or util.dominio_empresarial(lead.email)
    lead.chave_telefone = util.normalizar_telefone(lead.telefone)
    lead.chave_whatsapp = util.normalizar_telefone(lead.whatsapp)
    lead.chave_email = lead.email if util.email_valido(lead.email) else ""


def achar_duplicado(db: Session, lead: Lead, ignorar_id: int | None = None) -> tuple[Lead | None, str]:
    """Procura um lead já cadastrado com o mesmo CNPJ, domínio, telefone ou e-mail."""
    testes = []
    if lead.chave_cnpj:
        testes.append(("CNPJ", Lead.chave_cnpj == lead.chave_cnpj))
    if lead.chave_dominio:
        testes.append(("domínio", Lead.chave_dominio == lead.chave_dominio))
    for tel in {lead.chave_telefone, lead.chave_whatsapp} - {""}:
        testes.append(("telefone", or_(Lead.chave_telefone == tel, Lead.chave_whatsapp == tel)))
    if lead.chave_email:
        testes.append(("e-mail", Lead.chave_email == lead.chave_email))
    for motivo, condicao in testes:
        consulta = select(Lead).where(condicao)
        if ignorar_id:
            consulta = consulta.where(Lead.id != ignorar_id)
        existente = db.execute(consulta.limit(1)).scalars().first()
        if existente:
            return existente, motivo
    return None, ""


def historico(db: Session, lead_id: int, tipo: str, descricao: str, usuario: Usuario | None = None,
              canal: str = "") -> None:
    db.add(Historico(lead_id=lead_id, tipo=tipo, descricao=descricao, canal=canal,
                     usuario_id=usuario.id if usuario else None, criado_em=agora()))


def criar_lead(db: Session, dados: dict, usuario: Usuario | None, origem: str = "Cadastro manual",
               checar_duplicado: bool = True) -> tuple[Lead | None, str]:
    """Cria o lead. Devolve (lead, "") ou (lead_existente, motivo) quando for duplicado."""
    lead = Lead(origem=origem, criado_em=agora())
    preencher(lead, dados)
    if not lead.empresa:
        return None, "sem nome da empresa"
    limpar_campos(lead)
    if checar_duplicado:
        existente, motivo = achar_duplicado(db, lead)
        if existente:
            return existente, motivo
    if dados.get("categoria"):
        from .modelos import Categoria

        lead.categoria = db.execute(select(Categoria).where(Categoria.codigo == dados["categoria"])).scalars().first()
    if lead.vendedor_id is None and usuario and usuario.perfil in config.PERFIS_SO_PROPRIOS:
        lead.vendedor_id = usuario.id
    score.atualizar(db, lead)
    db.add(lead)
    db.flush()
    fonte = f" Fonte: {lead.fonte_url}" if lead.fonte_url else ""
    historico(db, lead.id, "sistema", f"Lead cadastrado. Origem: {lead.origem}.{fonte}", usuario)
    return lead, ""


def preencher(lead: Lead, dados: dict, so_vazios: bool = False) -> list[str]:
    """Copia os dados para o lead. Com so_vazios=True não sobrescreve o que já existe."""
    alterados = []
    for campo in CAMPOS_TEXTO:
        if campo in dados and dados[campo] is not None:
            novo = str(dados[campo]).strip()
            if so_vazios and getattr(lead, campo):
                continue
            if novo != (getattr(lead, campo) or ""):
                setattr(lead, campo, novo)
                alterados.append(campo)
    for campo in CAMPOS_NUMERO:
        if campo in dados:
            novo = util.para_int(dados[campo]) if dados[campo] not in (None, "") else None
            if so_vazios and getattr(lead, campo):
                continue
            if novo != getattr(lead, campo):
                setattr(lead, campo, novo)
                alterados.append(campo)
    for campo in CAMPOS_MARCA:
        if campo in dados:
            novo = bool(dados[campo])
            if so_vazios and not novo:
                continue
            if novo != bool(getattr(lead, campo)):
                setattr(lead, campo, novo)
                alterados.append(campo)
                if campo == "consentimento":  # LGPD: quando a autorização foi registrada
                    lead.consentimento_em = agora() if novo else None
    if "vendedor_id" in dados:
        lead.vendedor_id = dados["vendedor_id"] or None
    if "proximo_contato" in dados:
        lead.proximo_contato = util.para_data(dados["proximo_contato"])
    return alterados


def cnpj_inativo(db: Session, lead: Lead, situacao: str, usuario: Usuario | None = None) -> bool:
    """A Receita diz que o CNPJ não está ativo (baixada, inapta, suspensa...). Lead que ainda não conversou vira
    Perdido e sai das campanhas; com conversa em andamento, só fica o aviso. True = virou Perdido."""
    situacao = (situacao or "").strip()
    if not situacao or situacao.upper() == "ATIVA":
        return False
    historico(db, lead.id, "sistema", f"Atenção: situação cadastral do CNPJ na Receita: {situacao}.", usuario)
    if lead.etapa < 2 and not lead.perdido:
        return mudar_status(db, lead, "Perdido", usuario, "CNPJ inativo")
    return False


def mudar_status(db: Session, lead: Lead, novo: str, usuario: Usuario | None, motivo: str = "") -> bool:
    """Muda o status, grava as datas do funil, registra histórico e mantém o parceiro em dia."""
    if novo not in config.STATUS_LEAD or novo == lead.status:
        return False
    anterior = lead.status
    lead.status = novo
    etapa = config.ETAPA_DO_STATUS.get(novo)
    if etapa is not None:
        for numero, campo in config.DATA_DA_ETAPA.items():
            if numero <= etapa and getattr(lead, campo) is None:
                setattr(lead, campo, agora())
    if novo in config.STATUS_PERDIDO:
        lead.motivo_perda = motivo or novo
    texto = f"Status: {anterior} → {novo}" + (f" ({motivo})" if motivo else "")
    historico(db, lead.id, "status", texto, usuario)
    # Respondeu, avançou ou foi encerrado: as tentativas automáticas da cadência param.
    if (etapa is not None and etapa >= 2) or novo in config.STATUS_PERDIDO:
        cancelar_tarefas_de_prospeccao(db, lead.id, "lead mudou para " + novo)
    if novo in ("Parceiro", "Parceiro ativo"):
        parceiro = converter_em_parceiro(db, lead, usuario)
        if novo == "Parceiro ativo" and parceiro.status != "ATIVO":
            parceiro.status = "ATIVO"
    score.atualizar(db, lead)
    return True


def cancelar_tarefas_de_prospeccao(db: Session, lead_id: int, motivo: str) -> int:
    pendentes = db.execute(select(Tarefa).where(
        Tarefa.lead_id == lead_id, Tarefa.status == "pendente", Tarefa.tipo == "prospeccao")).scalars().all()
    for t in pendentes:
        t.status = "cancelada"
        t.resultado = f"Cancelada automaticamente: {motivo}"
        t.concluida_em = agora()
    return len(pendentes)


def converter_em_parceiro(db: Session, lead: Lead, usuario: Usuario | None) -> Parceiro:
    if lead.parceiro_id:
        existente = db.get(Parceiro, lead.parceiro_id)
        if existente:
            return existente
    parceiro = Parceiro(
        escritorio=lead.empresa, responsavel=lead.responsavel, cnpj=lead.cnpj,
        telefone=lead.whatsapp or lead.telefone, email=lead.email, cidade=lead.cidade, estado=lead.estado,
        data_entrada=date.today(), status="EM ATIVAÇÃO", vendedor_id=lead.vendedor_id, lead_id=lead.id,
        ultimo_contato=lead.ultimo_contato,
    )
    db.add(parceiro)
    db.flush()
    lead.parceiro_id = parceiro.id
    if lead.convertido_em is None:
        lead.convertido_em = agora()
    historico(db, lead.id, "sistema", f"Convertido em parceiro (cadastro de parceiro nº {parceiro.id}).", usuario)
    return parceiro


def registrar_opt_out(db: Session, lead: Lead, usuario: Usuario | None, origem: str = "pedido do contato"):
    if lead.opt_out:
        return
    lead.opt_out = True
    lead.opt_out_em = agora()
    cancelar_tarefas_de_prospeccao(db, lead.id, "opt-out")
    historico(db, lead.id, "lgpd", f"Opt-out registrado ({origem}). O sistema não vai sugerir novos contatos.", usuario)


def registrar_contato(db: Session, lead: Lead, canal: str, descricao: str, usuario: Usuario | None):
    lead.ultimo_contato = agora()
    if lead.status in ("Novo", "Pesquisando", "Abordagem criada"):
        mudar_status(db, lead, "Contatado", usuario)
    elif lead.status == "Contatado":
        mudar_status(db, lead, "Aguardando resposta", usuario)
    historico(db, lead.id, "contato", descricao, usuario, canal)
    if lead.parceiro_id:
        parceiro = db.get(Parceiro, lead.parceiro_id)
        if parceiro:
            parceiro.ultimo_contato = agora()


def registrar_resposta(db: Session, lead: Lead, canal: str, texto: str, usuario: Usuario | None):
    lead.ultimo_contato = agora()
    historico(db, lead.id, "resposta", texto or "O lead respondeu.", usuario, canal)
    if lead.etapa < 2:
        mudar_status(db, lead, "Respondeu", usuario)
    else:
        cancelar_tarefas_de_prospeccao(db, lead.id, "o lead respondeu")


def filtrar_por_usuario(consulta, usuario: Usuario):
    """Vendedor vê só os próprios leads; administrador e gestor veem todos."""
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        return consulta.where(Lead.vendedor_id == usuario.id)
    return consulta


def pode_ver(usuario: Usuario, lead: Lead) -> bool:
    return usuario.perfil in ("admin", "gestor") or (usuario.perfil in config.PERFIS_SO_PROPRIOS and lead.vendedor_id == usuario.id)


def anonimizar(lead: Lead, manter_bloqueio: bool = False) -> None:
    """Política de retenção: apaga dados de contato e pessoais, mantém só números para estatística.

    Com manter_bloqueio=True (lead que pediu opt-out) ficam só as chaves de deduplicação, o mínimo
    necessário para o sistema não cadastrar e contatar o mesmo escritório de novo.
    """
    for campo in ("responsavel", "cargo", "telefone", "whatsapp", "email", "instagram", "linkedin",
                  "endereco", "socios", "observacoes", "qualificacao", "cnpj", "site"):
        setattr(lead, campo, "")
    lead.empresa = f"Lead anonimizado nº {lead.id}"
    lead.anonimizado = True
    if not manter_bloqueio:
        lead.chave_cnpj = lead.chave_dominio = lead.chave_telefone = lead.chave_whatsapp = lead.chave_email = ""


def aplicar_retencao(db: Session) -> int:
    """Anonimiza leads encerrados (ou com opt-out) sem movimento há mais tempo que o configurado."""
    dias = ler_config_int(db, "dias_retencao_perdidos", 365)
    limite = agora() - timedelta(days=dias)
    candidatos = db.execute(select(Lead).where(
        Lead.anonimizado.is_(False),
        or_(Lead.status.in_(config.STATUS_PERDIDO), Lead.opt_out.is_(True)),
        Lead.atualizado_em < limite,
    )).scalars().all()
    for lead in candidatos:
        anonimizar(lead, manter_bloqueio=lead.opt_out)
        historico(db, lead.id, "lgpd", f"Dados anonimizados pela política de retenção ({dias} dias).")
    return len(candidatos)
