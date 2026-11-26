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
Foto do perfil (25/11/2026, pedido da Maria): trocar_foto e foto_atual (a tela mostra a foto que está na Meta).
"""

import json
import logging
import re
import secrets
from pathlib import Path

from sqlalchemy import and_, or_, select

from . import util
from .banco import agora
from .integracoes import whatsapp_cloud
from .modelos import ContaWhatsAppOficial, ModeloWhatsAppOficial
from .seguranca import criptografar, descriptografar

log = logging.getLogger(__name__)

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


# ---------------------------------------------------------------- foto do perfil do número (25/11/2026)
# Pedido da Maria: o logo da MS com "Canal oficial" na foto do número oficial. O número não abre em celular nenhum
# (está ligado direto na API), então a foto muda por aqui: Configurações > WhatsApp > API oficial > Foto do perfil.
FOTO_LADO = 640                # a foto vai quadrada, com 640 x 640 (o WhatsApp mostra num círculo)
FOTO_MINIMO = 192              # a Meta não aceita foto menor que 192 x 192
FOTO_MAXIMO_ARQUIVO = 5_000_000  # 5 MB, o limite da Meta para imagem
FOTO_MAXIMO_PIXELS = 40_000_000  # imagem maior que isso (40 megapixels) nem é aberta


def preparar_foto(conteudo: bytes) -> bytes:
    """A imagem escolhida vira a foto do perfil: o quadrado do meio, no máximo 640 x 640, em JPEG (o formato que a Meta
    aceita sem surpresa). Fundo transparente fica branco; foto de celular deitada fica de pé."""
    import io

    from PIL import Image, ImageOps

    if not conteudo:
        raise whatsapp_cloud.ErroWhatsApp("Escolha a imagem da foto (JPG ou PNG).")
    if len(conteudo) > FOTO_MAXIMO_ARQUIVO:
        raise whatsapp_cloud.ErroWhatsApp("A imagem passou de 5 MB: diminua o tamanho (ou salve em JPG) e tente de novo.")
    try:
        with Image.open(io.BytesIO(conteudo)) as original:
            largura, altura = original.size
            if largura * altura > FOTO_MAXIMO_PIXELS:
                raise whatsapp_cloud.ErroWhatsApp("A imagem é grande demais: use uma de até 4000 x 4000 pixels.")
            if min(largura, altura) < FOTO_MINIMO:
                raise whatsapp_cloud.ErroWhatsApp(
                    f"A imagem é pequena demais ({largura} x {altura}): use uma de pelo menos {FOTO_MINIMO} x "
                    f"{FOTO_MINIMO} pixels (o ideal é {FOTO_LADO} x {FOTO_LADO} ou maior).")
            imagem = ImageOps.exif_transpose(original)
            lado = min(imagem.size)
            esquerda, topo = (imagem.width - lado) // 2, (imagem.height - lado) // 2
            imagem = imagem.crop((esquerda, topo, esquerda + lado, topo + lado))
            if imagem.mode != "RGB":
                com_transparencia = imagem.convert("RGBA")
                imagem = Image.new("RGB", com_transparencia.size, (255, 255, 255))
                imagem.paste(com_transparencia, mask=com_transparencia.getchannel("A"))
            if lado > FOTO_LADO:
                imagem = imagem.resize((FOTO_LADO, FOTO_LADO), Image.Resampling.LANCZOS)
            saida = io.BytesIO()
            imagem.save(saida, "JPEG", quality=92, optimize=True)
    except whatsapp_cloud.ErroWhatsApp:
        raise
    except (OSError, ValueError, Image.DecompressionBombError):  # não é imagem, arquivo cortado, formato estranho
        raise whatsapp_cloud.ErroWhatsApp("O arquivo não é uma imagem que dê para usar: escolha um JPG ou PNG.") from None
    return saida.getvalue()


def trocar_foto(conta: ContaWhatsAppOficial, conteudo: bytes) -> bytes:
    """Troca a foto do perfil do número oficial na Meta: prepara a imagem (preparar_foto), sobe pelo app do token
    (envio em partes, como a imagem de exemplo dos modelos) e põe no perfil do número. Devolve a foto enviada."""
    foto = preparar_foto(conteudo)
    chave = token(conta)
    app_id = whatsapp_cloud.app_do_token(chave)
    if not app_id:
        raise whatsapp_cloud.ErroWhatsApp("Não consegui descobrir o app da Meta pelo token (ele é preciso para subir a "
                                          "foto): confira o token e clique em Salvar e testar.")
    codigo = whatsapp_cloud.subir_arquivo(app_id, chave, foto, "image/jpeg", "foto-do-perfil.jpg", "foto do perfil")
    whatsapp_cloud.trocar_foto_do_perfil(conta.phone_number_id, chave, codigo)
    return foto


def foto_atual(conta: ContaWhatsAppOficial) -> tuple[bytes, str]:
    """A foto que está no perfil do número agora, buscada na Meta (para a tela mostrar). (b"", "") = sem foto."""
    endereco = str(whatsapp_cloud.perfil(conta.phone_number_id, token(conta)).get("profile_picture_url") or "")
    return whatsapp_cloud.baixar_foto_do_perfil(endereco) if endereco else (b"", "")


# ---------------------------------------------------------------- conversas do número oficial (tela API Oficial)
# Pedido da Maria em 21/11/2026: "preciso ver as respostas dos clientes em algum lugar". O número oficial está ligado
# direto na API (não abre em celular nenhum): o sistema guarda tudo o que ele manda e tudo o que chega nele.

SITUACAO_DA_META = {"sent": "enviada", "delivered": "entregue", "read": "lida", "failed": "falhou"}
ORDEM_DA_SITUACAO = {"enviada": 1, "entregue": 2, "lida": 3}  # a Meta pode avisar fora de ordem: nunca volta
TIPO_QUE_CHEGA = {"text": "texto", "button": "botao", "interactive": "botao",  # o resto (imagem, áudio...) = mídia
                  "nfm_reply": "formulario"}  # a resposta do calendário da Renovação
MARCA_DA_ARTE = "[com a arte do aviso]\n"  # 1ª linha do aviso que foi com a arte (a tela mostra como etiqueta)
PREFIXO_DO_EXEMPLO = "[aviso de exemplo] "  # o aviso de exemplo do teste da tela (Configurações > WhatsApp)
# a mídia que chega sem legenda fica guardada como "[tipo]" (whatsapp_cloud.ler_webhook): o nome para a tela
NOMES_DAS_MIDIAS = {"[image]": "Imagem", "[audio]": "Áudio", "[video]": "Vídeo", "[document]": "Documento",
                    "[sticker]": "Figurinha", "[location]": "Localização", "[contacts]": "Contato", "[reaction]": "Reação"}
TENTATIVAS_DA_FOTO = 5     # foto de contato que a Meta não entregou nessas tentativas: a tela avisa e o relógio desiste
DIAS_DA_MIDIA_NA_META = 7  # o id da mídia que vem no webhook vale 7 dias (documentação da Meta)
FOTOS_POR_RODADA = 5       # fotos baixadas por rodada do relógio (a cada minuto)


def chave_da_conversa(telefone: str) -> str:
    """Telefone com DDD e o 9 dos celulares (como a tela Conversas); estrangeiro: só os dígitos."""
    return util.com_nono_digito(telefone) or util.so_digitos(telefone)


def guardar_conversa(db, conta: ContaWhatsAppOficial, telefone: str, direcao: str, texto: str, tipo: str = "texto",
                     wamid: str = "", nome: str = "", lead_id: int | None = None, status: str = "",
                     imagem: bytes | None = None, midia_id: str = ""):
    """Guarda uma mensagem do número oficial (a que saiu ou a que chegou) para a tela API Oficial, na AR da conta. A
    Meta às vezes manda o mesmo evento de novo: a mensagem com o mesmo id não entra duas vezes. `imagem`: a que foi
    junto (a arte do aviso), guardada para a tela mostrar dentro da mensagem; `midia_id`: a foto ou figurinha que o
    contato mandou, que o relógio baixa da Meta (baixar_imagens_recebidas). Devolve a linha nova (None = já estava ou
    sem telefone)."""
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
                            lida=direcao != "entrada", midia_id=(midia_id or "")[:120])
    db.add(linha)
    db.flush()
    if imagem:
        guardar_imagem(db, linha, imagem)
    return linha


def foto_perdida(mensagem) -> bool:
    """A foto que o contato mandou não vai mais aparecer: a Meta não entregou nas tentativas ou o id dela já venceu."""
    from datetime import timedelta

    return (mensagem.midia_tentativas or 0) >= TENTATIVAS_DA_FOTO or (
        mensagem.criado_em is not None and agora() - mensagem.criado_em > timedelta(days=DIAS_DA_MIDIA_NA_META))


def baixar_imagens_recebidas(db, maximo: int = FOTOS_POR_RODADA) -> int:
    """As fotos e figurinhas que os contatos mandam para o número oficial (pedido da Maria em 23/11/2026): o relógio
    baixa da Meta, a cada minuto (o id vale 7 dias), e guarda em imagens_oficiais; a tela API Oficial mostra dentro da
    mensagem e recarrega sozinha (atualizado_em). Erro conta uma tentativa (até TENTATIVAS_DA_FOTO); grande demais ou
    o que não é imagem para na hora. Uma foto que falha não trava as outras. Devolve quantas baixou."""
    from datetime import timedelta

    from .modelos import ImagemOficial, MensagemOficial

    sem = {"sem_filtro_de_ar": True}
    tem_imagem = select(ImagemOficial.id).where(ImagemOficial.mensagem_id == MensagemOficial.id,
                                                ImagemOficial.wamid == MensagemOficial.wamid).exists()
    pendentes = db.execute(select(MensagemOficial).where(
        MensagemOficial.direcao == "entrada", MensagemOficial.midia_id != "",
        MensagemOficial.midia_tentativas < TENTATIVAS_DA_FOTO,
        MensagemOficial.criado_em >= agora() - timedelta(days=DIAS_DA_MIDIA_NA_META), ~tem_imagem)
        .order_by(MensagemOficial.id).limit(maximo).execution_options(**sem)).scalars().all()
    baixadas, contas = 0, {}
    for m in pendentes:
        if m.conta_id not in contas:
            contas[m.conta_id] = db.execute(select(ContaWhatsAppOficial).where(
                ContaWhatsAppOficial.id == m.conta_id).execution_options(**sem)).scalars().first()
        conta = contas[m.conta_id]
        if conta is None or not conta.token_cripto:  # a conta saiu: não tem como baixar
            m.midia_tentativas = TENTATIVAS_DA_FOTO
            continue
        try:
            conteudo = whatsapp_cloud.baixar_midia(m.midia_id, token(conta))
        except whatsapp_cloud.ErroWhatsApp as erro:
            grande = erro.codigo == whatsapp_cloud.CODIGO_GRANDE_DEMAIS
            m.midia_tentativas = TENTATIVAS_DA_FOTO if grande else (m.midia_tentativas or 0) + 1
            log.warning("Foto do número oficial (mensagem %s) não baixou: %s", m.id, erro)
            continue
        except Exception:  # noqa: BLE001  (uma foto com problema não pode travar as outras)
            m.midia_tentativas = (m.midia_tentativas or 0) + 1
            log.exception("Erro ao baixar a foto da mensagem %s do número oficial", m.id)
            continue
        if guardar_imagem(db, m, conteudo) is None:  # não é imagem que o navegador mostra
            m.midia_tentativas = TENTATIVAS_DA_FOTO
            continue
        m.atualizado_em = agora()  # a tela aberta percebe (/oficial/marca) e mostra a foto
        baixadas += 1
    return baixadas


def guardar_imagem(db, mensagem, imagem: bytes):
    """Cópia da imagem que foi na mensagem do número oficial (tabela imagens_oficiais; a tela API Oficial mostra)."""
    from .modelos import ImagemOficial
    from .visual import tipo_da_imagem

    tipo = tipo_da_imagem(imagem[:16])
    if not tipo:
        return None
    linha = ImagemOficial(tenant_id=mensagem.tenant_id, mensagem_id=mensagem.id, wamid=mensagem.wamid or "", tipo=tipo,
                          imagem=imagem)
    db.add(linha)
    db.flush()
    return linha


def imagens_das_mensagens(ids: list[int], *colunas):
    """Consulta das imagens dessas mensagens do número oficial (a mesma mensagem: o número e o id da Meta). Sem
    `colunas`, as linhas inteiras."""
    from sqlalchemy import and_

    from .modelos import ImagemOficial, MensagemOficial

    return (select(*(colunas or (ImagemOficial,)))
            .join(MensagemOficial, and_(MensagemOficial.id == ImagemOficial.mensagem_id,
                                        MensagemOficial.wamid == ImagemOficial.wamid))
            .where(ImagemOficial.mensagem_id.in_(ids)))


def guardar_imagens_que_faltam(db) -> int:
    """Os avisos com a arte que saíram pelo número oficial antes de a tela mostrar a imagem (23/11/2026): copia a arte
    que ainda está guardada (artes_aviso fica 10 dias; achada pelo id da mensagem na Meta -> tarefa do aviso) ou, no
    aviso de exemplo do teste, a arte de exemplo. Pode rodar de novo: só mexe nos avisos ainda sem a imagem."""
    from .modelos import ArteAviso, ImagemOficial, Mensagem, MensagemOficial

    sem = {"sem_filtro_de_ar": True}
    tem_imagem = select(ImagemOficial.id).where(ImagemOficial.mensagem_id == MensagemOficial.id,
                                                ImagemOficial.wamid == MensagemOficial.wamid).exists()
    faltam = db.execute(select(MensagemOficial).where(
        MensagemOficial.direcao == "saida", MensagemOficial.texto.contains(MARCA_DA_ARTE.strip()), ~tem_imagem)
        .order_by(MensagemOficial.id).execution_options(**sem)).scalars().all()
    feitas = 0
    for m in faltam:
        if m.texto.startswith(PREFIXO_DO_EXEMPLO):
            imagem = IMAGEM_DE_EXEMPLO.read_bytes()
        else:
            tarefa_id = db.execute(select(Mensagem.tarefa_id).where(
                Mensagem.id_externo == m.wamid, Mensagem.tarefa_id.is_not(None)).limit(1)
                .execution_options(**sem)).scalar() if m.wamid else None
            arte = db.execute(select(ArteAviso).where(ArteAviso.tarefa_id == tarefa_id, ArteAviso.ponte_id == 0)
                              .order_by(ArteAviso.id.desc()).limit(1).execution_options(**sem)
                              ).scalars().first() if tarefa_id else None
            imagem = arte.imagem if arte is not None else None
        if imagem and guardar_imagem(db, m, imagem) is not None:
            feitas += 1
    return feitas


def atualizar_entrega(db, wamid: str, status_da_meta: str, erro: str = "", quando=None) -> bool:
    """A Meta avisou a situação de uma mensagem que o número oficial mandou (enviada, entregue, lida ou falhou), com a
    hora (`quando`, timestamp): a de entrega e a de leitura ficam guardadas para os "Dados da mensagem" da tela."""
    from .modelos import MensagemOficial

    situacao_nova = SITUACAO_DA_META.get(status_da_meta)
    if not wamid or not situacao_nova:
        return False
    linha = db.execute(select(MensagemOficial).where(MensagemOficial.wamid == wamid)
                       .execution_options(sem_filtro_de_ar=True)).scalars().first()
    if linha is None or linha.direcao != "saida":
        return False
    mudou = False
    hora = util.de_timestamp(quando) or agora()
    if situacao_nova in ("entregue", "lida") and linha.entregue_em is None:  # a Meta pode avisar fora de ordem
        linha.entregue_em, mudou = hora, True
    if situacao_nova == "lida" and linha.visualizada_em is None:
        linha.visualizada_em, mudou = hora, True
    if situacao_nova == "falhou":
        linha.status, linha.erro, mudou = "falhou", (erro or "")[:500], True
    elif ORDEM_DA_SITUACAO[situacao_nova] > ORDEM_DA_SITUACAO.get(linha.status, 0):
        linha.status, mudou = situacao_nova, True
    if mudou:
        linha.atualizado_em = agora()
    return mudou


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
    exemplo = IMAGEM_DE_EXEMPLO.read_bytes() if modelo.com_imagem else None
    imagem_id = whatsapp_cloud.subir_midia(conta.phone_number_id, token(conta), exemplo) if exemplo else ""
    wamid = whatsapp_cloud.enviar_modelo(conta.phone_number_id, token(conta), telefone, modelo.nome, modelo.idioma,
                                         EXEMPLO_DOS_VALORES, imagem_id=imagem_id)
    guardar_conversa(db, conta, telefone, "saida", PREFIXO_DO_EXEMPLO + texto_do_aviso(
        modelo, EXEMPLO_DOS_VALORES, bool(imagem_id)), "modelo", wamid or "", imagem=exemplo if imagem_id else None)
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
                     wamid or "", lead_id=lead.id, imagem=arte)  # a tela API Oficial mostra o aviso como o cliente viu
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
        if not sdr.recebe_automatico(t.lead, t) or not (t.mensagem or "").strip():
            continue  # o cliente pediu SAIR (aviso de renovação: só isso para, 26/11/2026) ou o aviso está sem texto
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
    if acao == "renovar":  # o calendário para o cliente escolher o dia e o horário (se a marca ligou)
        pedir_agendamento(db, conta, lead, tarefa, telefone)
    return True


# ---------------------------------------------------------------- o calendário da Renovação (Flow)
# Pedido da Maria em 23/11/2026: "em caso deles responderem que querem renovar, dar a opção de um calendário e ele
# informar a data e horário que ele quer". Quem toca em "Quero renovar" recebe pelo número oficial (na janela de 24 h
# que o toque abre, sem mudar o modelo aprovado) um formulário do WhatsApp com o calendário dos próximos 15 dias e os
# horários livres de quem atende (renov_agenda_usuario_id; a Maria escolheu o Paulo Lucas). A escolha vira reunião na
# Agenda dessa pessoa (agenda_horarios.agendar: nunca duas no mesmo horário) e o cliente recebe a confirmação ("nossa
# equipe vai falar com você ..."). O relógio manda o calendário e a confirmação (o webhook só grava).

FLOW_AGENDA_NOME = "agendar_renovacao"
FLOW_AGENDA_TELA = "AGENDAR"
FLOW_AGENDA_VERSAO = "7.3"   # a 5.0 a Meta já não aceita (conferido em 23/11/2026)
DIAS_DA_AGENDA = 15          # o calendário mostra os próximos 15 dias (escolha da Maria)
HORAS_DA_JANELA = 23         # a Meta só deixa mandar mensagem livre até 24 h depois da última do cliente
TENTATIVAS_DO_CALENDARIO = 3
PREFIXO_DO_TOKEN = "agenda:"
TEXTO_DO_CALENDARIO = ("Que bom! Escolha o melhor dia e horário para a nossa equipe falar com você e fazer a sua "
                       "renovação.")
BOTAO_DO_CALENDARIO = "Escolher o horário"
DIAS_DA_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def flow_agenda() -> dict:
    """O formulário do calendário (JSON do Flow, versão FLOW_AGENDA_VERSAO): o calendário (CalendarPicker) com os dias
    que dá para marcar, a lista de horários e Confirmar. As datas e os horários vêm na mensagem (dados_do_calendario)."""
    return {
        "version": FLOW_AGENDA_VERSAO,
        "screens": [{
            "id": FLOW_AGENDA_TELA, "title": "Agendar a renovação", "terminal": True, "success": True,
            "data": {
                "data_minima": {"type": "string", "__example__": "2026-11-24"},
                "data_maxima": {"type": "string", "__example__": "2026-12-08"},
                "datas_bloqueadas": {"type": "array", "items": {"type": "string"}, "__example__": ["2026-11-28"]},
                "horarios": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "string"}, "title": {"type": "string"}}},
                    "__example__": [{"id": "09:00", "title": "09:00"}, {"id": "09:30", "title": "09:30"}]},
            },
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "TextBody", "text": "Escolha o dia e o horário. Nossa equipe fala com você nesse horário para "
                                             "fazer a sua renovação."},
                {"type": "CalendarPicker", "name": "dia", "label": "Dia", "mode": "single", "required": True,
                 "min-date": "${data.data_minima}", "max-date": "${data.data_maxima}",
                 "unavailable-dates": "${data.datas_bloqueadas}"},
                {"type": "Dropdown", "name": "horario", "label": "Horário", "required": True,
                 "data-source": "${data.horarios}"},
                {"type": "Footer", "label": "Confirmar", "on-click-action": {
                    "name": "complete", "payload": {"dia": "${form.dia}", "horario": "${form.horario}"}}},
            ]},
        }],
    }


def garantir_flow_agenda(db, conta: ContaWhatsAppOficial) -> str:
    """O calendário publicado na Meta para esta conta (cria, sobe o JSON e publica na primeira vez). Devolve o problema
    ("" = pronto). O que a Meta recusar sai do rascunho (apagado) e volta como problema."""
    if conta is None or not conta.token_cripto:
        return "configure a API oficial da Meta em Configurações > WhatsApp"
    if conta.flow_agenda_id:
        return ""
    if not conta.waba_id:
        return "falta a conta de mensagens do número: clique em Testar conexão em Configurações > WhatsApp"
    tok = token(conta)
    try:
        flow_id = whatsapp_cloud.criar_flow(conta.waba_id, tok, f"{FLOW_AGENDA_NOME}_{agora():%Y%m%d_%H%M%S}")
        erros = whatsapp_cloud.subir_flow_json(flow_id, tok, flow_agenda())
        if erros:
            try:
                whatsapp_cloud.apagar_flow(flow_id, tok)
            except whatsapp_cloud.ErroWhatsApp:
                pass
            return "a Meta recusou o calendário: " + "; ".join(str(e.get("message") or e) for e in erros)[:300]
        whatsapp_cloud.publicar_flow(flow_id, tok)
    except whatsapp_cloud.ErroWhatsApp as erro:
        return f"não deu para criar o calendário na Meta ({erro})"
    conta.flow_agenda_id = flow_id
    return ""


def responsavel_da_agenda(db, lead=None):
    """Quem atende: a pessoa escolhida na tela Renovação (renov_agenda_usuario_id); sem ela (ou inativa), quem cuida
    do cliente. None = ninguém com agenda."""
    from . import renovacao
    from .modelos import Usuario

    uid = util.para_int(renovacao.cfg(db, "renov_agenda_usuario_id"))
    pessoa = db.get(Usuario, uid) if uid else None
    if (pessoa is None or not pessoa.ativo) and lead is not None and lead.vendedor_id:
        pessoa = db.get(Usuario, lead.vendedor_id)
    return pessoa if pessoa is not None and pessoa.ativo else None


def dados_do_calendario(db, pessoa) -> dict | None:
    """Os dados da tela do calendário: o primeiro e o último dia com horário livre nos próximos DIAS_DA_AGENDA dias, os
    dias sem horário no meio (fim de semana, feriado, agenda cheia) e os horários do expediente de quem atende.
    None = nenhum horário livre (a equipe combina o horário)."""
    from datetime import timedelta

    from . import agenda_horarios

    livres = agenda_horarios.horarios_livres(db, pessoa, dias=DIAS_DA_AGENDA, quantidade=2000, antecedencia_horas=2)
    if not livres:
        return None
    dias = sorted({h.date() for h in livres})
    inicio, fim = dias[0], dias[-1]
    com_vaga = set(dias)
    bloqueados = [d.isoformat() for d in (inicio + timedelta(days=n) for n in range((fim - inicio).days + 1))
                  if d not in com_vaga]
    horas = sorted({h.strftime("%H:%M") for h in livres})
    return {"data_minima": inicio.isoformat(), "data_maxima": fim.isoformat(), "datas_bloqueadas": bloqueados,
            "horarios": [{"id": h, "title": h} for h in horas]}


def pedir_agendamento(db, conta: ContaWhatsAppOficial, lead, tarefa, telefone: str):
    """Quem tocou em "Quero renovar" vai receber o calendário (o relógio manda): só com o calendário ligado na marca
    (renov_agenda) e publicado na Meta, e um por cliente enquanto a janela de 24 h estiver aberta."""
    from datetime import timedelta

    from . import renovacao
    from .modelos import AgendamentoOficial

    if renovacao.cfg(db, "renov_agenda") != "1" or not conta.flow_agenda_id or lead is None:
        return None
    if db.execute(select(AgendamentoOficial.id).where(
            AgendamentoOficial.lead_id == lead.id, AgendamentoOficial.situacao.in_(("a_enviar", "enviado")),
            AgendamentoOficial.criado_em >= agora() - timedelta(hours=HORAS_DA_JANELA))
            .execution_options(sem_filtro_de_ar=True)).first():
        return None
    pessoa = responsavel_da_agenda(db, lead)
    ag = AgendamentoOficial(tenant_id=conta.tenant_id, conta_id=conta.id, lead_id=lead.id,
                            tarefa_id=tarefa.id if tarefa is not None else None,
                            usuario_id=pessoa.id if pessoa is not None else None,
                            telefone=chave_da_conversa(telefone)[:20], token=PREFIXO_DO_TOKEN + secrets.token_urlsafe(18))
    db.add(ag)
    db.flush()
    return ag


def _enviar_calendario(db, ag, conta: ContaWhatsAppOficial) -> None:
    """Manda o calendário (o formulário) deste pedido. Sem horário livre: sem_vaga (a equipe combina)."""
    from .modelos import Usuario

    pessoa = db.get(Usuario, ag.usuario_id) if ag.usuario_id else None
    dados = dados_do_calendario(db, pessoa) if pessoa is not None else None
    if dados is None:
        ag.situacao = "sem_vaga"
        return
    wamid = whatsapp_cloud.enviar_flow(conta.phone_number_id, token(conta), ag.telefone, conta.flow_agenda_id, ag.token,
                                       TEXTO_DO_CALENDARIO, BOTAO_DO_CALENDARIO, FLOW_AGENDA_TELA, dados)
    ag.situacao, ag.enviado_em = "enviado", agora()
    guardar_conversa(db, conta, ag.telefone, "saida", ("[teste] " if ag.teste else "") + TEXTO_DO_CALENDARIO,
                     "calendario", wamid or "", lead_id=ag.lead_id)


def texto_da_confirmacao(ag) -> str:
    """A confirmação para o cliente (escolha da Maria: a equipe fala com ele no horário marcado)."""
    if ag.situacao == "sem_vaga" or ag.dia is None:
        return ("Recebemos o seu pedido! Nossa equipe vai falar com você em breve para combinar o melhor horário da "
                "sua renovação.")
    texto = (f"Combinado! Nossa equipe vai falar com você na {DIAS_DA_SEMANA[ag.dia.weekday()]}, {ag.dia:%d/%m}, "
             f"às {ag.hora} para fazer a sua renovação.")
    marcado = f"{ag.dia.isoformat()} {ag.hora}"
    if ag.pedido and ag.pedido != marcado:
        pedido = ag.pedido.split(" ")
        quando = pedido[1] if len(pedido) == 2 and pedido[0] == ag.dia.isoformat() else "que você escolheu"
        texto = (f"O horário {('das ' + quando) if quando[:1].isdigit() else quando} não estava livre, então marquei "
                 f"o mais próximo. " + texto)
    return ("[TESTE] " if ag.teste else "") + texto


def _ler_dia(valor):
    """O dia que veio do calendário: "AAAA-MM-DD" (ou um número de milissegundos, nas versões antigas)."""
    from datetime import date, datetime as _dt

    texto = str(valor or "").strip()
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        pass
    if texto.isdigit():
        try:
            return _dt.fromtimestamp(int(texto) / 1000).date()
        except (ValueError, OSError, OverflowError):
            return None
    return None


def _mais_perto(livres: list, pedido):
    """O horário livre mais perto do escolhido: o próprio; senão o mais perto no mesmo dia; senão o primeiro depois."""
    if not livres:
        return None
    if pedido is None:
        return livres[0]
    if pedido in livres:
        return pedido
    no_dia = [h for h in livres if h.date() == pedido.date()]
    if no_dia:
        return min(no_dia, key=lambda h: (abs((h - pedido).total_seconds()), h))
    depois = [h for h in livres if h > pedido]
    return depois[0] if depois else livres[-1]


def tratar_formulario(db, conta: ContaWhatsAppOficial, telefone: str, recebida: dict) -> bool:
    """O cliente respondeu o calendário: marca a reunião na Agenda de quem atende (o horário escolhido ou o livre mais
    perto) e avisa a equipe; a confirmação o relógio manda. Devolve False quando o formulário não é deste sistema."""
    from datetime import datetime as _dt, time as _time

    from . import agenda_horarios, sdr
    from .leads_servico import historico
    from .modelos import AgendamentoOficial, Lead, Tarefa, Usuario

    formulario = recebida.get("formulario") or {}
    token_ = str(formulario.get("flow_token") or "")
    if not token_.startswith(PREFIXO_DO_TOKEN):
        return False
    ag = db.execute(select(AgendamentoOficial).where(AgendamentoOficial.token == token_,
                                                     AgendamentoOficial.conta_id == conta.id)
                    .execution_options(sem_filtro_de_ar=True)).scalars().first()
    if ag is None or ag.telefone != chave_da_conversa(telefone)[:20]:
        log.warning("Resposta de calendário que não bate com nenhum pedido (conta %s)", conta.id)
        return True  # é um formulário do sistema: não vira resposta comum
    dia, hora = _ler_dia(formulario.get("dia")), str(formulario.get("horario") or "")[:5]
    try:
        pedido = _dt.combine(dia, _time.fromisoformat(hora)) if dia else None
    except ValueError:
        pedido = None
    ag.pedido = f"{dia.isoformat()} {hora}" if dia else hora
    ag.marcado_em, ag.confirmado_em = agora(), None  # nova escolha: nova confirmação
    if ag.teste:  # o teste da tela: confirma o que foi escolhido, sem marcar reunião
        ag.dia, ag.hora, ag.situacao = (pedido.date(), pedido.strftime("%H:%M"), "marcado") if pedido else (None, "", "sem_vaga")
        return True
    lead = db.get(Lead, ag.lead_id) if ag.lead_id else None
    pessoa = db.get(Usuario, ag.usuario_id) if ag.usuario_id else None
    livres = (agenda_horarios.horarios_livres(db, pessoa, dias=DIAS_DA_AGENDA + 1, quantidade=2000, antecedencia_horas=1)
              if pessoa is not None and pessoa.ativo else [])
    if ag.reuniao_id:  # escolheu de novo: a reunião anterior sai da agenda e o horário dela fica livre
        anterior = db.get(Tarefa, ag.reuniao_id)
        if anterior is not None and anterior.status == "pendente":
            anterior.status = "cancelada"
            db.flush()
            livres = sorted(set(livres) | {_dt.combine(anterior.data, _time.fromisoformat(anterior.hora or "09:00"))})
    escolhido = _mais_perto(livres, pedido)
    if lead is None or escolhido is None:
        ag.situacao, ag.dia, ag.hora = "sem_vaga", None, ""
        if lead is not None:
            sdr.notificar(db, lead, f"{lead.empresa} quer renovar e pediu {ag.pedido}, mas a agenda não tem horário "
                                    "livre: combine o horário com o cliente.", f"/leads/{lead.id}", equipe_toda=True)
        return True
    try:
        reuniao = agenda_horarios.agendar(db, lead, pessoa, escolhido, "whatsapp", None,
                                          pauta="Renovação do certificado · o cliente marcou no calendário do WhatsApp "
                                                "oficial · a equipe fala com ele nesse horário")
    except agenda_horarios.HorarioIndisponivel:
        ag.situacao = "sem_vaga"
        return True
    db.flush()
    ag.reuniao_id, ag.dia, ag.hora, ag.situacao = reuniao.id, escolhido.date(), escolhido.strftime("%H:%M"), "marcado"
    quando = f"{DIAS_DA_SEMANA[ag.dia.weekday()]}, {ag.dia:%d/%m}, às {ag.hora}"
    historico(db, lead.id, "sistema", f"O cliente marcou a renovação no calendário do WhatsApp oficial: {quando}"
                                      + (f" (pediu {ag.pedido})" if ag.pedido != f"{ag.dia.isoformat()} {ag.hora}" else "")
                                      + f". Agenda de {pessoa.nome}.", None)
    sdr.notificar(db, lead, f"{lead.empresa} marcou a renovação para {quando} (agenda de {pessoa.nome}).",
                  f"/leads/{lead.id}", equipe_toda=True)
    return True


def processar_agendamentos(db, maximo: int = 20) -> dict:
    """O relógio, a cada minuto: manda o calendário de quem tocou em "Quero renovar" e a confirmação de quem escolheu o
    horário. Passou a janela de 24 h: vencido (não dá mais para mandar mensagem livre). Erro: tenta de novo (até
    TENTATIVAS_DO_CALENDARIO). Um pedido que falha não trava os outros."""
    from datetime import timedelta

    from .banco import usar_config_da_ar
    from .modelos import AgendamentoOficial

    feito = {"calendarios": 0, "confirmacoes": 0, "vencidos": 0, "erros": 0}
    limite = agora() - timedelta(hours=HORAS_DA_JANELA)
    pendentes = db.execute(select(AgendamentoOficial).where(or_(
        AgendamentoOficial.situacao == "a_enviar",
        and_(AgendamentoOficial.situacao.in_(("marcado", "sem_vaga")), AgendamentoOficial.confirmado_em.is_(None))))
        .order_by(AgendamentoOficial.id).limit(maximo).execution_options(sem_filtro_de_ar=True)).scalars().all()
    anterior = db.info.get("ar_config")
    try:
        for ag in pendentes:
            momento = ag.marcado_em if ag.situacao != "a_enviar" and ag.marcado_em else ag.criado_em
            if momento < limite:  # a janela de 24 h fechou: a Meta não deixa mais mandar mensagem livre
                if ag.situacao == "a_enviar":
                    ag.situacao = "vencido"
                else:
                    ag.confirmado_em = agora()  # a confirmação não sai mais (a equipe vê na Agenda e na ficha)
                feito["vencidos"] += 1
                continue
            conta = db.get(ContaWhatsAppOficial, ag.conta_id)
            if conta is None or not conta.token_cripto or not conta.flow_agenda_id:
                ag.situacao, ag.erro = "erro", "a conta oficial ou o calendário não existem mais"
                feito["erros"] += 1
                continue
            usar_config_da_ar(db, ag.tenant_id)
            try:
                if ag.situacao == "a_enviar":
                    _enviar_calendario(db, ag, conta)
                    feito["calendarios"] += ag.situacao == "enviado"
                if ag.situacao in ("marcado", "sem_vaga") and ag.confirmado_em is None:
                    texto = texto_da_confirmacao(ag)
                    wamid = whatsapp_cloud.enviar_texto_por(conta.phone_number_id, token(conta), ag.telefone, texto)
                    ag.confirmado_em = agora()
                    guardar_conversa(db, conta, ag.telefone, "saida", texto, "texto", wamid or "", lead_id=ag.lead_id)
                    feito["confirmacoes"] += 1
            except whatsapp_cloud.ErroWhatsApp as erro:
                ag.tentativas = (ag.tentativas or 0) + 1
                ag.erro = str(erro)[:500]
                if ag.tentativas >= TENTATIVAS_DO_CALENDARIO:
                    if ag.situacao == "a_enviar":
                        ag.situacao = "erro"
                    else:
                        ag.confirmado_em = agora()  # a reunião está marcada; só a confirmação não saiu
                log.warning("Calendário da renovação (pedido %s) não saiu: %s", ag.id, erro)
                feito["erros"] += 1
    finally:
        usar_config_da_ar(db, anterior)
    return feito


def enviar_calendario_de_teste(db, conta: ContaWhatsAppOficial, telefone: str, usuario) -> None:
    """O teste da tela (Configurações > WhatsApp): o calendário para o WhatsApp de quem testa (que precisa ter escrito
    para o número oficial nas últimas 24 h). A resposta volta com a confirmação "[TESTE]" e não marca reunião. Lança
    whatsapp_cloud.ErroWhatsApp."""
    from .modelos import AgendamentoOficial

    problema = garantir_flow_agenda(db, conta)
    if problema:
        raise whatsapp_cloud.ErroWhatsApp(problema[:1].upper() + problema[1:] + ".")
    chave = chave_da_conversa(telefone)
    if not chave:
        raise whatsapp_cloud.ErroWhatsApp("Telefone inválido para WhatsApp (digite com DDD, ex.: 81 99999-0000).")
    pessoa = responsavel_da_agenda(db) or usuario
    ag = AgendamentoOficial(tenant_id=conta.tenant_id, conta_id=conta.id, usuario_id=pessoa.id if pessoa else None,
                            telefone=chave[:20], token=PREFIXO_DO_TOKEN + secrets.token_urlsafe(18), teste=True)
    db.add(ag)
    db.flush()
    try:
        _enviar_calendario(db, ag, conta)
    except whatsapp_cloud.ErroWhatsApp as erro:  # o teste não tenta de novo sozinho
        ag.situacao, ag.erro = "erro", str(erro)[:500]
        raise
    if ag.situacao != "enviado":
        ag.situacao = "erro"
        raise whatsapp_cloud.ErroWhatsApp(f"{pessoa.nome if pessoa else 'Quem atende'} não tem horário livre nos "
                                          "próximos 15 dias (confira o expediente em Configurações > Usuários).")
