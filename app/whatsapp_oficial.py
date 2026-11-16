"""API oficial do WhatsApp por AR (pedido da Maria em 16/11/2026; plano em docs/whatsapp-oficial.md).

Cada AR guarda aqui o número dela na Plataforma do WhatsApp Business da Meta (tabela contas_whatsapp_oficial): o ID
da conta do WhatsApp Business, a "Identificação do número de telefone", o token permanente do usuário do sistema e a
chave secreta do app (os dois criptografados, nunca voltam para a tela) e o token de verificação do webhook (gerado
aqui, a pessoa copia para o painel da Meta).

Etapa 1 (esta): guardar, testar a conexão, mandar uma mensagem de teste (um modelo aprovado, ex.: hello_world) e
receber pelo webhook as respostas, o SAIR e a situação das mensagens. As campanhas continuam saindo pelo WhatsApp
Leads (QR code) até a etapa 2 (modelos aprovados ligados aos toques, começando pela Renovação).
"""

import json
import re
import secrets

from sqlalchemy import select

from .banco import agora
from .integracoes import whatsapp_cloud
from .modelos import ContaWhatsAppOficial
from .seguranca import criptografar, descriptografar

MODELO_DE_TESTE = ("hello_world", "en_US")  # o modelo de exemplo que a Meta cria em toda conta nova


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
    if not conta.waba_id:
        try:
            ids = whatsapp_cloud.contas_do_token(token(conta))
        except whatsapp_cloud.ErroWhatsApp:
            ids = []
        if len(ids) == 1:
            conta.waba_id = ids[0]
        elif ids:
            avisos.append("O token alcança mais de uma conta do WhatsApp Business: preencha o ID da conta na tela.")
        else:
            avisos.append("Não consegui descobrir o ID da conta do WhatsApp Business pelo token: preencha na tela "
                          "(Configurações do negócio > Contas > Contas do WhatsApp).")
    if conta.waba_id:
        try:
            resultado["app_ligado"] = whatsapp_cloud.inscrever_app(conta.waba_id, token(conta))
        except whatsapp_cloud.ErroWhatsApp as erro:
            avisos.append(f"Não consegui ligar o app à conta do WhatsApp (as respostas não chegam até isso): {erro}")
    conta.numero = str(resultado["numero"])[:30]
    conta.situacao, conta.testado_em = json.dumps(resultado, ensure_ascii=False), agora()
    return resultado


def enviar_teste(conta: ContaWhatsAppOficial, telefone: str, modelo: str = "", idioma: str = "") -> str:
    """Manda um modelo aprovado (o de exemplo da Meta, se nenhum for escolhido) para um número da própria equipe."""
    nome = (modelo or "").strip()
    if nome:
        lingua = (idioma or "").strip() or "pt_BR"
    else:
        nome, lingua = MODELO_DE_TESTE
    return whatsapp_cloud.enviar_modelo(conta.phone_number_id, token(conta), telefone, nome, lingua)
