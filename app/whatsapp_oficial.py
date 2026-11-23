"""API oficial do WhatsApp por AR (pedido da Maria em 16/11/2026; plano em docs/whatsapp-oficial.md).

Cada AR guarda aqui o número dela na Plataforma do WhatsApp Business da Meta (tabela contas_whatsapp_oficial): o ID
da conta do WhatsApp Business, a "Identificação do número de telefone", o token permanente do usuário do sistema e a
chave secreta do app (os dois criptografados, nunca voltam para a tela) e o token de verificação do webhook (gerado
aqui, a pessoa copia para o painel da Meta).

Etapa 1: guardar, testar a conexão, ativar o número novo na Meta (ativar_numero, com a senha de 6 números), mandar
uma mensagem de teste (texto simples ou um modelo aprovado) e receber pelo webhook as respostas, o SAIR e a situação
das mensagens.
Etapa 2 (16/11/2026, pedido da Maria): os modelos do aviso de vencimento (pedir a aprovação e acompanhar) e os avisos
da Renovação pelo número oficial (Campanha.envio_oficial): fila própria, a arte do site no cabeçalho e os botões
Quero renovar / Já renovei / Parar avisos. As outras campanhas continuam pelo WhatsApp Leads (QR code).
"""

import json
import re
import secrets
from pathlib import Path

from sqlalchemy import select

from . import util
from .banco import agora
from .integracoes import whatsapp_cloud
from .modelos import ContaWhatsAppOficial, ModeloWhatsAppOficial
from .seguranca import criptografar, descriptografar

MODELO_DE_TESTE = ("hello_world", "en_US")  # o modelo de exemplo da Meta: só sai dos números de teste dela (131058)
TEXTO_DE_TESTE = ("Mensagem de teste do sistema pela API oficial do WhatsApp. Se ela chegou, o envio pelo número "
                  "oficial está funcionando.")
ERROS_DO_TESTE = {  # os códigos da Meta no envio do teste, explicados para a tela
    131047: ("A Meta só deixa mandar texto livre para quem escreveu para o número oficial nas últimas 24 horas: mande um "
             "\"oi\" do celular para o número oficial e tente de novo (ou use um modelo aprovado)."),
    131058: ("O modelo de exemplo hello_world só sai dos números de teste da Meta: deixe o modelo em branco (o teste vai "
             "como texto simples) ou escreva o nome de um modelo aprovado."),
    # 22/11/2026: o teste mandava o modelo sem os campos ({{1}}, {{2}}...) e a Meta recusava
    132000: ("Esse modelo tem campos para preencher (nome, certificado, vencimento...) e o teste manda o modelo sem eles. "
             "Para o aviso de vencimento, use o botão \"Enviar um aviso de exemplo\" (ele preenche com dados de exemplo)."),
    132001: ("A Meta não achou um modelo com esse nome nesse idioma. Escreva o nome exatamente como aparece no Gerenciador "
             "do WhatsApp (tudo minúsculo, com _), por exemplo aviso_vencimento_certificado, e o idioma pt_BR."),
}


def da_ar(db) -> ContaWhatsAppOficial | None:
    """A conta da AR da tela (a sessão da tela já enxerga só a AR da pessoa: app/isolamento.py)."""
    return db.execute(select(ContaWhatsAppOficial).order_by(ContaWhatsAppOficial.id).limit(1)).scalars().first()


def contas_do_webhook(db, numeros: set[str] | None = None) -> list[ContaWhatsAppOficial]:
    """Contas de todas as ARs (o webhook chega sem AR). `numeros`: só as desses phone_number_id."""
    consulta = select(ContaWhatsAppOficial).execution_options(sem_filtro_de_ar=True)
    if numeros is not None:
        consulta = consulta.where(ContaWhatsAppOficial.phone_number_id.in_(list(numeros)))
    return list(db.execute(consulta).scalars())


def token(conta: ContaWhatsAppOficial) -> str:
    return descriptografar(conta.token_cripto)


def segredo(conta: ContaWhatsAppOficial) -> str:
    return descriptografar(conta.segredo_cripto)


def _so_numeros(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def salvar(db, conta: ContaWhatsAppOficial | None, dados: dict) -> tuple[ContaWhatsAppOficial | None, list[str]]:
    """Grava os dados da tela. Token e chave secreta em branco = continuam os de antes. Devolve (conta, problemas)."""
    waba_id, numero_id = _so_numeros(dados.get("waba_id", "")), _so_numeros(dados.get("phone_number_id", ""))
    novo_token, novo_segredo = (dados.get("token") or "").strip(), (dados.get("segredo") or "").strip()
    problemas = []
    if not numero_id:
        problemas.append("Preencha a Identificação do número de telefone (só números, como aparece no Gerenciador "
                         "do WhatsApp).")
    if not novo_token and not (conta and conta.token_cripto):
        problemas.append("Cole o token permanente do usuário do sistema.")
    if novo_token and (len(novo_token) < 30 or " " in novo_token):
        problemas.append("O token parece incompleto: copie de novo o token inteiro (uma linha só, sem espaços).")
    outra = db.execute(select(ContaWhatsAppOficial).execution_options(sem_filtro_de_ar=True).where(
        ContaWhatsAppOficial.phone_number_id == numero_id)).scalars().first() if numero_id else None
    if outra is not None and (conta is None or outra.id != conta.id):
        problemas.append("Este número já está cadastrado em outra conta do sistema.")
    if problemas:
        return conta, problemas
    if conta is None:
        conta = ContaWhatsAppOficial()
        db.add(conta)
    if numero_id != conta.phone_number_id:
        conta.numero, conta.situacao, conta.testado_em = "", "", None  # outro número: o teste antigo não vale
    conta.nome = (dados.get("nome") or "").strip()[:120]
    conta.waba_id, conta.phone_number_id = waba_id, numero_id
    if novo_token:
        conta.token_cripto = criptografar(novo_token)
    if novo_segredo:
        conta.segredo_cripto = criptografar(novo_segredo)
    if not conta.verificacao:
        conta.verificacao = secrets.token_urlsafe(24)
    db.flush()
    return conta, []


def situacao(conta: ContaWhatsAppOficial | None) -> dict:
    try:
        return json.loads(conta.situacao) if conta and conta.situacao else {}
    except ValueError:
        return {}


QUALIDADE = {"GREEN": "Alta", "YELLOW": "Média", "RED": "Baixa", "UNKNOWN": "Ainda sem avaliação"}
STATUS_DO_NUMERO = {"CONNECTED": "Conectado", "PENDING": "Pendente", "DISCONNECTED": "Desconectado",
                    "FLAGGED": "Sinalizado pela Meta", "RESTRICTED": "Restrito pela Meta", "BANNED": "Banido",
                    "RATE_LIMITED": "No limite de envio", "UNVERIFIED": "Não confirmado", "DELETED": "Apagado",
                    "MIGRATED": "Migrado", "OFFLINE": "Fora do ar", "UNKNOWN": "Desconhecido"}
AVISO_SEM_ATIVAR = ("O número ainda não está ativado na API da Meta e nada sai por ele: digite uma senha de 6 números "
                    "em \"Ativar o número\", logo abaixo.")
AVISO_SEM_CODIGO = ("O número ainda não foi confirmado com o código da Meta: confirme por SMS ou ligação no Gerenciador "
                    "do WhatsApp > Números de telefone e depois use \"Ativar o número\", logo abaixo.")


ONDE_FICA_A_CONTA = "Configurações do negócio > Contas > Contas de mensagens"
AVISO_SEM_CONTA = ("Não consegui descobrir a conta de mensagens do número pelo token. Na Meta, dê essa conta ao usuário "
                   f"do sistema ({ONDE_FICA_A_CONTA} > a conta do número > Atribuir pessoas > o usuário do sistema, "
                   "controle total) e clique em Testar conexão, ou cole o ID dela na tela.")
AVISO_CONTAS_SEM_O_NUMERO = ("Nenhuma das contas de mensagens que o token alcança tem este número (pode ser só a de "
                             "teste). Na Meta, dê ao usuário do sistema a conta de mensagens do número "
                             f"({ONDE_FICA_A_CONTA} > Atribuir pessoas, controle total) e clique em Testar conexão, ou "
                             "cole o ID dela na tela.")
AVISO_VARIAS_CONTAS = ("O token alcança mais de uma conta de mensagens e não consegui saber qual tem o número: cole o ID "
                       f"da conta certa na tela ({ONDE_FICA_A_CONTA}).")
AVISO_NUMERO_FORA = ("O número não está na conta de mensagens informada (pode ser a conta de teste): cole o ID da conta "
                     f"do número na tela ({ONDE_FICA_A_CONTA}) ou deixe o campo em branco para o sistema procurar.")


def conta_do_numero(conta: ContaWhatsAppOficial) -> tuple[str, str]:
    """Acha a conta de mensagens (a antiga "conta do WhatsApp Business", WABA) do número pelo token: as contas das
    permissões granulares do token e as atribuídas ao usuário do sistema (o token de um administrador vale para todos
    os ativos e vem sem contas nas permissões). Com mais de uma, fica a que tem o número (a de teste sai).
    Devolve (id, aviso para a tela); id vazio = não achou."""
    chave, candidatas = token(conta), []
    for buscar in (whatsapp_cloud.contas_do_token, whatsapp_cloud.contas_atribuidas):
        try:
            candidatas += [c for c in buscar(chave) if c not in candidatas]
        except whatsapp_cloud.ErroWhatsApp:
            pass
    if not candidatas:
        return "", AVISO_SEM_CONTA
    com_o_numero, conferidas = [], 0
    for candidata in candidatas:
        try:
            numeros = whatsapp_cloud.numeros_da_conta(candidata, chave)
        except whatsapp_cloud.ErroWhatsApp:
            continue
        conferidas += 1
        if conta.phone_number_id in numeros:
            com_o_numero.append(candidata)
    if len(com_o_numero) == 1:
        return com_o_numero[0], ""
    if len(candidatas) == 1 and not conferidas:  # não deu para conferir os números: fica a única
        return candidatas[0], ""
    if conferidas and not com_o_numero:
        return "", AVISO_CONTAS_SEM_O_NUMERO
    return "", AVISO_VARIAS_CONTAS


def numero_fora_da_conta(conta: ContaWhatsAppOficial) -> bool:
    """A conta de mensagens preenchida na tela não tem o número (ex.: a de teste)? False quando não deu para conferir."""
    try:
        numeros = whatsapp_cloud.numeros_da_conta(conta.waba_id, token(conta))
    except whatsapp_cloud.ErroWhatsApp:
        return False
    return bool(numeros) and conta.phone_number_id not in numeros


def numero_ativado(registro: dict) -> bool | None:
    """O número está ativado na API (registrado na Cloud API)? None = a Meta não disse."""
    plataforma = str(registro.get("platform_type") or "").upper()
    if plataforma:
        return plataforma == "CLOUD_API"
    status = str(registro.get("status") or "").upper()
    return (status == "CONNECTED") if status else None


def testar(db, conta: ContaWhatsAppOficial) -> dict:
    """Pergunta à Meta pelo número (teste de conexão), descobre o ID da conta do WhatsApp Business pelo token se ele não
    foi preenchido, liga o app à conta (para o webhook receber as respostas) e guarda o resultado para a tela.
    `avisos`: o que não deu certo, sem impedir o resto (ex.: a conta não foi achada pelo token)."""
    dados = whatsapp_cloud.consultar_numero(conta.phone_number_id, token(conta))
    limite = str(dados.get("whatsapp_business_manager_messaging_limit") or "")
    resultado = {"numero": dados.get("display_phone_number", ""), "nome": dados.get("verified_name", ""),
                 "qualidade": QUALIDADE.get(str(dados.get("quality_rating") or "").upper(),
                                            dados.get("quality_rating") or "—"),
                 "limite": limite.replace("TIER_", "").replace("UNLIMITED", "ilimitado") or "—",
                 "nome_aprovado": dados.get("name_status", ""), "app_ligado": False, "avisos": []}
    avisos = resultado["avisos"]
    try:  # ativado na API? (número novo: falta o "Ativar o número", ativar_numero)
        registro = whatsapp_cloud.registro_do_numero(conta.phone_number_id, token(conta))
    except whatsapp_cloud.ErroWhatsApp:
        registro = {}
    resultado["ativado"] = numero_ativado(registro)
    status = str(registro.get("status") or "").upper()
    resultado["status_numero"] = STATUS_DO_NUMERO.get(status, status)
    if resultado["ativado"] is False:
        sem_codigo = str(registro.get("code_verification_status") or "").upper() in ("NOT_VERIFIED", "EXPIRED")
        avisos.append(AVISO_SEM_CODIGO if sem_codigo else AVISO_SEM_ATIVAR)
    if not conta.waba_id:  # a conta de mensagens (antigo WABA): o sistema procura pelo token
        conta.waba_id, aviso = conta_do_numero(conta)
        if aviso:
            avisos.append(aviso)
    elif numero_fora_da_conta(conta):
        avisos.append(AVISO_NUMERO_FORA)
    if conta.waba_id:
        try:
            resultado["app_ligado"] = whatsapp_cloud.inscrever_app(conta.waba_id, token(conta))
        except whatsapp_cloud.ErroWhatsApp as erro:
            avisos.append(f"Não consegui ligar o app à conta do WhatsApp (as respostas não chegam até isso): {erro}")
    conta.numero = str(resultado["numero"])[:30]
    conta.situacao, conta.testado_em = json.dumps(resultado, ensure_ascii=False), agora()
    return resultado


SENHA_DO_NUMERO = re.compile(r"^\d{6}$")
ERROS_DA_ATIVACAO = {  # os códigos da Meta no POST /register, explicados para a tela
    133004: "A Meta está com instabilidade agora. Tente de novo em alguns minutos.",
    133005: ("A senha não confere com a verificação em duas etapas que o número já tem: use a mesma senha de 6 "
             "números criada antes (ou troque no Gerenciador do WhatsApp > Números de telefone > o número > "
             "Verificação em duas etapas)."),
    133006: ("Antes de ativar, confirme o número com o código (SMS ou ligação) no Gerenciador do WhatsApp > Números de "
             "telefone."),
    133008: "Muitas tentativas com a senha errada. Espere o tempo que a Meta pede e tente de novo com a senha certa.",
    133009: "Tentativas rápidas demais. Espere alguns minutos e tente de novo.",
    133015: "Este número foi apagado há pouco e a Meta ainda está terminando. Espere alguns minutos e tente de novo.",
    133016: ("A Meta aceita até 10 tentativas de ativar o número a cada 3 dias e esse limite acabou. Tente de novo "
             "daqui a 3 dias."),
}


def ativar_numero(db, conta: ContaWhatsAppOficial, senha: str, repeticao: str | None = None) -> dict:
    """Ativa (registra) o número na API da Meta com a senha de 6 números (a verificação em duas etapas dele) e refaz o
    teste de conexão para a tela. É o último passo de um número novo e a Meta só aceita pela API (pedido da Maria em
    18/11/2026). A senha não fica guardada em lugar nenhum (nem no registro de atividades, nem nas mensagens de erro)."""
    senha = re.sub(r"\s", "", senha or "")
    if not SENHA_DO_NUMERO.match(senha):
        raise whatsapp_cloud.ErroWhatsApp("A senha precisa ter exatamente 6 números.")
    if repeticao is not None and re.sub(r"\s", "", repeticao) != senha:
        raise whatsapp_cloud.ErroWhatsApp("As duas senhas não são iguais: digite a mesma senha de 6 números nos dois "
                                          "campos.")
    try:
        whatsapp_cloud.registrar_numero(conta.phone_number_id, token(conta), senha)
    except whatsapp_cloud.ErroWhatsApp as erro:
        detalhe = str(erro).replace(senha, "******")
        amigavel = ERROS_DA_ATIVACAO.get(erro.codigo)
        raise whatsapp_cloud.ErroWhatsApp(f"{amigavel} ({detalhe})" if amigavel else detalhe, erro.codigo) from None
    try:
        resultado = testar(db, conta)
    except whatsapp_cloud.ErroWhatsApp:
        return {"avisos": []}
    if resultado.get("ativado") is False:  # a Meta aceitou, mas ainda não mostra o número como ativado
        resultado["ativado"] = None
        resultado["avisos"] = [a for a in resultado["avisos"] if a not in (AVISO_SEM_ATIVAR, AVISO_SEM_CODIGO)]
        resultado["avisos"].append("A Meta aceitou a ativação, mas pode levar alguns minutos para mostrar o número "
                                   "como conectado: clique em Testar conexão daqui a pouco.")
        conta.situacao = json.dumps(resultado, ensure_ascii=False)
    return resultado


# ---------------------------------------------------------------- conversas do número oficial (tela API Oficial)
# Pedido da Maria em 21/11/2026: "preciso ver as respostas dos clientes em algum lugar". O número oficial está ligado
# direto na API (não abre em celular nenhum): o sistema guarda tudo o que ele manda e tudo o que chega nele.

SITUACAO_DA_META = {"sent": "enviada", "delivered": "entregue", "read": "lida", "failed": "falhou"}
ORDEM_DA_SITUACAO = {"enviada": 1, "entregue": 2, "lida": 3}  # a Meta pode avisar fora de ordem: nunca volta
TIPO_QUE_CHEGA = {"text": "texto", "button": "botao", "interactive": "botao"}  # o resto (imagem, áudio...) = mídia
MARCA_DA_ARTE = "[com a arte do aviso]\n"  # 1ª linha do aviso que foi com a arte (a tela mostra como etiqueta)


def chave_da_conversa(telefone: str) -> str:
    """Telefone com DDD e o 9 dos celulares (como a tela Conversas); estrangeiro: só os dígitos."""
    return util.com_nono_digito(telefone) or util.so_digitos(telefone)


def guardar_conversa(db, conta: ContaWhatsAppOficial, telefone: str, direcao: str, texto: str, tipo: str = "texto",
                     wamid: str = "", nome: str = "", lead_id: int | None = None, status: str = ""):
    """Guarda uma mensagem do número oficial (a que saiu ou a que chegou) para a tela API Oficial, na AR da conta. A
    Meta às vezes manda o mesmo evento de novo: a mensagem com o mesmo id não entra duas vezes. Devolve a linha nova
    (None = já estava ou sem telefone)."""
    from .modelos import MensagemOficial

    chave = chave_da_conversa(telefone)
    if conta is None or not chave:
        return None
    if wamid and db.execute(select(MensagemOficial.id).where(MensagemOficial.wamid == wamid)
                            .execution_options(sem_filtro_de_ar=True)).first():
        return None
    linha = MensagemOficial(tenant_id=conta.tenant_id, conta_id=conta.id, telefone=chave[:20], nome=(nome or "")[:200],
                            direcao=direcao, tipo=tipo, texto=texto or "", wamid=(wamid or "")[:160],
                            status=status or ("recebida" if direcao == "entrada" else "enviada"), lead_id=lead_id,
                            lida=direcao != "entrada")
    db.add(linha)
    db.flush()
    return linha


def atualizar_entrega(db, wamid: str, status_da_meta: str, erro: str = "") -> bool:
    """A Meta avisou a situação de uma mensagem que o número oficial mandou (enviada, entregue, lida ou falhou)."""
    from .modelos import MensagemOficial

    situacao_nova = SITUACAO_DA_META.get(status_da_meta)
    if not wamid or not situacao_nova:
        return False
    linha = db.execute(select(MensagemOficial).where(MensagemOficial.wamid == wamid)
                       .execution_options(sem_filtro_de_ar=True)).scalars().first()
    if linha is None or linha.direcao != "saida":
        return False
    if situacao_nova == "falhou":
        linha.status, linha.erro = "falhou", (erro or "")[:500]
    elif ORDEM_DA_SITUACAO[situacao_nova] > ORDEM_DA_SITUACAO.get(linha.status, 0):
        linha.status = situacao_nova
    else:
        return False
    linha.atualizado_em = agora()
    return True


def texto_do_aviso(modelo, valores: list[str], com_arte: bool) -> str:
    """O aviso como o cliente vê (o corpo do modelo preenchido, o rodapé e os botões), para a tela API Oficial."""
    return ((MARCA_DA_ARTE if com_arte else "") + preencher(modelo.corpo, valores) + "\n\n"
            + (modelo.rodape or RODAPE_RENOVACAO) + "\n" + " · ".join(f"[{b}]" for b in BOTOES_RENOVACAO))


def enviar_teste(conta: ContaWhatsAppOficial, telefone: str, modelo: str = "", idioma: str = "") -> str:
    """Mensagem de teste para um número da própria equipe. Sem modelo: texto simples (de graça; a Meta só entrega para
    quem escreveu para o número oficial nas últimas 24 horas). Com modelo: o modelo aprovado, no idioma escolhido (sem
    idioma, português; o hello_world, de exemplo, só existe em inglês e só sai dos números de teste da Meta: erro
    131058, visto em 19/11/2026, quando o teste passou a ser em texto simples, pedido da Maria)."""
    nome = (modelo or "").strip()
    try:
        if not nome:
            return whatsapp_cloud.enviar_texto_por(conta.phone_number_id, token(conta), telefone, TEXTO_DE_TESTE)
        lingua = (idioma or "").strip() or (MODELO_DE_TESTE[1] if nome == MODELO_DE_TESTE[0] else "pt_BR")
        return whatsapp_cloud.enviar_modelo(conta.phone_number_id, token(conta), telefone, nome, lingua)
    except whatsapp_cloud.ErroWhatsApp as erro:
        amigavel = ERROS_DO_TESTE.get(erro.codigo)
        if amigavel:
            raise whatsapp_cloud.ErroWhatsApp(f"{amigavel} ({erro})", erro.codigo) from None
        raise


# ---------------------------------------------------------------- Etapa 2: modelos e Renovação pela API oficial
# Pedido da Maria em 16/11/2026: "que continue fazendo essa campanha mas que seja enviada pela API da Meta". Os avisos
# de vencimento saem do número oficial da AR com um modelo aprovado (utilidade): a arte do site no cabeçalho (desenhada
# pelo computador do WhatsApp Leads, como no QR code) e três botões (Quero renovar, Já renovei, Parar avisos) que
# voltam pelo webhook e fazem o trabalho sozinhos (tratar_botao).

USO_ARTE, USO_TEXTO = "renovacao_arte", "renovacao_texto"
NOMES_DOS_MODELOS = {USO_ARTE: "aviso_vencimento_certificado_arte", USO_TEXTO: "aviso_vencimento_certificado"}
NOMES_DE_USO = {USO_ARTE: "Aviso com a arte", USO_TEXTO: "Aviso só com o texto"}
BOTOES_RENOVACAO = ["Quero renovar", "Já renovei", "Parar avisos"]
ACOES_DOS_BOTOES = ["renovar", "renovei", "parar"]  # na ordem dos botões: o payload "renov:<ação>:<tarefa>" volta
RODAPE_RENOVACAO = "Para não receber estes avisos, toque em Parar avisos."
EXEMPLO_DOS_VALORES = ["Guilherme", "e-CNPJ A1 em nome de EMPRESA EXEMPLO LTDA", "21/11/2026 (faltam 5 dias)"]
IMAGEM_DE_EXEMPLO = Path(__file__).resolve().parent / "static" / "renovacao" / "aviso_exemplo.png"
ACAO_ARTE = "desenhar_arte"  # pedido ao computador do WhatsApp Leads (comandos_whatsapp): só desenha e devolve a arte
ESPERA_DA_ARTE_MIN = 15      # sem a arte nesse tempo (computador desligado), o aviso sai com o modelo só de texto
ARTES_POR_RODADA = 5         # pedidos de arte por rodada do relógio (o computador desenha um por vez)
POR_RODADA = 5               # avisos pela API em cada rodada do relógio (a cada minuto)
NOVA_TENTATIVA_MIN = 30      # aviso que a Meta recusou tenta de novo depois disso (sem insistir a cada minuto)
SITUACOES_DO_MODELO = {"APPROVED": "Aprovado", "PENDING": "Em análise na Meta", "REJECTED": "Recusado",
                       "PAUSED": "Pausado pela Meta", "DISABLED": "Desativado pela Meta", "IN_APPEAL": "Em recurso",
                       "erro": "Não chegou à Meta"}
CATEGORIAS = {"UTILITY": "Utilidade", "MARKETING": "Marketing", "AUTHENTICATION": "Autenticação"}


class EnvioOficialRecusado(Exception):
    """O aviso não saiu pela API oficial agora (motivo pronto para a tela)."""


class EsperandoArte(EnvioOficialRecusado):
    """A arte do aviso está sendo desenhada no computador do WhatsApp Leads: o aviso sai na próxima rodada."""


def corpo_renovacao(nome_da_marca: str) -> str:
    """O texto do modelo do aviso ({{1}} nome do contato, {{2}} o certificado ou a lista, {{3}} o vencimento)."""
    return ("Olá, {{1}}! Aqui é da " + nome_da_marca + ".\n\n"
            "Aviso de vencimento de certificado digital: {{2}}.\n"
            "Vencimento: {{3}}.\n\n"
            "Para não ficar sem certificado, toque em Quero renovar e a nossa equipe cuida de tudo. "
            "Se você já renovou, toque em Já renovei.")


def componentes_renovacao(nome_da_marca: str, codigo_da_imagem: str = "") -> list[dict]:
    """As partes do modelo como a Meta pede (com a imagem de exemplo no cabeçalho, no modelo com a arte)."""
    partes = []
    if codigo_da_imagem:
        partes.append({"type": "HEADER", "format": "IMAGE", "example": {"header_handle": [codigo_da_imagem]}})
    partes.append({"type": "BODY", "text": corpo_renovacao(nome_da_marca),
                   "example": {"body_text": [EXEMPLO_DOS_VALORES]}})
    partes.append({"type": "FOOTER", "text": RODAPE_RENOVACAO})
    partes.append({"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": b} for b in BOTOES_RENOVACAO]})
    return partes


def preencher(corpo: str, valores: list[str]) -> str:
    """O texto do modelo com os valores (o que o cliente lê), para o histórico e as telas."""
    for i, valor in enumerate(valores, start=1):
        corpo = corpo.replace("{{" + str(i) + "}}", " ".join(str(valor or "").split()))
    return corpo


def conta_da_ar(db, ar: int | None) -> ContaWhatsAppOficial | None:
    """A conta oficial de uma AR (as rotinas e a fila não têm AR na sessão)."""
    consulta = select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.tenant_id == ar if ar is not None
                                                  else ContaWhatsAppOficial.tenant_id.is_(None))
    return db.execute(consulta.order_by(ContaWhatsAppOficial.id).limit(1)
                      .execution_options(sem_filtro_de_ar=True)).scalars().first()


def modelos_da_conta(db, conta: ContaWhatsAppOficial | None) -> dict[str, ModeloWhatsAppOficial]:
    if conta is None:
        return {}
    linhas = db.execute(select(ModeloWhatsAppOficial).where(ModeloWhatsAppOficial.conta_id == conta.id)
                        .order_by(ModeloWhatsAppOficial.id).execution_options(sem_filtro_de_ar=True)).scalars().all()
    return {m.uso: m for m in linhas}


def falta_para_renovacao(db, ar: int | None) -> str:
    """Por que os avisos da Renovação ainda não podem sair pela API oficial nesta AR ("" = pode): falta a conta, o
    teste de conexão ou o modelo só de texto aprovado (ele vale para todos; o com a arte é o preferido)."""
    conta = conta_da_ar(db, ar)
    if conta is None or not conta.token_cripto:
        return "configure a API oficial da Meta em Configurações > WhatsApp (o número e o token)"
    if not conta.testado_em:
        return "teste a conexão da API oficial em Configurações > WhatsApp"
    if situacao(conta).get("ativado") is False:  # número novo sem o último passo: a Meta recusaria todo envio
        return "ative o número na Meta em Configurações > WhatsApp > API oficial da Meta (Ativar o número)"
    if not conta.segredo_cripto:  # sem ela o webhook recusa tudo: as respostas e os botões não chegariam
        return ("cole a chave secreta do app em Configurações > WhatsApp > API oficial da Meta (sem ela as respostas "
                "e os botões dos avisos não chegam ao sistema)")
    texto = modelos_da_conta(db, conta).get(USO_TEXTO)
    if texto is None:
        return "peça a aprovação dos modelos do aviso em Configurações > WhatsApp > API oficial da Meta"
    if texto.status != "APPROVED":
        return (f"o modelo do aviso está \"{SITUACOES_DO_MODELO.get(texto.status, texto.status).lower()}\" na Meta "
                "(Configurações > WhatsApp > API oficial da Meta)")
    return ""


def atualizar_modelos(db, conta: ContaWhatsAppOficial) -> int:
    """Busca na Meta a situação dos modelos do sistema (pelo nome) e guarda. Devolve quantos mudaram."""
    if not conta.waba_id:
        return 0
    remotos = {(r.get("name"), r.get("language")): r for r in whatsapp_cloud.modelos_da_conta(conta.waba_id, token(conta))}
    locais = modelos_da_conta(db, conta)
    mudaram = 0
    for uso, nome in NOMES_DOS_MODELOS.items():
        r = remotos.get((nome, "pt_BR"))
        if r is None:
            continue
        m = locais.get(uso)
        if m is None:  # criado na Meta fora do sistema (ex.: no Gerenciador do WhatsApp): passa a ser acompanhado
            m = ModeloWhatsAppOficial(conta_id=conta.id, uso=uso, nome=nome, com_imagem=uso == USO_ARTE,
                                      tenant_id=conta.tenant_id)
            db.add(m)
        motivo = str(r.get("rejected_reason") or "")
        novo = (str(r.get("status") or ""), str(r.get("category") or ""), "" if motivo == "NONE" else motivo,
                str(r.get("id") or m.meta_id or ""))
        if (m.status, m.categoria_meta, m.motivo, m.meta_id) != novo:
            m.status, m.categoria_meta, m.motivo, m.meta_id = novo
            m.atualizado_em = agora()
            mudaram += 1
    db.flush()
    return mudaram


def atualizar_modelos_pendentes(db) -> int:
    """Rotina de hora em hora: as contas com modelo em análise perguntam à Meta se já saiu a resposta."""
    total = 0
    pendentes = {m.conta_id for m in db.execute(select(ModeloWhatsAppOficial).where(
        ModeloWhatsAppOficial.status.in_(("PENDING", "IN_APPEAL"))).execution_options(sem_filtro_de_ar=True)).scalars()}
    for conta_id in pendentes:
        conta = db.get(ContaWhatsAppOficial, conta_id)
        if conta is None or not conta.token_cripto:
            continue
        try:
            total += atualizar_modelos(db, conta)
        except whatsapp_cloud.ErroWhatsApp:
            continue  # sem resposta da Meta agora: tenta na próxima hora
    return total


def pedir_modelos_renovacao(db, conta: ContaWhatsAppOficial) -> list[str]:
    """Pede à Meta a aprovação dos dois modelos do aviso de vencimento (com a arte e só com o texto), na categoria
    utilidade. Aprovado ou em análise fica como está; recusado vai de novo (editado). Devolve os problemas."""
    from . import marca

    if not conta.waba_id:
        return ["Falta a conta de mensagens do número: clique em Testar conexão (o sistema procura pelo token) ou "
                "cole o ID dela na tela."]
    try:
        atualizar_modelos(db, conta)  # pode já existir na Meta (criado antes ou à mão)
    except whatsapp_cloud.ErroWhatsApp as erro:
        return [f"Não consegui falar com a Meta: {erro}"]
    nome_da_marca = marca.da_ar(db, conta.tenant_id)["nome"]
    existentes, problemas, codigo_da_imagem = modelos_da_conta(db, conta), [], ""
    for uso in (USO_ARTE, USO_TEXTO):
        atual = existentes.get(uso)
        if atual is not None and atual.status in ("APPROVED", "PENDING", "IN_APPEAL"):
            continue
        try:
            if uso == USO_ARTE and not codigo_da_imagem:
                app_id = whatsapp_cloud.app_do_token(token(conta))
                if not app_id:
                    raise whatsapp_cloud.ErroWhatsApp("não consegui descobrir o app do token")
                codigo_da_imagem = whatsapp_cloud.subir_exemplo(app_id, token(conta), IMAGEM_DE_EXEMPLO.read_bytes())
            partes = componentes_renovacao(nome_da_marca, codigo_da_imagem if uso == USO_ARTE else "")
            if atual is not None and atual.meta_id and atual.status in ("REJECTED", "PAUSED", "DISABLED"):
                resposta = whatsapp_cloud.editar_modelo(atual.meta_id, token(conta), "UTILITY", partes)
                resposta = {"id": atual.meta_id, "status": "PENDING", **{k: v for k, v in resposta.items() if k != "success"}}
            else:
                resposta = whatsapp_cloud.criar_modelo(conta.waba_id, token(conta), NOMES_DOS_MODELOS[uso], "pt_BR",
                                                       "UTILITY", partes)
            situacao_nova = (str(resposta.get("status") or "PENDING"), "", str(resposta.get("id") or ""),
                             str(resposta.get("category") or ""))
        except whatsapp_cloud.ErroWhatsApp as erro:
            situacao_nova = ("erro", str(erro)[:500], "", "")
            problemas.append(f"{NOMES_DE_USO[uso]}: {erro}")
        m = atual
        if m is None:
            m = ModeloWhatsAppOficial(conta_id=conta.id, uso=uso, tenant_id=conta.tenant_id)
            db.add(m)
        m.nome, m.idioma, m.categoria, m.com_imagem = NOMES_DOS_MODELOS[uso], "pt_BR", "UTILITY", uso == USO_ARTE
        m.status, m.motivo = situacao_nova[0], situacao_nova[1]
        m.meta_id = situacao_nova[2] or m.meta_id
        m.categoria_meta = situacao_nova[3] or m.categoria_meta
        m.corpo, m.rodape = corpo_renovacao(nome_da_marca), RODAPE_RENOVACAO
        m.botoes = json.dumps(BOTOES_RENOVACAO, ensure_ascii=False)
        m.atualizado_em = agora()
    db.flush()
    return problemas


def modelo_do_aviso_pelo_nome(nome: str) -> str:
    """O nome certo do modelo do aviso de vencimento quando a pessoa escreve um deles no teste (sem ligar para
    maiúsculas e espaços); "" = não é um modelo do aviso."""
    procurado = re.sub(r"\s+", "_", (nome or "").strip().lower())
    return procurado if procurado in NOMES_DOS_MODELOS.values() else ""


def enviar_teste_renovacao(db, conta: ContaWhatsAppOficial, telefone: str, nome: str = "") -> str:
    """Um aviso de exemplo (EMPRESA EXEMPLO LTDA) para o WhatsApp de quem testa: com a arte de exemplo se o modelo com
    a arte estiver aprovado, senão o só de texto (`nome`: aquele modelo do aviso, escrito no teste da tela). Os campos
    vão preenchidos com dados de exemplo (sem eles a Meta recusa: erro 132000). Os botões do teste não fazem nada.
    Devolve o modelo usado."""
    modelos = modelos_da_conta(db, conta)
    arte, texto = modelos.get(USO_ARTE), modelos.get(USO_TEXTO)
    if nome:
        modelo = next((m for m in modelos.values() if m.nome == nome), None)
        if modelo is None or modelo.status != "APPROVED":
            raise whatsapp_cloud.ErroWhatsApp(f"O modelo {nome} ainda não está aprovado pela Meta.")
    else:
        modelo = arte if arte is not None and arte.status == "APPROVED" else texto
    if modelo is None or modelo.status != "APPROVED":
        raise whatsapp_cloud.ErroWhatsApp("Ainda não há modelo do aviso aprovado pela Meta.")
    imagem_id = (whatsapp_cloud.subir_midia(conta.phone_number_id, token(conta), IMAGEM_DE_EXEMPLO.read_bytes())
                 if modelo.com_imagem else "")
    wamid = whatsapp_cloud.enviar_modelo(conta.phone_number_id, token(conta), telefone, modelo.nome, modelo.idioma,
                                         EXEMPLO_DOS_VALORES, imagem_id=imagem_id)
    guardar_conversa(db, conta, telefone, "saida", "[aviso de exemplo] " + texto_do_aviso(
        modelo, EXEMPLO_DOS_VALORES, bool(imagem_id)), "modelo", wamid or "")
    return modelo.nome


# ---------------------------------------------------------------- a arte do aviso (desenhada no computador)

def pedir_arte(db, tarefa, dados: dict) -> None:
    """Pede ao computador do WhatsApp Leads que desenhe a arte deste aviso (ele devolve em /api/ponte/arte-pedido)."""
    from .modelos import ComandoWhatsApp

    db.add(ComandoWhatsApp(acao=ACAO_ARTE, dados=json.dumps({"tarefa": tarefa.id, "arte": dados}, ensure_ascii=False),
                           tarefa_id=tarefa.id, tenant_id=tarefa.tenant_id))
    db.flush()


def arte_do_envio(db, tarefa, dados: dict, pode_pedir: bool = True) -> tuple[bytes | None, bool]:
    """(arte, esperar): a arte pronta deste aviso, ou esperar=True enquanto o computador desenha (pede na primeira
    vez). Sem a arte depois de ESPERA_DA_ARTE_MIN minutos, ou se o computador não conseguiu, sai só o texto."""
    from datetime import timedelta

    from .modelos import ArteAviso, ComandoWhatsApp

    arte = db.execute(select(ArteAviso).where(ArteAviso.tarefa_id == tarefa.id).order_by(ArteAviso.id.desc())
                      .limit(1).execution_options(sem_filtro_de_ar=True)).scalars().first()
    if arte is not None and arte.imagem:
        return arte.imagem, False
    pedido = db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.acao == ACAO_ARTE,
                                                      ComandoWhatsApp.tarefa_id == tarefa.id)
                        .order_by(ComandoWhatsApp.id.desc()).limit(1).execution_options(sem_filtro_de_ar=True)
                        ).scalars().first()
    if pedido is None:
        if not pode_pedir:
            return None, True
        pedir_arte(db, tarefa, dados)
        return None, True
    if pedido.status in ("aguardando", "retirado") and agora() - pedido.criado_em < timedelta(minutes=ESPERA_DA_ARTE_MIN):
        return None, True
    return None, False


# ---------------------------------------------------------------- envio dos avisos

def _sem_whatsapp() -> str:
    from .sdr import SEM_WHATSAPP

    return SEM_WHATSAPP


def enviar_toque(db, t, usuario=None, pode_pedir_arte: bool = True):
    """Manda UM aviso da Renovação pelo número oficial da AR (modelo aprovado, com a arte quando der e os botões).
    As regras do contato continuam (opt-out, controle de frequência, limite da campanha); o teto de contatos frios e
    os limites por número são do QR code e não valem aqui (o limite é o da Meta). Lança EnvioOficialRecusado."""
    from . import config, mensagens, renovacao
    from .leads_servico import registrar_contato

    lead = t.lead
    if lead is None or not (lead.whatsapp or "").strip():
        raise EnvioOficialRecusado(_sem_whatsapp())
    bloqueio = mensagens.bloqueio_de_envio(db, lead, "whatsapp", t.campanha_id)
    if bloqueio:
        raise EnvioOficialRecusado(bloqueio)
    falta = falta_para_renovacao(db, t.tenant_id)
    if falta:
        raise EnvioOficialRecusado("A API oficial ainda não está pronta: " + falta + ".")
    conta = conta_da_ar(db, t.tenant_id)
    modelos = modelos_da_conta(db, conta)
    valores = renovacao.valores_do_modelo(db, t)
    if valores is None:
        raise EnvioOficialRecusado("Este aviso não tem certificado ativo (renovado, vencido ou com os avisos cancelados).")
    modelo, arte = modelos[USO_TEXTO], None
    com_arte = modelos.get(USO_ARTE)
    if com_arte is not None and com_arte.status == "APPROVED":
        dados = renovacao.arte_do_toque(db, t)
        if dados:
            arte, esperar = arte_do_envio(db, t, dados, pode_pedir_arte)
            if esperar:
                raise EsperandoArte("A arte do aviso está sendo desenhada no computador do WhatsApp Leads: o aviso sai "
                                    "em instantes, com ela.")
            if arte:
                modelo = com_arte
    parametros = [valores["nome"], valores["certificados"], valores["vencimento"]]
    try:
        imagem_id = whatsapp_cloud.subir_midia(conta.phone_number_id, token(conta), arte) if arte else ""
        wamid = whatsapp_cloud.enviar_modelo(conta.phone_number_id, token(conta), lead.whatsapp, modelo.nome,
                                             modelo.idioma, parametros, imagem_id=imagem_id,
                                             botoes=[f"renov:{acao}:{t.id}" for acao in ACOES_DOS_BOTOES])
    except whatsapp_cloud.ErroWhatsApp as erro:
        raise EnvioOficialRecusado(str(erro)) from None
    texto = (preencher(modelo.corpo, parametros) + "\n\n" + (modelo.rodape or RODAPE_RENOVACAO) + "\n"
             + " · ".join(f"[{b}]" for b in BOTOES_RENOVACAO))
    msg = mensagens.registrar(db, lead.id, "whatsapp", texto, usuario, modo="oficial", status="enviada",
                              tarefa_id=t.id, id_externo=wamid, campanha_id=t.campanha_id, angulo=t.angulo,
                              categoria_id=lead.categoria_id,
                              assunto="[com a arte do aviso de vencimento]" if arte else "")
    msg.conexao = ("oficial:" + conta.phone_number_id)[:40]
    guardar_conversa(db, conta, lead.whatsapp, "saida", texto_do_aviso(modelo, parametros, bool(arte)), "modelo",
                     wamid or "", lead_id=lead.id)  # a tela API Oficial mostra o aviso como o cliente viu
    t.status, t.concluida_em = "feita", agora()
    t.resultado = "Enviada pela API oficial da Meta" + (f" por {usuario.nome}" if usuario else "")
    nome_do_aviso = config.ANGULOS.get(t.angulo) or renovacao.ANGULOS.get(t.angulo) or t.acao or "aviso"
    registrar_contato(db, lead, "whatsapp", f"Aviso de vencimento enviado pela API oficial do WhatsApp ({nome_do_aviso}).",
                      usuario)
    return msg


def processar_fila(db, maximo: int = POR_RODADA) -> dict:
    """Fila dos avisos que saem pela API oficial (campanhas com envio_oficial): no horário da Renovação (segunda a
    sexta, sem feriados), um aviso por vez para cada empresa, nunca dois WhatsApps automáticos em menos de 20 h, SAIR e
    opt-out. Sem o teto de contatos frios do QR code: o limite é o da Meta (2.000 conversas por dia no número da MS)."""
    from datetime import date, timedelta

    from sqlalchemy import func

    from . import campanhas, mensagens, renovacao, sdr
    from .banco import usar_config_da_ar
    from .modelos import Campanha, Lead, Mensagem, Tarefa

    feito = {"enviados": 0, "esperando_arte": 0, "recusados": 0}
    ativas = db.execute(select(Campanha.id).where(Campanha.envio_oficial.is_(True), Campanha.status == "ativa",
                                                  Campanha.aprovado_em.is_not(None)).limit(1)).first()
    if not ativas:
        return feito
    if renovacao.encerrar_toques(db):  # aviso de certificado vencido ou renovado não sai
        db.flush()
    hoje, hora = date.today(), agora().strftime("%H:%M")
    recebeu_ha_pouco = (select(Mensagem.id).where(
        Mensagem.lead_id == Lead.id, Mensagem.canal == "whatsapp", Mensagem.direcao == "saida",
        Mensagem.angulo != "resposta", Mensagem.status.in_(mensagens.ENVIADAS),
        Mensagem.criado_em > agora() - timedelta(hours=campanhas.horas_minimas_automatico(db))).exists())
    consulta = (select(Tarefa.id).join(Campanha, Tarefa.campanha_id == Campanha.id).join(Lead, Tarefa.lead_id == Lead.id)
                .where(Tarefa.status == "pendente", Tarefa.tipo == "prospeccao", Tarefa.canal == "whatsapp",
                       campanhas._ja_na_hora(hoje, hora), Campanha.status == "ativa", Campanha.aprovado_em.is_not(None),
                       Campanha.envio_oficial.is_(True),
                       Tarefa.data >= hoje - timedelta(days=campanhas.DIAS_ATRASO_AUTOMATICO),
                       func.coalesce(Lead.whatsapp, "") != "", ~campanhas._toque_anterior_pendente(), ~recebeu_ha_pouco)
                .order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(100))
    artes_pedidas = 0
    for t in campanhas._em_lotes(db, [i for (i,) in db.execute(consulta).all()]):
        if feito["enviados"] >= maximo:
            break
        usar_config_da_ar(db, t.tenant_id)  # o horário de envio da AR da tarefa
        if not mensagens.dentro_do_horario(db):
            continue
        camp = db.get(Campanha, t.campanha_id)
        if camp is not None and camp.tipo == renovacao.TIPO_CAMPANHA and renovacao.fora_do_horario(db):
            continue
        if not sdr.automacao_ativa(t.lead) or not (t.mensagem or "").strip():
            continue  # o cliente respondeu, saiu ou está com alguém da equipe
        from . import feriados

        if feriados.adiar_se_feriado(db, t):
            continue  # feriado da cidade de quem envia: o aviso passou para o próximo dia de envio
        if not renovacao.ajustar_a_etapa(db, t):
            continue  # o aviso desta etapa já saiu (o modelo já diz quantos dias faltam; os repetidos são cancelados)
        try:
            enviar_toque(db, t, None, pode_pedir_arte=artes_pedidas < ARTES_POR_RODADA)
        except EsperandoArte:
            feito["esperando_arte"] += 1
            artes_pedidas += 1
            continue
        except EnvioOficialRecusado as erro:
            feito["recusados"] += 1
            texto = str(erro)
            t.resultado = f"Não saiu pela API oficial: {texto}"[:300]
            if "não está pronta" in texto or "token" in texto.lower():
                break  # problema da conta (vale para todos os avisos dela): tenta de novo na próxima rodada
            mais_tarde = agora() + timedelta(minutes=NOVA_TENTATIVA_MIN)
            if mais_tarde.date() == t.data:
                t.hora = mais_tarde.strftime("%H:%M")  # não insiste a cada minuto no mesmo aviso
            continue
        feito["enviados"] += 1
    usar_config_da_ar(db, None)
    return feito


# ---------------------------------------------------------------- botões do aviso (resposta do cliente)

def tratar_botao(db, conta: ContaWhatsAppOficial, telefone: str, recebida: dict) -> bool:
    """O cliente tocou num botão do aviso de vencimento (payload "renov:<ação>:<tarefa>"):
    - Quero renovar: oportunidade quente para a equipe (todos são avisados);
    - Já renovei: o certificado vira Renovado e os avisos param (com mais de um certificado, a equipe confere);
    - Parar avisos: SAIR, em todas as ARs.
    Devolve False quando o botão não é de um aviso deste sistema (aí segue como uma resposta comum)."""
    from . import config, renovacao, sdr
    from .leads_servico import cancelar_tarefas_de_prospeccao, historico, mudar_status, registrar_opt_out
    from .modelos import Tarefa

    partes = str(recebida.get("botao") or "").split(":")
    if len(partes) != 3 or partes[0] != "renov" or partes[1] not in ACOES_DOS_BOTOES or not partes[2].isdigit():
        return False
    tarefa = db.get(Tarefa, int(partes[2]))
    lead = tarefa.lead if tarefa is not None else None
    if (lead is None or tarefa.tenant_id != conta.tenant_id
            or not sdr.variantes_do_telefone(lead.whatsapp or "") & sdr.variantes_do_telefone(telefone)):
        return False  # o botão não bate com quem mandou: segue como resposta comum
    acao = partes[1]
    texto = str(recebida.get("texto") or BOTOES_RENOVACAO[ACOES_DOS_BOTOES.index(acao)])
    if acao == "parar":
        for outro in sdr.leads_pelo_telefone(db, telefone):  # SAIR vale para todas as ARs
            if not outro.opt_out:
                registrar_opt_out(db, outro, None, "tocou em Parar avisos no aviso de vencimento (WhatsApp oficial)")
        return True
    enviada = sdr._registrar_entrada(db, lead, f"[botão] {texto}", "whatsapp", None, str(recebida.get("id") or ""))
    lead.ultimo_contato = agora()
    lead.automacao_pausada = True
    cancelar_tarefas_de_prospeccao(db, lead.id, f"o cliente tocou em \"{texto}\" no aviso")
    historico(db, lead.id, "resposta", f"Resposta pelo botão do aviso de vencimento: {texto}", None, "whatsapp")
    if acao == "renovei":
        ativos = renovacao.ativos_do_lead(db, lead)
        if len(ativos) == 1:
            cert = ativos[0]
            renovacao.mudar_situacao(db, cert, "Renovado", None)
            historico(db, lead.id, "sistema", f"Certificado de {cert.cliente_nome} marcado como Renovado: o cliente "
                                              "tocou em \"Já renovei\" no aviso.", None)
            if lead.etapa < 2:
                mudar_status(db, lead, "Respondeu", None)
            lead.classificacao_resposta = "JÁ RENOVOU"
            return True
        analise = {"classe": "JÁ RENOVOU", "interesse": "", "objecoes": [],
                   "resumo": ("O cliente tocou em \"Já renovei\" no aviso de vencimento. "
                              + (f"Ele tem {len(ativos)} certificados ativos na Renovação: confira qual foi renovado e "
                                 "marque lá." if ativos else "Nenhum certificado ativo dele na Renovação.")),
                   "proximo_passo": "Marcar na tela Renovação o certificado renovado"}
        temperatura = "morna"
    else:
        analise = {"classe": "QUER RENOVAR", "interesse": "alto", "objecoes": [],
                   "resumo": "O cliente tocou em \"Quero renovar\" no aviso de vencimento: chame e encaminhe a renovação.",
                   "proximo_passo": "Chamar o cliente e encaminhar a renovação"}
        temperatura = "quente"
        lead.demonstrou_interesse = True
    lead.classificacao_resposta = analise["classe"]
    if temperatura == "quente" and lead.etapa < config.ETAPA_DO_STATUS["Interessado"] and not lead.perdido:
        mudar_status(db, lead, "Interessado", None)
    elif lead.etapa < 2 and not lead.perdido:
        mudar_status(db, lead, "Respondeu", None)
    sdr.criar_oportunidade(db, lead, analise, texto, "whatsapp", enviada, temperatura)
    return True
