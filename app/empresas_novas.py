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
    "novas_excluir_listas": "1",       # 1 = deixa de fora quem já está em alguma lista importada (bases_importadas)
}
LIMITE_TESTE = 10  # consulta de teste: 10 empresas = 1 crédito
ATRASO_DIAS = 2    # a busca diária pega as empresas abertas até 2 dias atrás (a Receita publica com atraso)

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


def buscar_abertas(desde: date, ate: date, ufs: list[str], limite: int | None = None) -> list[dict]:
    """Estabelecimentos ATIVOS abertos entre as datas nos estados, de QUALQUER atividade (a venda do e-CNPJ serve
    para toda empresa nova). Custa 1 crédito a cada 10 empresas. limite: no máximo essa quantidade (teste: 10)."""
    params = {"founded.gte": desde.isoformat(), "founded.lte": ate.isoformat(),
              "address.state.in": ",".join(ufs), "status.id.in": "2",
              "limit": min(POR_PAGINA, limite) if limite else POR_PAGINA}
    registros = []
    for _ in range(MAXIMO_PAGINAS):
        pagina = _pedir("/office", params)
        registros += pagina.get("records") or []
        proximo = pagina.get("next")
        if not proximo or (limite and len(registros) >= limite):
            break
        params = {"token": proximo}
    return registros[:limite] if limite else registros


def telefones(registro: dict) -> tuple[list[str], list[str]]:
    """(fixos, celulares) com DDD. A CNPJá diz o tipo (LANDLINE / MOBILE); sem tipo, o celular é deduzido."""
    fixos, celulares = [], []
    for t in registro.get("phones") or []:
        area, numero = util.so_digitos(t.get("area", "")), util.so_digitos(t.get("number", ""))
        if not area or not numero:
            continue
        movel = celular(area, numero)
        if t.get("type") == "MOBILE" or (not t.get("type") and movel):
            alvo, valor = celulares, movel or area + numero
        else:
            alvo, valor = fixos, area + numero
        if valor not in alvo:
            alvo.append(valor)
    return fixos, celulares


def dados_da_empresa(registro: dict) -> dict:
    """Registro da CNPJá → linha da lista de empresas encontradas (EmpresaCnpja)."""
    empresa = registro.get("company") or {}
    endereco = registro.get("address") or {}
    atividade = registro.get("mainActivity") or {}
    natureza = empresa.get("nature") or {}
    fixos, celulares = telefones(registro)
    emails = []
    for e in registro.get("emails") or []:
        endereco_email = (e.get("address") or "").strip().lower()
        if util.email_valido(endereco_email) and endereco_email not in emails:
            emails.append(endereco_email)
    rua = " ".join(x for x in (endereco.get("street"), endereco.get("number"), endereco.get("details")) if x)
    try:
        aberta = datetime.strptime((registro.get("founded") or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        aberta = None
    return {
        "cnpj": util.normalizar_cnpj(registro.get("taxId", ""))[:14],
        "razao_social": (empresa.get("name") or "")[:200], "nome_fantasia": (registro.get("alias") or "")[:200],
        "cnae": str(atividade.get("id") or "").zfill(7)[:7] if atividade.get("id") else "",
        "cnae_texto": (atividade.get("text") or "")[:200],
        "uf": (endereco.get("state") or "")[:2], "cidade": (endereco.get("city") or "")[:120],
        "endereco": f"{rua} – {endereco.get('district', '')} – CEP {endereco.get('zip', '')}".strip(" –")[:250],
        "aberta_em": aberta, "situacao": ((registro.get("status") or {}).get("text") or "Ativa")[:40],
        "porte": ((empresa.get("size") or {}).get("text") or "")[:60], "natureza": (natureza.get("text") or "")[:120],
        "natureza_id": natureza.get("id"), "telefones_fixos": ",".join(fixos)[:120],
        "celulares": ",".join(celulares)[:120], "emails": ",".join(emails),
    }


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


def para_lead(e) -> dict:
    """Empresa encontrada (EmpresaCnpja) → dados do lead. Telefone = fixo (ou o celular); WhatsApp = celular."""
    fixos = [t for t in (e.telefones_fixos or "").split(",") if t]
    celulares = [t for t in (e.celulares or "").split(",") if t]
    emails = [m for m in (e.emails or "").split(",") if m]
    obs = [f"Aberta em {e.aberta_em:%d/%m/%Y}." if e.aberta_em else "",
           f"Atividade: {e.cnae_texto}." if e.cnae_texto else "", f"Natureza: {e.natureza}." if e.natureza else "",
           f"Outros telefones: {', '.join(util.formatar_telefone(t) for t in (fixos + celulares)[1:])}."
           if len(fixos + celulares) > 1 else "",
           f"Outros e-mails: {', '.join(emails[1:])}." if len(emails) > 1 else ""]
    return {
        "empresa": (e.razao_social or e.nome_fantasia)[:200], "cnpj": e.cnpj,
        "telefone": (fixos or celulares or [""])[0], "whatsapp": celulares[0] if celulares else "",
        "email": emails[0] if emails else "", "cidade": e.cidade, "estado": e.uf, "endereco": e.endereco,
        "porte": e.porte, "tipo_empresa": (e.natureza or "")[:80], "observacoes": " ".join(o for o in obs if o),
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


def registrar_busca(db, registros: list[dict], desde: date, ate: date, ufs: list[str], usuario: Usuario | None, teste: bool = False, automatica: bool = False):
    """Guarda a lista das empresas que a API devolveu (para o usuário conferir) e marca quem fica de fora da campanha:
    repetida, empresário individual/MEI (se configurado), já está numa lista importada (lista de exclusão) ou já é
    lead em atendimento/que pediu para sair."""
    from .bases_importadas import BaseDados, EmpresaBase
    from .modelos import BuscaCnpja, EmpresaCnpja

    busca = BuscaCnpja(usuario_id=usuario.id if usuario else None, desde=desde, ate=ate, ufs=",".join(ufs)[:120],
                       teste=teste, automatica=automatica,
                       encontradas=len(registros), creditos=-(-len(registros) // 10))
    db.add(busca)
    db.flush()
    linhas = [dados_da_empresa(r) for r in registros]
    cnpjs = [l["cnpj"] for l in linhas if l["cnpj"]]
    em_listas: dict[str, str] = {}
    if cnpjs and cfg(db, "novas_excluir_listas") == "1":
        for i in range(0, len(cnpjs), 500):
            for cnpj, nome in db.execute(select(EmpresaBase.cnpj, BaseDados.nome)
                                         .join(BaseDados, BaseDados.id == EmpresaBase.base_id)
                                         .where(EmpresaBase.cnpj.in_(cnpjs[i:i + 500]))):
                em_listas.setdefault(cnpj, nome)
    # Empresa que já veio numa busca anterior que virou campanha (manual, diária ou teste aproveitado): não entra de
    # novo (senão a mesma empresa receberia a campanha duas vezes). Teste que não virou campanha não conta.
    ja_vieram: dict[str, date] = {}
    for i in range(0, len(cnpjs), 500):
        for cnpj, quando in db.execute(select(EmpresaCnpja.cnpj, BuscaCnpja.criado_em)
                                       .join(BuscaCnpja, BuscaCnpja.id == EmpresaCnpja.busca_id)
                                       .where(EmpresaCnpja.cnpj.in_(cnpjs[i:i + 500]), EmpresaCnpja.busca_id != busca.id,
                                              EmpresaCnpja.motivo_fora == "", BuscaCnpja.campanha_id.is_not(None))):
            ja_vieram.setdefault(cnpj, quando)
    leads = {}
    if cnpjs:
        for i in range(0, len(cnpjs), 500):
            for lead in db.execute(select(Lead).where(Lead.chave_cnpj.in_(cnpjs[i:i + 500]))).scalars():
                leads[lead.chave_cnpj] = lead
    sem_individual = cfg(db, "novas_sem_individual") == "1"
    vistos = set()
    for linha in linhas:
        motivo = ""
        lead = leads.get(linha["cnpj"])
        if not linha["cnpj"] or not (linha["razao_social"] or linha["nome_fantasia"]):
            motivo = "sem CNPJ ou sem nome"
        elif util.chave_texto(linha["situacao"]) != "ativa":
            # a busca já pede só ativas (status.id.in=2), mas a CNPJá às vezes devolve quem foi baixada no mesmo dia
            motivo = f"situação {linha['situacao']} na Receita (só entram empresas ativas)"
        elif linha["cnpj"] in vistos:
            motivo = "repetida na resposta da API"
        elif sem_individual and linha["natureza_id"] == NATUREZA_EMPRESARIO_INDIVIDUAL:
            motivo = "empresário individual / MEI (configurado para ficar de fora)"
        elif linha["cnpj"] in ja_vieram:
            motivo = f"já veio na busca de {ja_vieram[linha['cnpj']]:%d/%m/%Y %H:%M}"
        elif linha["cnpj"] in em_listas:
            motivo = f"já está na lista \"{em_listas[linha['cnpj']]}\""
        elif lead and (lead.opt_out or lead.perdido or lead.etapa >= 1 or lead.automacao_pausada):
            motivo = "já é lead em atendimento ou pediu para não receber mensagens"
        vistos.add(linha["cnpj"])
        db.add(EmpresaCnpja(busca_id=busca.id, motivo_fora=motivo, lead_id=lead.id if lead else None, **linha))
    db.flush()
    busca.fora = sum(1 for _ in db.execute(select(EmpresaCnpja.id).where(EmpresaCnpja.busca_id == busca.id,
                                                                         EmpresaCnpja.motivo_fora != "")))
    return busca


def criar_campanha_da_busca(db, busca, usuario: Usuario) -> Campanha | None:
    """Campanha de venda com as empresas da busca que podem entrar (sem gastar crédito: usa a lista guardada)."""
    from .modelos import EmpresaCnpja

    empresas = db.execute(select(EmpresaCnpja).where(EmpresaCnpja.busca_id == busca.id, EmpresaCnpja.motivo_fora == "")
                          .order_by(EmpresaCnpja.id)).scalars().all()
    periodo = f"{busca.desde:%d/%m}" if busca.desde == busca.ate else f"{busca.desde:%d/%m} a {busca.ate:%d/%m}"
    camp = criar_campanha(db, [para_lead(e) for e in empresas], usuario, f"{periodo} – {busca.ufs.replace(',', ', ')}")
    if camp:
        busca.campanha_id = camp.id
        db.commit()
    return camp


def criar_campanha(db, dados: list[dict], usuario: Usuario, rotulo: str) -> Campanha | None:
    """Cria a campanha do dia (status "gerando") com as empresas (dados de lead); o trabalho em etapas cadastra os
    leads e monta as mensagens. Devolve None se não houver nada novo."""
    from . import trabalhos

    dados = [d for d in dados if d["empresa"] and d["cnpj"]]
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


def buscar_e_criar(db, usuario: Usuario, desde: date, ate: date, automatica: bool = False) -> dict:
    """Busca na API, guarda a lista e cria a campanha. Devolve {"encontradas", "campanha_id", "busca_id", "fora"}
    (lança ErroCnpja)."""
    ufs = _ufs(db)
    # Pede à CNPJá só o que cabe na campanha (o dobro do máximo, para sobrar depois das exclusões): cada empresa
    # devolvida gasta crédito, e as que não cabem na campanha do dia não seriam contatadas.
    maximo = util.para_int(cfg(db, "novas_maximo_dia")) or 60
    registros = buscar_abertas(desde, ate, ufs, limite=min(POR_PAGINA * MAXIMO_PAGINAS, maximo * 2))
    busca = registrar_busca(db, registros, desde, ate, ufs, usuario, automatica=automatica)
    db.commit()
    camp = criar_campanha_da_busca(db, busca, usuario)
    return {"encontradas": len(registros), "campanha_id": camp.id if camp else None, "busca_id": busca.id,
            "fora": busca.fora}


def dia_do_teste(db, hoje: date | None = None) -> date:
    """Cada teste olha UM dia de abertura diferente (o mais recente que ainda não foi testado, entre 1 e 10 dias
    atrás). Antes o teste pedia sempre "os últimos 7 dias" e a CNPJá devolvia as mesmas 10 empresas, na mesma ordem."""
    from .modelos import BuscaCnpja

    hoje = hoje or date.today()
    testados = {d for (d,) in db.execute(select(BuscaCnpja.desde).where(BuscaCnpja.teste.is_(True),
                                                                     BuscaCnpja.desde == BuscaCnpja.ate))}
    for atras in range(1, 11):
        dia = hoje - timedelta(days=atras)
        if dia not in testados:
            return dia
    return hoje - timedelta(days=1)


def testar(db, usuario: Usuario | None) -> dict:
    """Consulta de TESTE: no máximo 10 empresas (1 crédito) abertas num dia, com os filtros configurados.
    Só guarda a lista para conferência; a campanha sai depois, por um botão na lista (sem gastar crédito)."""
    dia = dia_do_teste(db)
    ufs = _ufs(db)
    registros = buscar_abertas(dia, dia, ufs, limite=LIMITE_TESTE)
    busca = registrar_busca(db, registros, dia, dia, ufs, usuario, teste=True)
    db.commit()
    return {"encontradas": len(registros), "busca_id": busca.id, "fora": busca.fora, "dia": dia}


def buscas_recentes(db, limite: int = 30):
    from .modelos import BuscaCnpja

    return db.execute(select(BuscaCnpja).order_by(BuscaCnpja.criado_em.desc()).limit(limite)).scalars().all()


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
        # Janela de datas de abertura SEM sobreposição: continua do dia seguinte ao último já buscado. Termina
        # "atraso" dias atrás porque a Receita (e a CNPJá) publica as empresas abertas com alguns dias de atraso: buscar
        # o próprio dia trazia poucas e as que apareciam depois ficavam de fora para sempre.
        ate = hoje - timedelta(days=ATRASO_DIAS)
        ultima = cfg(db, "novas_ultima_data")
        desde = (date.fromisoformat(ultima) + timedelta(days=1)) if ultima else ate
        desde = max(desde, ate - timedelta(days=6))  # parado muitos dias: no máximo 7 dias de uma vez
        gravar_config(db, "novas_ultima_busca", hoje.isoformat())
        if desde > ate:
            return ""  # esses dias já foram buscados
        try:
            r = buscar_e_criar(db, usuario, desde, ate, automatica=True)
        except ErroCnpja as erro:
            texto = f"{agora():%d/%m %H:%M} – não deu certo: {erro}."
            gravar_config(db, "novas_ultimo_resultado", texto)
            gravar_config(db, "novas_ultima_busca", "")  # tenta de novo na próxima volta do relógio
            return texto
        gravar_config(db, "novas_ultima_data", ate.isoformat())
        periodo = f"{desde:%d/%m}" if desde == ate else f"{desde:%d/%m} a {ate:%d/%m}"
        texto = (f"{agora():%d/%m %H:%M} – {r['encontradas']} empresas abertas em {periodo} encontradas"
                 + (f" ({r['fora']} ficaram de fora)" if r.get("fora") else "")
                 + ("; campanha do dia montada (aguarda aprovação)." if r["campanha_id"] else "; nenhuma nova."))
        gravar_config(db, "novas_ultimo_resultado", texto)
        return texto


def campanhas_recentes(db, limite: int = 30) -> list[Campanha]:
    return db.execute(select(Campanha).where(Campanha.tipo == TIPO_CAMPANHA)
                      .order_by(Campanha.criado_em.desc()).limit(limite)).scalars().all()


def e_lead_de_venda(lead: Lead) -> bool:
    return (lead.origem or "").startswith("Empresas novas")
