"""Empresas novas: campanha diária de VENDA de certificado digital para empresas que acabaram de abrir.

Todo dia (a partir do horário configurado), o sistema:
1. pergunta à API da CNPJá (paga, chave CNPJA_API_KEY) quais empresas ATIVAS foram abertas desde a última busca
   nos estados escolhidos (filtro por data de abertura: founded.gte / founded.lte);
2. cadastra essas empresas como leads (origem "Empresas novas (CNPJá)"), sem duplicar quem já existe;
3. monta a campanha do dia ("Empresas novas 05/11 – PE"), com 3 toques de venda (D1, D3, D7), e deixa
   esperando APROVAÇÃO, como as outras campanhas.

Depois de aprovada, vale tudo o que já existe nas campanhas: e-mail sai sozinho pela fila (horário e limites),
WhatsApp aparece para o time enviar com 1 clique (contato frio), respostas viram Oportunidades, opt-out, e-mails
inexistentes saem da campanha e as empresas ficam reservadas para o dono da campanha por 60 dias.

Diferença das campanhas de parceria: aqui a mensagem é de VENDA e pode ter preço (as regras da IA SDR de "nunca
falar valor" valem para parceiros, não para esta oferta). A IA não responde sozinha estes leads: quem conversa é
o time.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import select

from . import config, util
from .banco import agora, gravar_config, ler_config, sessao
from .modelos import Campanha, Lead, Usuario

log = logging.getLogger(__name__)

ORIGEM = "Empresas novas (CNPJá)"
TIPO_CAMPANHA = "empresas_novas"
URL_API = "https://api.cnpja.com"
POR_PAGINA = 1000
MAXIMO_PAGINAS = 5  # 5 mil empresas por busca, no máximo (proteção dos créditos)

ANGULOS = {
    "venda_boas_vindas": "Boas-vindas à empresa nova + oferta do e-CNPJ",
    "venda_lembrete": "Lembrete",
    "venda_ultimo": "Último contato (encerramento educado)",
}
CADENCIA_NOME = "Venda – Empresas novas (D1, D3, D7)"
CADENCIA_PASSOS = [(1, "venda_boas_vindas", "Boas-vindas e oferta do certificado"),
                   (3, "venda_lembrete", "Lembrete"),
                   (7, "venda_ultimo", "Último contato")]

PADRAO = {
    "novas_ativo": "0",
    "novas_ufs": "PE",
    "novas_hora": "07:30",
    "novas_maximo_dia": "60",          # empresas por campanha diária (os limites de envio continuam valendo)
    "novas_sem_individual": "0",       # 1 = deixa de fora empresário individual (inclui os MEIs)
    "novas_canais": "whatsapp,email",
    "novas_dono_id": "",
    "novas_ultima_data": "",           # última data de abertura já buscada (AAAA-MM-DD)
    "novas_ultima_busca": "",          # dia em que a busca automática rodou (AAAA-MM-DD)
    "novas_ultimo_resultado": "",
}

MENSAGENS_PADRAO = {
    "venda_boas_vindas": {
        "assunto": "Certificado digital para a {empresa}",
        "whatsapp": ("Olá! Tudo bem? Vi que a {empresa} acabou de abrir. Parabéns pela nova empresa!\n\n"
                     "Sou {vendedor}, da {minha_empresa}. "
                     "Para emitir nota fiscal eletrônica, acessar o e-CAC e cumprir as obrigações da empresa, "
                     "normalmente é preciso o certificado digital e-CNPJ.\n\n"
                     "Posso te ajudar a emitir o seu?\n\n(Se não quiser receber mensagens, é só responder SAIR.)"),
        "email": ("Olá! Tudo bem?\n\nVi que a {empresa} acabou de abrir. Parabéns pela nova empresa!\n\n"
                  "Sou {vendedor}, da {minha_empresa}. Para "
                  "emitir nota fiscal eletrônica, acessar o e-CAC e cumprir as obrigações da empresa, normalmente é "
                  "preciso o certificado digital e-CNPJ.\n\n"
                  "Posso te ajudar a emitir o seu? É só responder este e-mail."),
    },
    "venda_lembrete": {
        "assunto": "Certificado digital da {empresa}",
        "whatsapp": ("Olá! Passando para lembrar: se a {empresa} precisar do certificado digital e-CNPJ para emitir "
                     "nota fiscal ou acessar o e-CAC, posso te ajudar. Quer que eu te explique como funciona?"),
        "email": ("Olá!\n\nPassando para lembrar: se a {empresa} precisar do certificado digital e-CNPJ para "
                  "emitir nota fiscal ou acessar o e-CAC, posso te ajudar.\n\nQuer que eu te explique como "
                  "funciona? É só responder."),
    },
    "venda_ultimo": {
        "assunto": "Encerrando meu contato — {minha_empresa}",
        "whatsapp": ("Olá! Este é meu último contato sobre o certificado digital da {empresa}. Se precisar, é só "
                     "responder aqui que eu te atendo. Sucesso com a nova empresa!"),
        "email": ("Olá!\n\nEste é meu último contato sobre o certificado digital da {empresa}. Se em algum momento "
                  "precisar, é só responder este e-mail que eu te atendo.\n\nSucesso com a nova empresa!"),
    },
}

NATUREZA_EMPRESARIO_INDIVIDUAL = 2135  # inclui os MEIs


class ErroCnpja(Exception):
    """Erro da API da CNPJá com texto pronto para a tela."""


# ---------------------------------------------------------------- Configurações

def cfg(db, chave: str) -> str:
    valor = ler_config(db, chave)
    return valor if valor != "" else PADRAO.get(chave, "")


def mensagens(db) -> dict:
    try:
        salvas = json.loads(ler_config(db, "novas_mensagens") or "{}")
    except ValueError:
        salvas = {}
    return {a: {**MENSAGENS_PADRAO[a], **(salvas.get(a) or {})} for a in MENSAGENS_PADRAO}


def chave_api() -> str:
    from . import arquivo_env

    arquivo_env.carregar_do_banco()
    return config.CNPJA_API_KEY


def dono(db) -> Usuario | None:
    uid = util.para_int(cfg(db, "novas_dono_id"))
    return db.get(Usuario, uid) if uid else None


# ---------------------------------------------------------------- API da CNPJá

def _pedir(caminho: str, params: dict | None = None) -> dict:
    chave = chave_api()
    if not chave:
        raise ErroCnpja("a chave da API da CNPJá ainda não foi colocada (Empresas novas > Configurar)")
    try:
        r = httpx.get(URL_API + caminho, params=params, headers={"Authorization": chave}, timeout=60)
    except httpx.HTTPError as erro:
        raise ErroCnpja(f"a CNPJá não respondeu ({erro}). Tento de novo mais tarde") from None
    if r.status_code == 401:
        raise ErroCnpja("a chave da API da CNPJá está errada. Copie de novo em cnpja.com > Chave de API")
    if r.status_code == 429:
        corpo = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if "credit" in str(corpo.get("message", "")):
            raise ErroCnpja("acabaram os créditos da CNPJá. Compre mais créditos ou espere o próximo mês")
        raise ErroCnpja("muitas consultas por minuto na CNPJá. Tento de novo mais tarde")
    if r.status_code >= 400:
        raise ErroCnpja(f"a CNPJá respondeu erro {r.status_code}: {r.text[:200]}")
    return r.json()


def saldo() -> dict:
    """Créditos da conta (não gasta crédito)."""
    return _pedir("/credit")


def buscar_abertas(desde: date, ate: date, ufs: list[str]) -> list[dict]:
    """Estabelecimentos ATIVOS abertos entre as datas nos estados. Custa 1 crédito a cada 10 empresas."""
    params = {"founded.gte": desde.isoformat(), "founded.lte": ate.isoformat(),
              "address.state.in": ",".join(ufs), "status.id.in": "2", "limit": POR_PAGINA}
    registros = []
    for _ in range(MAXIMO_PAGINAS):
        pagina = _pedir("/office", params)
        registros += pagina.get("records") or []
        proximo = pagina.get("next")
        if not proximo:
            break
        params = {"token": proximo}
    return registros


def celular(area: str, numero: str) -> str:
    """WhatsApp provável: 11 dígitos com o 9. A Receita guarda muitos celulares sem o 9 (8 dígitos)."""
    area, numero = util.so_digitos(area), util.so_digitos(numero)
    if len(area) != 2:
        return ""
    if len(numero) == 9 and numero[0] == "9":
        return area + numero
    if len(numero) == 8 and numero[0] in "6789":
        return area + "9" + numero
    return ""


def para_lead(registro: dict) -> dict:
    """Registro da CNPJá → dados do lead."""
    empresa = registro.get("company") or {}
    endereco = registro.get("address") or {}
    telefones = registro.get("phones") or []
    fixo, zap = "", ""
    for t in telefones:
        numero = f"{t.get('area', '')}{t.get('number', '')}"
        zap = zap or celular(t.get("area", ""), t.get("number", ""))
        fixo = fixo or numero
    emails = [e.get("address", "") for e in registro.get("emails") or [] if e.get("address")]
    atividade = registro.get("mainActivity") or {}
    natureza = (empresa.get("nature") or {}).get("text", "")
    nome = empresa.get("name") or registro.get("alias") or ""
    rua = " ".join(x for x in (endereco.get("street"), endereco.get("number"), endereco.get("details")) if x)
    obs = [f"Aberta em {_data_br(registro.get('founded'))}." if registro.get("founded") else "",
           f"Atividade: {atividade.get('text', '')}." if atividade else "", f"Natureza: {natureza}." if natureza else ""]
    return {
        "empresa": nome[:200], "cnpj": registro.get("taxId", ""), "telefone": fixo, "whatsapp": zap,
        "email": emails[0] if emails else "", "cidade": endereco.get("city", ""), "estado": endereco.get("state", ""),
        "endereco": f"{rua} – {endereco.get('district', '')} – CEP {endereco.get('zip', '')}".strip(" –")[:250],
        "porte": ((empresa.get("size") or {}).get("text") or "")[:60], "tipo_empresa": natureza[:80],
        "observacoes": " ".join(o for o in obs if o), "_natureza_id": (empresa.get("nature") or {}).get("id"),
    }


def _data_br(texto: str | None) -> str:
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return texto or ""


# ---------------------------------------------------------------- Campanha do dia

def garantir_cadencia(db):
    from .modelos import Cadencia, PassoCadencia

    cad = db.execute(select(Cadencia).where(Cadencia.nome == CADENCIA_NOME)).scalars().first()
    if cad is None:
        cad = Cadencia(nome=CADENCIA_NOME, descricao="Venda de certificado digital para empresas recém-abertas.")
        for dia, angulo, acao in CADENCIA_PASSOS:
            cad.passos.append(PassoCadencia(dia=dia, canal="auto", acao=acao, angulo=angulo))
        db.add(cad)
        db.flush()
    return cad


def textos_do_lead(db, lead: Lead, usuario: Usuario | None) -> dict:
    """Mensagens dos 3 toques para a empresa ({empresa}, {vendedor}, {cidade} trocados)."""
    from . import marca

    vendedor = util.primeiro_nome(usuario.nome) if usuario and usuario.perfil != "parceiro" else "a equipe"
    m = marca.da_pessoa(usuario)
    assinatura = marca.assinatura(usuario, vendedor)
    valores = {"empresa": util.nome_para_mensagem(lead.empresa), "vendedor": vendedor, "cidade": lead.cidade or "", "minha_empresa": m["nome"]}

    def trocar(texto: str) -> str:
        texto = re.sub(r"\{(empresa|vendedor|cidade|minha_empresa)\}",
                       lambda x: valores[x.group(1)], texto or "")
        return marca.aplicar(texto, usuario)

    return {a: {"whatsapp": trocar(m["whatsapp"]), "email": trocar(m["email"]) + assinatura,
                "assunto": trocar(m["assunto"])[:200], "fonte": "empresas_novas"}
            for a, m in mensagens(db).items()}


def criar_campanha(db, registros: list[dict], usuario: Usuario, rotulo: str) -> Campanha | None:
    """Cria a campanha do dia (status "gerando") com os registros da API; o trabalho em etapas cadastra os leads e
    monta as mensagens. Devolve None se não houver nada novo."""
    from . import trabalhos

    sem_individual = cfg(db, "novas_sem_individual") == "1"
    vistos, dados = set(), []
    for r in registros:
        d = para_lead(r)
        if not d["empresa"] or not d["cnpj"] or d["cnpj"] in vistos:
            continue
        if sem_individual and d.get("_natureza_id") == NATUREZA_EMPRESARIO_INDIVIDUAL:
            continue
        vistos.add(d["cnpj"])
        d.pop("_natureza_id", None)
        dados.append(d)
    if not dados:
        return None
    # quem tem e-mail e celular primeiro: são os que a campanha consegue alcançar
    dados.sort(key=lambda d: (not d["whatsapp"], not d["email"]))
    canais = cfg(db, "novas_canais")
    camp = Campanha(nome=f"Empresas novas {rotulo}"[:160], tipo=TIPO_CAMPANHA, objetivo="Vender certificado digital",
                    estado=",".join(_ufs(db))[:2], cidade="", quantidade=util.para_int(cfg(db, "novas_maximo_dia")) or 60,
                    canais=canais, status="gerando", usuario_id=usuario.id, inicio=date.today(),
                    cadencia_id=garantir_cadencia(db).id, pedido=f"Empresas abertas {rotulo} (API CNPJá)")
    db.add(camp)
    db.commit()
    trabalhos.iniciar("campanha", camp.id, usuario.id, {"fase": "novas", "registros": dados})
    return camp


def etapa_importar(campanha_id: int, estado: dict, prazo: float) -> bool:
    """Fase "novas" da montagem: cadastra as empresas (em lotes) e escreve as mensagens. True = pronta para montar."""
    import time

    from .leads_servico import criar_lead

    registros = estado["registros"]
    estado.setdefault("feitos", 0)
    estado.setdefault("escolhidos", [])
    with sessao() as db:
        camp = db.get(Campanha, campanha_id)
        usuario = db.get(Usuario, camp.usuario_id)
        maximo = camp.quantidade or 60
    from . import reservas

    while estado["feitos"] < len(registros) and len(estado["escolhidos"]) < maximo:
        if time.monotonic() > prazo:
            return False
        lote = registros[estado["feitos"]:estado["feitos"] + 20]
        with sessao() as db:
            usuario = db.get(Usuario, usuario.id)
            for dados in lote:
                if len(estado["escolhidos"]) >= maximo:
                    break
                # Repetida só pelo CNPJ: muitas empresas novas usam o telefone/e-mail do contador, e o controle de
                # duplicados normal (que também olha telefone e e-mail) juntaria empresas diferentes num lead só.
                chave = util.normalizar_cnpj(dados["cnpj"])
                lead = db.execute(select(Lead).where(Lead.chave_cnpj == chave)).scalars().first() if chave else None
                motivo = "mesmo CNPJ" if lead else ""
                if lead is None:
                    lead, _ = criar_lead(db, dados, usuario, origem=ORIGEM, checar_duplicado=False)
                if not lead or lead.id in estado["escolhidos"]:
                    continue
                if motivo:  # já existia: só entra se ninguém trabalhou com ela e não está com outra pessoa
                    if lead.opt_out or lead.perdido or lead.etapa >= 1 or lead.automacao_pausada \
                            or reservas.de_outro(lead, usuario.id):
                        continue
                    for campo in ("whatsapp", "email", "telefone"):
                        if not getattr(lead, campo) and dados.get(campo):
                            setattr(lead, campo, dados[campo])
                estado["escolhidos"].append(lead.id)
            db.commit()
        estado["feitos"] += len(lote)
    with sessao() as db:
        camp = db.get(Campanha, campanha_id)
        usuario = db.get(Usuario, camp.usuario_id)
        estado["textos"] = {str(i): textos_do_lead(db, db.get(Lead, i), usuario) for i in estado["escolhidos"]}
        estado["so_fixo"] = [i for i in estado["escolhidos"]
                             if not (db.get(Lead, i).whatsapp or db.get(Lead, i).email)]
    estado.pop("registros", None)  # não precisa mais guardar a lista inteira
    return True


def _ufs(db) -> list[str]:
    return [u.strip().upper() for u in re.split(r"[,; ]+", cfg(db, "novas_ufs")) if len(u.strip()) == 2] or ["PE"]


def buscar_e_criar(db, usuario: Usuario, desde: date, ate: date) -> dict:
    """Busca na API e cria a campanha. Devolve {"encontradas", "campanha_id"} (lança ErroCnpja)."""
    registros = buscar_abertas(desde, ate, _ufs(db))
    rotulo = (f"{desde:%d/%m}" if desde == ate else f"{desde:%d/%m} a {ate:%d/%m}") + " – " + ", ".join(_ufs(db))
    camp = criar_campanha(db, registros, usuario, rotulo)
    return {"encontradas": len(registros), "campanha_id": camp.id if camp else None}


def rodada_diaria() -> str:
    """Chamado pelo relógio: uma vez por dia, depois do horário configurado. Devolve o que aconteceu."""
    with sessao() as db:
        if cfg(db, "novas_ativo") != "1" or not chave_api():
            return ""
        hoje = date.today()
        if cfg(db, "novas_ultima_busca") == hoje.isoformat() or agora().strftime("%H:%M") < cfg(db, "novas_hora"):
            return ""
        usuario = dono(db)
        if usuario is None:
            gravar_config(db, "novas_ultimo_resultado", "Escolha quem é o dono das campanhas diárias.")
            return ""
        ultima = cfg(db, "novas_ultima_data")
        desde = (date.fromisoformat(ultima) + timedelta(days=1)) if ultima else hoje - timedelta(days=1)
        desde = max(desde, hoje - timedelta(days=7))  # parado muitos dias: não busca semanas de uma vez
        gravar_config(db, "novas_ultima_busca", hoje.isoformat())
        try:
            r = buscar_e_criar(db, usuario, desde, hoje)
        except ErroCnpja as erro:
            texto = f"{agora():%d/%m %H:%M} – não deu certo: {erro}."
            gravar_config(db, "novas_ultimo_resultado", texto)
            gravar_config(db, "novas_ultima_busca", "")  # tenta de novo na próxima volta do relógio
            return texto
        gravar_config(db, "novas_ultima_data", hoje.isoformat())
        texto = (f"{agora():%d/%m %H:%M} – {r['encontradas']} empresas abertas encontradas"
                 + ("; campanha do dia montada (aguarda aprovação)." if r["campanha_id"] else "; nenhuma nova."))
        gravar_config(db, "novas_ultimo_resultado", texto)
        return texto


def campanhas_recentes(db, limite: int = 30) -> list[Campanha]:
    return db.execute(select(Campanha).where(Campanha.tipo == TIPO_CAMPANHA)
                      .order_by(Campanha.criado_em.desc()).limit(limite)).scalars().all()


def e_lead_de_venda(lead: Lead) -> bool:
    return (lead.origem or "").startswith("Empresas novas")
