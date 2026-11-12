"""Tons de abordagem e os textos de cada toque, sem IA (nov/2026).

Antes, o "Tom" da Nova campanha só mudava alguma coisa com a IA ligada; na nuvem (sem IA) todas as campanhas saíam
com os mesmos textos. Aqui cada tom tem a própria primeira mensagem e um jeito de escrever os toques seguintes
(registro: neutro, informal, curto ou formal).

Base da escolha (pesquisa de nov/2026 + dados da auditoria da MS):
- a 1ª mensagem curta, com UMA pergunta fácil de responder, é a que mais abre conversa;
- falar como parceiro/colega de mercado (os dois lados ganham), não como vendedor;
- um sinal de credibilidade concreto (Autoridade de Registro, validação presencial ou por vídeo, aviso de
  vencimento) vale mais que adjetivos;
- pedido pequeno (uma pergunta, 15 minutos);
- no WhatsApp frio, poucos toques (risco de bloqueio do número).

Regras da SDR valem para todos: nada de valores, porcentagem, desconto, exclusividade, contrato ou frases de spam
(sdr.texto_seguro); a 1ª mensagem tem saída educada; nenhum follow-up pergunta "viu minha mensagem?".
Os textos usam "MS Certificação Digital" e "Autoridade de Registro ICP-Brasil" para que marca.aplicar troque pela
empresa de quem representa outra empresa."""

from . import util
from .banco import ler_config

RODAPE = "(Se não fizer sentido para vocês, é só me avisar que não envio mais mensagens.)"
RODAPE_FORMAL = "(Caso não seja de interesse, basta responder esta mensagem e não enviaremos novos contatos.)"

# Vocabulário de quando o segmento da empresa não está confirmado (não inventa o ramo)
VOCAB_GENERICO = dict(
    quem="empresas que atendem outras empresas", clientes="os clientes de vocês",
    momento="para emitir notas, acessar a Receita e assinar documentos",
    dor="um certificado vencido parando o cliente bem na hora de emitir nota ou enviar uma obrigação",
    ganho="um serviço a mais para os clientes e uma receita extra", papel="vocês já são de confiança dos clientes")

# Toques novos (além dos 4 da IA: apresentacao, praticidade, receita, encerramento)
ANGULOS_NOVOS = {
    "pergunta": "Pergunta rápida",
    "conteudo": "Dica útil para os clientes deles",
    "convite": "Convite para conversar (e-mail com link do WhatsApp)",
}

ASSUNTOS = {
    "apresentacao": "Possível parceria — MS Certificação Digital + {empresa}",
    "pergunta": "Uma pergunta rápida sobre os clientes da {empresa}",
    "praticidade": "Certificado digital para os clientes da {empresa}, sem trabalho para vocês",
    "conteudo": "Uma dica sobre o vencimento dos certificados dos seus clientes",
    "receita": "Receita recorrente com os certificados dos seus clientes",
    "convite": "Convite: parceria MS Certificação Digital + {empresa}",
    "encerramento": "Encerrando meu contato — MS Certificação Digital",
}
ASSUNTOS_FORMAIS = {
    "apresentacao": "Proposta de parceria — MS Certificação Digital e {empresa}",
    "convite": "Convite para parceria — MS Certificação Digital e {empresa}",
    "encerramento": "Agradecimento — MS Certificação Digital",
}

# Primeira mensagem de cada tom ({rodape} = saída educada). O tom "consultivo" usa os textos de sempre do sistema
# (sdr.mensagens_por_regras + modelos do segmento), por isso não aparece aqui.
PRIMEIRA = {
    "pergunta": (
        "{oi} Uma pergunta rápida: quando {clientes} precisam emitir ou renovar o certificado digital, vocês indicam "
        "alguém?\n\nPergunto porque sou {vendedor}, da MS Certificação Digital, e estamos fazendo parcerias com {quem} "
        "em {cidade}.\n\n{rodape}"),
    "parceiro": (
        "{ola} Sou {vendedor}, da MS Certificação Digital. Trabalhamos lado a lado com {quem}: {papel}, e nós "
        "cuidamos da parte do certificado digital, do atendimento à renovação.\n\nA ideia é uma parceria em que os dois "
        "lados ganham e {clientes} ficam bem atendidos {momento}.\n\n{cta}\n\n{rodape}"),
    "cliente": (
        "{ola} Uma situação que vemos muito com {quem}: {dor}.\n\nSou {vendedor}, da MS Certificação Digital, e a "
        "nossa parceria existe para evitar isso: {clientes} são atendidos rápido {momento}, e avisamos antes de cada "
        "vencimento.\n\n{cta}\n\n{rodape}"),
    "local": (
        "{ola} Aqui é {vendedor}, da MS Certificação Digital, Autoridade de Registro ICP-Brasil, com validação "
        "presencial em Recife ou por videoconferência.\n\nEstamos conversando com {quem} de {cidade} sobre uma "
        "parceria simples: vocês indicam e a MS cuida de tudo, da emissão à renovação.\n\n{cta}\n\n{rodape}"),
    "direto": (
        "{ola} Sou {vendedor}, da MS Certificação Digital. Em uma frase: vocês indicam {clientes} que precisam de "
        "certificado digital, a MS faz todo o atendimento e vocês são remunerados por cada certificado.\n\n{cta}\n\n"
        "{rodape}"),
    "informal": (
        "{oi} Aqui é {vendedor}, da MS Certificação Digital. Vi a {empresa} e pensei numa parceria: quando algum "
        "cliente de vocês precisar de certificado digital, vocês indicam e a gente resolve tudo, sem dor de "
        "cabeça.\n\n{cta}\n\n{rodape}"),
    "formal": (
        "{prezado}\n\nMeu nome é {vendedor} e represento a MS Certificação Digital, Autoridade de Registro "
        "ICP-Brasil.\n\nGostaríamos de propor à {empresa} uma parceria para o atendimento de {clientes} que "
        "necessitam de certificado digital: a indicação é feita por vocês, e todo o processo (atendimento, "
        "emissão, validação e renovação) fica sob responsabilidade da MS.\n\nSeria possível agendarmos uma breve "
        "conversa?\n\n{rodape_formal}"),
}

# Os toques seguintes, por registro. Cada tom usa um registro.
SEGUINTES = {
    "neutro": {
        "pergunta": ("{ola_curto} Só uma pergunta rápida: hoje, quando {clientes} precisam do certificado digital, "
                     "quem resolve isso para vocês?\n\n{rodape}"),
        "praticidade": ("{ola_curto} Retomando meu contato: a ideia da parceria é tirar esse assunto das costas de "
                        "vocês. Quando {clientes} precisam de certificado, basta indicar; a MS atende, faz a validação "
                        "(presencial em Recife ou por videoconferência) e avisa antes do vencimento.\n\n"
                        "Faz sentido conversarmos?"),
        "conteudo": ("{ola_curto} Uma dica que tem ajudado {quem}: conferir com antecedência o vencimento dos "
                     "certificados de {clientes}. Quando ele vence sem aviso, o resultado costuma ser {dor}.\n\n"
                     "Na parceria, esse controle fica com a MS: avisamos antes de vencer e cuidamos da renovação. "
                     "Quer que eu explique como funciona?"),
        "receita": ("{ola_curto} Um ponto que chama a atenção dos nossos parceiros: cada certificado indicado gera "
                    "remuneração, e as renovações dos anos seguintes também, porque a MS controla os vencimentos. "
                    "Para {quem}, isso vira {ganho}.\n\nQuem seria a pessoa responsável por parcerias aí na "
                    "{empresa}?"),
        "convite": ("{ola} Sou {vendedor}, da MS Certificação Digital, Autoridade de Registro ICP-Brasil.\n\n"
                    "Criamos uma parceria simples para {quem}: vocês indicam e a MS cuida de todo o atendimento de "
                    "{clientes}, da emissão à renovação, e vocês são remunerados por cada certificado.\n\n"
                    "Se quiser conversar, {convite}\n\n{rodape}"),
        "encerramento": ("{ola_curto} Para não ficar insistindo, este é meu último contato sobre a parceria com a MS "
                         "Certificação Digital. Se em algum momento fizer sentido oferecer certificado digital para "
                         "{clientes}, é só responder esta mensagem. Obrigado pela atenção!"),
    },
    "informal": {
        "pergunta": ("{oi_curto} Só pra eu não incomodar à toa: faz sentido eu te explicar em 2 minutinhos como "
                     "funciona a parceria para {quem}?\n\n{rodape}"),
        "praticidade": ("{oi_curto} Voltando aqui rapidinho: com a parceria, vocês só indicam. A gente atende o "
                        "cliente, faz a validação (presencial em Recife ou por videoconferência) e ainda avisa antes "
                        "de vencer. Zero trabalho pra {empresa}.\n\nBora conversar?"),
        "conteudo": ("{oi_curto} Uma dica rápida: certificado digital vencido costuma virar {dor}. Na parceria, a "
                     "gente controla os vencimentos de {clientes} e avisa antes. Quer que eu te conte como "
                     "funciona?"),
        "receita": ("{oi_curto} Sabia que cada certificado indicado gera remuneração pra quem indica? E nas "
                    "renovações também, porque a gente controla os vencimentos. Com quem eu falo sobre parcerias "
                    "aí?"),
        "convite": ("{oi} Aqui é {vendedor}, da MS Certificação Digital. Pensei numa parceria com a {empresa}: "
                    "vocês indicam quem precisa de certificado digital e a gente resolve tudo, da emissão à "
                    "renovação.\n\nSe quiser trocar uma ideia, {convite}\n\n{rodape}"),
        "encerramento": ("{oi_curto} Não quero encher sua caixa, então esta é minha última mensagem sobre a "
                         "parceria. Se um dia fizer sentido, é só me chamar aqui. Valeu!"),
    },
    "curto": {
        "pergunta": "{ola_curto} Faz sentido falarmos 10 minutos sobre a parceria para {quem}?\n\n{rodape}",
        "praticidade": ("{ola_curto} Resumo da parceria: vocês indicam, a MS atende, valida e avisa antes do "
                        "vencimento. Faz sentido para a {empresa}?"),
        "conteudo": ("{ola_curto} Certificado vencido costuma virar {dor}. A MS controla os vencimentos de "
                     "{clientes} e avisa antes. Posso explicar em 10 minutos?"),
        "receita": ("{ola_curto} Cada certificado indicado gera remuneração, inclusive nas renovações. Quem cuida "
                    "de parcerias aí?"),
        "convite": ("{ola} Sou {vendedor}, da MS Certificação Digital. Proposta: vocês indicam {clientes} que "
                    "precisam de certificado digital, a MS faz todo o atendimento e vocês são remunerados.\n\n"
                    "Para conversar, {convite}\n\n{rodape}"),
        "encerramento": ("{ola_curto} Último contato sobre a parceria com a MS Certificação Digital. Se fizer "
                         "sentido no futuro, é só responder. Obrigado!"),
    },
    "formal": {
        "pergunta": ("{prezado}\n\nPermita-me uma pergunta: atualmente, quando {clientes} necessitam emitir ou "
                     "renovar o certificado digital, a quem vocês os encaminham?\n\n{rodape_formal}"),
        "praticidade": ("{prezado}\n\nRetomo o contato anterior. Na parceria proposta, a {empresa} apenas indica; a "
                        "MS Certificação Digital realiza o atendimento, a validação (presencial em Recife ou por "
                        "videoconferência) e o aviso prévio de vencimento.\n\nPodemos agendar uma breve conversa?"),
        "conteudo": ("{prezado}\n\nCompartilho uma observação frequente entre {quem}: o vencimento não acompanhado "
                     "dos certificados de {clientes} costuma resultar em {dor}.\n\nNa parceria, a MS assume esse "
                     "acompanhamento e a renovação. Teria interesse em conhecer os detalhes?"),
        "receita": ("{prezado}\n\nDestaco que cada certificado indicado pela {empresa} gera remuneração, inclusive "
                    "nas renovações dos anos seguintes, cujo controle é feito pela MS.\n\nPoderia me indicar a "
                    "pessoa responsável por parcerias?"),
        "convite": ("{prezado}\n\nMeu nome é {vendedor} e represento a MS Certificação Digital, Autoridade de "
                    "Registro ICP-Brasil. Convidamos a {empresa} a conhecer nossa parceria para {quem}: a "
                    "indicação é feita por vocês, e todo o atendimento de {clientes}, da emissão à renovação, fica "
                    "sob responsabilidade da MS.\n\nCaso deseje conversar, {convite}\n\n{rodape_formal}"),
        "encerramento": ("{prezado}\n\nAgradeço a atenção e encerro aqui meus contatos sobre a parceria com a MS "
                         "Certificação Digital. Permanecemos à disposição caso o tema se torne oportuno."),
    },
}

REGISTRO = {"consultivo": "neutro", "pergunta": "informal", "parceiro": "neutro", "cliente": "neutro",
            "local": "neutro", "direto": "curto", "informal": "informal", "formal": "formal"}


def vocabulario(lead, confirmado: bool) -> dict:
    """{quem}, {clientes}, {momento}, {dor}, {ganho}, {papel} do segmento (ou genéricos, se o ramo não é certo)."""
    from .modelos_segmento import SEGMENTOS

    cat = lead.categoria
    if confirmado and cat and cat.codigo in SEGMENTOS:
        return {k: v for k, v in SEGMENTOS[cat.codigo].items() if k != "rotulo"}
    return dict(VOCAB_GENERICO)


def convite(db, usuario) -> str:
    """Final do convite: o link do WhatsApp da MS (Configurações > Geral) ou "é só responder"."""
    from . import marca

    numero = util.so_digitos(ler_config(db, "whatsapp_convite") or "")
    if numero and not marca.da_pessoa(usuario)["propria"]:
        link = util.link_whatsapp(numero)  # sem texto pronto: o "%" da URL esbarra na trava de percentuais
        return f"é só responder este e-mail ou chamar no WhatsApp: {link}"
    return "é só responder esta mensagem que eu explico em poucos minutos."


def textos(db, lead, usuario, v: dict, tom: str, cta: str, confirmado: bool) -> dict:
    """{angulo: (texto, assunto)} do tom. v = valores do lead (nome, empresa, vendedor, cidade...)."""
    tom = tom if tom in REGISTRO else "consultivo"
    registro = REGISTRO[tom]
    n = v.get("nome") or ""
    voc = vocabulario(lead, confirmado)
    campos = {
        **voc, "nome": n, "empresa": v.get("empresa") or "sua empresa", "vendedor": v.get("vendedor") or "a equipe",
        "cidade": v.get("cidade") or "sua região", "cta": cta, "rodape": RODAPE, "rodape_formal": RODAPE_FORMAL,
        "ola": f"Olá, {n}! Tudo bem?" if n else "Olá! Tudo bem?", "ola_curto": f"Olá, {n}!" if n else "Olá!",
        "oi": f"Oi, {n}! Tudo certo?" if n else "Oi! Tudo certo?", "oi_curto": f"Oi, {n}!" if n else "Oi!",
        "prezado": f"Prezado(a) {n}," if n else "Prezados,", "convite": convite(db, usuario),
    }
    saida = {}
    modelos = dict(SEGUINTES[registro])
    if tom in PRIMEIRA:
        modelos["apresentacao"] = PRIMEIRA[tom]
    for angulo, modelo in modelos.items():
        assunto = (ASSUNTOS_FORMAIS.get(angulo) if registro == "formal" else None) or ASSUNTOS[angulo]
        saida[angulo] = (modelo.format(**campos).strip(), assunto.format(empresa=campos["empresa"]))
    return saida
