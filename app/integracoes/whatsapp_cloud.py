"""WhatsApp Cloud API (oficial da Meta, Plataforma do WhatsApp Business).

Regras da Meta: para iniciar conversa com quem não falou com você nas últimas 24 horas, só é permitido
enviar MODELOS (templates) aprovados no Gerenciador do WhatsApp. Texto livre só dentro da janela de 24 h depois da
última mensagem do contato.

Duas formas de usar:
- por AR (app/whatsapp_oficial.py, tela Configurações > WhatsApp > "API oficial da Meta"): as funções com
  `phone_number_id` e `token` explícitos (consultar_numero, registro_do_numero e registrar_numero, enviar_modelo, enviar_texto_por, subir_midia) e as dos
  modelos, com o ID da conta do WhatsApp Business (criar_modelo, modelos_da_conta; a imagem de exemplo do modelo
  sobe pelo app do token: app_do_token + subir_exemplo);
- a antiga, por variável (WHATSAPP_TOKEN e WHATSAPP_PHONE_NUMBER_ID): configurado(), enviar_template(),
  enviar_texto() — botão "Enviar pela API" da ficha do lead.
"""

import hashlib
import hmac
import json

import httpx

from .. import config, util


class ErroWhatsApp(Exception):
    def __init__(self, mensagem: str = "", codigo: int = 0):
        super().__init__(mensagem)
        self.codigo = codigo  # o código de erro da Meta (0 = o erro não veio da Meta)


CAMPOS_DO_NUMERO = "display_phone_number,verified_name,quality_rating,whatsapp_business_manager_messaging_limit,name_status"


def _url(caminho: str, versao: str | None = None) -> str:
    return f"https://graph.facebook.com/{versao or config.WHATSAPP_API_VERSAO}/{caminho}"


def _destino(telefone: str) -> str:
    """Telefone brasileiro como a Meta pede: 55 + DDD + número, celular sempre com o 9 da frente."""
    numero = util.com_nono_digito(telefone or "")
    if not numero:
        raise ErroWhatsApp("Telefone inválido para WhatsApp (digite com DDD, ex.: 81 99999-0000).")
    return "55" + numero


def _erro_da_meta(r: httpx.Response) -> str:
    try:
        erro = r.json().get("error") or {}
    except ValueError:
        return r.text[:200]
    detalhe = (erro.get("error_data") or {}).get("details") or ""
    return " ".join(x for x in (erro.get("message", ""), detalhe) if x)[:400] or f"erro {r.status_code}"


def _codigo_do_erro(r: httpx.Response) -> int:
    try:
        return int((r.json().get("error") or {}).get("code") or 0)
    except (ValueError, TypeError, AttributeError):
        return 0


def _pedir(metodo: str, caminho: str, token: str, versao: str | None = None, **kw) -> dict:
    if not token:
        raise ErroWhatsApp("Falta o token da API oficial (Configurações > WhatsApp > API oficial da Meta).")
    try:
        r = httpx.request(metodo, _url(caminho, versao), timeout=30, headers={"Authorization": f"Bearer {token}"}, **kw)
    except httpx.HTTPError:
        raise ErroWhatsApp("Sem conexão com a API do WhatsApp. Confira a internet.") from None
    if r.status_code >= 400:
        raise ErroWhatsApp(f"A Meta recusou: {_erro_da_meta(r)}", _codigo_do_erro(r))
    try:
        return r.json()
    except ValueError:
        return {}


def consultar_numero(phone_number_id: str, token: str, versao: str | None = None) -> dict:
    """Dados do número na Meta: número, nome verificado, qualidade e limite de mensagens (teste de conexão)."""
    return _pedir("GET", phone_number_id, token, versao, params={"fields": CAMPOS_DO_NUMERO})


CAMPOS_DO_REGISTRO = "status,platform_type,code_verification_status"


def registro_do_numero(phone_number_id: str, token: str, versao: str | None = None) -> dict:
    """Se o número já está ativado na API (platform_type CLOUD_API, status CONNECTED) e se foi confirmado com o
    código por SMS ou ligação (code_verification_status VERIFIED). Pedido à parte do teste de conexão: se a Meta
    recusar estes campos, o teste não cai por isso."""
    dados = _pedir("GET", phone_number_id, token, versao, params={"fields": CAMPOS_DO_REGISTRO})
    return dados if isinstance(dados, dict) else {}


def registrar_numero(phone_number_id: str, token: str, pin: str, versao: str | None = None) -> bool:
    """Ativa (registra) o número na API: o último passo de um número novo, que a Meta só aceita pela API (não pelo
    Gerenciador do WhatsApp nem pelo painel do app). `pin`: 6 números, a verificação em duas etapas do número (se ele
    já tem uma, precisa ser a mesma; se não tem, passa a ser esta). Limite da Meta: 10 pedidos por número a cada
    72 h (erro 133016)."""
    dados = _pedir("POST", f"{phone_number_id}/register", token, versao,
                   json={"messaging_product": "whatsapp", "pin": pin})
    return bool(dados.get("success", True)) if isinstance(dados, dict) else True


def contas_do_token(token: str, versao: str | None = None) -> list[str]:
    """IDs das contas do WhatsApp Business que o token alcança (as permissões granulares do próprio token): assim a
    pessoa não precisa procurar o ID da conta na Meta."""
    dados = _pedir("GET", "debug_token", token, versao, params={"input_token": token})
    ids: list[str] = []
    for escopo in (dados.get("data") or {}).get("granular_scopes") or []:
        if escopo.get("scope") in ("whatsapp_business_management", "whatsapp_business_messaging"):
            ids += [str(i) for i in escopo.get("target_ids") or [] if str(i) not in ids]
    return ids


def contas_atribuidas(token: str, versao: str | None = None) -> list[str]:
    """IDs das contas de mensagens (as antigas "contas do WhatsApp Business") atribuídas ao usuário do sistema dono do
    token. Serve quando o token vale para todos os ativos (usuário do sistema administrador): aí as permissões
    granulares vêm sem as contas e contas_do_token não acha nada (caso real da MS em 19/11/2026)."""
    eu = _pedir("GET", "me", token, versao, params={"fields": "id"})
    if not isinstance(eu, dict) or not eu.get("id"):
        return []
    dados = _pedir("GET", f"{eu['id']}/assigned_whatsapp_business_accounts", token, versao,
                   params={"fields": "id", "limit": 100})
    return [str(x["id"]) for x in (dados.get("data") or []) if isinstance(x, dict) and x.get("id")]


def numeros_da_conta(waba_id: str, token: str, versao: str | None = None) -> list[str]:
    """As "Identificações do número de telefone" de uma conta de mensagens (para saber qual conta tem o número)."""
    dados = _pedir("GET", f"{waba_id}/phone_numbers", token, versao, params={"fields": "id", "limit": 100})
    return [str(x["id"]) for x in (dados.get("data") or []) if isinstance(x, dict) and x.get("id")]


def inscrever_app(waba_id: str, token: str, versao: str | None = None) -> bool:
    """Liga o app do token à conta do WhatsApp Business (o que o "Início rápido" da Meta faria): sem isso, as
    respostas e a situação das mensagens da conta não chegam ao webhook do app."""
    dados = _pedir("POST", f"{waba_id}/subscribed_apps", token, versao)
    return bool(dados.get("success", True))


def _texto_do_parametro(valor) -> str:
    """A Meta recusa parâmetro vazio, com quebra de linha, tabulação ou mais de 4 espaços seguidos."""
    texto = " ".join(str(valor or "").split())
    return texto[:900] or "-"


def enviar_modelo(phone_number_id: str, token: str, telefone: str, nome_modelo: str, idioma: str = "pt_BR",
                  parametros: list[str] | None = None, versao: str | None = None, imagem_id: str = "",
                  botoes: list[str] | None = None) -> str:
    """Envia um modelo aprovado. `imagem_id`: a imagem do cabeçalho (subir_midia); `botoes`: o payload de cada botão
    de resposta rápida, na ordem do modelo (volta no webhook quando o contato toca nele). Devolve o id da mensagem na
    Meta (wamid)."""
    if not nome_modelo:
        raise ErroWhatsApp("Falta o nome do modelo aprovado na Meta.")
    corpo = {"messaging_product": "whatsapp", "to": _destino(telefone), "type": "template",
             "template": {"name": nome_modelo, "language": {"code": idioma or "pt_BR"}}}
    componentes = []
    if imagem_id:
        componentes.append({"type": "header", "parameters": [{"type": "image", "image": {"id": imagem_id}}]})
    if parametros:
        componentes.append({"type": "body", "parameters": [
            {"type": "text", "text": _texto_do_parametro(p)} for p in parametros]})
    for indice, carga in enumerate(botoes or []):
        componentes.append({"type": "button", "sub_type": "quick_reply", "index": str(indice),
                            "parameters": [{"type": "payload", "payload": str(carga)[:256]}]})
    if componentes:
        corpo["template"]["components"] = componentes
    dados = _pedir("POST", f"{phone_number_id}/messages", token, versao, json=corpo)
    return (dados.get("messages") or [{}])[0].get("id", "")


def subir_midia(phone_number_id: str, token: str, conteudo: bytes, tipo: str = "image/png",
                versao: str | None = None) -> str:
    """Manda uma imagem para a Meta (fica lá 30 dias) e devolve o id dela, para usar no cabeçalho do modelo."""
    dados = _pedir("POST", f"{phone_number_id}/media", token, versao, data={"messaging_product": "whatsapp", "type": tipo},
                   files={"file": ("imagem" + (".png" if "png" in tipo else ".jpg"), conteudo, tipo)})
    if not dados.get("id"):
        raise ErroWhatsApp("A Meta não devolveu o número da imagem enviada.")
    return str(dados["id"])


# Mídia que um contato mandou (23/11/2026, pedido da Maria: as fotos dos clientes na tela API Oficial). Conferido na
# Meta de verdade no mesmo dia: o id dá o endereço (lookaside.fbsbx.com, vale 5 minutos), que devolve o arquivo com o
# token (sem ele, 401), sem redirecionar. O id que vem no webhook vale 7 dias.
TIPOS_DE_IMAGEM = ("image", "sticker")
SERVIDORES_DA_MIDIA = ("fbsbx.com", "fbcdn.net", "facebook.com", "whatsapp.net")  # o token só vai para a Meta
MAXIMO_DA_MIDIA = 6_000_000  # foto até 5 MB na Meta; figurinha até 500 KB
CODIGO_GRANDE_DEMAIS = -1    # erro que não adianta tentar de novo


def baixar_midia(midia_id: str, token: str, maximo: int = MAXIMO_DA_MIDIA, versao: str | None = None) -> bytes:
    """Baixa a mídia de um contato pelo id que veio no webhook (foto, figurinha). Lança ErroWhatsApp."""
    from urllib.parse import urlsplit

    dados = _pedir("GET", str(midia_id), token, versao)
    url, tamanho = str(dados.get("url") or ""), int(dados.get("file_size") or 0)
    servidor = (urlsplit(url).hostname or "").lower()
    if not url.startswith("https://") or not any(servidor == s or servidor.endswith("." + s) for s in SERVIDORES_DA_MIDIA):
        raise ErroWhatsApp("A Meta não devolveu um endereço válido para baixar a mídia.")
    if tamanho > maximo:
        raise ErroWhatsApp(f"A mídia tem {tamanho // 1_000_000} MB: grande demais para guardar.", CODIGO_GRANDE_DEMAIS)
    try:
        r = httpx.request("GET", url, timeout=60, follow_redirects=False, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        raise ErroWhatsApp("Sem conexão com a API do WhatsApp. Confira a internet.") from None
    if r.status_code != 200:
        raise ErroWhatsApp(f"A Meta não entregou a mídia (situação {r.status_code}).", _codigo_do_erro(r))
    if len(r.content) > maximo:
        raise ErroWhatsApp("A mídia é grande demais para guardar.", CODIGO_GRANDE_DEMAIS)
    return r.content


# ---------------------------------------------------------------- formulários do WhatsApp (Flows)
# O calendário da Renovação (23/11/2026). Conferido na Meta de verdade no mesmo dia, com rascunhos apagados em seguida:
# a versão 5.0 do JSON não é mais aceita ("INVALID_FLOW_JSON_VERSION"); a 7.3 passa sem erros com o CalendarPicker,
# a lista de horários e as datas vindas na mensagem (data_minima, data_maxima, datas_bloqueadas, horarios).

def criar_flow(waba_id: str, token: str, nome: str, categorias: tuple = ("APPOINTMENT_BOOKING",),
               versao: str | None = None) -> str:
    """Cria o formulário (rascunho) na conta de mensagens e devolve o id dele."""
    dados = _pedir("POST", f"{waba_id}/flows", token, versao, json={"name": nome, "categories": list(categorias)})
    if not dados.get("id"):
        raise ErroWhatsApp("A Meta não devolveu o número do formulário criado.")
    return str(dados["id"])


def subir_flow_json(flow_id: str, token: str, conteudo: dict, versao: str | None = None) -> list[dict]:
    """Sobe o JSON do formulário. Devolve os erros de validação da Meta (vazio = aceito)."""
    corpo = json.dumps(conteudo, ensure_ascii=False).encode()
    dados = _pedir("POST", f"{flow_id}/assets", token, versao, data={"name": "flow.json", "asset_type": "FLOW_JSON"},
                   files={"file": ("flow.json", corpo, "application/json")})
    return list(dados.get("validation_errors") or [])


def publicar_flow(flow_id: str, token: str, versao: str | None = None) -> None:
    """Publica o formulário (depois disso ele não muda mais: mudança = formulário novo)."""
    _pedir("POST", f"{flow_id}/publish", token, versao)


def apagar_flow(flow_id: str, token: str, versao: str | None = None) -> None:
    """Apaga um rascunho (o que a Meta recusou)."""
    _pedir("DELETE", str(flow_id), token, versao)


def enviar_flow(phone_number_id: str, token: str, telefone: str, flow_id: str, flow_token: str, texto: str,
                botao: str, tela: str, dados: dict, versao: str | None = None) -> str:
    """Manda o formulário como mensagem livre (só dentro da janela de 24 h aberta pelo contato): `texto` em cima,
    `botao` abre o formulário na `tela`, já com os `dados` dela. `flow_token` volta junto com a resposta."""
    corpo = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": _destino(telefone),
             "type": "interactive",
             "interactive": {"type": "flow", "body": {"text": texto},
                             "action": {"name": "flow", "parameters": {
                                 "flow_message_version": "3", "flow_token": flow_token, "flow_id": flow_id,
                                 "flow_cta": botao, "flow_action": "navigate",
                                 "flow_action_payload": {"screen": tela, "data": dados}}}}}
    dados_ = _pedir("POST", f"{phone_number_id}/messages", token, versao, json=corpo)
    return (dados_.get("messages") or [{}])[0].get("id", "")


def _texto_do_formulario(formulario: dict) -> str:
    """A resposta do calendário como gente lê: "Escolheu 25/11/2026 às 10:00"."""
    dia, hora = str(formulario.get("dia") or ""), str(formulario.get("horario") or "")
    partes = dia[:10].split("-")
    if len(partes) == 3 and all(p.isdigit() for p in partes):
        dia = f"{partes[2]}/{partes[1]}/{partes[0]}"
    if dia and hora:
        return f"Escolheu {dia} às {hora}"
    return "Respondeu o formulário" + (f": {dia or hora}" if dia or hora else "")


# ---------------------------------------------------------------- modelos (templates)

def app_do_token(token: str, versao: str | None = None) -> str:
    """O ID do app da Meta dono do token (precisa dele para subir a imagem de exemplo de um modelo novo)."""
    dados = _pedir("GET", "debug_token", token, versao, params={"input_token": token})
    return str((dados.get("data") or {}).get("app_id") or "")


def subir_exemplo(app_id: str, token: str, conteudo: bytes, tipo: str = "image/png", nome: str = "exemplo.png",
                  versao: str | None = None) -> str:
    """Sobe a imagem de exemplo de um modelo com imagem no cabeçalho (envio em partes da Meta, "Resumable Upload")
    e devolve o código dela (header_handle) para o pedido de aprovação."""
    sessao_envio = _pedir("POST", f"{app_id}/uploads", token, versao,
                          params={"file_name": nome, "file_length": len(conteudo), "file_type": tipo})
    if not sessao_envio.get("id"):
        raise ErroWhatsApp("A Meta não abriu o envio da imagem de exemplo.")
    try:
        r = httpx.request("POST", _url(str(sessao_envio["id"]), versao), content=conteudo, timeout=60,
                          headers={"Authorization": f"OAuth {token}", "file_offset": "0"})
    except httpx.HTTPError:
        raise ErroWhatsApp("Sem conexão com a API do WhatsApp. Confira a internet.") from None
    if r.status_code >= 400:
        raise ErroWhatsApp(f"A Meta recusou a imagem de exemplo: {_erro_da_meta(r)}")
    try:
        codigo = r.json().get("h", "")
    except ValueError:
        codigo = ""
    if not codigo:
        raise ErroWhatsApp("A Meta não devolveu o código da imagem de exemplo.")
    return codigo


def criar_modelo(waba_id: str, token: str, nome: str, idioma: str, categoria: str, componentes: list[dict],
                 versao: str | None = None) -> dict:
    """Pede a aprovação de um modelo novo. Devolve {"id", "status", "category"} (a Meta pode trocar a categoria)."""
    return _pedir("POST", f"{waba_id}/message_templates", token, versao,
                  json={"name": nome, "language": idioma, "category": categoria, "components": componentes})


def editar_modelo(meta_id: str, token: str, categoria: str, componentes: list[dict], versao: str | None = None) -> dict:
    """Manda de novo um modelo recusado (ou pausado) com o texto atual: volta para a análise da Meta."""
    return _pedir("POST", meta_id, token, versao, json={"category": categoria, "components": componentes})


def modelos_da_conta(waba_id: str, token: str, versao: str | None = None) -> list[dict]:
    """Os modelos da conta do WhatsApp Business, com a situação (APPROVED, PENDING, REJECTED, PAUSED, DISABLED), a
    categoria e o motivo da recusa."""
    dados = _pedir("GET", f"{waba_id}/message_templates", token, versao,
                   params={"fields": "id,name,language,status,category,rejected_reason", "limit": 200})
    return list(dados.get("data") or [])


def enviar_texto_por(phone_number_id: str, token: str, telefone: str, texto: str, versao: str | None = None) -> str:
    """Mensagem livre: a Meta só permite dentro de 24 h depois que o contato escreveu (janela de atendimento)."""
    dados = _pedir("POST", f"{phone_number_id}/messages", token, versao,
                   json={"messaging_product": "whatsapp", "to": _destino(telefone), "type": "text",
                         "text": {"body": texto[:4000]}})
    return (dados.get("messages") or [{}])[0].get("id", "")


# ---------------------------------------------------------------- forma antiga (variáveis WHATSAPP_*)

def configurado() -> bool:
    return bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID)


def enviar_template(telefone: str, nome_template: str, parametros: list[str], idioma: str = "pt_BR") -> str:
    """Envia um template aprovado pelo número das variáveis. Devolve o id da mensagem na Meta."""
    if not configurado():
        raise ErroWhatsApp("A API oficial do WhatsApp não está configurada (veja docs/configuracao.md).")
    if not util.normalizar_telefone(telefone):
        raise ErroWhatsApp("Telefone inválido para WhatsApp.")
    if not nome_template:
        raise ErroWhatsApp("Este template não tem o nome do template aprovado na Meta. Preencha em Cadências > Templates.")
    return enviar_modelo(config.WHATSAPP_PHONE_NUMBER_ID, config.WHATSAPP_TOKEN, telefone, nome_template, idioma,
                         parametros)


def enviar_texto(telefone: str, texto: str) -> str:
    if not configurado():
        raise ErroWhatsApp("A API oficial do WhatsApp não está configurada.")
    return enviar_texto_por(config.WHATSAPP_PHONE_NUMBER_ID, config.WHATSAPP_TOKEN, telefone, texto)


# ---------------------------------------------------------------- webhook

def assinatura_confere(corpo: bytes, assinatura: str, segredo: str) -> bool:
    """Confere o cabeçalho X-Hub-Signature-256 dos webhooks com a chave secreta do app."""
    if not segredo:
        return False
    esperado = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, assinatura or "")


def assinatura_valida(corpo: bytes, assinatura: str) -> bool:
    """Forma antiga: confere com WHATSAPP_APP_SECRET."""
    return assinatura_confere(corpo, assinatura, config.WHATSAPP_APP_SECRET)


def numeros_do_webhook(dados: dict) -> set[str]:
    """As "Identificações do número de telefone" (phone_number_id) que aparecem no webhook: dizem de qual AR ele é."""
    return {str(((m.get("value") or {}).get("metadata") or {}).get("phone_number_id") or "")
            for e in dados.get("entry", []) for m in e.get("changes", [])} - {""}


def contas_por_numero(dados: dict) -> dict[str, str]:
    """{phone_number_id: ID da conta de mensagens} dos eventos do webhook (o `entry.id` de cada evento é a conta)."""
    saida: dict[str, str] = {}
    for entrada in dados.get("entry", []) or []:
        conta_id = str(entrada.get("id") or "")
        for mudanca in entrada.get("changes", []) or []:
            numero_id = str(((mudanca.get("value") or {}).get("metadata") or {}).get("phone_number_id") or "")
            if numero_id and conta_id.isdigit():
                saida[numero_id] = conta_id
    return saida


def ler_webhook(dados: dict) -> tuple[list[dict], list[dict]]:
    """Separa (mensagens recebidas, atualizações de status) do JSON do webhook. Cada item leva o `numero_id`
    (phone_number_id) do número que recebeu ou mandou; a recebida leva também o nome do contato."""
    recebidas, status = [], []
    for entrada in dados.get("entry", []):
        for mudanca in entrada.get("changes", []):
            valor = mudanca.get("value", {})
            numero_id = str((valor.get("metadata") or {}).get("phone_number_id") or "")
            nomes = {c.get("wa_id", ""): (c.get("profile") or {}).get("name", "") for c in valor.get("contacts", [])}
            for m in valor.get("messages", []):
                tipo = str(m.get("type") or "")
                # foto e figurinha: o id da mídia, para baixar (a Meta guarda só 7 dias) e mostrar na tela API Oficial
                midia = (m.get(tipo) or {}) if tipo in TIPOS_DE_IMAGEM else {}
                # resposta de um formulário (o calendário da Renovação): os campos vêm num JSON dentro de nfm_reply
                interativo = m.get("interactive") or {}
                formulario: dict = {}
                if interativo.get("type") == "nfm_reply":
                    tipo = "nfm_reply"
                    try:
                        formulario = json.loads((interativo.get("nfm_reply") or {}).get("response_json") or "{}")
                    except (ValueError, TypeError):
                        formulario = {}
                    formulario = formulario if isinstance(formulario, dict) else {}
                texto = ((m.get("text") or {}).get("body") or (m.get("button") or {}).get("text")
                         or (interativo.get("button_reply") or {}).get("title")
                         or str(midia.get("caption") or "").strip()  # a legenda da foto
                         or (_texto_do_formulario(formulario) if tipo == "nfm_reply" else "")
                         or f"[{m.get('type')}]")
                # botão de resposta rápida de um modelo: o payload que o sistema mandou junto (ex.: renov:renovar:123)
                botao = str((m.get("button") or {}).get("payload")
                            or ((m.get("interactive") or {}).get("button_reply") or {}).get("id") or "")
                recebidas.append({"de": m.get("from", ""), "texto": texto, "id": m.get("id", ""), "numero_id": numero_id,
                                  "nome": nomes.get(m.get("from", ""), ""), "botao": botao[:256], "tipo": tipo,
                                  "midia_id": str(midia.get("id") or "")[:120], "formulario": formulario})
            for s in valor.get("statuses", []):
                erros = s.get("errors") or [{}]
                status.append({"id": s.get("id", ""), "status": s.get("status", ""), "numero_id": numero_id,
                               "erro": (erros[0].get("title") or erros[0].get("message") or "")[:300],
                               "quando": str(s.get("timestamp") or "")})  # a hora da entrega / leitura
    return recebidas, status
