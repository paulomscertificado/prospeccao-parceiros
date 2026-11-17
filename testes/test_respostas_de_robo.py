"""Pedido da Maria em 17/11/2026: muitas respostas das campanhas (sobretudo Empresas novas) eram de robô (ausência,
menu de departamentos, "você será atendido", pesquisa de satisfação) e viravam oportunidade. Os textos abaixo são os
reais de 03 a 17/11/2026, com nomes, números e endereços trocados. Mensagens de gente continuam virando oportunidade."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import config, email_validacao, sdr
from app.banco import agora, sessao
from app.leads_servico import criar_lead
from app.modelos import Lead, Mensagem, Oportunidade, Usuario

ROBOS = [
    "🚀 Olá! Você está falando com a equipe da agência Exemplo, especialista em estratégias que geram resultado real."
    "\n\nPara oferecer o melhor atendimento, me envie seu nome e o assunto que deseja tratar — estamos prontos para te "
    "atender!",
    "Ola 😃 Exemplo Refeições agradece seu contato. Hoje não teremos atendimento, voltaremos amanhã 😃👍 espero te "
    "atender em breve.",
    "Agradecemos sua mensagem. Não estamos disponíveis no momento, responderemos assim que possível.",
    "*Exemplo Contabilidade*:\n\nBem vindo(a)! \nEm breve você será atendido.",
    "Exemplo Tratores agradece sua mensagem. Não estamos disponíveis no momento, mas responderemos assim que possível.",
    "Oiee, não estou agora por aqui! Qualquer urgência pode me ligar. ✌️☺️",
    "Agradecemos sua mensagem. Não estamos disponíveis no momento, mas entraremos em contato assim que possível.",
    "*Exemplo Organização Contábil*:\n\nVocê foi removido do menu por inatividade.",
    "Poderia nos informar o número do departamento desejado para o seu atendimento?\n\n 1 - Pessoal\n2 - Fiscal\n"
    "3 - Contábil\n4 - Financeiro\n5 - Comercial\n0 - Não sei o departamento",
    "Em razão da ausência de interação, este atendimento está sendo encaminhado para um atendente do escritório.",
    "Devido à falta de interação, este atendimento está sendo transferido para um atendente do escritório.",
    "*EXEMPLO CONTABILIDADE - DOCUMENTOS*:\n\nOlá, !\nEste canal é exclusivo para o recebimento de documentos e "
    "obrigações.\nPara falar com nossa equipe sobre dúvidas e solicitações, favor chamar no número abaixo:\n"
    "https://wa.me/5500000000000\nAtt,\nExemplo Contabilidade.",
    "Por gentileza aguarde, em breve você será atendido por um atendente do escritório.",
    "Esperamos ter ajudado você da melhor forma.\n\nQueremos continuar aprimorando nossos serviços e seu feedback faz "
    "toda a diferença. Conte pra gente: como você avalia este atendimento?\n\nhttps://exemplo.com.br/pesquisa/abc",
    "Olá! É um prazer atendê-lo(a).\n\nEscolha o NÚMERO conforme o DEPTO desejado:\n\n*1* *-* Recepção\n"
    "*2* *-* Pessoal\n*3* *-* Fiscal\n*4* *-* Contábil",
    "*Exemplo Contabilidade*:\n\nObrigado, volte sempre!\n\nCaso queira iniciar um novo atendimento, basta enviar uma "
    "nova mensagem.",
    "Olá! Escolha o setor:\n1️⃣ Fiscal\n2️⃣ Pessoal\n3️⃣ Contábil",  # menu com os números em emoji
    "Olá! Você está falando com a Exemplo. Estamos prontos para ajudar você.",  # duas frases "fracas" juntas
    "\u200eExemplo Contabilidade agradece seu contato. Em que podemos ajudar?",
    "Olá!! Tudo bem? 😄\nNós da Exemplo Contabilidade agradecemos seu contato. Como podemos ajudá-lo?",
    "Olá, tudo bem?\n\nSeja bem-vindo à Exemplo! 💙\n\nÉ um prazer ter você conosco. Para agilizar seu atendimento, "
    "descreva sua solicitação.",
    "Olá! Como posso ajudar? Por favor, informe seu nome.",  # duas fracas
    "\u200e*Sofia:*\n\nOi, tudo bem? Aqui é a Sofia, da Exemplo.",  # agente de IA com a marca invisível
    "Desculpe, não entendi. Por favor, digite uma das opções!",
    "Para agilizar seu atendimento, pode nos contar rapidamente qual é sua dúvida?",
    "Estamos finalizando nosso atendimento. Caso necessite de algum apoio posterior, estaremos à disposição!",
    "✅ Atendimento finalizado. Se precisar de mais alguma coisa, estou à disposição!",
    "Olá somos da \u200eExemplo Contabilidade. 😉👍\n\nComo podemos lhe ajudar?",  # marca invisível + frase fraca
    "Olá, não estamos atendendo no momento. Assim que retornarmos iremos entrar em contato com você.",
    "*Exemplo Contabilidade*:\n\nSelecione uma das opções abaixo:\n(1) Geral\n(2) Contábil\n(3) Fiscal",
    "Olá, responderemos em breve.",
    "** Mensagem não entregue **\n\nOcorreu um problema na entrega da mensagem para x@exemplo.com.br.",
]

PESSOAS = [
    "Bom Dia\n\nObrigada, já tenho uma parceria de mais de 10 anos...", "Ótima semana!",
    "Bom Dia! Quanto ta o de um ano?", "Sim", "Como funciona?", "*Exemplo Contabil Ltda*:\n\nboa tarde, a principio não",
    "*Exemplo Contabil Ltda*:\n\nja temos uma parceria e pór enquanto estamos satisfeito", "[áudio]", "Pode deixar",
    "Não faço mais parte da empresa...favor dirigir-se ao número ja repassado",
    "Boa noite  não removei  fechei a loja e no momento estou sem dinheiro", "Já renovamos",
    "Não sei a hora exata ainda.", "Umas 16:00 acho", "14 pode ser?", "👍👍👍", "Já fiz obg", "Não existe mais",
    "Boa tarde", "Aí preciso ver a disponibilidade dele", "Amigo", "Oi Jefferson, tenho interesse sim, me liga amanhã",
    "Olá, você está falando com a Ana, dona da loja. Pode me explicar melhor?",  # uma frase "fraca" sozinha não basta
    "Pode ser:\n16:00\n17:30\n18:00",  # horários em linhas não são menu
    # nome do atendente em negrito, posto pela plataforma de atendimento em mensagens de gente (sem a marca invisível)
    "*Gabi:*\nBoa tarde!", "*Recepção/Financeiro:*\ntemos o nosso próprio controle,",
    "*Fulano Exemplo - Dep. Administrativo:*\n\nBoa tarde, tudo bem?\nAgradeço o contato, mas já tenho uma parceira "
    "para certificação digital.", "*👩🏻\u200d💻Jessica Exemplo:*\nBom dia!\nTudo bem?",
    "*Exemplo Contabil Ltda*:\n\nboa tarde, em que posso ajudar?",  # atendente de verdade, uma frase fraca só
    "Encaminhamos para o Sescon.", "Desculpe, não entendi, quem fala?", "Boa tarde. Já possuímos parceria, mas obrigado "
    "pela oferta.", "Oi boa tarde, estamos em processo de baixa, não vamos mais trabalhar com contabilidade",
]


@pytest.mark.parametrize("texto", ROBOS)
def test_respostas_de_robo_das_campanhas_sao_reconhecidas(texto):
    assert sdr.e_resposta_automatica(texto)


@pytest.mark.parametrize("texto", PESSOAS)
def test_mensagens_de_gente_continuam_sendo_de_gente(texto):
    assert not sdr.e_resposta_automatica(texto)


def _lead(db, nome, whatsapp):
    admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
    lead, _ = criar_lead(db, {"empresa": nome, "cidade": "Recife", "estado": "PE", "whatsapp": whatsapp}, admin,
                         checar_duplicado=False)
    db.flush()
    return lead


def test_robo_das_empresas_novas_nao_vira_oportunidade_e_gente_vira(cliente):
    with sessao() as db:
        robo = _lead(db, "Robo Agencia Teste Ltda", "81999770001")
        gente = _lead(db, "Gente De Verdade Teste Ltda", "81999770002")
        analise = sdr.processar_resposta(db, robo, ROBOS[0], "whatsapp")
        assert analise["classe"] == config.CLASSE_AUTOMATICA and analise["oportunidade_id"] is None
        assert not robo.automacao_pausada  # a sequência continua: a próxima mensagem pode chegar numa pessoa
        assert sdr.processar_resposta(db, gente, "Bom dia! Quanto ta o de um ano?", "whatsapp")["oportunidade_id"]
        contar = select(func.count(Oportunidade.id)).where(Oportunidade.lead_id.in_([robo.id, gente.id]))
        assert db.execute(contar).scalar() == 1
        db.rollback()


def test_recusa_educada_com_frase_de_robo_vale_a_recusa(cliente):
    """"Agradecemos o contato, mas não temos interesse" é de gente: o lead sai da sequência (Sem interesse)."""
    with sessao() as db:
        lead = _lead(db, "Recusa Educada Teste Ltda", "81999770003")
        assert sdr.e_resposta_automatica("Agradecemos o contato, mas não temos interesse.")
        analise = sdr.processar_resposta(db, lead, "Agradecemos o contato, mas não temos interesse.", "whatsapp")
        assert analise["classe"] == "SEM INTERESSE" and lead.status == "Perdido"
        db.rollback()


def test_varias_mensagens_seguidas_de_gente_nao_viram_robo(cliente):
    """Casos reais da Renovação (16/11): "Sim" / "Bom dia" / "Vamos agendar para fazer" e, 2 minutos depois, mais
    duas mensagens; a última ficou como robô. Rajada só de robô continua sendo robô."""
    with sessao() as db:
        gente = _lead(db, "Cliente Rajada Teste Ltda", "81999770004")
        robo = _lead(db, "Robo Rajada Teste Ltda", "81999770005")
        for lead, modo in ((gente, "manual"), (robo, "robo")):
            for i, texto in enumerate(("Sim", "Bom dia", "Vamos agendar para fazer")):
                db.add(Mensagem(lead_id=lead.id, canal="whatsapp", direcao="entrada", status="recebida", modo=modo,
                                corpo=texto, criado_em=agora() - timedelta(seconds=60 - i)))
        db.flush()
        assert not sdr._rajada_de_mensagens(db, gente)
        assert sdr._rajada_de_mensagens(db, robo)
        assert sdr.classificar_resposta(db, gente, "Aí preciso ver a disponibilidade dele")["classe"] != \
            config.CLASSE_AUTOMATICA
        db.rollback()


def test_aviso_de_entrega_do_gmail_nao_e_resposta():
    assert email_validacao.texto_de_devolucao(
        "** Entrega incompleta **\n\nOcorreu um problema temporário na entrega da mensagem para x@exemplo.com.br.")
    assert email_validacao.texto_de_devolucao(
        "** Caixa de entrada do destinatário cheia **\n\nA mensagem não foi entregue a x@exemplo.com.br.")
    assert not email_validacao.texto_de_devolucao("Bom dia, recebi o e-mail e tenho interesse.")
