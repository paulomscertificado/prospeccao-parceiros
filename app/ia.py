"""Camada de IA (Claude, da Anthropic).

Funções: gerar abordagem personalizada, sugerir o próximo passo, resumir histórico, analisar a resposta
do lead (objeções + resposta sugerida), criar templates de campanha e responder perguntas na IA Comercial.

Sem chave configurada (ANTHROPIC_API_KEY no .env), cada função usa regras próprias: o sistema continua
funcionando, só com textos menos personalizados.
"""

import json
import logging
from datetime import date

from sqlalchemy.orm import Session

from . import config, mensagens, score, util
from .banco import ler_config
from .modelos import Lead, Usuario

log = logging.getLogger(__name__)

REGRAS = """Você é especialista em prospecção B2B da MS Certificação Digital e ajuda vendedores a
conquistar escritórios de contabilidade como PARCEIROS comerciais recorrentes.

Regras obrigatórias:
- Escreva em português do Brasil, tom cordial, humano e profissional. Nada de cara de spam: sem exageros,
  sem CAIXA ALTA, sem promessas de ganhos, no máximo 1 emoji (ou nenhum).
- Use SOMENTE os dados fornecidos. Nunca invente nomes, números, clientes, prêmios ou fatos sobre o escritório.
  Se não souber o nome do responsável, cumprimente sem nome.
- Mensagens de WhatsApp: curtas (até ~700 caracteres), terminam com UMA pergunta simples e aberta.
- Primeiro contato sempre oferece uma saída educada (ex.: "se não fizer sentido, é só me avisar").
- Respeite a LGPD: não peça dados pessoais desnecessários.
"""


class ErroDaIA(Exception):
    """Erro com texto pronto para mostrar na tela."""


def disponivel() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def criar_cliente():
    """Cliente da Anthropic. Os testes trocam esta função por uma IA de mentira."""
    import anthropic

    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=2, timeout=90.0)


def _contexto_empresa(db: Session) -> str:
    return (f"{ler_config(db, 'programa_parceria')}\nComissão: {ler_config(db, 'texto_comissao')}.\n"
            f"Link da parceria: {ler_config(db, 'link_parceria')}")


def perguntar(db: Session, pedido: str, esquema: dict | None = None, max_tokens: int = 4000):
    """Chama o Claude. Com esquema, devolve dict (JSON validado); sem esquema, devolve texto."""
    import anthropic

    sistema = [{"type": "text", "text": REGRAS + "\nSOBRE A MS E O PROGRAMA DE PARCERIA:\n" + _contexto_empresa(db),
                "cache_control": {"type": "ephemeral"}}]
    opcoes = {"effort": "low"}
    if esquema:
        opcoes["format"] = {"type": "json_schema", "schema": esquema}
    try:
        resposta = criar_cliente().messages.create(
            model=config.IA_MODELO, max_tokens=max_tokens, system=sistema,
            messages=[{"role": "user", "content": pedido}], output_config=opcoes)
    except anthropic.AuthenticationError:
        raise ErroDaIA("A chave da IA está errada. Confira ANTHROPIC_API_KEY no arquivo .env.") from None
    except anthropic.PermissionDeniedError:
        raise ErroDaIA("A chave da IA não tem permissão para usar esse modelo.") from None
    except anthropic.NotFoundError:
        raise ErroDaIA(f"O modelo {config.IA_MODELO} não foi encontrado. Confira IA_MODELO no .env.") from None
    except anthropic.RateLimitError:
        raise ErroDaIA("A IA está recebendo pedidos demais agora. Tente de novo em um minuto.") from None
    except anthropic.BadRequestError as erro:
        if "credit" in str(erro).lower():
            raise ErroDaIA("Acabaram os créditos da IA. Coloque créditos em console.anthropic.com.") from None
        raise ErroDaIA(f"A IA recusou o pedido ({str(erro)[:150]}).") from None
    except anthropic.APIConnectionError:
        raise ErroDaIA("Sem conexão com a IA. Confira a internet.") from None
    except anthropic.APIStatusError as erro:
        raise ErroDaIA(f"A IA está com problema agora (erro {erro.status_code}). Tente de novo depois.") from None
    if resposta.stop_reason == "refusal":
        raise ErroDaIA("A IA preferiu não responder esse pedido.")
    texto = next((b.text for b in resposta.content if b.type == "text"), "").strip()
    if not esquema:
        return texto
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        raise ErroDaIA("A IA respondeu num formato inesperado. Tente de novo.") from None


def ficha_do_lead(lead: Lead) -> str:
    """Somente dados empresariais/públicos que ajudam a personalizar (sem telefone nem e-mail)."""
    campos = [
        ("Empresa", lead.empresa), ("Responsável", lead.responsavel), ("Cargo", lead.cargo),
        ("Cidade", f"{lead.cidade}/{lead.estado}".strip("/")), ("Site", lead.site), ("Instagram", lead.instagram),
        ("LinkedIn", "sim" if lead.linkedin else ""), ("Especialidade", lead.especialidade),
        ("Tipo", lead.tipo_empresa), ("Clientes estimados", lead.qtd_clientes_estimada),
        ("Funcionários", lead.funcionarios), ("Sócios", "mais de um" if lead.multiplos_socios else ""),
        ("Atende empresas", "sim" if lead.atende_empresas else ""),
        ("Equipe comercial", "sim" if lead.equipe_comercial else ""),
        ("Status no funil", lead.status), ("Score", f"{lead.score} ({lead.potencial})"),
        ("Observações do vendedor", lead.observacoes[:600] if lead.observacoes else ""),
    ]
    return "\n".join(f"{k}: {v}" for k, v in campos if v not in (None, ""))


def _texto_historico(itens) -> str:
    return "\n".join(f"- {h.criado_em:%d/%m/%Y} [{h.tipo}{'/' + h.canal if h.canal else ''}] {h.descricao[:300]}"
                     for h in itens[-30:]) or "(sem histórico)"


# ---------------------------------------------------------------- 1. Abordagem personalizada

ESQUEMA_ABORDAGEM = {
    "type": "object",
    "properties": {
        "motivos": {"type": "array", "items": {"type": "string"}},
        "melhor_abordagem": {"type": "string"},
        "canal_recomendado": {"type": "string", "enum": ["whatsapp", "ligacao", "email", "linkedin"]},
        "mensagem_whatsapp": {"type": "string"},
        "assunto_email": {"type": "string"},
        "mensagem_email": {"type": "string"},
    },
    "required": ["motivos", "melhor_abordagem", "canal_recomendado", "mensagem_whatsapp", "assunto_email",
                 "mensagem_email"],
    "additionalProperties": False,
}


def canal_recomendado(lead: Lead) -> str:
    if lead.whatsapp:
        return "whatsapp"
    if lead.telefone:
        return "ligacao"
    if lead.email:
        return "email"
    return "linkedin"


def abordagem_por_regras(db: Session, lead: Lead, usuario: Usuario | None) -> dict:
    _, _, detalhes = score.calcular(db, lead)
    motivos = [f"+{p} {d}" for d, p, ok in detalhes if ok] or ["Poucos dados públicos ainda: vale pesquisar mais."]
    canal = canal_recomendado(lead)
    foco = "atendimento a empresas" if lead.atende_empresas else (lead.especialidade or "contabilidade")
    abordagem = {
        "whatsapp": f"Começar pelo WhatsApp, citando o foco em {foco.lower()} e perguntando se já têm parceiro de certificação.",
        "ligacao": "Ligar no horário comercial (9h–11h ou 14h–16h), apresentar a parceria em 1 minuto e propor reunião curta.",
        "email": "Enviar e-mail curto com a proposta de parceria e um convite para conversa de 15 minutos.",
        "linkedin": "Conectar no LinkedIn com o sócio e depois enviar mensagem curta sobre a parceria.",
    }[canal]
    t_whats = mensagens.template_padrao(db, "whatsapp")
    t_email = mensagens.template_padrao(db, "email")
    _, whats = mensagens.montar(db, t_whats, lead, usuario)
    assunto, email = mensagens.montar(db, t_email, lead, usuario)
    return {"motivos": motivos, "melhor_abordagem": abordagem, "canal_recomendado": canal,
            "mensagem_whatsapp": whats, "assunto_email": assunto, "mensagem_email": email, "fonte": "regras"}


def gerar_abordagem(db: Session, lead: Lead, usuario: Usuario | None) -> dict:
    if not disponivel():
        return abordagem_por_regras(db, lead, usuario)
    vendedor = util.primeiro_nome(usuario.nome) if usuario else "a equipe"
    pedido = (f"Analise o escritório abaixo e crie uma abordagem personalizada de parceria.\n"
              f"Vendedor que vai assinar: {vendedor}.\n\nDADOS DO ESCRITÓRIO:\n{ficha_do_lead(lead)}\n\n"
              "Devolva: motivos (por que é um bom ou mau candidato, com base nos dados), melhor abordagem "
              "(1–2 frases), canal recomendado, mensagem de WhatsApp e e-mail (assunto + corpo) personalizados.")
    dados = perguntar(db, pedido, ESQUEMA_ABORDAGEM)
    dados["fonte"] = "ia"
    return dados


# ---------------------------------------------------------------- 2. Próximo melhor passo

ESQUEMA_PASSO = {
    "type": "object",
    "properties": {
        "proximo_passo": {"type": "string"},
        "canal": {"type": "string", "enum": ["whatsapp", "ligacao", "email", "linkedin", "reuniao", "nenhum"]},
        "quando": {"type": "string"},
        "justificativa": {"type": "string"},
        "mensagem_sugerida": {"type": "string"},
        "temperatura": {"type": "string", "enum": ["quente", "morno", "frio"]},
        "resumo_historico": {"type": "string"},
    },
    "required": ["proximo_passo", "canal", "quando", "justificativa", "mensagem_sugerida", "temperatura",
                 "resumo_historico"],
    "additionalProperties": False,
}


def passo_por_regras(lead: Lead, itens) -> dict:
    s = lead.status
    tabela = {
        "Novo": ("Pesquisar o escritório e fazer o primeiro contato", canal_recomendado(lead), "hoje"),
        "Pesquisando": ("Concluir a pesquisa e criar a abordagem", canal_recomendado(lead), "hoje"),
        "Abordagem criada": ("Fazer o primeiro contato", canal_recomendado(lead), "hoje"),
        "Contatado": ("Fazer follow-up com um ângulo novo (praticidade)", "whatsapp" if lead.whatsapp else "email", "em 2 dias"),
        "Aguardando resposta": ("Tentar outro canal (ligação ou e-mail)", "ligacao" if lead.telefone else "email", "amanhã"),
        "Respondeu": ("Entender a necessidade e propor uma reunião de 15 minutos", "ligacao", "hoje"),
        "Interessado": ("Agendar reunião para apresentar o programa de parceria", "reuniao", "esta semana"),
        "Humano assumiu": ("Ligar ou chamar no WhatsApp e marcar a reunião", "ligacao", "hoje"),
        "Reunião": ("Confirmar a reunião na véspera e preparar a proposta", "whatsapp", "véspera da reunião"),
        "Negociação": ("Resolver as objeções e fechar a parceria", "ligacao", "hoje"),
        "Parceiro": ("Fazer o onboarding e pedir a primeira indicação", "reuniao", "esta semana"),
        "Parceiro ativo": ("Acompanhar indicações e avisar sobre vencimentos da carteira", "whatsapp", "mensalmente"),
    }
    passo, canal, quando = tabela.get(s, ("Nenhum contato: lead encerrado", "nenhum", "-"))
    if lead.opt_out:
        passo, canal, quando = "Não contatar: o lead pediu opt-out", "nenhum", "-"
    temperatura = "quente" if lead.etapa >= 3 else ("morno" if lead.etapa == 2 or lead.score >= 61 else "frio")
    ultimos = [h.descricao for h in itens[-3:]]
    return {"proximo_passo": passo, "canal": canal, "quando": quando,
            "justificativa": f"Regra pelo status atual ({s}) e score {lead.score}.",
            "mensagem_sugerida": "", "temperatura": temperatura,
            "resumo_historico": " | ".join(ultimos) or "Sem histórico.", "fonte": "regras"}


def proximo_passo(db: Session, lead: Lead, itens) -> dict:
    if not disponivel() or lead.opt_out:
        return passo_por_regras(lead, itens)
    pedido = (f"Hoje é {util.data_br(date.today())}. Com base nos dados e no histórico "
              f"do lead, diga qual é o próximo melhor passo comercial, resuma o histórico em 2 frases e "
              f"classifique a temperatura.\n\nDADOS:\n{ficha_do_lead(lead)}\n\nHISTÓRICO:\n{_texto_historico(itens)}")
    dados = perguntar(db, pedido, ESQUEMA_PASSO)
    dados["fonte"] = "ia"
    return dados


# ---------------------------------------------------------------- 3. Analisar a resposta do lead (objeções)

ESQUEMA_RESPOSTA = {
    "type": "object",
    "properties": {
        "interesse": {"type": "string", "enum": ["quente", "morno", "frio", "pediu para sair"]},
        "objecoes": {"type": "array", "items": {"type": "string"}},
        "status_sugerido": {"type": "string", "enum": config.STATUS_LEAD},
        "resposta_sugerida": {"type": "string"},
    },
    "required": ["interesse", "objecoes", "status_sugerido", "resposta_sugerida"],
    "additionalProperties": False,
}

OBJECOES_CONHECIDAS = [
    (("ja temos", "já temos", "ja trabalhamos", "já trabalhamos", "outro parceiro", "outra certificadora"),
     "Já tem parceiro de certificação",
     "Que bom que vocês já oferecem! Muitos escritórios trabalham com mais de uma opção para comparar prazo e "
     "atendimento. Posso te mostrar em 10 minutos como funciona nosso controle de renovação e a comissão?"),
    (("preco", "preço", "caro", "valor"), "Preço",
     "Entendo. Nossos valores seguem a tabela da MS e o escritório ainda recebe comissão por certificado. "
     "Posso te enviar a tabela e um exemplo de quanto a carteira de vocês pode gerar?"),
    (("sem tempo", "corrido", "depois", "mais tarde", "outro momento"), "Falta de tempo",
     "Sem problema! A parceria foi pensada para não dar trabalho: vocês só indicam, nós fazemos o resto. "
     "Qual seria um bom dia para uma conversa rápida de 10 minutos?"),
    (("email", "e-mail", "manda", "envia"), "Pediu material",
     "Claro! Vou te enviar um resumo da parceria. Para quem posso mandar?"),
    (("nao temos interesse", "não temos interesse", "nao tenho interesse", "não tenho interesse", "nao precisamos",
      "não precisamos"), "Sem interesse",
     "Entendido, obrigado pelo retorno! Se no futuro fizer sentido, fico à disposição."),
    (("quanto", "comissao", "comissão", "como funciona"), "Quer saber como funciona",
     "Funciona assim: vocês indicam, nossa equipe atende e emite, e o escritório recebe comissão por certificado. "
     "Posso te explicar os detalhes numa ligação rápida?"),
]


def resposta_por_regras(texto: str) -> dict:
    t = util.chave_texto(texto)
    if mensagens.pede_opt_out(texto):
        return {"interesse": "pediu para sair", "objecoes": ["Pediu para não receber mensagens"],
                "status_sugerido": "Perdido",
                "resposta_sugerida": "Combinado, não enviaremos mais mensagens. Obrigado!", "fonte": "regras"}
    objecoes, resposta = [], ""
    for chaves, nome, sugestao in OBJECOES_CONHECIDAS:
        if any(util.chave_texto(c) in t for c in chaves):
            objecoes.append(nome)
            resposta = resposta or sugestao
    if "Sem interesse" in objecoes:
        return {"interesse": "frio", "objecoes": objecoes, "status_sugerido": "Perdido",
                "resposta_sugerida": resposta, "fonte": "regras"}
    positivo = any(p in t for p in ("interess", "sim", "pode", "vamos", "gostaria", "quero", "bora", "claro"))
    return {"interesse": "quente" if positivo else "morno", "objecoes": objecoes,
            "status_sugerido": "Interessado" if positivo else "Respondeu",
            "resposta_sugerida": resposta or "Obrigado pelo retorno! Qual o melhor horário para uma conversa rápida de 10 minutos?",
            "fonte": "regras"}


def analisar_resposta(db: Session, lead: Lead, texto: str, itens) -> dict:
    if not disponivel():
        return resposta_por_regras(texto)
    pedido = (f"O lead respondeu a nossa prospecção. Classifique o interesse, liste as objeções, sugira o novo "
              f"status do funil e escreva uma resposta curta para o vendedor enviar.\n\nRESPOSTA DO LEAD:\n"
              f"\"\"\"{texto[:2000]}\"\"\"\n\nDADOS:\n{ficha_do_lead(lead)}\n\nHISTÓRICO:\n{_texto_historico(itens)}")
    dados = perguntar(db, pedido, ESQUEMA_RESPOSTA)
    dados["fonte"] = "ia"
    return dados


# ---------------------------------------------------------------- 4. Criar template de campanha

ESQUEMA_TEMPLATE = {
    "type": "object",
    "properties": {"nome": {"type": "string"}, "assunto": {"type": "string"}, "corpo": {"type": "string"}},
    "required": ["nome", "assunto", "corpo"],
    "additionalProperties": False,
}


def criar_template(db: Session, canal: str, objetivo: str) -> dict:
    if not disponivel():
        raise ErroDaIA("Para criar templates com IA, configure ANTHROPIC_API_KEY no arquivo .env.")
    variaveis = ", ".join("{{" + v + "}}" for v in mensagens.VARIAVEIS)
    pedido = (f"Crie um template de mensagem para o canal {config.CANAIS.get(canal, canal)} com este objetivo: "
              f"{objetivo}\nUse as variáveis (exatamente assim, com chaves duplas) quando fizer sentido: {variaveis}.\n"
              "Para WhatsApp e LinkedIn deixe o assunto vazio.")
    return perguntar(db, pedido, ESQUEMA_TEMPLATE)


# ---------------------------------------------------------------- 5. IA Comercial (perguntas livres)

def responder_pergunta(db: Session, pergunta: str, dados_do_sistema: str) -> str:
    if not disponivel():
        raise ErroDaIA("Para perguntas livres, configure ANTHROPIC_API_KEY no .env. "
                       "Enquanto isso, use as perguntas prontas ao lado (funcionam sem IA).")
    pedido = (f"Responda a pergunta do gestor comercial usando SOMENTE os dados do sistema abaixo. "
              f"Se os dados não bastarem, diga o que falta. Seja direto, use listas curtas e números.\n\n"
              f"PERGUNTA: {pergunta[:1000]}\n\nDADOS DO SISTEMA (gerados agora):\n{dados_do_sistema}")
    return perguntar(db, pedido, max_tokens=3000)
