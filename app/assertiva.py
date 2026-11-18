"""Consultas da Assertiva por AR (pedido da Maria em 18/11/2026): API Localize v3, "Consultas principais" — CPF, CNPJ,
telefone, e-mail e nome/endereço. Documentação: https://integracao.assertivasolucoes.com.br/v3/doc (Localize).
Doc do sistema: docs/assertiva.md.

- Cada marca (AR) usa as próprias credenciais (Client ID + Client Secret), salvas em Configurações > Integrações e
  guardadas criptografadas na tabela contas_assertiva (a AR vem da tela de quem salva: app/isolamento.py).
- Entrada por OAuth2 "client credentials" (/oauth2/v3/token): o token dura pouco (expires_in) e fica guardado em
  memória até perto de vencer. Pedir o token não gasta consulta: é o "Testar credenciais" da tela.
- Toda consulta leva a finalidade da LGPD (idFinalidade) escolhida pela marca (padrão: 5, legítimo interesse).
- Cada consulta é COBRADA pela Assertiva: só sai por clique de quem tem a permissão assertiva.consultar. A mesma
  consulta (tipo + documento) feita há menos de 30 dias é reaproveitada sem cobrar de novo, a não ser que a pessoa
  peça "consultar de novo". Fica registrada (consultas_assertiva + registro de atividades) e o resultado é apagado
  depois de 30 dias (apagar_antigas, de hora em hora).
"""

import hashlib
import json
import time
from datetime import timedelta

import httpx
from sqlalchemy import delete, select

from . import util
from .banco import agora
from .modelos import ConsultaAssertiva, ContaAssertiva, Lead, Usuario
from .seguranca import criptografar, descriptografar

URL_TOKEN = "https://api.assertivasolucoes.com.br/oauth2/v3/token"
URL_API = "https://api.assertivasolucoes.com.br"
CAMINHOS = {"cnpj": "/localize/v3/cnpj", "cpf": "/localize/v3/cpf", "telefone": "/localize/v3/telefone",
            "email": "/localize/v3/email", "nome": "/localize/v3/nome-endereco"}
TIPOS = {"cnpj": "CNPJ", "cpf": "CPF", "telefone": "Telefone", "email": "E-mail", "nome": "Nome ou endereço"}
# idFinalidade (LGPD). A 4 a Assertiva encerra em 31/12/2026.
FINALIDADES = {5: "Legítimo interesse", 1: "Confirmação de identidade", 2: "Ciclo de crédito",
               4: "Execução de contrato (a Assertiva encerra em 31/12/2026)"}
BUSCAR_POR = {"ambas": "Pessoas e empresas", "empresas": "Só empresas", "pessoas": "Só pessoas"}
UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
       "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO")
DIAS_GUARDA = 30
CAMPOS_DO_LEAD = {"whatsapp": "WhatsApp", "telefone": "Telefone", "email": "E-mail", "responsavel": "Responsável"}


class ErroAssertiva(Exception):
    """Algo deu errado na conversa com a Assertiva; a mensagem já é para a tela."""


# ---------------------------------------------------------------- conta da AR

def da_ar(db) -> ContaAssertiva | None:
    """A conta da AR da tela (a sessão da tela já enxerga só a AR da pessoa: app/isolamento.py)."""
    return db.execute(select(ContaAssertiva).order_by(ContaAssertiva.id).limit(1)).scalars().first()


def configurada(conta: ContaAssertiva | None) -> bool:
    return bool(conta is not None and conta.client_id_cripto and conta.segredo_cripto)


def id_mascarado(conta: ContaAssertiva | None) -> str:
    """Só o começo e o fim do Client ID, para a tela mostrar qual está salvo (o segredo nunca aparece)."""
    cid = descriptografar(conta.client_id_cripto) if conta and conta.client_id_cripto else ""
    return f"{cid[:4]}…{cid[-2:]}" if len(cid) > 8 else ("…" if cid else "")


def situacao(conta: ContaAssertiva | None) -> dict:
    try:
        return json.loads(conta.situacao) if conta and conta.situacao else {}
    except ValueError:
        return {}


def salvar(db, conta: ContaAssertiva | None, dados: dict) -> tuple[ContaAssertiva | None, list[str]]:
    """Grava os dados da tela. Client ID e Client Secret em branco = continuam os de antes. Devolve (conta, problemas)."""
    novo_id, novo_segredo = (dados.get("client_id") or "").strip(), (dados.get("segredo") or "").strip()
    finalidade = util.para_int(dados.get("finalidade")) or 5
    problemas = []
    if not novo_id and not (conta and conta.client_id_cripto):
        problemas.append("Cole o Client ID da Assertiva (portal da Assertiva > Integração > Credenciais).")
    if not novo_segredo and not (conta and conta.segredo_cripto):
        problemas.append("Cole o Client Secret da Assertiva (fica junto do Client ID no portal).")
    for nome, valor in (("Client ID", novo_id), ("Client Secret", novo_segredo)):
        if valor and (len(valor) < 8 or " " in valor):
            problemas.append(f"O {nome} parece incompleto: copie de novo o valor inteiro (uma linha só, sem espaços).")
    if finalidade not in FINALIDADES:
        problemas.append("Escolha a finalidade das consultas (LGPD).")
    if problemas:
        return conta, problemas
    if conta is None:
        conta = ContaAssertiva()
        db.add(conta)
    if novo_id or novo_segredo:
        conta.situacao, conta.testado_em = "", None  # credenciais novas: o teste antigo não vale
    if novo_id:
        conta.client_id_cripto = criptografar(novo_id)
    if novo_segredo:
        conta.segredo_cripto = criptografar(novo_segredo)
    conta.finalidade = finalidade
    conta.atualizado_em = agora()
    db.flush()
    return conta, []


# ---------------------------------------------------------------- conversa com a Assertiva

_TOKENS: dict[str, tuple[str, float]] = {}  # versão das credenciais -> (token, quando vence, relógio do processo)


def _post(url: str, **kwargs) -> httpx.Response:
    return httpx.post(url, **kwargs)


def _get(url: str, **kwargs) -> httpx.Response:
    return httpx.get(url, **kwargs)


def _versao(conta: ContaAssertiva) -> str:
    """Muda sempre que as credenciais são salvas de novo (o texto criptografado muda): o token antigo não vale mais."""
    return hashlib.sha256(f"{conta.id}|{conta.client_id_cripto}|{conta.segredo_cripto}".encode()).hexdigest()


def _token(conta: ContaAssertiva, renovar: bool = False) -> str:
    chave, agora_ = _versao(conta), time.monotonic()
    guardado = _TOKENS.get(chave)
    if guardado and not renovar and guardado[1] > agora_ + 5:
        return guardado[0]
    cid, segredo = descriptografar(conta.client_id_cripto), descriptografar(conta.segredo_cripto)
    if not cid or not segredo:
        raise ErroAssertiva("As credenciais da Assertiva desta marca não foram salvas (Configurações > Integrações).")
    try:
        r = _post(URL_TOKEN, auth=(cid, segredo), data={"grant_type": "client_credentials"},
                  headers={"Accept": "application/json"}, timeout=20)
    except httpx.HTTPError as erro:
        raise ErroAssertiva(f"Não consegui falar com a Assertiva ({type(erro).__name__}). Tente de novo em alguns "
                            "minutos.") from None
    if r.status_code in (400, 401, 403):
        raise ErroAssertiva("A Assertiva recusou o Client ID e o Client Secret. Copie de novo no portal da Assertiva "
                            "(Integração > Credenciais) e salve em Configurações > Integrações.")
    if r.status_code >= 300:
        raise ErroAssertiva(f"A Assertiva respondeu com erro {r.status_code} ao liberar o acesso. Tente de novo em "
                            "alguns minutos.")
    try:
        dados = r.json()
    except ValueError:
        dados = {}
    token = str(dados.get("access_token") or "")
    if not token:
        raise ErroAssertiva("A Assertiva não liberou o acesso (resposta sem token). Tente de novo em alguns minutos.")
    validade = util.para_int(dados.get("expires_in")) or 60
    _TOKENS[chave] = (token, agora_ + max(10, validade))
    return token


def _mensagem_da_resposta(r: httpx.Response) -> str:
    try:
        corpo = r.json()
    except ValueError:
        return ""
    if isinstance(corpo, dict):
        texto = corpo.get("resposta") or corpo.get("mensagem") or corpo.get("message") or corpo.get("erro") or ""
        return str(texto)[:300] if isinstance(texto, (str, int, float)) else ""
    return ""


def _pedir(conta: ContaAssertiva, caminho: str, params: dict) -> dict:
    r = None
    for tentativa in (1, 2):
        token = _token(conta, renovar=tentativa == 2)
        try:
            r = _get(URL_API + caminho, params=params, timeout=40,
                     headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        except httpx.TimeoutException:
            raise ErroAssertiva("A Assertiva demorou demais para responder. Tente de novo em alguns minutos.") from None
        except httpx.HTTPError as erro:
            raise ErroAssertiva(f"Não consegui falar com a Assertiva ({type(erro).__name__}). Tente de novo em "
                                "alguns minutos.") from None
        if r.status_code != 401:
            break  # 401 na 1ª vez: o token venceu antes da hora; pede outro e tenta de novo
    if r.status_code == 200:
        try:
            return r.json()
        except ValueError:
            raise ErroAssertiva("A Assertiva devolveu uma resposta que não consegui ler. Tente de novo.") from None
    texto = _mensagem_da_resposta(r)
    if r.status_code == 400:
        raise ErroAssertiva("A Assertiva não aceitou os dados da consulta" + (f": {texto}" if texto else
                            ". Confira o que foi digitado."))
    if r.status_code == 401:
        raise ErroAssertiva("A Assertiva recusou as credenciais desta marca. Confira o Client ID e o Client Secret em "
                            "Configurações > Integrações.")
    if r.status_code == 403:
        raise ErroAssertiva("A conta da Assertiva desta marca não tem permissão para esta consulta (produto "
                            "Localize). Fale com a Assertiva.")
    if r.status_code == 404:
        raise ErroAssertiva("A Assertiva não encontrou nada para essa consulta.")
    if r.status_code == 422:
        raise ErroAssertiva(texto or "A Assertiva não fez a consulta (regra de negócio dela).")
    if r.status_code == 429:
        raise ErroAssertiva("Muitas consultas seguidas: a Assertiva pediu para esperar um pouco. Tente de novo em "
                            "alguns minutos.")
    raise ErroAssertiva(f"A Assertiva está instável agora (erro {r.status_code}). Tente de novo em alguns minutos.")


def testar(db, conta: ContaAssertiva) -> str:
    """Pede um token novo (não gasta consulta) e guarda o resultado para a tela."""
    try:
        _token(conta, renovar=True)
    except ErroAssertiva as erro:
        conta.situacao, conta.testado_em = json.dumps({"ok": False, "erro": str(erro)}, ensure_ascii=False), agora()
        db.flush()
        raise
    conta.situacao, conta.testado_em = json.dumps({"ok": True}), agora()
    db.flush()
    return "As credenciais da Assertiva funcionam: o acesso foi liberado. O teste não gasta consulta."


# ---------------------------------------------------------------- consultas

def cpf_valido(cpf: str) -> bool:
    d = util.so_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if int(d[n]) != (soma * 10) % 11 % 10:
            return False
    return True


def preparar(tipo: str, valor: str, filtros: dict | None = None) -> tuple[str, dict]:
    """Confere e normaliza o que vai ser consultado. Devolve (chave para reaproveitar, parâmetros da Assertiva)."""
    filtros, valor = filtros or {}, (valor or "").strip()
    if tipo == "cnpj":
        d = util.normalizar_cnpj(valor)
        if not util.cnpj_valido(d):
            raise ErroAssertiva("CNPJ inválido: confira os números (14 caracteres).")
        return d, {"cnpj": d}
    if tipo == "cpf":
        d = util.so_digitos(valor).zfill(11) if util.so_digitos(valor) else ""
        if not cpf_valido(d):
            raise ErroAssertiva("CPF inválido: confira os números (11 dígitos).")
        return d, {"cpf": d}
    if tipo == "telefone":
        d = util.normalizar_telefone(valor)
        if not d:
            raise ErroAssertiva("Telefone inválido: digite o DDD e o número (10 ou 11 números).")
        return d, {"telefone": d}
    if tipo == "email":
        e = valor.lower()
        if not util.email_valido(e):
            raise ErroAssertiva("E-mail inválido: confira o endereço.")
        return e, {"email": e}
    if tipo == "nome":
        nome = " ".join((filtros.get("nome") or valor or "").split())[:120]
        buscar_por = filtros.get("buscar_por") if filtros.get("buscar_por") in BUSCAR_POR else "ambas"
        uf = (filtros.get("uf") or "").strip().upper()
        uf = uf if uf in UFS else ""
        cidade = " ".join((filtros.get("cidade") or "").split())[:80]
        if len(nome) < 3:
            raise ErroAssertiva("Digite o nome da pessoa ou a razão social da empresa (pelo menos 3 letras).")
        if cidade and not uf:
            raise ErroAssertiva("Para filtrar pela cidade, escolha também o estado (UF).")
        params = {"buscarPor": buscar_por, "nomeOuRazaoSocial": nome}
        if uf:
            params["uf"] = uf
        if cidade:
            params["cidade"] = cidade
        return "|".join([buscar_por, nome.upper(), uf, cidade.upper()]), params
    raise ErroAssertiva("Escolha o tipo de consulta (CPF, CNPJ, telefone, e-mail ou nome).")


def mascarar(tipo: str, chave: str) -> str:
    """O que foi consultado, para o registro de atividades (CPF, telefone e e-mail mascarados)."""
    if tipo == "cpf" and len(chave) == 11:
        return f"{chave[:3]}.***.***-{chave[-2:]}"
    if tipo == "cnpj":
        return util.formatar_cnpj(chave)
    if tipo == "telefone":
        return f"({chave[:2]}) ****-{chave[-4:]}" if len(chave) >= 10 else "****"
    if tipo == "email":
        return util.mascarar_contatos(chave)
    partes = chave.split("|")
    return f"nome {partes[1].split(' ')[0]}… ({partes[2] or 'Brasil'})" if len(partes) > 2 else "nome"


def recente(db, tipo: str, chave: str) -> ConsultaAssertiva | None:
    """A mesma consulta feita pela AR nos últimos 30 dias (para ver de novo sem pagar)."""
    return db.execute(select(ConsultaAssertiva).where(
        ConsultaAssertiva.tipo == tipo, ConsultaAssertiva.chave == chave,
        ConsultaAssertiva.criado_em >= agora() - timedelta(days=DIAS_GUARDA))
        .order_by(ConsultaAssertiva.id.desc()).limit(1)).scalars().first()


def consultar(db, conta: ContaAssertiva | None, usuario: Usuario | None, tipo: str, valor: str, *,
              filtros: dict | None = None, lead: Lead | None = None,
              de_novo: bool = False) -> tuple[ConsultaAssertiva, bool]:
    """Faz a consulta (cobrada) ou reaproveita a mesma dos últimos 30 dias. Devolve (consulta, reaproveitada)."""
    from .seguranca import registrar_log

    if tipo not in TIPOS:
        raise ErroAssertiva("Escolha o tipo de consulta (CPF, CNPJ, telefone, e-mail ou nome).")
    if not configurada(conta):
        raise ErroAssertiva("Esta marca ainda não tem as credenciais da Assertiva. O administrador coloca em "
                            "Configurações > Integrações.")
    chave, params = preparar(tipo, valor, filtros)
    if not de_novo:
        anterior = recente(db, tipo, chave)
        if anterior is not None:
            if lead is not None and anterior.lead_id is None:
                anterior.lead_id = lead.id
            return anterior, True
    params["idFinalidade"] = conta.finalidade if conta.finalidade in FINALIDADES else 5
    dados = _pedir(conta, CAMINHOS[tipo], params)
    cabecalho = dados.get("cabecalho") if isinstance(dados, dict) else {}
    resposta = dados.get("resposta") if isinstance(dados, dict) else {}
    consulta = ConsultaAssertiva(usuario_id=usuario.id if usuario else None, lead_id=lead.id if lead else None,
                                 tipo=tipo, chave=chave[:300], finalidade=params["idFinalidade"],
                                 protocolo=str((cabecalho or {}).get("protocolo") or "")[:80],
                                 resultado=json.dumps(resposta or {}, ensure_ascii=False))
    db.add(consulta)
    db.flush()
    registrar_log(db, usuario, "consultou_assertiva", "consulta_assertiva", consulta.id,
                  f"{TIPOS[tipo]} {mascarar(tipo, chave)} · finalidade {consulta.finalidade}"
                  + (f" · protocolo {consulta.protocolo}" if consulta.protocolo else "")
                  + (f" · lead {lead.id}" if lead is not None else ""), modulo="assertiva")
    return consulta, False


# ---------------------------------------------------------------- resultado para a tela

def _lista(valor) -> list:
    return valor if isinstance(valor, list) else []


def _telefones(r: dict) -> list[dict]:
    lista = []
    for grupo, celular_ in (("moveis", True), ("fixos", False)):
        for origem in ("telefones", "telefonesAdicionados"):
            for t in _lista((r.get(origem) or {}).get(grupo) if isinstance(r.get(origem), dict) else None):
                if not isinstance(t, dict) or not t.get("numero"):
                    continue
                digitos = util.normalizar_telefone(t.get("numero")) or util.so_digitos(t.get("numero"))
                if any(x["digitos"] == digitos for x in lista):
                    continue
                apps = t.get("aplicativos") if isinstance(t.get("aplicativos"), dict) else {}
                lista.append({"numero": str(t.get("numero")), "digitos": digitos, "celular": celular_,
                              "whatsapp": bool(apps.get("whatsApp") is True or apps.get("whatsAppBusiness") is True),
                              "nao_perturbe": bool(t.get("naoPerturbe") is True),
                              "relacao": str(t.get("relacao") or ""),
                              "ultimo_contato": str(t.get("ultimoContato") or ""),
                              "adicionado": origem == "telefonesAdicionados"})
    return lista


def _emails(r: dict) -> list[str]:
    vistos = []
    for origem in ("emails", "emailsAdicionados"):
        for e in _lista(r.get(origem)):
            texto = str((e or {}).get("email") or "").strip().lower() if isinstance(e, dict) else ""
            if texto and texto not in vistos:
                vistos.append(texto)
    return vistos


def _enderecos(r: dict) -> list[str]:
    linhas = []
    for e in _lista(r.get("enderecos")) + _lista(r.get("enderecosAdicionados")):
        if not isinstance(e, dict):
            continue
        rua = " ".join(str(e.get(c) or "") for c in ("tipoLogradouro", "logradouro")).strip()
        partes = [f"{rua}, {e.get('numero')}" if e.get("numero") not in (None, "") else rua,
                  str(e.get("complemento") or ""), str(e.get("bairro") or ""),
                  " / ".join(str(e.get(c) or "") for c in ("cidade", "uf") if e.get(c)),
                  f"CEP {e.get('cep')}" if e.get("cep") else ""]
        linha = " · ".join(p for p in partes if p.strip())
        if linha and linha not in linhas:
            linhas.append(linha)
    return linhas


def _documento_na_tela(documento: str) -> str:
    """CPF mascarado na tela (123.***.***-01); CNPJ inteiro."""
    d = util.so_digitos(documento)
    return f"{d[:3]}.***.***-{d[-2:]}" if len(d) == 11 else documento


def resumo(consulta: ConsultaAssertiva) -> dict:
    """O resultado da Assertiva arrumado para a tela (só o que interessa ao comercial)."""
    try:
        r = json.loads(consulta.resultado or "{}")
    except ValueError:
        r = {}
    r = r if isinstance(r, dict) else {}
    saida = {"tipo": consulta.tipo, "rotulo": TIPOS.get(consulta.tipo, consulta.tipo), "titulo": "", "documento": "",
             "dados": [], "telefones": [], "emails": [], "enderecos": [], "socios": [], "pessoas": []}
    if consulta.tipo in ("cnpj", "cpf"):
        dc = r.get("dadosCadastrais") if isinstance(r.get("dadosCadastrais"), dict) else {}
        saida["titulo"] = str(dc.get("razaoSocial") or dc.get("nome") or "")
        saida["documento"] = _documento_na_tela(str(dc.get("cnpj") or dc.get("cpf") or ""))
        if consulta.tipo == "cnpj":
            campos = [("Nome fantasia", dc.get("nomeFantasia")), ("Situação cadastral", dc.get("situacaoCadastral")),
                      ("Abertura", " ".join(str(x) for x in (dc.get("dataAbertura"),
                                            f"({dc.get('idadeEmpresa')} anos)" if dc.get("idadeEmpresa") else "")
                                            if x).strip()),
                      ("Porte", dc.get("porteEmpresa")), ("Funcionários", dc.get("quantidadeFuncionarios")),
                      ("Natureza jurídica", dc.get("naturezaJuridica")),
                      ("Atividade principal", " - ".join(str(x) for x in (dc.get("cnae"), dc.get("cnaeDescricao"))
                                                         if x)),
                      ("Site", dc.get("site"))]
            saida["socios"] = [{"documento": _documento_na_tela(str(s.get("documento") or "")),
                                "nome": str(s.get("nomeOuRazaoSocial") or ""),
                                "entrada": str(s.get("dataEntrada") or "")}
                               for s in _lista(r.get("socios")) if isinstance(s, dict) and s.get("nomeOuRazaoSocial")]
        else:
            campos = [("Situação cadastral", dc.get("situacaoCadastral")),
                      ("Nascimento", " ".join(str(x) for x in (dc.get("dataNascimento"),
                                              f"({dc.get('idade')} anos)" if dc.get("idade") else "") if x).strip()),
                      ("Óbito provável", "sim" if dc.get("obitoProvavel") is True else "")]
        saida["dados"] = [(rotulo, str(valor)) for rotulo, valor in campos if valor not in (None, "", 0)]
        saida["telefones"], saida["emails"], saida["enderecos"] = _telefones(r), _emails(r), _enderecos(r)
    else:
        for p in _lista(r.get("pessoaJuridica")):
            if isinstance(p, dict):
                detalhe = [f"aberta em {p['dataAbertura']}" if p.get("dataAbertura") else "",
                           f"sócio: {p['socio']}" if p.get("socio") else "",
                           " / ".join(str(p.get(c)) for c in ("cidade", "uf") if p.get(c))]
                saida["pessoas"].append({"tipo": "cnpj", "documento": str(p.get("cnpj") or ""),
                                         "documento_tela": str(p.get("cnpj") or ""),
                                         "nome": str(p.get("razaoSocial") or ""),
                                         "detalhe": " · ".join(d for d in detalhe if d)})
        for p in _lista(r.get("pessoaFisica")):
            if isinstance(p, dict):
                detalhe = [" / ".join(str(p.get(c)) for c in ("cidade", "uf") if p.get(c))]
                saida["pessoas"].append({"tipo": "cpf", "documento": str(p.get("cpf") or ""),
                                         "documento_tela": _documento_na_tela(str(p.get("cpf") or "")),
                                         "nome": str(p.get("nome") or ""),
                                         "detalhe": " · ".join(d for d in detalhe if d)})
    saida["vazio"] = not any(saida[c] for c in ("titulo", "dados", "telefones", "emails", "enderecos", "pessoas"))
    return saida


def usar_no_lead(db, lead: Lead, consulta: ConsultaAssertiva, campo: str, valor: str,
                 usuario: Usuario | None) -> str:
    """Põe no lead um telefone, e-mail ou sócio que veio NESTA consulta (nunca um valor digitado). Devolve o aviso."""
    from .leads_servico import historico, limpar_campos

    if campo not in CAMPOS_DO_LEAD:
        raise ErroAssertiva("Campo do lead inválido.")
    res = resumo(consulta)
    if campo in ("whatsapp", "telefone"):
        digitos = util.normalizar_telefone(valor)
        if not digitos or digitos not in {t["digitos"] for t in res["telefones"]}:
            raise ErroAssertiva("Esse telefone não veio nesta consulta.")
        novo = digitos
    elif campo == "email":
        novo = (valor or "").strip().lower()
        if novo not in res["emails"]:
            raise ErroAssertiva("Esse e-mail não veio nesta consulta.")
    else:
        novo = " ".join((valor or "").split())
        if novo not in {s["nome"] for s in res["socios"]}:
            raise ErroAssertiva("Esse nome não veio nesta consulta.")
        novo = novo.title()[:120]
    antes = getattr(lead, campo) or ""
    setattr(lead, campo, novo)
    if campo == "email":
        lead.email_invalido, lead.email_motivo = False, ""  # e-mail novo: a conferência antiga não vale
    limpar_campos(lead)
    rotulo = CAMPOS_DO_LEAD[campo]
    historico(db, lead.id, "sistema",
              f"{rotulo} {'trocado' if antes else 'preenchido'} com dado da Assertiva (consulta de "
              f"{consulta.criado_em:%d/%m/%Y}{', protocolo ' + consulta.protocolo if consulta.protocolo else ''})"
              + (f"; antes: {antes}" if antes else "") + ".", usuario)
    return f"{rotulo} do lead {'trocado' if antes else 'preenchido'} com o dado da Assertiva."


def apagar_antigas(db) -> int:
    """LGPD: o resultado das consultas fica só 30 dias (o registro de atividades continua)."""
    limite = agora() - timedelta(days=DIAS_GUARDA)
    resultado = db.execute(delete(ConsultaAssertiva).where(ConsultaAssertiva.criado_em < limite)
                           .execution_options(sem_filtro_de_ar=True))
    return resultado.rowcount or 0
