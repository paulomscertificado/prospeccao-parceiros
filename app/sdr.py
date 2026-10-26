"""IA SDR: a IA NÃO é o vendedor. Ela encontra, chama a atenção, gera resposta, qualifica e ENTREGA
a oportunidade ao time humano.

- escolher_canal: canal com mais chance de resposta, na ordem definida pelo administrador.
- gerar_mensagens: mensagem ÚNICA por empresa para cada toque da cadência (4 ângulos diferentes).
- classificar_resposta / processar_resposta: entende a resposta (15 classes) e decide o que fazer.
- Interesse → PARA a automação, cria OPORTUNIDADE, avisa o responsável (handoff).
- assumir_lead: o humano assume e toda automação daquele lead para na hora.

Limites da IA (prompt + conferência depois): não negocia preço nem comissão, não dá desconto,
não promete exclusividade, não aceita condições, não fecha parceria. Nesses casos: humano.
"""

import json
import logging
import re

from sqlalchemy import select

from . import config, ia, mensagens, util
from .banco import agora, ler_config
from .leads_servico import cancelar_tarefas_de_prospeccao, historico, mudar_status, registrar_opt_out
from .modelos import Conhecimento, Lead, Mensagem, Notificacao, Oportunidade, Tarefa, Usuario

log = logging.getLogger(__name__)

FRASES_PROIBIDAS = ["gostaria de apresentar nossa empresa", "excelente oportunidade", "líderes de mercado",
                    "lideres de mercado", "oportunidade imperdível", "oportunidade unica", "oportunidade única",
                    "promoção", "não perca", "nao perca"]
RE_NEGOCIACAO = re.compile(r"R\$\s*\d|\d+\s*%|\bdesconto|\bexclusiv|\bcontrato\b|\bgarant[oi]mos\b", re.I)
RODAPE_OPT_OUT = "(Se não fizer sentido para vocês, é só me avisar que não envio mais mensagens.)"
ASSUNTOS = {
    "apresentacao": "Possível parceria — MS Certificação Digital + {empresa}",
    "praticidade": "Certificado digital para os clientes da {empresa}, sem trabalho para vocês",
    "receita": "Receita recorrente com os certificados dos seus clientes",
    "encerramento": "Encerrando meu contato — MS Certificação Digital",
}
TEXTO_HANDOFF = ("Claro! Para não te passar informações incompletas, vou pedir para nosso time comercial falar "
                 "diretamente com você. Você prefere que eles entrem em contato por WhatsApp, ligação ou que a gente "
                 "marque uma conversa rápida?")


# ---------------------------------------------------------------- Canal

def ordem_canais(db) -> list[str]:
    ordem = [c.strip() for c in ler_config(db, "prioridade_canais").split(",") if c.strip()]
    return ordem or ["whatsapp", "email", "linkedin"]


def escolher_canal(db, lead: Lead, permitidos: list[str] | None = None) -> str:
    """Primeiro canal da prioridade configurada que o lead tem (e que a campanha permite)."""
    if lead.canal_preferido and (not permitidos or lead.canal_preferido in permitidos):
        disponivel = {"whatsapp": lead.whatsapp, "email": lead.email, "linkedin": lead.linkedin,
                      "ligacao": lead.telefone}.get(lead.canal_preferido)
        if disponivel:
            return lead.canal_preferido
    for canal in ordem_canais(db):
        if permitidos and canal not in permitidos:
            continue
        if {"whatsapp": lead.whatsapp, "email": lead.email, "linkedin": lead.linkedin}.get(canal):
            return canal
    return "ligacao" if lead.telefone else "manual"


# ---------------------------------------------------------------- Mensagens

def ramo_confirmado(lead: Lead) -> bool:
    """A categoria descreve mesmo o negócio desta empresa? Categorias com palavras-chave (ex.: condomínios)
    têm atividades na Receita que misturam outros ramos: só confirmamos com a palavra no nome ou no site."""
    cat = lead.categoria
    if not cat or cat.codigo == "outros":
        return False
    palavras = [util.chave_texto(p) for p in cat.lista("palavras_chave")]
    if not palavras:
        return True  # a atividade (CNAE) já descreve o ramo (ex.: contabilidade)
    perfil = json.loads(lead.perfil) if lead.perfil else {}
    especialidade = "" if util.chave_texto(lead.especialidade or "") == util.chave_texto(cat.nome) else lead.especialidade
    # Evidência só do que foi lido de verdade: nome, especialidade informada, público achado no site e,
    # quando a IA leu o site, o segmento descrito por ela.
    segmento = perfil.get("segmento", "") if perfil.get("fonte") == "ia" else ""
    texto = util.chave_texto(" ".join([lead.empresa or "", especialidade or "", segmento or "",
                                      perfil.get("publico", "") or ""]))
    return any(p in texto for p in palavras)


def _valores(db, lead: Lead, usuario) -> dict:
    v = mensagens.valores_variaveis(db, lead, usuario)
    cat = lead.categoria
    if ramo_confirmado(lead):
        v["abertura"] = mensagens.aplicar_variaveis(cat.abertura, v)
        v["gancho"] = cat.gancho
    else:  # modelo de negócio não confirmado: abordagem genérica (não inventa)
        v["abertura"] = mensagens.aplicar_variaveis(
            "Conheci a {{empresa}} e vi que vocês trabalham diretamente com empresas.", v)
        v["gancho"] = "estamos ampliando nossa rede de parceiros B2B."
    return v


def mensagens_por_regras(db, lead: Lead, usuario, cta: str = "") -> dict:
    """Mensagens de cada ângulo montadas com os dados reais do lead e da categoria (sem IA)."""
    v = _valores(db, lead, usuario)
    generico = not ramo_confirmado(lead)
    cta = cta or ("Queria entender com quem posso falar sobre possíveis parcerias comerciais na empresa."
                  if generico else config.CTAS[0])
    ola = f"Olá, {v['nome']}! Tudo bem?" if v["nome"] else "Olá! Tudo bem?"
    textos = {
        "apresentacao": f"{ola}\n\n{v['abertura']}\n\nSou {v['vendedor']}, da MS Certificação Digital, e {v['gancho']}"
                        f"\n\n{cta}\n\n{RODAPE_OPT_OUT}",
        "praticidade": f"Olá{', ' + v['nome'] if v['nome'] else ''}! Retomando meu contato sobre a parceria com a MS "
                       f"Certificação Digital: a ideia é tirar esse assunto das costas de vocês. Quando um cliente da "
                       f"{v['empresa']} precisar de certificado, basta indicar — nossa equipe faz o atendimento, a "
                       f"validação (presencial em Recife ou por videoconferência) e avisa antes do vencimento.\n\n"
                       f"Faz sentido conversarmos sobre isso?",
        "receita": f"Olá{', ' + v['nome'] if v['nome'] else ''}! Um ponto que costuma chamar a atenção dos nossos "
                   f"parceiros: cada certificado indicado gera remuneração para o parceiro, e as renovações dos anos "
                   f"seguintes também — a MS controla os vencimentos.\n\nQuem seria a pessoa responsável por "
                   f"parcerias aí na {v['empresa']}?",
        "encerramento": f"Olá{', ' + v['nome'] if v['nome'] else ''}! Para não ficar insistindo, este é meu último "
                        f"contato sobre a parceria com a MS Certificação Digital. Se em algum momento fizer sentido "
                        f"oferecer certificado digital aos clientes da {v['empresa']}, é só responder esta mensagem. "
                        f"Obrigado!",
    }
    assinatura = f"\n\n{v['vendedor']}\nMS Certificação Digital · mscertificados.com.br"
    resultado = {a: {"whatsapp": t, "assunto": ASSUNTOS[a].format(empresa=v["empresa"]), "email": t + assinatura,
                     "fonte": "regras"} for a, t in textos.items()}
    if not generico and lead.categoria:
        _usar_modelos_do_segmento(db, lead, v, resultado)
    return resultado


def _usar_modelos_do_segmento(db, lead: Lead, v: dict, resultado: dict) -> None:
    """Troca os textos-base pelos modelos do segmento (Cadências > Templates), escolhendo um modelo por toque de
    acordo com a empresa: assim cada empresa da campanha recebe uma variação diferente."""
    from .modelos import Template

    modelos = db.execute(select(Template).where(Template.ativo.is_(True), Template.categoria == lead.categoria.codigo,
                                                Template.angulo != "").order_by(Template.id)).scalars().all()
    for angulo, msgs in resultado.items():
        for canal in ("whatsapp", "email"):
            opcoes = [m for m in modelos if m.angulo == angulo and m.canal == canal]
            if not opcoes:
                continue
            m = opcoes[(lead.id or 0) % len(opcoes)]
            corpo = mensagens.aplicar_variaveis(m.corpo, v)
            if not texto_seguro(corpo):
                continue
            msgs[canal] = corpo
            if canal == "email" and m.assunto:
                msgs["assunto"] = mensagens.aplicar_variaveis(m.assunto, v)
        msgs["fonte"] = "modelos do segmento"


ESQUEMA_MENSAGENS = {
    "type": "object",
    "properties": {
        a: {"type": "object", "properties": {"whatsapp": {"type": "string"}, "assunto": {"type": "string"},
                                             "email": {"type": "string"}},
            "required": ["whatsapp", "assunto", "email"], "additionalProperties": False}
        for a in config.ANGULOS
    } | {"fatos_usados": {"type": "array", "items": {"type": "string"}}},
    "required": list(config.ANGULOS) + ["fatos_usados"],
    "additionalProperties": False,
}


def texto_seguro(texto: str) -> bool:
    t = (texto or "").lower()
    return bool(texto) and not any(f in t for f in FRASES_PROIBIDAS) and not RE_NEGOCIACAO.search(texto or "")


def gerar_mensagens(db, lead: Lead, usuario, cta: str = "", tom: str = "consultivo") -> dict:
    """Mensagens únicas da empresa para os 4 toques. IA quando houver chave; senão, regras."""
    base = mensagens_por_regras(db, lead, usuario, cta)
    if not ia.disponivel():
        return base
    perfil = json.loads(lead.perfil) if lead.perfil else {}
    fatos = {k: perfil.get(k) for k in ("segmento", "publico", "produtos", "servicos", "clientes_estimados",
                                        "perfil_clientes", "programa_parceiros", "integracoes", "diferenciais",
                                        "motivo_para_indicar_certificado") if perfil.get(k)}
    cat = lead.categoria
    vendedor = util.primeiro_nome(usuario.nome) if usuario and usuario.perfil != "parceiro" else "a equipe"
    pedido = (
        "Você é a SDR virtual da MS Certificação Digital. Objetivo do contato: CONSEGUIR UMA RESPOSTA, não vender.\n"
        "Escreva 4 mensagens (uma por toque da cadência) para ESTA empresa, cada uma com ângulo diferente:\n"
        + "\n".join(f"- {a}: {d}" for a, d in config.ANGULOS.items()) +
        "\nCada mensagem: contexto real da empresa + motivo do contato + benefício potencial + UMA pergunta simples "
        "(CTA de baixa fricção). WhatsApp até 600 caracteres; e-mail curto (até 900) com assunto.\n"
        "Primeira mensagem termina com saída educada (ex.: se não fizer sentido, é só avisar). Follow-ups NUNCA "
        "perguntam 'viu minha mensagem?'. O último encerra com educação.\n"
        "PROIBIDO: 'Gostaria de apresentar nossa empresa', 'excelente oportunidade', 'líderes de mercado', valores, "
        "percentuais, comissão em números, desconto, exclusividade, prazos não informados. Não invente fatos: use só "
        "os FATOS abaixo; se o modelo de negócio não estiver claro, use uma abordagem genérica perguntando com quem "
        "falar sobre parcerias. Liste em fatos_usados os fatos da empresa que você citou.\n"
        f"Tom: {config.TONS.get(tom, tom)}. CTA preferido: {cta or 'escolha o mais natural'}. Assinatura: {vendedor}.\n\n"
        f"EMPRESA: {lead.empresa} ({lead.cidade}/{lead.estado}). Responsável: {lead.responsavel or 'não identificado'}.\n"
        f"CATEGORIA: {cat.nome if cat else 'não definida'}. Por que pode ser parceira: {cat.motivo if cat else '-'}\n"
        f"Estratégia sugerida: {cat.estrategia if cat else '-'}\n"
        f"FATOS (pesquisa pública): {json.dumps(fatos, ensure_ascii=False) if fatos else 'nenhum além do nome e cidade'}")
    try:
        dados = ia.perguntar(db, pedido, ESQUEMA_MENSAGENS, max_tokens=4000)
    except ia.ErroDaIA as erro:
        log.warning("Mensagens por IA falharam (%s): %s", lead.empresa, erro)
        return base
    resultado = {}
    for angulo in config.ANGULOS:
        m = dados.get(angulo) or {}
        if texto_seguro(m.get("whatsapp")) and texto_seguro(m.get("email")):
            resultado[angulo] = {"whatsapp": m["whatsapp"].strip(), "assunto": m.get("assunto", "").strip()
                                 or base[angulo]["assunto"], "email": m["email"].strip(), "fonte": "ia"}
        else:
            resultado[angulo] = base[angulo]  # a IA saiu das regras: usa a versão segura
    return resultado


# ---------------------------------------------------------------- Respostas dos leads

REGRAS_RESPOSTA = [
    ("OPT-OUT", ["sair", "remova", "remover meu", "nao quero receber", "não quero receber", "pare de", "parem de",
                 "descadastr", "nao me mande", "não me mande", "nao quero contato", "não quero contato"]),
    ("QUER PREÇO", ["quanto custa", "qual o valor", "qual valor", "preço", "preco", "tabela de"]),
    ("QUER PROPOSTA", ["proposta", "manda as condi", "quais as condi", "condições", "condicoes"]),
    ("QUER REUNIÃO", ["reuni", "marcar uma conversa", "agendar", "call", "videochamada", "vamos conversar",
                      "podemos conversar", "quero conversar", "bora conversar", "vamos marcar", "pode marcar"]),
    ("QUER LIGAÇÃO", ["me liga", "pode ligar", "liga pra", "ligação", "ligacao", "telefona"]),
    ("PEDIU PARA ENVIAR E-MAIL", ["manda por email", "manda por e-mail", "envia por email", "envia por e-mail",
                                  "meu email", "meu e-mail", "por e-mail", "por email"]),
    ("PEDIU PARA ENVIAR WHATSAPP", ["manda no whats", "pelo whats", "no whatsapp", "meu whats"]),
    ("JÁ POSSUI PARCEIRO", ["ja temos parceiro", "já temos parceiro", "ja trabalhamos com", "já trabalhamos com",
                            "temos uma certificadora", "ja temos certificadora", "já temos certificadora", "já temos",
                            "ja temos"]),
    ("NÃO É RESPONSÁVEL", ["nao sou o responsavel", "não sou o responsável", "não sou responsável", "falar com o",
                           "falar com a", "responsavel e o", "responsável é", "nao cuido", "não cuido"]),
    ("SEM INTERESSE", ["sem interesse", "nao tenho interesse", "não tenho interesse", "nao temos interesse",
                       "não temos interesse", "nao precisamos", "não precisamos", "nao faz sentido", "não faz sentido"]),
    ("MUITO INTERESSADO", ["tenho muito interesse", "muito interess", "quero muito", "vamos fechar", "bora"]),
    ("QUER SABER MAIS", ["como funciona", "me explica", "explica melhor", "mais detalhes", "saber mais", "como seria"]),
    ("INTERESSADO", ["tenho interesse", "temos interesse", "interessante", "interessa", "pode ser", "sim", "faz sentido",
                     "gostaria"]),
    ("OBJEÇÃO", ["mas ", "porem", "porém", "agora nao", "agora não", "sem tempo", "depois", "caro"]),
]


def classificar_por_regras(texto: str) -> dict:
    t = util.chave_texto(texto)
    classe = "RESPOSTA INDEFINIDA"
    for nome, chaves in REGRAS_RESPOSTA:
        # (?<!\w): a palavra-chave precisa começar uma palavra ("sim" não casa com "assim")
        if any(re.search(r"(?<!\w)" + re.escape(util.chave_texto(c)), t) for c in chaves):
            classe = nome
            break
    objecoes = [o for o, chaves in (("Já possui parceiro", ["ja temos", "ja trabalhamos"]),
                                    ("Falta de tempo", ["sem tempo", "depois", "agora nao"]),
                                    ("Preço", ["caro", "preco", "valor"])) if any(c in t for c in chaves)]
    interesse = {"MUITO INTERESSADO": "muito alto", "QUER REUNIÃO": "alto", "QUER LIGAÇÃO": "alto",
                 "QUER PROPOSTA": "alto", "QUER PREÇO": "alto", "INTERESSADO": "alto", "QUER SABER MAIS": "médio",
                 "SEM INTERESSE": "nenhum", "OPT-OUT": "nenhum"}.get(classe, "baixo")
    return {"classe": classe, "interesse": interesse, "objecoes": objecoes, "resumo": texto.strip()[:300],
            "proximo_passo": PROXIMO_PASSO.get(classe, "Ler a resposta e decidir o próximo passo"),
            "pergunta_basica": "", "contato_indicado": "", "fonte": "regras"}


PROXIMO_PASSO = {
    "INTERESSADO": "Ligar para o lead e apresentar a parceria", "MUITO INTERESSADO": "LIGAR AGORA para o lead",
    "QUER SABER MAIS": "Ligar e explicar como funciona a parceria", "QUER REUNIÃO": "Agendar a reunião",
    "QUER LIGAÇÃO": "Ligar para o lead", "QUER PROPOSTA": "Preparar e enviar a proposta comercial",
    "QUER PREÇO": "Apresentar as condições comerciais (time humano)",
    "JÁ POSSUI PARCEIRO": "Entender o parceiro atual e mostrar o diferencial (renovação, atendimento)",
    "NÃO É RESPONSÁVEL": "Pedir o contato do responsável por parcerias",
    "PEDIU PARA ENVIAR E-MAIL": "Enviar apresentação por e-mail", "PEDIU PARA ENVIAR WHATSAPP": "Enviar apresentação pelo WhatsApp",
    "OBJEÇÃO": "Tratar a objeção (time humano)", "SEM INTERESSE": "Encerrar com educação",
    "OPT-OUT": "Não contatar mais", "RESPOSTA INDEFINIDA": "Ler a resposta e decidir o próximo passo",
}

ESQUEMA_RESPOSTA = {
    "type": "object",
    "properties": {
        "classe": {"type": "string", "enum": config.CLASSES_RESPOSTA},
        "interesse": {"type": "string", "enum": ["muito alto", "alto", "médio", "baixo", "nenhum"]},
        "objecoes": {"type": "array", "items": {"type": "string"}},
        "resumo": {"type": "string"},
        "proximo_passo": {"type": "string"},
        "pergunta_basica": {"type": "string"},
        "contato_indicado": {"type": "string"},
    },
    "required": ["classe", "interesse", "objecoes", "resumo", "proximo_passo", "pergunta_basica", "contato_indicado"],
    "additionalProperties": False,
}


def classificar_resposta(db, lead: Lead, texto: str) -> dict:
    regras = classificar_por_regras(texto)
    if regras["classe"] == "OPT-OUT" or mensagens.pede_opt_out(texto):
        regras["classe"] = "OPT-OUT"
        return regras  # pedido de saída é respeitado sem depender da IA
    if not ia.disponivel():
        return regras
    ultimas = db.execute(select(Mensagem).where(Mensagem.lead_id == lead.id, Mensagem.direcao == "saida")
                         .order_by(Mensagem.criado_em.desc()).limit(2)).scalars().all()
    pedido = (
        "Classifique a resposta de um possível parceiro a uma prospecção da MS Certificação Digital.\n"
        f"Classes possíveis: {', '.join(config.CLASSES_RESPOSTA)}.\n"
        "resumo: 1–2 frases para o time humano (só com o que a pessoa disse e o que sabemos da empresa). "
        "pergunta_basica: se a pessoa fez uma pergunta simples (o que é a MS, como funciona, como valida), copie a "
        "pergunta; senão vazio. contato_indicado: se indicou outra pessoa/contato, copie; senão vazio.\n\n"
        f"EMPRESA: {lead.empresa} ({lead.categoria.nome if lead.categoria else 'sem categoria'}).\n"
        f"NOSSAS ÚLTIMAS MENSAGENS: {' | '.join(m.corpo[:400] for m in ultimas) or '-'}\n"
        f"RESPOSTA DA PESSOA: \"\"\"{texto[:2000]}\"\"\"")
    try:
        dados = ia.perguntar(db, pedido, ESQUEMA_RESPOSTA, max_tokens=1500)
        dados["fonte"] = "ia"
        return dados
    except ia.ErroDaIA as erro:
        log.warning("Classificação por IA falhou: %s", erro)
        return regras


def resposta_da_base(db, pergunta: str) -> str:
    """Resposta da base de conhecimento para perguntas básicas (por palavras em comum)."""
    if not pergunta:
        return ""
    palavras = {p for p in re.split(r"\W+", util.chave_texto(pergunta)) if len(p) > 3}
    melhor, pontos = "", 0
    for item in db.execute(select(Conhecimento).where(Conhecimento.ativa.is_(True))).scalars():
        comuns = len(palavras & {p for p in re.split(r"\W+", util.chave_texto(item.pergunta)) if len(p) > 3})
        if comuns > pontos:
            melhor, pontos = item.resposta, comuns
    return melhor if pontos >= 1 else ""


def resposta_sugerida(db, lead: Lead, analise: dict) -> str:
    """O que a SDR responde. Nunca negocia: interesse → transfere para o time humano."""
    from .agenda_horarios import horarios_livres, texto_horarios

    classe = analise["classe"]
    nome = util.primeiro_nome(lead.responsavel)
    ola = f"{nome}, " if nome else ""
    if classe == "OPT-OUT":
        return "Combinado, não enviaremos mais mensagens. Obrigado pelo retorno!"
    if classe == "SEM INTERESSE":
        return "Entendido, obrigado pelo retorno! Se no futuro fizer sentido, fico à disposição."
    if classe == "NÃO É RESPONSÁVEL":
        return f"Obrigado, {ola}e desculpe o incômodo! Com quem posso falar sobre parcerias comerciais aí na empresa?"
    if classe in ("PEDIU PARA ENVIAR E-MAIL", "PEDIU PARA ENVIAR WHATSAPP"):
        return "Combinado! Nosso time comercial vai te enviar os detalhes por lá. Obrigado!"
    if classe in config.CLASSES_QUENTES:
        base = resposta_da_base(db, analise.get("pergunta_basica", ""))
        texto = (base + "\n\n" if base and classe == "QUER SABER MAIS" else "") + TEXTO_HANDOFF
        responsavel = lead.vendedor or lead.humano
        if classe == "QUER REUNIÃO" and responsavel:
            horarios = horarios_livres(db, responsavel, quantidade=3)
            if horarios:
                texto = ("Perfeito! Posso agendar uma conversa rápida com nosso time para explicar a parceria e as "
                         f"condições comerciais. Tenho estes horários: {texto_horarios(horarios)}. Algum fica bom?")
        return texto
    if classe == "JÁ POSSUI PARCEIRO":
        return ("Que bom que vocês já têm isso resolvido! Muitos parceiros trabalham com mais de uma opção. Posso pedir "
                "para alguém do nosso time te mostrar em poucos minutos como funciona o nosso controle de renovações?")
    return "Obrigado pelo retorno! Vou pedir para alguém do nosso time comercial falar com você."


def ultima_mensagem_enviada(db, lead_id: int) -> Mensagem | None:
    return db.execute(select(Mensagem).where(Mensagem.lead_id == lead_id, Mensagem.direcao == "saida",
                                             Mensagem.angulo != "resposta", Mensagem.status.in_(mensagens.ENVIADAS))
                      .order_by(Mensagem.criado_em.desc(), Mensagem.id.desc()).limit(1)).scalars().first()


def processar_resposta(db, lead: Lead, texto: str, canal: str, usuario: Usuario | None = None,
                       registrar_entrada: bool = True) -> dict:
    """Registra e interpreta a resposta do lead. Interesse → para tudo e entrega ao humano."""
    analise = classificar_resposta(db, lead, texto)
    classe = analise["classe"]
    enviada = ultima_mensagem_enviada(db, lead.id)
    if enviada:
        enviada.respondida = True
    if registrar_entrada:
        entrada = mensagens.registrar(db, lead.id, canal, texto, usuario, status="recebida")
        entrada.direcao = "entrada"
        entrada.campanha_id = enviada.campanha_id if enviada else None
        entrada.categoria_id = lead.categoria_id
    lead.ultimo_contato = agora()
    lead.classificacao_resposta = classe
    historico(db, lead.id, "resposta", f"Resposta ({classe}): {texto[:1500]}", usuario, canal)
    if lead.etapa < 2:
        mudar_status(db, lead, "Respondeu", usuario)
    cancelar_tarefas_de_prospeccao(db, lead.id, "o lead respondeu")
    analise["resposta_sugerida"] = resposta_sugerida(db, lead, analise)
    analise["oportunidade_id"] = None
    if classe == "OPT-OUT":
        registrar_opt_out(db, lead, usuario, "pediu na resposta")
        mudar_status(db, lead, "Perdido", usuario, "Opt-out")
    elif classe == "SEM INTERESSE":
        mudar_status(db, lead, "Perdido", usuario, "Sem interesse")
    else:
        if classe in ("PEDIU PARA ENVIAR E-MAIL", "PEDIU PARA ENVIAR WHATSAPP"):
            lead.canal_preferido = "email" if "E-MAIL" in classe else "whatsapp"
        quente = classe in config.CLASSES_QUENTES
        if quente:
            lead.demonstrou_interesse = True
            mudar_status(db, lead, "Interessado", usuario)
        lead.automacao_pausada = True
        oportunidade = criar_oportunidade(db, lead, analise, texto, canal, enviada, "quente" if quente else "morna")
        analise["oportunidade_id"] = oportunidade.id
    historico(db, lead.id, "ia", f"Classificação: {classe} · interesse {analise.get('interesse')} · "
                                 f"próximo passo: {analise.get('proximo_passo')}\nResposta sugerida: "
                                 f"{analise['resposta_sugerida']}", None)
    from . import score

    score.atualizar(db, lead)
    return analise


def criar_oportunidade(db, lead: Lead, analise: dict, texto: str, canal: str, enviada: Mensagem | None,
                       temperatura: str) -> Oportunidade:
    oportunidade = Oportunidade(
        lead_id=lead.id, temperatura=temperatura, classificacao=analise["classe"], canal=canal,
        mensagem_enviada=enviada.corpo if enviada else "", resposta=texto[:3000],
        resumo=analise.get("resumo", "")[:2000], objecoes=", ".join(analise.get("objecoes", []))[:500],
        interesse=analise.get("interesse", ""), proximo_passo=analise.get("proximo_passo", "")[:250],
    )
    db.add(oportunidade)
    db.flush()
    emoji = "🔥 NOVO LEAD QUENTE" if temperatura == "quente" else "Nova resposta para analisar"
    notificar(db, lead, f"{emoji}: {lead.empresa} ({analise['classe'].lower()})", f"/oportunidades#op-{oportunidade.id}")
    return oportunidade


def destinatarios(db, lead: Lead) -> list[Usuario]:
    if lead.vendedor_id:
        dono = db.get(Usuario, lead.vendedor_id)
        if dono and dono.ativo:
            return [dono]
    return list(db.execute(select(Usuario).where(Usuario.perfil.in_(["admin", "gestor"]), Usuario.ativo.is_(True))).scalars())


def notificar(db, lead: Lead, texto: str, link: str) -> None:
    from .integracoes import email_smtp

    for usuario in destinatarios(db, lead):
        db.add(Notificacao(usuario_id=usuario.id, texto=texto[:300], link=link))
        if ler_config(db, "notificar_por_email") == "1" and email_smtp.configurado():
            try:
                email_smtp.enviar(usuario.email, texto[:150], f"{texto}\n\nAbra no sistema: {config.URL_PUBLICA}{link}",
                                  com_rodape=False)
            except email_smtp.ErroEmail as erro:
                log.warning("Aviso por e-mail falhou: %s", erro)


# ---------------------------------------------------------------- Handoff humano

def assumir_lead(db, lead: Lead, usuario: Usuario) -> None:
    """O humano assume: toda automação deste lead para imediatamente."""
    lead.automacao_pausada = True
    lead.humano_id = usuario.id
    if lead.vendedor_id is None:
        lead.vendedor_id = usuario.id
    canceladas = cancelar_tarefas_de_prospeccao(db, lead.id, f"{usuario.nome} assumiu o lead")
    for t in db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id, Tarefa.status == "rascunho")).scalars():
        t.status, t.concluida_em, t.resultado = "cancelada", agora(), "Lead assumido por humano"
    if lead.etapa < 4 and not lead.perdido:
        mudar_status(db, lead, "Humano assumiu", usuario)
    for op in db.execute(select(Oportunidade).where(Oportunidade.lead_id == lead.id,
                                                    Oportunidade.status == "nova")).scalars():
        op.status, op.responsavel_id, op.assumida_em = "assumida", usuario.id, agora()
    historico(db, lead.id, "sistema", f"{usuario.nome} assumiu o lead. Automação parada ({canceladas} tarefas "
                                      f"automáticas canceladas).", usuario)


def resumo_handoff(db, lead: Lead) -> dict:
    """Tudo o que o humano precisa saber ao assumir."""
    op = db.execute(select(Oportunidade).where(Oportunidade.lead_id == lead.id)
                    .order_by(Oportunidade.criado_em.desc()).limit(1)).scalars().first()
    enviada = ultima_mensagem_enviada(db, lead.id)
    return {
        "nome": lead.responsavel or "não identificado", "empresa": lead.empresa,
        "categoria": lead.categoria.nome if lead.categoria else "-", "site": lead.site or "-",
        "cidade": f"{lead.cidade}/{lead.estado}".strip("/"), "responsavel": lead.responsavel or "-",
        "score": lead.score, "fit": lead.fit, "motivo": lead.motivo_potencial or (lead.categoria.motivo if lead.categoria else ""),
        "mensagem_enviada": (op.mensagem_enviada if op else "") or (enviada.corpo if enviada else ""),
        "resposta": op.resposta if op else "", "resumo": op.resumo if op else "",
        "objecoes": op.objecoes if op else "", "interesse": op.interesse if op else "",
        "proximo_passo": op.proximo_passo if op else "", "classificacao": op.classificacao if op else "",
    }


def automacao_ativa(lead: Lead) -> bool:
    return not (lead.automacao_pausada or lead.opt_out or lead.anonimizado or lead.perdido or lead.etapa >= 2)


# ---------------------------------------------------------------- WhatsApp conectado (WhatsApp Leads)

class EnvioRecusado(Exception):
    """Motivo pronto para mostrar na tela."""


def enviar_whatsapp_conectado(db, texto: str, usuario: Usuario | None, lead: Lead | None = None,
                              telefone: str = "", nome: str = "", tarefa: Tarefa | None = None,
                              conexao: str | None = None) -> Mensagem:
    """Envia UMA mensagem pelo WhatsApp conectado no WhatsApp Leads (clique de uma pessoa ou fila da IA SDR).
    Sai pelo número do responsável pelo lead (app/conexoes.py). Aplica as regras daqui (opt-out, frequência,
    limites) antes de colocar na fila de lá."""
    from . import conexoes
    from .integracoes import whatsapp_leads
    from .leads_servico import registrar_contato

    texto = (texto or "").strip()
    if not texto:
        raise EnvioRecusado("A mensagem está vazia.")
    if lead is not None:
        telefone = lead.whatsapp or lead.telefone
        nome = lead.responsavel or lead.empresa
    if not telefone:
        raise EnvioRecusado("Este contato não tem WhatsApp/telefone cadastrado.")
    bloqueio = mensagens.bloqueio_de_envio(db, lead, "whatsapp", tarefa.campanha_id if tarefa else None)
    if bloqueio:
        raise EnvioRecusado(bloqueio)
    if not conexao:
        try:
            conexao = conexoes.para_enviar(db, conexoes.responsavel(db, lead, usuario, tarefa))
        except conexoes.SemNumero as erro:
            raise EnvioRecusado(str(erro)) from None
    try:
        id_externo = whatsapp_leads.enviar(telefone, nome, texto, db=db, conexao=conexao)
    except whatsapp_leads.ErroWhatsAppLeads as erro:
        raise EnvioRecusado(str(erro)) from None
    msg = mensagens.registrar(db, lead.id if lead else None, "whatsapp", texto, usuario, modo="whatsapp-leads",
                              status="na_fila", tarefa_id=tarefa.id if tarefa else None, id_externo=str(id_externo),
                              campanha_id=tarefa.campanha_id if tarefa else None, angulo=tarefa.angulo if tarefa else "",
                              categoria_id=lead.categoria_id if lead else None)
    msg.conexao = conexao
    if tarefa is not None:
        tarefa.status, tarefa.concluida_em, tarefa.resultado = "feita", agora(), "Enviada pelo WhatsApp conectado"
    if lead is not None:
        registrar_contato(db, lead, "whatsapp", "Mensagem enviada pelo WhatsApp conectado"
                          + (f" ({config.ANGULOS.get(tarefa.angulo, tarefa.acao)})" if tarefa else "") + ".", usuario)
    return msg


def sincronizar_whatsapp_conectado(db) -> dict:
    """Busca no WhatsApp Leads: respostas dos parceiros (→ IA SDR), status dos envios e opt-outs."""
    from .banco import gravar_config, ler_config_int
    from .integracoes import whatsapp_leads

    if config.WHATSAPP_PONTE or not whatsapp_leads.configurado():
        return {"respostas": 0, "status": 0, "opt_out": 0}  # na nuvem as novidades chegam pela ponte
    desde = ler_config_int(db, "wl_ultimo_id", 0)
    try:
        dados = whatsapp_leads.novidades(desde)
    except whatsapp_leads.ErroWhatsAppLeads:
        return {"respostas": 0, "status": 0, "opt_out": 0}  # WhatsApp Leads fechado: tenta na próxima rodada
    resultado = aplicar_novidades_whatsapp(db, dados)
    gravar_config(db, "wl_ultimo_id", str(dados.get("ultimo_id", desde)))
    return resultado


def variantes_do_telefone(telefone: str) -> set[str]:
    """O WhatsApp às vezes entrega celulares antigos sem o nono dígito: o número com e sem ele."""
    numero = util.normalizar_telefone(telefone)
    if not numero:
        return set()
    candidatos = {numero}
    if len(numero) == 11 and numero[2] == "9":
        candidatos.add(numero[:2] + numero[3:])
    elif len(numero) == 10 and numero[2] in "6789":
        candidatos.add(numero[:2] + "9" + numero[2:])
    return candidatos


def lead_pelo_telefone(db, telefone: str) -> Lead | None:
    candidatos = variantes_do_telefone(telefone)
    if not candidatos:
        return None
    return db.execute(select(Lead).where(Lead.chave_whatsapp.in_(candidatos) | Lead.chave_telefone.in_(candidatos))
                      .limit(1)).scalars().first()


def aplicar_novidades_whatsapp(db, dados: dict) -> dict:
    """Respostas dos parceiros (→ IA SDR), status dos envios e opt-outs vindos do WhatsApp Leads."""
    from .leads_servico import registrar_opt_out

    resultado = {"respostas": 0, "status": 0, "opt_out": 0}

    def lead_do_telefone(telefone: str) -> Lead | None:
        return lead_pelo_telefone(db, telefone)

    situacao = {"enviada": "enviada", "erro": "falhou", "cancelada": "falhou"}
    for envio in dados.get("envios", []):
        msg = db.execute(select(Mensagem).where(Mensagem.modo == "whatsapp-leads",
                                                Mensagem.id_externo == str(envio["id"]))).scalars().first()
        novo = situacao.get(envio["status"])
        if msg and novo and msg.status != novo:
            msg.status, msg.erro = novo, envio.get("erro", "")[:500]
            resultado["status"] += 1
    for telefone in dados.get("bloqueados", []):
        lead = lead_do_telefone(telefone)
        if lead and not lead.opt_out:
            registrar_opt_out(db, lead, None, "respondeu SAIR no WhatsApp")
            resultado["opt_out"] += 1
    for recebida in dados.get("recebidas", []):
        lead = lead_do_telefone(recebida["telefone"])
        if lead is None or not recebida.get("texto"):
            continue
        analise = processar_resposta(db, lead, recebida["texto"], "whatsapp")
        from .rotinas import responder_automaticamente

        responder_automaticamente(db, lead, "whatsapp", analise, conexao=recebida.get("conexao"))  # pelo mesmo número
        resultado["respostas"] += 1
    return resultado
