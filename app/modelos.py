"""Tabelas do banco (schema). Ver docs/arquitetura.md para o desenho completo."""

from datetime import date, datetime

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func,
                        select)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import config
from .banco import Base, agora


class Configuracao(Base):
    __tablename__ = "configuracoes"
    chave: Mapped[str] = mapped_column(String(80), primary_key=True)
    valor: Mapped[str] = mapped_column(Text, default="")


class Trava(Base):
    """Impede que duas cópias do sistema (na nuvem) façam a mesma coisa ao mesmo tempo. Ver app/trabalhos.py."""
    __tablename__ = "travas"
    nome: Mapped[str] = mapped_column(String(80), primary_key=True)
    ate: Mapped[datetime] = mapped_column(DateTime)


class Trabalho(Base):
    """Trabalho longo feito em etapas curtas (montar campanha, buscar empresas, personalizar com IA)."""
    __tablename__ = "trabalhos"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30))
    ref_id: Mapped[int] = mapped_column(Integer)
    usuario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="na_fila", index=True)  # na_fila, feito, erro
    estado: Mapped[str] = mapped_column(Text, default="{}")  # JSON com o ponto onde parou
    etapas: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class PonteWhatsApp(Base):
    """Mensagem esperando o computador com o WhatsApp Leads buscar (sistema na nuvem). Ver whatsapp_leads.py."""
    __tablename__ = "ponte_whatsapp"
    id: Mapped[int] = mapped_column(primary_key=True)
    telefone: Mapped[str] = mapped_column(String(30))
    nome: Mapped[str] = mapped_column(String(200), default="")
    texto: Mapped[str] = mapped_column(Text)
    resposta: Mapped[bool] = mapped_column(Boolean, default=False)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)  # escrita por uma pessoa na tela Conversas
    conexao: Mapped[str] = mapped_column(String(40), default="principal")  # por qual número sai
    usuario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="aguardando", index=True)  # aguardando, retirada, na_fila, erro
    id_wl: Mapped[str] = mapped_column(String(40), default="")  # id da mensagem no WhatsApp Leads
    erro: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class MensagemWhatsApp(Base):
    """Cópia das conversas do número conectado (todas, de qualquer contato), trazida do WhatsApp Leads pela ponte
    para a tela Conversas. Chave da conversa: telefone com DDD, sem o 55 (util.normalizar_telefone)."""
    __tablename__ = "mensagens_whatsapp"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_wl: Mapped[int] = mapped_column(Integer, unique=True, index=True)  # id da mensagem no WhatsApp Leads
    telefone: Mapped[str] = mapped_column(String(20), index=True)
    conexao: Mapped[str] = mapped_column(String(40), default="principal", index=True)  # por qual número passou
    nome: Mapped[str] = mapped_column(String(200), default="")
    direcao: Mapped[str] = mapped_column(String(10))   # entrada (contato -> MS) ou saida
    texto: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="")  # recebida, na_fila, enviada, erro, cancelada
    erro: Mapped[str] = mapped_column(Text, default="")
    origem: Mapped[str] = mapped_column(String(30), default="")  # manual, automacao, sdr, ia, celular
    lida: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)


class ConexaoWhatsApp(Base):
    """Um número de WhatsApp ligado no computador da MS: o principal ou o de um usuário. Ver app/conexoes.py."""
    __tablename__ = "conexoes_whatsapp"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "principal" ou "u<id do usuário>"
    nome: Mapped[str] = mapped_column(String(120), default="")
    dono_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compartilhada_todos: Mapped[bool] = mapped_column(Boolean, default=False)
    compartilhada_com: Mapped[str] = mapped_column(Text, default="[]")  # JSON com ids de usuários
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class ContatoWhatsApp(Base):
    """Nome do contato escolhido na tela Conversas (vale mais que o nome que veio do WhatsApp)."""
    __tablename__ = "contatos_whatsapp"
    telefone: Mapped[str] = mapped_column(String(20), primary_key=True)  # DDD + número, sem o 55
    nome: Mapped[str] = mapped_column(String(200), default="")
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class ComandoWhatsApp(Base):
    """Botão da tela WhatsApp (nuvem) esperando o computador do WhatsApp Leads executar. Ver rotas/whatsapp.py."""
    __tablename__ = "comandos_whatsapp"
    id: Mapped[int] = mapped_column(primary_key=True)
    acao: Mapped[str] = mapped_column(String(30))       # conectar, pausar, desligar, salvar_regras
    dados: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="aguardando", index=True)  # aguardando, retirado, feito, erro
    erro: Mapped[str] = mapped_column(Text, default="")
    usuario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(200))
    perfil: Mapped[str] = mapped_column(String(20), default="vendedor")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    parceiro_id: Mapped[int | None] = mapped_column(ForeignKey("parceiros.id"), nullable=True)
    versao_sessao: Mapped[int] = mapped_column(Integer, default=1)  # muda ao trocar a senha: derruba sessões antigas
    # Agenda para reuniões marcadas pela IA SDR (ex.: "seg-sex 09:00-12:00,14:00-18:00")
    expediente: Mapped[str] = mapped_column(String(120), default="seg-sex 09:00-12:00,14:00-18:00")
    duracao_reuniao: Mapped[int] = mapped_column(Integer, default=30)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    ultimo_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def perfil_nome(self) -> str:
        return config.PERFIS.get(self.perfil, self.perfil)


class Categoria(Base):
    """Categoria de parceiro (contábeis, administradoras, ERPs...). Define como achar e como abordar."""
    __tablename__ = "categorias"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nome: Mapped[str] = mapped_column(String(120))
    prioridade: Mapped[int] = mapped_column(Integer, default=50)
    aderencia: Mapped[int] = mapped_column(Integer, default=10)        # pontos de aderência ao certificado (score)
    recorrente: Mapped[bool] = mapped_column(Boolean, default=False)   # relacionamento recorrente com clientes
    cnaes: Mapped[str] = mapped_column(Text, default="")
    cnaes_com_palavra: Mapped[str] = mapped_column(Text, default="")
    palavras_chave: Mapped[str] = mapped_column(Text, default="")
    motivo: Mapped[str] = mapped_column(Text, default="")
    estrategia: Mapped[str] = mapped_column(Text, default="")
    abertura: Mapped[str] = mapped_column(Text, default="")
    gancho: Mapped[str] = mapped_column(Text, default="")
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    sugerida_pela_ia: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    def lista(self, campo: str) -> list[str]:
        return [x.strip() for x in (getattr(self, campo) or "").split(",") if x.strip()]


class Busca(Base):
    """Uma busca de "Encontrar novos parceiros"."""
    __tablename__ = "buscas"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    cidade: Mapped[str] = mapped_column(String(120), default="")
    estado: Mapped[str] = mapped_column(String(2), default="")
    raio_km: Mapped[int] = mapped_column(Integer, default=10)
    quantidade: Mapped[int] = mapped_column(Integer, default=100)
    tipo_empresa: Mapped[str] = mapped_column(String(80), default="")
    categoria: Mapped[str] = mapped_column(String(40), default="contabil")   # código da categoria de parceiro
    tamanho_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tamanho_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fontes: Mapped[str] = mapped_column(String(120), default="")
    enriquecer: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="na fila")  # na fila, buscando, enriquecendo, concluida, erro
    etapa: Mapped[str] = mapped_column(String(200), default="")
    encontrados: Mapped[int] = mapped_column(Integer, default=0)
    novos: Mapped[int] = mapped_column(Integer, default=0)
    duplicados: Mapped[int] = mapped_column(Integer, default=0)
    fora_do_tamanho: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    empresa: Mapped[str] = mapped_column(String(200), index=True)
    cnpj: Mapped[str] = mapped_column(String(20), default="")
    responsavel: Mapped[str] = mapped_column(String(120), default="")
    cargo: Mapped[str] = mapped_column(String(80), default="")
    telefone: Mapped[str] = mapped_column(String(30), default="")
    whatsapp: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    site: Mapped[str] = mapped_column(String(200), default="")
    instagram: Mapped[str] = mapped_column(String(120), default="")
    linkedin: Mapped[str] = mapped_column(String(200), default="")
    cidade: Mapped[str] = mapped_column(String(120), default="", index=True)
    estado: Mapped[str] = mapped_column(String(2), default="", index=True)
    endereco: Mapped[str] = mapped_column(String(250), default="")
    qtd_clientes_estimada: Mapped[int | None] = mapped_column(Integer, nullable=True)
    funcionarios: Mapped[int | None] = mapped_column(Integer, nullable=True)
    especialidade: Mapped[str] = mapped_column(String(120), default="")
    tipo_empresa: Mapped[str] = mapped_column(String(80), default="")
    socios: Mapped[str] = mapped_column(Text, default="")  # um por linha (dados públicos da Receita)
    porte: Mapped[str] = mapped_column(String(60), default="")
    regime: Mapped[str] = mapped_column(String(30), default="")  # MEI, Simples Nacional, Fora do Simples (Receita)
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"), nullable=True, index=True)
    # Pesquisa da IA SDR (perfil do parceiro, só com informações encontradas)
    perfil: Mapped[str] = mapped_column(Text, default="")              # JSON
    pesquisado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fit: Mapped[str] = mapped_column(String(30), default="")
    motivo_potencial: Mapped[str] = mapped_column(Text, default="")
    programa_parceiros: Mapped[bool] = mapped_column(Boolean, default=False)
    possibilidade_indicacao: Mapped[bool] = mapped_column(Boolean, default=False)
    canal_preferido: Mapped[str] = mapped_column(String(20), default="")
    classificacao_resposta: Mapped[str] = mapped_column(String(40), default="")
    automacao_pausada: Mapped[bool] = mapped_column(Boolean, default=False)
    humano_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    assumido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Critérios marcados pelo vendedor (entram no score)
    equipe_comercial: Mapped[bool] = mapped_column(Boolean, default=False)
    multiplos_socios: Mapped[bool] = mapped_column(Boolean, default=False)
    atende_empresas: Mapped[bool] = mapped_column(Boolean, default=False)
    presenca_digital_forte: Mapped[bool] = mapped_column(Boolean, default=False)
    demonstrou_interesse: Mapped[bool] = mapped_column(Boolean, default=False)
    # Origem e LGPD
    origem: Mapped[str] = mapped_column(String(120), default="Cadastro manual")
    fonte_url: Mapped[str] = mapped_column(String(300), default="")
    busca_id: Mapped[int | None] = mapped_column(ForeignKey("buscas.id"), nullable=True, index=True)
    base_legal: Mapped[str] = mapped_column(String(120), default="Legítimo interesse (contato B2B)")
    consentimento: Mapped[bool] = mapped_column(Boolean, default=False)
    consentimento_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    opt_out_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    anonimizado: Mapped[bool] = mapped_column(Boolean, default=False)
    # Funil
    status: Mapped[str] = mapped_column(String(40), default="Novo", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    potencial: Mapped[str] = mapped_column(String(30), default="Baixo potencial")
    motivo_perda: Mapped[str] = mapped_column(String(200), default="")
    observacoes: Mapped[str] = mapped_column(Text, default="")
    qualificacao: Mapped[str] = mapped_column(Text, default="")  # JSON da última qualificação
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True, index=True)
    parceiro_id: Mapped[int | None] = mapped_column(ForeignKey("parceiros.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)
    ultimo_contato: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    proximo_contato: Mapped[date | None] = mapped_column(Date, nullable=True)
    enriquecido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    contatado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    respondeu_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    interessado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reuniao_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    proposta_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    convertido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Chaves de deduplicação (preenchidas automaticamente)
    chave_cnpj: Mapped[str] = mapped_column(String(14), default="", index=True)
    chave_dominio: Mapped[str] = mapped_column(String(160), default="", index=True)
    chave_telefone: Mapped[str] = mapped_column(String(13), default="", index=True)
    chave_whatsapp: Mapped[str] = mapped_column(String(13), default="", index=True)
    chave_email: Mapped[str] = mapped_column(String(160), default="", index=True)

    vendedor: Mapped["Usuario | None"] = relationship(foreign_keys=[vendedor_id])
    humano: Mapped["Usuario | None"] = relationship(foreign_keys=[humano_id])
    categoria: Mapped["Categoria | None"] = relationship()

    @property
    def etapa(self) -> int:
        return config.ETAPA_DO_STATUS.get(self.status, -1)

    @property
    def perdido(self) -> bool:
        return self.status in config.STATUS_PERDIDO


class Historico(Base):
    """Tudo que aconteceu com um lead (também serve de registro de tratamento para a LGPD)."""
    __tablename__ = "historico"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(30))  # status, contato, resposta, nota, ia, sistema, reuniao, lgpd
    canal: Mapped[str] = mapped_column(String(20), default="")
    descricao: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)

    usuario: Mapped["Usuario | None"] = relationship()


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    canal: Mapped[str] = mapped_column(String(20), default="whatsapp")
    assunto: Mapped[str] = mapped_column(String(200), default="")
    corpo: Mapped[str] = mapped_column(Text, default="")
    # Nome do template aprovado na Meta (só para envio pela API oficial do WhatsApp)
    nome_meta: Mapped[str] = mapped_column(String(120), default="")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Modelos por segmento (app/modelos_segmento.py): código da categoria e toque da IA SDR; vazio = geral
    categoria: Mapped[str] = mapped_column(String(40), default="", index=True)
    angulo: Mapped[str] = mapped_column(String(20), default="")


class Cadencia(Base):
    __tablename__ = "cadencias"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    descricao: Mapped[str] = mapped_column(Text, default="")
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    passos: Mapped[list["PassoCadencia"]] = relationship(
        back_populates="cadencia", order_by="PassoCadencia.dia", cascade="all, delete-orphan")


class PassoCadencia(Base):
    __tablename__ = "passos_cadencia"
    id: Mapped[int] = mapped_column(primary_key=True)
    cadencia_id: Mapped[int] = mapped_column(ForeignKey("cadencias.id", ondelete="CASCADE"))
    dia: Mapped[int] = mapped_column(Integer, default=1)
    canal: Mapped[str] = mapped_column(String(20), default="whatsapp")
    acao: Mapped[str] = mapped_column(String(200), default="")
    template_id: Mapped[int | None] = mapped_column(ForeignKey("templates.id"), nullable=True)
    hora: Mapped[str] = mapped_column(String(5), default="09:00")
    angulo: Mapped[str] = mapped_column(String(20), default="")   # ângulo da mensagem na cadência SDR

    cadencia: Mapped[Cadencia] = relationship(back_populates="passos")
    template: Mapped["Template | None"] = relationship()


class Campanha(Base):
    __tablename__ = "campanhas"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160))
    pedido: Mapped[str] = mapped_column(Text, default="")              # texto livre da MS ("quero parceiros...")
    categorias: Mapped[str] = mapped_column(String(300), default="")   # códigos separados por vírgula
    cidade: Mapped[str] = mapped_column(String(120), default="")
    estado: Mapped[str] = mapped_column(String(2), default="")
    quantidade: Mapped[int] = mapped_column(Integer, default=0)
    canais: Mapped[str] = mapped_column(String(60), default="whatsapp,email")
    objetivo: Mapped[str] = mapped_column(String(200), default="Encontrar parceiros")
    tom: Mapped[str] = mapped_column(String(30), default="consultivo")
    cta: Mapped[str] = mapped_column(String(200), default="")
    # gerando → aguardando_aprovacao → ativa → concluida | cancelada | erro
    status: Mapped[str] = mapped_column(String(30), default="ativa", index=True)
    etapa: Mapped[str] = mapped_column(String(200), default="")
    erro: Mapped[str] = mapped_column(Text, default="")
    inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    aprovado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    aprovado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cadencia_id: Mapped[int | None] = mapped_column(ForeignKey("cadencias.id"), nullable=True)
    busca_id: Mapped[int | None] = mapped_column(ForeignKey("buscas.id"), nullable=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    personalizar_ia: Mapped[bool] = mapped_column(Boolean, default=False)
    status_ia: Mapped[str] = mapped_column(String(120), default="")
    arquivada: Mapped[bool] = mapped_column(Boolean, default=False)  # some da lista (Ver arquivadas)
    so_fixo: Mapped[str] = mapped_column(Text, default="")  # ids dos leads só com telefone fixo (o usuário liga)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    cadencia: Mapped["Cadencia | None"] = relationship()


class Tarefa(Base):
    """Item da agenda: passo de cadência, follow-up, reunião ou renovação."""
    __tablename__ = "tarefas"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), default="prospeccao")  # prospeccao, followup, reuniao, renovacao, indicacao
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=True, index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id", ondelete="CASCADE"), nullable=True)
    certificado_id: Mapped[int | None] = mapped_column(ForeignKey("certificados.id", ondelete="CASCADE"), nullable=True)
    parceiro_id: Mapped[int | None] = mapped_column(ForeignKey("parceiros.id"), nullable=True)
    campanha_id: Mapped[int | None] = mapped_column(ForeignKey("campanhas.id"), nullable=True)
    passo_id: Mapped[int | None] = mapped_column(ForeignKey("passos_cadencia.id", ondelete="SET NULL"), nullable=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True, index=True)
    canal: Mapped[str] = mapped_column(String(20), default="whatsapp")
    data: Mapped[date] = mapped_column(Date, index=True)
    hora: Mapped[str] = mapped_column(String(5), default="09:00")
    acao: Mapped[str] = mapped_column(String(250), default="")
    assunto: Mapped[str] = mapped_column(String(200), default="")
    mensagem: Mapped[str] = mapped_column(Text, default="")
    # Campanha da IA: os dois modelos do mesmo toque (o time pode trocar de canal se achar outro contato)
    mensagem_whatsapp: Mapped[str] = mapped_column(Text, default="")
    mensagem_email: Mapped[str] = mapped_column(Text, default="")
    assunto_email: Mapped[str] = mapped_column(String(200), default="")
    angulo: Mapped[str] = mapped_column(String(20), default="")
    # rascunho (campanha aguardando aprovação), pendente, feita, pulada, cancelada
    status: Mapped[str] = mapped_column(String(20), default="pendente", index=True)
    resultado: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lead: Mapped["Lead | None"] = relationship()
    cliente: Mapped["Cliente | None"] = relationship()
    certificado: Mapped["Certificado | None"] = relationship()
    parceiro: Mapped["Parceiro | None"] = relationship()
    usuario: Mapped["Usuario | None"] = relationship()


class Mensagem(Base):
    """Histórico de mensagens (geradas, copiadas, enviadas). Base do limite diário e do controle de frequência."""
    __tablename__ = "mensagens"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=True, index=True)
    tarefa_id: Mapped[int | None] = mapped_column(ForeignKey("tarefas.id", ondelete="SET NULL"), nullable=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    canal: Mapped[str] = mapped_column(String(20))
    campanha_id: Mapped[int | None] = mapped_column(ForeignKey("campanhas.id"), nullable=True, index=True)
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"), nullable=True)
    angulo: Mapped[str] = mapped_column(String(20), default="")
    respondida: Mapped[bool] = mapped_column(Boolean, default=False)   # o lead respondeu depois desta mensagem
    modo: Mapped[str] = mapped_column(String(20), default="manual")  # manual (copiar/abrir) ou api
    direcao: Mapped[str] = mapped_column(String(10), default="saida")
    assunto: Mapped[str] = mapped_column(String(200), default="")
    corpo: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="enviada")  # copiada, enviada, entregue, lida, falhou, recebida
    id_externo: Mapped[str] = mapped_column(String(120), default="", index=True)
    conexao: Mapped[str] = mapped_column(String(40), default="")  # WhatsApp: por qual número saiu
    erro: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)


class Parceiro(Base):
    __tablename__ = "parceiros"
    id: Mapped[int] = mapped_column(primary_key=True)
    escritorio: Mapped[str] = mapped_column(String(200))
    responsavel: Mapped[str] = mapped_column(String(120), default="")
    cnpj: Mapped[str] = mapped_column(String(20), default="")
    telefone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    cidade: Mapped[str] = mapped_column(String(120), default="")
    estado: Mapped[str] = mapped_column(String(2), default="")
    data_entrada: Mapped[date] = mapped_column(Date, default=date.today)
    status: Mapped[str] = mapped_column(String(20), default="EM ATIVAÇÃO", index=True)
    # Regra de comissão própria (vazio = usa a regra do produto)
    comissao_tipo: Mapped[str] = mapped_column(String(12), default="")  # "", percentual, fixo
    comissao_valor: Mapped[float] = mapped_column(Float, default=0)
    chave_pix_cripto: Mapped[str] = mapped_column(Text, default="")  # guardada criptografada
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    ultimo_contato: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    observacoes: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    vendedor: Mapped["Usuario | None"] = relationship(foreign_keys=[vendedor_id])


class Cliente(Base):
    """Cliente final (quem compra o certificado), normalmente indicado por um parceiro."""
    __tablename__ = "clientes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    cnpj: Mapped[str] = mapped_column(String(20), default="")  # CNPJ ou CPF
    contato: Mapped[str] = mapped_column(String(120), default="")
    telefone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    parceiro_id: Mapped[int | None] = mapped_column(ForeignKey("parceiros.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="Indicado")
    produto_interesse: Mapped[str] = mapped_column(String(120), default="")
    origem: Mapped[str] = mapped_column(String(40), default="Indicação")
    observacoes: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)

    parceiro: Mapped["Parceiro | None"] = relationship()


class Produto(Base):
    __tablename__ = "produtos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    preco: Mapped[float] = mapped_column(Float, default=0)
    custo: Mapped[float] = mapped_column(Float, default=0)
    comissao_tipo: Mapped[str] = mapped_column(String(12), default="percentual")  # percentual ou fixo
    comissao_valor: Mapped[float] = mapped_column(Float, default=config.COMISSAO_PADRAO_PERCENTUAL)
    validade_meses: Mapped[int] = mapped_column(Integer, default=12)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Venda(Base):
    __tablename__ = "vendas"
    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    parceiro_id: Mapped[int | None] = mapped_column(ForeignKey("parceiros.id"), nullable=True, index=True)
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produtos.id"), nullable=True)
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    data: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    tipo: Mapped[str] = mapped_column(String(12), default="nova")  # nova ou renovacao
    valor: Mapped[float] = mapped_column(Float, default=0)
    custo: Mapped[float] = mapped_column(Float, default=0)
    comissao: Mapped[float] = mapped_column(Float, default=0)
    comissao_paga: Mapped[bool] = mapped_column(Boolean, default=False)
    comissao_paga_em: Mapped[date | None] = mapped_column(Date, nullable=True)
    observacoes: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    cliente: Mapped[Cliente] = relationship()
    parceiro: Mapped["Parceiro | None"] = relationship()
    produto: Mapped["Produto | None"] = relationship()
    vendedor: Mapped["Usuario | None"] = relationship()


class Certificado(Base):
    """Certificado emitido: base do controle de vencimentos e renovações."""
    __tablename__ = "certificados"
    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"), nullable=True)
    cliente_nome: Mapped[str] = mapped_column(String(200))
    cnpj: Mapped[str] = mapped_column(String(20), default="")
    tipo: Mapped[str] = mapped_column(String(120), default="")
    data_emissao: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_vencimento: Mapped[date] = mapped_column(Date, index=True)
    parceiro_id: Mapped[int | None] = mapped_column(ForeignKey("parceiros.id"), nullable=True, index=True)
    venda_id: Mapped[int | None] = mapped_column(ForeignKey("vendas.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Ativo", index=True)
    ultimo_alerta: Mapped[int | None] = mapped_column(Integer, nullable=True)  # menor alerta já gerado (dias)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    parceiro: Mapped["Parceiro | None"] = relationship()
    cliente: Mapped["Cliente | None"] = relationship()


class Oportunidade(Base):
    """Lead que respondeu: a IA para e entrega ao time humano (handoff)."""
    __tablename__ = "oportunidades"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    temperatura: Mapped[str] = mapped_column(String(10), default="quente")   # quente ou morna
    classificacao: Mapped[str] = mapped_column(String(40), default="")
    canal: Mapped[str] = mapped_column(String(20), default="")
    mensagem_enviada: Mapped[str] = mapped_column(Text, default="")
    resposta: Mapped[str] = mapped_column(Text, default="")
    resumo: Mapped[str] = mapped_column(Text, default="")
    objecoes: Mapped[str] = mapped_column(Text, default="")
    interesse: Mapped[str] = mapped_column(String(60), default="")
    proximo_passo: Mapped[str] = mapped_column(String(250), default="")
    status: Mapped[str] = mapped_column(String(20), default="nova", index=True)  # nova, assumida, descartada
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    assumida_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)

    lead: Mapped["Lead"] = relationship()
    responsavel: Mapped["Usuario | None"] = relationship()


class Notificacao(Base):
    __tablename__ = "notificacoes"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    texto: Mapped[str] = mapped_column(String(300))
    link: Mapped[str] = mapped_column(String(200), default="")
    lida: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Conhecimento(Base):
    """Base de conhecimento: o que a IA SDR pode responder sozinha (sem negociar)."""
    __tablename__ = "base_conhecimento"
    id: Mapped[int] = mapped_column(primary_key=True)
    pergunta: Mapped[str] = mapped_column(String(250))
    resposta: Mapped[str] = mapped_column(Text)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)


class LogAuditoria(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    usuario_nome: Mapped[str] = mapped_column(String(120), default="")
    acao: Mapped[str] = mapped_column(String(80))
    entidade: Mapped[str] = mapped_column(String(40), default="")
    entidade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detalhes: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(60), default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)


# ---------------------------------------------------------------- Dados iniciais (não são dados de demonstração)

TEMPLATES_PADRAO = [
    ("Primeiro contato – WhatsApp", "whatsapp", "",
     "Olá, {{nome}}! Tudo bem?\n\n"
     "Vi que a {{empresa}} atende empresas aqui em {{cidade}}. Sou {{vendedor}}, da MS Certificação Digital, "
     "e estamos ampliando nosso programa de parceria com escritórios contábeis.\n\n"
     "A ideia é simples: vocês indicam os clientes que precisam de certificado digital, nossa equipe cuida de "
     "todo o processo e o escritório recebe {{comissao}}.\n\n"
     "Hoje vocês já trabalham com algum parceiro de certificação digital?\n\n"
     "(Se não fizer sentido para vocês, é só me avisar que não envio mais mensagens.)"),
    ("Follow-up – WhatsApp", "whatsapp", "",
     "Olá, {{nome}}! Passando para saber se conseguiu ver minha mensagem sobre a parceria da MS "
     "Certificação Digital com a {{empresa}}.\n\nSe fizer sentido, posso explicar em 10 minutos como "
     "funciona a comissão e o controle de renovações dos seus clientes. Qual o melhor horário?"),
    ("Apresentação – E-mail", "email", "Parceria em certificado digital para a {{empresa}}",
     "Olá, {{nome}}, tudo bem?\n\n"
     "Sou {{vendedor}}, da MS Certificação Digital (Autoridade de Registro ICP-Brasil). Estamos ampliando "
     "nosso programa de parceria com escritórios contábeis de {{cidade}}.\n\n"
     "Como funciona:\n"
     "1. O escritório indica os clientes que precisam emitir ou renovar o certificado digital;\n"
     "2. Nossa equipe faz todo o atendimento, emissão e validação;\n"
     "3. O escritório recebe {{comissao}};\n"
     "4. Nós controlamos o vencimento e cuidamos da renovação, sempre mantendo vocês como parceiros.\n\n"
     "Posso apresentar a proposta em uma conversa rápida? Mais detalhes: {{link_parceria}}\n\n"
     "Abraço,\n{{vendedor}}\nMS Certificação Digital"),
    ("Última tentativa – E-mail", "email", "Encerrando meu contato, {{nome}}",
     "Olá, {{nome}}!\n\nTentei falar com você algumas vezes sobre a parceria da MS Certificação Digital "
     "com a {{empresa}}. Para não incomodar, este é meu último contato.\n\n"
     "Se no futuro quiser oferecer certificado digital aos seus clientes com comissão para o escritório, "
     "é só responder este e-mail.\n\nAbraço,\n{{vendedor}}"),
    ("Conexão – LinkedIn", "linkedin", "",
     "Olá, {{nome}}! Trabalho com parcerias entre escritórios contábeis e a MS Certificação Digital em "
     "{{cidade}}. Gostaria de me conectar para trocarmos ideias."),
    ("Roteiro de ligação", "ligacao", "",
     "1. Apresente-se: {{vendedor}}, da MS Certificação Digital.\n"
     "2. Pergunte se a {{empresa}} emite ou indica certificados digitais para os clientes.\n"
     "3. Explique a parceria: indicação + MS cuida de tudo + {{comissao}} + controle de renovação.\n"
     "4. Pergunte: 'Hoje vocês já têm um parceiro de certificação digital?'\n"
     "5. Proponha uma reunião de 15 minutos."),
]

CADENCIA_PADRAO = [
    (1, "whatsapp", "Primeiro contato pelo WhatsApp", "Primeiro contato – WhatsApp"),
    (2, "ligacao", "Ligar para apresentar a parceria", "Roteiro de ligação"),
    (4, "whatsapp", "Follow-up pelo WhatsApp", "Follow-up – WhatsApp"),
    (6, "email", "Enviar apresentação por e-mail", "Apresentação – E-mail"),
    (8, "linkedin", "Conectar no LinkedIn", "Conexão – LinkedIn"),
    (10, "email", "Última tentativa", "Última tentativa – E-mail"),
]


CONHECIMENTO_PADRAO = [
    ("O que é a MS Certificação Digital?",
     "A MS Certificação Digital é Autoridade de Registro ICP-Brasil e emite certificados digitais (e-CPF, e-CNPJ, "
     "NF-e e outros). Site: mscertificados.com.br."),
    ("Como funciona a parceria?",
     "O parceiro indica os clientes que precisam de certificado digital; a equipe da MS faz o atendimento, a emissão "
     "e a validação, e controla o vencimento para a renovação. O parceiro é remunerado pelas indicações; as "
     "condições comerciais são apresentadas pelo time comercial."),
    ("Como é feita a validação?", "Validação presencial em Recife ou por videoconferência."),
    ("Quais formas de pagamento?", "Pix, cartão ou boleto."),
    ("Quais certificados vocês emitem?",
     "e-CPF, e-CNPJ, NF-e, e-CPF com CEI, e-Jurídico e e-Médico, nos modelos A1 (arquivo) e A3 (sem mídia, cartão, "
     "cartão + leitora ou token)."),
]

NOME_CADENCIA_SDR = "IA SDR – 4 toques (D1, D3, D7, D12)"
CADENCIA_SDR = [
    (1, "apresentacao", "Primeiro contato (apresentação da parceria)"),
    (3, "praticidade", "Follow-up com foco em praticidade"),
    (7, "receita", "Segundo follow-up com foco em receita"),
    (12, "encerramento", "Último contato (encerramento educado)"),
]


def dados_iniciais(db) -> None:
    """Cria templates, cadências, produtos, categorias e base de conhecimento na primeira vez."""
    if not db.execute(select(func.count(Categoria.id))).scalar():
        for c in config.CATEGORIAS_PADRAO:
            db.add(Categoria(codigo=c["codigo"], nome=c["nome"], prioridade=c["prioridade"], aderencia=c["aderencia"],
                             recorrente=c["recorrente"], cnaes=c["cnaes"], cnaes_com_palavra=c["cnaes_com_palavra"],
                             palavras_chave=c["palavras_chave"], motivo=c["motivo"], estrategia=c["estrategia"],
                             abertura=c["abertura"], gancho=c["gancho"]))
    if not db.execute(select(func.count(Conhecimento.id))).scalar():
        for pergunta, resposta in CONHECIMENTO_PADRAO:
            db.add(Conhecimento(pergunta=pergunta, resposta=resposta))
    if not db.execute(select(func.count(Template.id))).scalar():
        for nome, canal, assunto, corpo in TEMPLATES_PADRAO:
            db.add(Template(nome=nome, canal=canal, assunto=assunto, corpo=corpo))
        db.flush()
    if not db.execute(select(func.count(Cadencia.id))).scalar():
        por_nome = {t.nome: t.id for t in db.execute(select(Template)).scalars()}
        cad = Cadencia(nome="Prospecção de escritórios (10 dias)",
                       descricao="Sequência padrão: WhatsApp, ligação, follow-up, e-mail, LinkedIn e última tentativa.")
        for dia, canal, acao, template in CADENCIA_PADRAO:
            cad.passos.append(PassoCadencia(dia=dia, canal=canal, acao=acao, template_id=por_nome.get(template)))
        db.add(cad)
    db.flush()
    if not db.execute(select(Cadencia.id).where(Cadencia.nome == NOME_CADENCIA_SDR)).first():
        cad = Cadencia(nome=NOME_CADENCIA_SDR,
                       descricao="Cadência da IA SDR: cada toque tem um ângulo diferente; depois do último, "
                                 "o lead vira 'Sem resposta'.")
        for dia, angulo, acao in CADENCIA_SDR:
            cad.passos.append(PassoCadencia(dia=dia, canal="auto", acao=acao, angulo=angulo))
        db.add(cad)
    from . import modelos_segmento

    modelos_segmento.garantir(db)  # 15 modelos por segmento (só cria os que faltam)
    if not db.execute(select(func.count(Produto.id))).scalar():
        for nome, preco, meses in config.PRODUTOS_PADRAO:
            db.add(Produto(nome=nome, preco=preco, custo=0, validade_meses=meses))
