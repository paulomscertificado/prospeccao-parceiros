"""Configurações gerais do sistema.

Tudo que é chave, senha ou endereço de servidor vem do arquivo .env (ver .env.example).
Nada de chave escrita no código.
"""

import os
import secrets
import time
from pathlib import Path

from dotenv import load_dotenv

PASTA_DO_SISTEMA = Path(__file__).resolve().parent.parent
load_dotenv(PASTA_DO_SISTEMA / ".env")

# Na nuvem (Vercel) não existe "este computador": o disco é apagado a toda hora e só /tmp aceita gravação.
# Lá, tudo que precisa durar fica no banco PostgreSQL e as chaves vêm das variáveis de ambiente.
NA_NUVEM = bool(os.environ.get("VERCEL")) or os.environ.get("MODO_NUVEM", "0") == "1"

if NA_NUVEM:
    # Horário de Brasília (UTC-3, sem horário de verão). Os servidores da nuvem usam UTC.
    os.environ["TZ"] = os.environ.get("FUSO_HORARIO", "<-03>3")
    if hasattr(time, "tzset"):
        time.tzset()

PASTA_DADOS = Path(os.environ.get("PP_PASTA_DADOS", "/tmp/prospeccao" if NA_NUVEM else PASTA_DO_SISTEMA / "dados"))
PASTA_DADOS.mkdir(parents=True, exist_ok=True)
ARQUIVO_LOG = PASTA_DADOS / "sistema.log"

# Banco: SQLite neste computador; em produção use PostgreSQL
# (ex.: postgresql+psycopg://usuario:senha@servidor:5432/prospeccao).
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{(PASTA_DADOS / 'banco.db').as_posix()}"

HOST = os.environ.get("HOST", "127.0.0.1")
PORTA = int(os.environ.get("PORTA", "8001"))
PRODUCAO = os.environ.get("AMBIENTE", "local").lower() == "producao"
URL_PUBLICA = os.environ.get("URL_PUBLICA", f"http://localhost:{PORTA}").rstrip("/")


class FaltaConfiguracao(RuntimeError):
    pass


def _chave_guardada(nome_arquivo: str, gerar) -> str:
    """Gera uma chave no primeiro uso e guarda em dados/ (só quando o .env não informa)."""
    if NA_NUVEM:
        nome = "SECRET_KEY" if "sessao" in nome_arquivo else "CHAVE_CRIPTOGRAFIA"
        raise FaltaConfiguracao(f"Falta a variável {nome} no painel da Vercel (Settings > Environment Variables). "
                                "Veja docs/deploy-vercel.md.")
    arquivo = PASTA_DADOS / nome_arquivo
    if arquivo.exists():
        return arquivo.read_text(encoding="utf-8").strip()
    chave = gerar()
    arquivo.write_text(chave, encoding="utf-8")
    return chave


SECRET_KEY = os.environ.get("SECRET_KEY") or _chave_guardada("chave_sessao.txt", lambda: secrets.token_hex(32))


def _gerar_chave_fernet() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


CHAVE_CRIPTOGRAFIA = os.environ.get("CHAVE_CRIPTOGRAFIA") or _chave_guardada("chave_criptografia.txt", _gerar_chave_fernet)

if NA_NUVEM and DATABASE_URL.startswith("sqlite"):
    raise FaltaConfiguracao("Falta a variável DATABASE_URL (banco PostgreSQL) no painel da Vercel. Veja docs/deploy-vercel.md.")
if DATABASE_URL.startswith("postgres://"):  # formato que Neon/Supabase mostram
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

# Senha do agendador (Vercel Cron ou cron-job.org) que chama /api/cron a cada minuto.
CRON_SECRET = os.environ.get("CRON_SECRET", "")
# Segundos que cada chamada do agendador pode trabalhar (a Vercel corta em maxDuration do vercel.json).
SEGUNDOS_POR_RODADA = int(os.environ.get("SEGUNDOS_POR_RODADA", "240"))

# Sessão: expira depois deste tempo sem uso.
MINUTOS_SESSAO_OCIOSA = int(os.environ.get("MINUTOS_SESSAO_OCIOSA", "120"))
# Verificação em 2 etapas (código do celular) para administrador e gestor. "0" desliga (só para testes).
EXIGIR_2FA = os.environ.get("EXIGIR_2FA", "1") != "0"

# ---------------------------------------------------------------- Integrações (todas opcionais)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
IA_MODELO = os.environ.get("IA_MODELO", "claude-opus-5-5")

GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "")
# Contato exigido pela política de uso do OpenStreetMap (Nominatim/Overpass).
OSM_CONTATO = os.environ.get("OSM_CONTATO", "contato@mscertificados.com.br")

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")
WHATSAPP_API_VERSAO = os.environ.get("WHATSAPP_API_VERSAO", "v21.0")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORTA = int(os.environ.get("SMTP_PORTA", "587"))
SMTP_USUARIO = os.environ.get("SMTP_USUARIO", "")
SMTP_SENHA = os.environ.get("SMTP_SENHA", "")
SMTP_REMETENTE = os.environ.get("SMTP_REMETENTE", "")
SMTP_TLS = os.environ.get("SMTP_TLS", "1") == "1"
SMTP_RESPONDER_PARA = os.environ.get("SMTP_RESPONDER_PARA", "")
# Só envia com remetente deste domínio (vazio = qualquer domínio)
EMAIL_DOMINIO = os.environ.get("EMAIL_DOMINIO", "mscertificados.com.br").strip().lower()
# WhatsApp conectado pelo sistema WhatsApp Leads (pasta vizinha "whatsapp-leads", porta 8000)
WHATSAPP_LEADS_URL = os.environ.get("WHATSAPP_LEADS_URL", "http://127.0.0.1:8000").rstrip("/")
WHATSAPP_LEADS_TOKEN = os.environ.get("WHATSAPP_LEADS_TOKEN", "")
WHATSAPP_LEADS_PASTA = Path(os.environ.get("WHATSAPP_LEADS_PASTA", PASTA_DO_SISTEMA.parent / "whatsapp-leads"))
# Sistema na nuvem: o computador com o WhatsApp Leads é quem busca as mensagens aqui ("ponte"),
# usando esta senha (a mesma vai no .env do WhatsApp Leads como PROSPECCAO_TOKEN).
WHATSAPP_PONTE_TOKEN = os.environ.get("WHATSAPP_PONTE_TOKEN", "")
WHATSAPP_PONTE = NA_NUVEM or os.environ.get("WHATSAPP_PONTE", "0") == "1"

# Leitura das respostas por e-mail (IMAP, opcional)
IMAP_HOST = os.environ.get("IMAP_HOST", "")
IMAP_PORTA = int(os.environ.get("IMAP_PORTA", "993"))
IMAP_USUARIO = os.environ.get("IMAP_USUARIO", "")
IMAP_SENHA = os.environ.get("IMAP_SENHA", "")

# ---------------------------------------------------------------- Regras do negócio

PERFIS = {
    "admin": "Administrador",
    "gestor": "Gestor",
    "funcionario": "Funcionário MS",
    "vendedor": "Vendedor",
    "parceiro": "Parceiro",
}
# O que cada perfil (papel) pode fazer e com que alcance (tudo / equipe / só os próprios) fica em app/autorizacao.py
# e na tela Permissões. Os perfis acima são os 5 papéis do sistema e o "tipo" de cada usuário.

# Funil do CRM da IA SDR (a IA trabalha até "Interessado"; daí em diante é o time humano).
STATUS_LEAD = [
    "Novo", "Pesquisando", "Abordagem criada", "Contatado", "Aguardando resposta", "Respondeu",
    "Interessado", "Humano assumiu", "Reunião", "Negociação", "Parceiro", "Parceiro ativo", "Perdido",
]
STATUS_PERDIDO = ["Perdido"]
MOTIVOS_PERDA = ["Sem interesse", "Sem resposta", "Já possui parceiro", "Contato inválido", "Sem fit",
                 "CNPJ inativo", "Opt-out", "Outro"]

# Status antigos (versão 1) → novos. Aplicado sozinho ao abrir o sistema.
MIGRACAO_STATUS = {
    "Em pesquisa": ("Pesquisando", ""), "Contato realizado": ("Contatado", ""),
    "Reunião agendada": ("Reunião", ""), "Proposta enviada": ("Negociação", ""),
    "Sem interesse": ("Perdido", "Sem interesse"), "Não respondeu": ("Perdido", "Sem resposta"),
    "Número inválido": ("Perdido", "Contato inválido"), "Não qualificado": ("Perdido", "Sem fit"),
}

# Etapa do funil de cada status (usada no funil, nas taxas e no pipeline).
ETAPA_DO_STATUS = {
    "Novo": 0, "Pesquisando": 0, "Abordagem criada": 0, "Contatado": 1, "Aguardando resposta": 1,
    "Respondeu": 2, "Interessado": 3, "Humano assumiu": 4, "Reunião": 5, "Negociação": 6,
    "Parceiro": 7, "Parceiro ativo": 8,
}
# Data gravada no lead quando ele chega pela primeira vez em cada etapa.
DATA_DA_ETAPA = {1: "contatado_em", 2: "respondeu_em", 3: "interessado_em", 4: "assumido_em",
                 5: "reuniao_em", 6: "proposta_em", 7: "convertido_em"}

COLUNAS_PIPELINE = [(s.lower().replace(" ", "-"), s, [s]) for s in STATUS_LEAD]

# Classificação das respostas dos leads (IA SDR).
CLASSES_RESPOSTA = [
    "INTERESSADO", "MUITO INTERESSADO", "QUER SABER MAIS", "QUER REUNIÃO", "QUER LIGAÇÃO", "QUER PROPOSTA",
    "QUER PREÇO", "JÁ POSSUI PARCEIRO", "SEM INTERESSE", "NÃO É RESPONSÁVEL", "PEDIU PARA ENVIAR E-MAIL",
    "PEDIU PARA ENVIAR WHATSAPP", "OBJEÇÃO", "OPT-OUT", "RESPOSTA INDEFINIDA", "RESPOSTA AUTOMÁTICA",
]
# Mensagem de robô/chatbot/ausência do lado do lead: não é resposta de gente. A SDR não responde (evita conversa
# de robô com robô), não vira oportunidade e a sequência continua.
CLASSE_AUTOMATICA = "RESPOSTA AUTOMÁTICA"
# Estas classes param a automação e viram oportunidade para o time humano.
CLASSES_QUENTES = ["INTERESSADO", "MUITO INTERESSADO", "QUER SABER MAIS", "QUER REUNIÃO", "QUER LIGAÇÃO",
                   "QUER PROPOSTA", "QUER PREÇO"]
# Estas também vão para o humano, mas como oportunidade "morna" (decidir se insiste).
CLASSES_MORNAS = ["JÁ POSSUI PARCEIRO", "OBJEÇÃO", "NÃO É RESPONSÁVEL", "RESPOSTA INDEFINIDA"]

FITS = ["Muito alto potencial", "Alto potencial", "Médio potencial", "Baixo potencial", "Sem fit"]

# Ângulos da cadência SDR: cada toque tem um foco diferente (nunca "viu minha mensagem?").
ANGULOS = {
    "apresentacao": "Apresentação da parceria",
    "praticidade": "Foco em praticidade para o parceiro e os clientes dele",
    "receita": "Foco em geração de receita recorrente",
    "encerramento": "Encerramento educado",
}
CTAS = [
    "Hoje vocês já trabalham com algum parceiro de certificação digital?",
    "Faz sentido conversarmos sobre isso?",
    "Quem seria a pessoa responsável por parcerias aí?",
    "Posso te explicar rapidamente como funciona?",
    "Vocês já possuem algo parecido?",
]
TONS = {"consultivo": "Consultivo e cordial", "direto": "Direto e objetivo", "informal": "Leve e informal"}

STATUS_PARCEIRO = ["ATIVO", "INATIVO", "EM ATIVAÇÃO", "BLOQUEADO"]
STATUS_CLIENTE = ["Indicado", "Em contato", "Emitido", "Perdido"]
STATUS_CERTIFICADO = ["Ativo", "Em renovação", "Renovado", "Vencido", "Não renovará"]
CANAIS = {"whatsapp": "WhatsApp", "ligacao": "Ligação", "email": "E-mail", "linkedin": "LinkedIn",
          "reuniao": "Reunião", "manual": "Contato manual", "auto": "Automático (IA escolhe)", "outro": "Outro"}
ESPECIALIDADES = ["Contabilidade empresarial", "Abertura de empresas", "Departamento pessoal",
                  "Fiscal/tributário", "MEI e pequenas empresas", "Terceiro setor", "Rural/agro",
                  "Médicos e profissionais liberais", "Consultoria contábil", "Outra"]
TIPOS_EMPRESA = ["Escritório de contabilidade", "Consultoria contábil", "Empresa de serviços contábeis",
                 "Contador autônomo"]
UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR",
       "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]
NOMES_UF = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}

# Configurações que o administrador altera na tela (guardadas no banco).
CONFIG_PADRAO = {
    "enviar_whatsapp_automatico": "1",  # só para quem já conversou/autorizou (campanhas.whatsapp_liberado)
    "mostrar_vendas": "0",
    "mostrar_agenda": "0",  # Agenda (follow-ups) oculta no menu e no Dashboard (pedido da MS)  # Vendas, Vencimentos e Comissões ocultos no menu e no Dashboard (pedido da MS)
    "empresa_nome": "MS Certificação Digital",
    "link_parceria": "https://mscertificados.com.br",
    "texto_comissao": "comissão por cada certificado emitido",
    "programa_parceria": (
        "Programa de parceria da MS Certificação Digital (Autoridade de Registro ICP-Brasil, "
        "mscertificados.com.br): o escritório contábil indica os clientes que precisam de certificado "
        "digital; a equipe da MS entra em contato e cuida de todo o processo (emissão e validação presencial "
        "em Recife ou por videoconferência); o escritório recebe comissão por certificado emitido; a MS "
        "controla os vencimentos e cuida das renovações, mantendo o escritório como parceiro."
    ),
    "limite_diario_whatsapp": "40",
    "limite_diario_email": "80",
    "horas_entre_contatos": "20",
    "pular_fim_de_semana": "1",
    "alertas_vencimento": "90,60,30,15,7",
    "dias_parceiro_parado": "30",
    "dias_lead_parado": "7",
    "dias_retencao_perdidos": "365",
    "custo_mensal_prospeccao": "0",
    # IA SDR
    "prioridade_canais": "whatsapp,email,linkedin",
    "limite_hora_email": "20",
    "limite_hora_whatsapp": "15",
    "limite_diario_campanha": "60",
    "limite_diario_dominio": "3",
    "horario_envio_inicio": "08:30",
    "horario_envio_fim": "18:00",
    "enviar_email_automatico": "1",        # depois da aprovação, a fila envia os e-mails sozinha
    "sdr_resposta_automatica": "1",        # responde "vou passar para o time" quando o canal permite
    "dias_sem_resposta": "3",              # dias após o último toque para marcar "Sem resposta"
    "aprovacao_obrigatoria": "1",
    "notificar_por_email": "1",
}

# Categorias de parceiros (o administrador cria outras na tela Categorias).
# Motivos para tirar uma empresa de uma campanha (obrigatório escolher um; fica guardado no toque e no histórico do lead)
MOTIVOS_RETIRADA = ["Já fiz campanha", "Já entramos em contato", "Não condiz com os objetivos da MS"]

# CNAEs que dá para escolher na Prospecção (filtro direto na base da Receita), em grupos de atividades parecidas
CNAES_BUSCA = {
    "Internet, dados e software": [
        ("6319400", "Portais, provedores de conteúdo e outros serviços de informação na internet"),
        ("6311900", "Tratamento de dados, provedores de aplicação e hospedagem na internet"),
        ("6201501", "Desenvolvimento de software sob encomenda"),
        ("6202300", "Desenvolvimento e licenciamento de software customizável"),
        ("6203100", "Desenvolvimento e licenciamento de software não customizável"),
        ("6204000", "Consultoria em tecnologia da informação"),
        ("6209100", "Suporte técnico, manutenção e outros serviços em TI"),
    ],
}

# cnaes: entram todas as empresas ativas com essa atividade principal.
# cnaes_com_palavra: só entram se o NOME tiver uma das palavras_chave (atividades genéricas demais).
# prioridade: a empresa fica na primeira categoria que combinar (menor número primeiro).
CATEGORIAS_PADRAO = [
    {"codigo": "contabil", "nome": "Escritórios contábeis", "prioridade": 50, "aderencia": 25, "recorrente": True,
     "cnaes": "6920601,6920602", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Atendem empresas o ano todo e são consultados quando o cliente precisa emitir ou renovar o certificado (e-CNPJ, e-CPF para eSocial, NF-e, SPED).",
     "estrategia": "Mensagem curta pelo WhatsApp ao sócio, citando o atendimento a empresas na cidade; perguntar se já têm parceiro de certificação.",
     "abertura": "Vi que a {{empresa}} trabalha com contabilidade para empresas aqui em {{cidade}}.",
     "gancho": "estamos ampliando nossa rede de parceiros justamente com escritórios contábeis. A ideia é simples: o escritório indica os clientes que precisam de certificado e nossa equipe cuida da emissão e do atendimento."},
    {"codigo": "condominio", "nome": "Administradoras de condomínios", "prioridade": 40, "aderencia": 20, "recorrente": True,
     "cnaes": "6822600", "cnaes_com_palavra": "8211300,8219999", "palavras_chave": "condom",
     "motivo": "Têm relacionamento recorrente com síndicos e condomínios, que precisam de certificado digital (e-CNPJ do condomínio) para folha, eSocial e obrigações fiscais.",
     "estrategia": "Abordar o gestor da administradora citando a carteira de condomínios; perguntar como o certificado é tratado hoje.",
     "abertura": "Vi que a {{empresa}} administra condomínios e trabalha diretamente com síndicos.",
     "gancho": "estamos estudando parcerias com empresas que têm relacionamento recorrente com esse público."},
    {"codigo": "nf", "nome": "Sistemas de emissão de nota fiscal", "prioridade": 10, "aderencia": 25, "recorrente": True,
     "cnaes": "", "cnaes_com_palavra": "6201501,6202300,6203100,6311900,6204000,6209100",
     "palavras_chave": "nota fiscal,nfe,nf-e,nfse,emissor,fiscal",
     "motivo": "Todo cliente de emissor de NF-e precisa de certificado digital válido para emitir notas: demanda recorrente e integrada ao produto.",
     "estrategia": "Parceria de tecnologia: perguntar se já possuem integração ou parceria com certificadora.",
     "abertura": "Vi que a {{empresa}} oferece uma plataforma de emissão de notas para empresas.",
     "gancho": "estamos buscando parceiros de tecnologia que atendam empresas com demanda recorrente por certificados digitais."},
    {"codigo": "software_contabil", "nome": "Software contábil", "prioridade": 11, "aderencia": 22, "recorrente": True,
     "cnaes": "", "cnaes_com_palavra": "6201501,6202300,6203100,6311900", "palavras_chave": "contab,contabil",
     "motivo": "Os clientes (escritórios contábeis) usam certificado no dia a dia para obrigações acessórias.",
     "estrategia": "Parceria de tecnologia e indicação para a base de escritórios usuários.",
     "abertura": "Vi que a {{empresa}} desenvolve software para a área contábil.",
     "gancho": "estamos ampliando nossa rede de parceiros de tecnologia e achei que poderia existir uma sinergia com a base de clientes de vocês."},
    {"codigo": "erp", "nome": "ERP / software empresarial", "prioridade": 60, "aderencia": 18, "recorrente": True,
     "cnaes": "6202300,6203100,6311900", "cnaes_com_palavra": "6201501", "palavras_chave": "erp,gestao,sistema",
     "motivo": "Software de gestão para PMEs: parte da base precisa de certificado para NF-e, folha e integrações fiscais.",
     "estrategia": "Abordar como parceria de tecnologia; perguntar se já trabalham com alguma certificadora.",
     "abertura": "Vi que a {{empresa}} oferece software de gestão para empresas.",
     "gancho": "estamos ampliando nossa rede de parceiros de tecnologia e achei que poderia existir uma sinergia com a base de clientes de vocês."},
    {"codigo": "bpo", "nome": "BPO financeiro", "prioridade": 12, "aderencia": 20, "recorrente": True,
     "cnaes": "", "cnaes_com_palavra": "8211300,8219999,7020400,6920602", "palavras_chave": "bpo,financ,terceiriz",
     "motivo": "Cuidam da rotina financeira de PMEs (notas, impostos, bancos), que depende de certificado digital.",
     "estrategia": "Mostrar praticidade: o cliente do BPO resolve o certificado sem sair da rotina.",
     "abertura": "Vi que a {{empresa}} cuida da rotina financeira de empresas.",
     "gancho": "estamos buscando parceiros que acompanham empresas de perto e conseguem indicar quem precisa de certificado digital."},
    {"codigo": "rh", "nome": "Empresas de RH / folha", "prioridade": 55, "aderencia": 15, "recorrente": True,
     "cnaes": "7810800,7820500,7830200", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Folha e eSocial exigem certificado digital das empresas clientes.",
     "estrategia": "Citar eSocial/folha e perguntar como os clientes resolvem o certificado hoje.",
     "abertura": "Vi que a {{empresa}} trabalha com RH e gestão de pessoas para empresas.",
     "gancho": "estamos ampliando nossa rede de parceiros com empresas que atendem outras empresas de forma recorrente."},
    {"codigo": "consultoria", "nome": "Consultorias empresariais", "prioridade": 70, "aderencia": 10, "recorrente": False,
     "cnaes": "7020400", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Atendem empresas em projetos de gestão; potencial de indicação pontual.",
     "estrategia": "Abordagem consultiva perguntando quem cuida de parcerias.",
     "abertura": "Vi que a {{empresa}} presta consultoria para empresas.",
     "gancho": "estamos ampliando nossa rede de parceiros B2B."},
    {"codigo": "despachante", "nome": "Despachantes", "prioridade": 13, "aderencia": 15, "recorrente": True,
     "cnaes": "5250802", "cnaes_com_palavra": "8299799,8219999,8211300", "palavras_chave": "despach",
     "motivo": "Lidam com documentação de empresas e pessoas; o certificado aparece em vários desses processos.",
     "estrategia": "Mensagem direta perguntando se os clientes pedem certificado e como resolvem.",
     "abertura": "Vi que a {{empresa}} cuida de documentação e processos para clientes.",
     "gancho": "estamos buscando parceiros que atendem clientes com demanda por certificado digital."},
    {"codigo": "tecnologia", "nome": "Empresas de tecnologia", "prioridade": 65, "aderencia": 10, "recorrente": False,
     "cnaes": "6204000,6209100", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Atendem empresas com serviços de TI; podem indicar ou integrar certificado digital.",
     "estrategia": "Descobrir o responsável por parcerias antes de explicar a proposta.",
     "abertura": "Vi que a {{empresa}} oferece soluções de tecnologia para empresas.",
     "gancho": "estamos ampliando nossa rede de parceiros de tecnologia."},
    {"codigo": "internet", "nome": "Portais e serviços de internet", "prioridade": 66, "aderencia": 10,
     "recorrente": False, "cnaes": "6319400", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Portais, provedores de conteúdo e serviços de informação na internet (CNAE 6319-4/00): têm audiência "
               "e base de empresas que usam certificado digital.",
     "estrategia": "Descobrir quem cuida de parcerias e se o portal atende empresas (B2B) antes de explicar a proposta.",
     "abertura": "Vi que a {{empresa}} atua com serviços e conteúdo na internet.",
     "gancho": "estamos ampliando nossa rede de parceiros digitais."},
    {"codigo": "associacao", "nome": "Associações empresariais", "prioridade": 30, "aderencia": 18, "recorrente": True,
     "cnaes": "9411100", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Reúnem muitas empresas associadas; uma parceria pode virar benefício para todos os associados.",
     "estrategia": "Propor condição para associados; perguntar quem cuida de convênios e benefícios.",
     "abertura": "Vi que a {{empresa}} reúne empresas associadas aqui em {{cidade}}.",
     "gancho": "estamos buscando entidades que queiram oferecer certificado digital como benefício para os associados."},
    {"codigo": "coworking", "nome": "Coworkings", "prioridade": 14, "aderencia": 12, "recorrente": True,
     "cnaes": "", "cnaes_com_palavra": "8211300,6810202,7490104,8219999", "palavras_chave": "cowork",
     "motivo": "Concentram pequenas empresas e profissionais que abrem CNPJ e precisam de certificado.",
     "estrategia": "Propor benefício para os membros; perguntar quem cuida de parcerias.",
     "abertura": "Vi que a {{empresa}} reúne empresas e profissionais no coworking de vocês.",
     "gancho": "estamos buscando parceiros que queiram oferecer certificado digital como benefício para os membros."},
    {"codigo": "franquia", "nome": "Franquias (franqueadoras)", "prioridade": 35, "aderencia": 12, "recorrente": True,
     "cnaes": "7740300", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Cada unidade franqueada é uma empresa que precisa de certificado; acordo com a franqueadora alcança toda a rede.",
     "estrategia": "Falar com expansão/suprimentos da franqueadora; propor atendimento para a rede.",
     "abertura": "Vi que a {{empresa}} tem uma rede de unidades franqueadas.",
     "gancho": "estamos buscando parceiros com redes de empresas que possam ter demanda por certificados digitais."},
    {"codigo": "servicos_pme", "nome": "Empresas de serviços para PMEs", "prioridade": 75, "aderencia": 8, "recorrente": False,
     "cnaes": "8291100,7490104", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Prestam serviços a pequenas empresas; indicação ocasional.",
     "estrategia": "Abordagem genérica pedindo o responsável por parcerias.",
     "abertura": "Vi que a {{empresa}} trabalha diretamente com empresas.",
     "gancho": "estamos ampliando nossa rede de parceiros B2B."},
    {"codigo": "restaurante", "nome": "Restaurantes e lanchonetes", "prioridade": 80, "aderencia": 6,
     "recorrente": False, "cnaes": "5611201,5611203", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Restaurantes e lanchonetes (CNAE 5611-2/01 e 5611-2/03) emitem NFC-e e precisam de e-CNPJ; conhecem "
               "fornecedores e outros donos de restaurante que também precisam.",
     "estrategia": "Falar com o dono ou o gerente; foco na NFC-e e no certificado que não pode vencer no meio do mês.",
     "abertura": "Vi que a {{empresa}} trabalha com alimentação aqui na região.",
     "gancho": "estamos ampliando nossa rede de parceiros no setor de alimentação."},
    {"codigo": "outros", "nome": "Outros", "prioridade": 99, "aderencia": 0, "recorrente": False,
     "cnaes": "", "cnaes_com_palavra": "", "palavras_chave": "",
     "motivo": "Sem motivo específico identificado.",
     "estrategia": "Abordagem genérica pedindo o responsável por parcerias.",
     "abertura": "Conheci a {{empresa}} e vi que vocês trabalham diretamente com empresas.",
     "gancho": "estamos ampliando nossa rede de parceiros B2B."},
]

# Produtos iniciais: preços da tabela MS (MS_Tabela_de_Precos_editavel.pdf, out/2026).
# O custo fica 0 até o administrador informar (não inventamos custo).
PRODUTOS_PADRAO = [
    ("e-CPF A1 (1 ano)", 150, 12), ("e-CNPJ A1 (1 ano)", 200, 12), ("NF-e A1 (1 ano)", 200, 12),
    ("e-CPF A3 token (1 ano)", 355, 12), ("e-CNPJ A3 token (1 ano)", 435, 12),
    ("e-CPF A3 sem mídia (3 anos)", 250, 36), ("e-CNPJ A3 sem mídia (3 anos)", 340, 36),
    ("e-CNPJ A3 token (3 anos)", 540, 36), ("e-CPF A1 (6 meses)", 100, 6), ("e-CNPJ A1 (6 meses)", 150, 6),
]
COMISSAO_PADRAO_PERCENTUAL = 20  # ajuste na tela Comissões
