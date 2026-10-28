"""Modelos de mensagem por segmento: 15 por segmento (8 de WhatsApp e 7 de e-mail), cobrindo os 4 toques da
IA SDR (apresentação, praticidade, receita, encerramento).

Cada modelo é um texto-base com o vocabulário do segmento ({quem}, {clientes}, {momento}, {dor}, {ganho}, {papel})
e as variáveis normais dos templates ({{nome}}, {{empresa}}, {{cidade}}, {{vendedor}}). Ficam na tabela de templates
(editáveis em Cadências > Templates), aparecem no lead conforme o segmento dele e dão variedade às campanhas.
Regras da SDR: nada de valores, porcentagem, desconto, exclusividade ou contrato (ver sdr.texto_seguro)."""

from sqlalchemy import select

RODAPE = "(Se não fizer sentido para vocês, é só me avisar que não envio mais mensagens.)"
ASSINATURA = "\n\n{{vendedor}}\nMS Certificação Digital · mscertificados.com.br"
NOMES_ANGULO = {"apresentacao": "Apresentação", "praticidade": "Praticidade", "receita": "Receita",
                "encerramento": "Encerramento"}

SEGMENTOS = {
    "contabil": dict(
        rotulo="Contábeis", quem="escritórios contábeis", clientes="os clientes do escritório",
        momento="na abertura de empresas, no eSocial, na NF-e e nas entregas do SPED",
        dor="um certificado vencido travando uma entrega importante do cliente",
        ganho="uma receita extra e recorrente, sem mudar a rotina do escritório",
        papel="o escritório é quem o cliente procura quando o certificado vence"),
    "restaurante": dict(
        rotulo="Restaurantes", quem="restaurantes e lanchonetes", clientes="os fornecedores e outros donos de restaurante",
        momento="para emitir NFC-e no caixa, no eSocial dos funcionários e a cada renovação do e-CNPJ",
        dor="o certificado vencer e o caixa parar de emitir nota no meio do movimento",
        ganho="certificado sem dor de cabeça e uma renda extra indicando outros restaurantes",
        papel="o restaurante conversa todo dia com fornecedores e com outros donos do ramo"),
    "condominio": dict(
        rotulo="Condomínios", quem="administradoras de condomínios", clientes="os condomínios administrados",
        momento="na troca de síndico, no eSocial dos funcionários e nas obrigações do condomínio",
        dor="o certificado do condomínio vencer bem na hora de enviar o eSocial ou a folha",
        ganho="um serviço a mais para os condomínios e uma receita extra para a administradora",
        papel="a administradora cuida da parte burocrática de cada condomínio"),
    "nf": dict(
        rotulo="Sistemas de NF", quem="empresas de sistemas de emissão de nota fiscal", clientes="os usuários do sistema",
        momento="para começar a emitir NF-e e NFC-e e a cada renovação",
        dor="o cliente parado, sem emitir nota, porque o certificado venceu",
        ganho="menos chamados no suporte e uma receita extra por indicação",
        papel="sem certificado válido o cliente não consegue usar o sistema"),
    "software_contabil": dict(
        rotulo="Software contábil", quem="empresas de software contábil", clientes="os escritórios que usam o software",
        momento="para assinar e transmitir SPED, ECD, ECF e eSocial",
        dor="o escritório travado na transmissão por causa de um certificado vencido",
        ganho="mais valor para a base de clientes e uma receita extra",
        papel="o certificado é o que permite transmitir as obrigações pelo software"),
    "erp": dict(
        rotulo="ERP", quem="empresas de ERP e software empresarial", clientes="as empresas que usam o ERP",
        momento="na implantação, para emitir notas e integrar com o fisco",
        dor="uma implantação atrasada esperando o cliente providenciar o certificado",
        ganho="implantações mais rápidas e uma receita extra por indicação",
        papel="o certificado costuma ser pré-requisito para o ERP conversar com o fisco"),
    "bpo": dict(
        rotulo="BPO financeiro", quem="empresas de BPO financeiro", clientes="as empresas atendidas",
        momento="para acessar bancos, emitir notas e cuidar das obrigações fiscais",
        dor="a rotina financeira do cliente parada por falta de certificado válido",
        ganho="mais um serviço no pacote e uma receita extra",
        papel="o BPO opera o dia a dia financeiro, onde o certificado é usado o tempo todo"),
    "rh": dict(
        rotulo="RH / folha", quem="empresas de RH e folha de pagamento", clientes="as empresas atendidas",
        momento="no envio do eSocial, do FGTS Digital e da DCTFWeb",
        dor="a folha atrasada porque o certificado do cliente venceu",
        ganho="menos atraso no eSocial e uma receita extra por indicação",
        papel="sem certificado válido o eSocial não sai"),
    "consultoria": dict(
        rotulo="Consultorias", quem="consultorias empresariais", clientes="as empresas assessoradas",
        momento="na regularização, em licitações e na assinatura digital de documentos",
        dor="um projeto atrasado esperando o cliente resolver o certificado",
        ganho="uma solução a mais para os clientes e uma receita extra",
        papel="a consultoria é quem orienta o cliente nos próximos passos"),
    "despachante": dict(
        rotulo="Despachantes", quem="despachantes", clientes="os clientes do despachante",
        momento="em processos no Detran, na Junta Comercial e em órgãos públicos",
        dor="um processo parado esperando o certificado do cliente",
        ganho="um atendimento mais completo e uma receita extra por indicação",
        papel="o despachante resolve a burocracia que muitas vezes exige certificado digital"),
    "tecnologia": dict(
        rotulo="Tecnologia", quem="empresas de tecnologia", clientes="os clientes atendidos",
        momento="em integrações com o governo, assinaturas digitais e documentos fiscais",
        dor="um projeto travado na integração por falta de certificado",
        ganho="entregas mais rápidas e uma receita extra por indicação",
        papel="muitas soluções de tecnologia dependem de um certificado válido do cliente"),
    "internet": dict(
        rotulo="Portais e internet", quem="portais e empresas de serviços de informação na internet",
        clientes="as empresas que usam o portal",
        momento="para emitir notas, assinar documentos e acessar os serviços digitais do governo",
        dor="o cliente perdendo tempo para resolver o certificado sem ter a quem recorrer",
        ganho="um serviço a mais para o público do portal e uma receita extra por indicação",
        papel="o portal já fala todos os dias com empresas que precisam de certificado digital"),
    "associacao": dict(
        rotulo="Associações", quem="associações empresariais", clientes="os associados",
        momento="no dia a dia fiscal e no acesso aos serviços públicos digitais",
        dor="associados com dificuldade para emitir ou renovar o certificado",
        ganho="um benefício a mais para os associados e receita para a associação",
        papel="a associação é a referência que o empresário consulta"),
    "coworking": dict(
        rotulo="Coworkings", quem="coworkings", clientes="as empresas e profissionais do espaço",
        momento="na abertura de empresa, na emissão de notas e na assinatura de documentos",
        dor="o residente perdendo tempo para resolver o certificado",
        ganho="um serviço a mais no espaço e uma receita extra",
        papel="o coworking é a casa de muitas empresas em início de atividade"),
    "franquia": dict(
        rotulo="Franquias", quem="franqueadoras", clientes="as unidades franqueadas",
        momento="na abertura de cada nova unidade e nas renovações",
        dor="uma unidade nova atrasando a inauguração por causa do certificado",
        ganho="abertura de unidades mais ágil e uma receita extra para a rede",
        papel="a franqueadora padroniza o que cada unidade precisa para começar"),
    "servicos_pme": dict(
        rotulo="Serviços para PMEs", quem="empresas de serviços para PMEs", clientes="as pequenas e médias empresas atendidas",
        momento="para emitir notas, acessar a Receita e assinar documentos",
        dor="o cliente parado porque o certificado venceu sem ninguém avisar",
        ganho="mais um serviço para oferecer e uma receita extra",
        papel="vocês já são o parceiro de confiança dessas empresas"),
}

# (canal, ângulo, assunto, corpo) — 8 de WhatsApp + 7 de e-mail
MODELOS = [
    ("whatsapp", "apresentacao", "",
     "Olá, {{nome}}! Tudo bem? Sou {{vendedor}}, da MS Certificação Digital (Autoridade de Registro ICP-Brasil). "
     "Trabalhamos com {quem} aqui da região: {clientes} precisam de certificado digital {momento}, e nós cuidamos "
     "de todo o atendimento.\n\nPosso te explicar em 2 minutos como funciona a parceria?\n\n" + RODAPE),
    ("whatsapp", "apresentacao", "",
     "Oi, {{nome}}! Aqui é {{vendedor}}, da MS Certificação Digital. Conheci a {{empresa}} e lembrei que {papel}.\n\n"
     "Temos um programa de parceria pensado para {quem}: vocês indicam e a MS faz todo o atendimento, da emissão "
     "à renovação. Faz sentido conversarmos?\n\n" + RODAPE),
    ("whatsapp", "apresentacao", "",
     "Olá, {{nome}}! Uma pergunta rápida: quando {clientes} precisam emitir ou renovar o certificado digital, para "
     "quem vocês indicam hoje?\n\nSou {{vendedor}}, da MS Certificação Digital, e estamos montando parcerias com "
     "{quem} em {{cidade}}.\n\n" + RODAPE),
    ("whatsapp", "praticidade", "",
     "Olá, {{nome}}! Retomando nosso contato: a ideia da parceria é evitar {dor}.\n\nVocês só indicam; a MS atende, "
     "faz a validação (presencial ou por videoconferência) e avisa antes do vencimento. Posso te mandar como funciona?"),
    ("whatsapp", "praticidade", "",
     "Oi, {{nome}}! Um detalhe de que os parceiros gostam: a MS controla o vencimento dos certificados de {clientes} "
     "e avisa com antecedência. Ninguém é pego de surpresa e a {{empresa}} não precisa se preocupar com isso.\n\n"
     "Vale uma conversa rápida?"),
    ("whatsapp", "receita", "",
     "Olá, {{nome}}! Cada certificado indicado pela {{empresa}} gera remuneração para vocês, inclusive nas renovações "
     "dos anos seguintes. Para {quem}, isso vira {ganho}.\n\nQuem cuida de parcerias aí?"),
    ("whatsapp", "receita", "",
     "Oi, {{nome}}! Os certificados de {clientes} são renovados de tempos em tempos. Com a parceria, cada renovação "
     "também gera remuneração para a {{empresa}}, e a MS faz todo o trabalho.\n\nPosso te explicar os detalhes?"),
    ("whatsapp", "encerramento", "",
     "Olá, {{nome}}! Para não insistir, este é meu último contato sobre a parceria da MS Certificação Digital com "
     "{quem}. Se um dia fizer sentido, é só responder aqui. Obrigado pela atenção!"),
    ("email", "apresentacao", "Parceria MS Certificação Digital + {{empresa}}",
     "Olá, {{nome}}, tudo bem?\n\nSou {{vendedor}}, da MS Certificação Digital, Autoridade de Registro ICP-Brasil.\n\n"
     "Trabalhamos com {quem} e sabemos que {clientes} precisam de certificado digital {momento}. Por isso criamos "
     "um programa de parceria simples:\n\n1. A {{empresa}} indica o cliente;\n2. A MS faz todo o atendimento, emissão "
     "e validação;\n3. A {{empresa}} é remunerada por certificado emitido;\n4. Cuidamos do vencimento e da renovação, "
     "mantendo vocês como parceiros.\n\nPodemos marcar 15 minutos para eu apresentar?\n\n" + RODAPE),
    ("email", "apresentacao", "Uma pergunta sobre os certificados dos clientes da {{empresa}}",
     "Olá, {{nome}}!\n\nQuando {clientes} precisam emitir ou renovar o certificado digital, quem resolve isso hoje?\n\n"
     "Pergunto porque {papel}, e a MS Certificação Digital tem uma parceria feita para {quem}: vocês indicam e nós "
     "cuidamos de tudo, do atendimento à renovação.\n\nSe fizer sentido, me diga o melhor dia para uma conversa "
     "rápida.\n\n" + RODAPE),
    ("email", "praticidade", "Menos dor de cabeça com certificado digital na {{empresa}}",
     "Olá, {{nome}}!\n\nRetomando meu contato. O problema mais comum que ouvimos de {quem} é {dor}.\n\nNa parceria, "
     "isso fica com a MS: atendimento, validação presencial em Recife ou por videoconferência e aviso antes de cada "
     "vencimento. Para a {{empresa}}, basta indicar.\n\nFaz sentido conversarmos esta semana?"),
    ("email", "praticidade", "Como funciona a indicação para a MS (é simples)",
     "Olá, {{nome}}!\n\nResumindo como a indicação funciona na prática:\n\n- vocês passam o contato do cliente (ou "
     "enviam o link de parceria);\n- a MS chama o cliente, agenda a validação e emite o certificado;\n- vocês "
     "acompanham tudo, sem precisar mexer em sistema nenhum.\n\nAssim {clientes} são atendidos rápido {momento}.\n\n"
     "Posso mandar o passo a passo?"),
    ("email", "receita", "Receita recorrente com os certificados dos clientes da {{empresa}}",
     "Olá, {{nome}}!\n\nUm ponto que chama a atenção de {quem}: cada certificado indicado gera remuneração, e as "
     "renovações dos anos seguintes também. A MS controla os vencimentos e avisa os clientes.\n\nNa prática, é "
     "{ganho}.\n\nQuem é a pessoa responsável por parcerias na {{empresa}}?"),
    ("email", "receita", "{{empresa}}: uma receita que se repete a cada renovação",
     "Olá, {{nome}}!\n\nCertificado digital vence, e o cliente precisa renovar. Com a parceria, cada renovação de "
     "{clientes} indicada pela {{empresa}} volta a gerar remuneração para vocês, sem trabalho extra.\n\nSe quiser, "
     "mostro em uma conversa curta como outros parceiros organizam isso."),
    ("email", "encerramento", "Encerrando meu contato — MS Certificação Digital",
     "Olá, {{nome}}!\n\nPara não lotar sua caixa, este é meu último e-mail sobre a parceria da MS Certificação "
     "Digital com {quem}.\n\nSe em algum momento fizer sentido oferecer certificado digital para {clientes}, é só "
     "responder esta mensagem que eu retomo de onde paramos.\n\nObrigado pela atenção!"),
]


def _preencher(texto: str, seg: dict) -> str:
    """Troca {quem}, {clientes}... e deixa {{nome}}, {{empresa}}... para o envio (por isso não usa str.format)."""
    for chave, valor in seg.items():
        texto = texto.replace("{" + chave + "}", valor)
    return texto


def modelos_do_segmento(codigo: str) -> list[dict]:
    """Os 15 modelos prontos de um segmento (nome, canal, ângulo, assunto, corpo)."""
    seg = SEGMENTOS[codigo]
    lista, contagem = [], {"whatsapp": 0, "email": 0}
    for canal, angulo, assunto, corpo in MODELOS:
        contagem[canal] += 1
        texto = _preencher(corpo, seg) + (ASSINATURA if canal == "email" else "")
        lista.append({"nome": f"{seg['rotulo']} · {'WhatsApp' if canal == 'whatsapp' else 'E-mail'} {contagem[canal]} · "
                              f"{NOMES_ANGULO[angulo]}",
                      "canal": canal, "angulo": angulo, "categoria": codigo,
                      "assunto": _preencher(assunto, seg), "corpo": texto})
    return lista


def garantir(db) -> int:
    """Cria os modelos que ainda não existem (pelo nome). Os que a equipe editou ficam como estão."""
    from .modelos import Template

    existentes = {n for (n,) in db.execute(select(Template.nome).where(Template.categoria != ""))}
    novos = 0
    for codigo in SEGMENTOS:
        for m in modelos_do_segmento(codigo):
            if m["nome"] not in existentes:
                db.add(Template(nome=m["nome"], canal=m["canal"], assunto=m["assunto"], corpo=m["corpo"],
                                categoria=m["categoria"], angulo=m["angulo"]))
                novos += 1
    return novos
