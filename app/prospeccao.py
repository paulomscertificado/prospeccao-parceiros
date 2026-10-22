"""Prospecção automática: "Encontrar novos parceiros".

Só usa dados PÚBLICOS e REAIS, sempre guardando a fonte:
- OpenStreetMap (gratuito): escritórios marcados como contabilidade no mapa.
- Google Places (opcional, precisa de GOOGLE_PLACES_API_KEY no .env).
- Site da própria empresa: e-mail, Instagram, LinkedIn, WhatsApp e CNPJ publicados no site.
- BrasilAPI (dados abertos da Receita Federal): razão social, sócios, endereço, atividade.

Nada é inventado: se a fonte não traz o telefone, o lead fica sem telefone.
"""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import httpx
from sqlalchemy import select

from . import base_receita, config, score, trabalhos, util
from .banco import agora, sessao
from .leads_servico import criar_lead, historico, limpar_campos, preencher
from .modelos import Busca, Lead, Usuario

log = logging.getLogger(__name__)

AGENTE = f"MS-Prospeccao/1.0 ({config.OSM_CONTATO})"
SERVIDORES_OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
TIPOS_OSM = {
    "Escritório de contabilidade": ['nwr["office"="accountant"]', 'nwr["office"="tax_advisor"]'],
    "Consultoria contábil": ['nwr["office"="consulting"]["name"~"cont[aá]b",i]', 'nwr["office"="accountant"]'],
    "Empresa de serviços contábeis": ['nwr["office"="accountant"]', 'nwr["office"="company"]["name"~"cont[aá]b",i]'],
    "Contador autônomo": ['nwr["office"="accountant"]'],
}
TEXTO_GOOGLE = {
    "Escritório de contabilidade": "escritório de contabilidade",
    "Consultoria contábil": "consultoria contábil",
    "Empresa de serviços contábeis": "serviços contábeis",
    "Contador autônomo": "contador",
}


class ErroBusca(Exception):
    pass


def fontes_disponiveis(db) -> list[tuple[str, str, bool]]:
    base = base_receita.resumo(db)
    return [
        ("receita", f"Base da Receita Federal ({base['total']} escritórios, atualizada em {base['atualizada_em']})"
         if base["total"] else "Base da Receita Federal – importe em Configurações > Integrações", base["total"] > 0),
        ("osm", "OpenStreetMap (gratuito, poucos escritórios cadastrados no Brasil)", True),
        ("google", "Google Places" + ("" if config.GOOGLE_PLACES_API_KEY else " – configure a chave no .env"),
         bool(config.GOOGLE_PLACES_API_KEY)),
    ]


def _cliente() -> httpx.Client:
    return httpx.Client(timeout=30, headers={"User-Agent": AGENTE}, follow_redirects=True)


# ---------------------------------------------------------------- Fontes

def geocodificar(cidade: str, uf: str) -> tuple[float, float]:
    with _cliente() as c:
        r = c.get("https://nominatim.openstreetmap.org/search", params={
            "city": cidade, "state": config.NOMES_UF.get(uf, uf), "country": "Brasil",
            "format": "jsonv2", "limit": 1})
    r.raise_for_status()
    dados = r.json()
    if not dados:
        raise ErroBusca(f"Não encontrei a cidade \"{cidade}/{uf}\" no mapa. Confira o nome e a UF.")
    return float(dados[0]["lat"]), float(dados[0]["lon"])


def buscar_osm(cidade: str, uf: str, raio_km: int, limite: int, tipo: str) -> list[dict]:
    lat, lon = geocodificar(cidade, uf)
    raio_m = max(1, min(int(raio_km or 10), 50)) * 1000
    filtros = TIPOS_OSM.get(tipo, TIPOS_OSM["Escritório de contabilidade"])
    corpo = "".join(f"{f}(around:{raio_m},{lat},{lon});" for f in filtros)
    consulta = f"[out:json][timeout:90];({corpo});out center tags {int(limite) * 2};"
    r = None
    with _cliente() as c:
        # Servidores públicos do Overpass: se um estiver fora do ar ou lotado, tenta o próximo.
        for servidor in SERVIDORES_OVERPASS:
            try:
                r = c.post(servidor, data={"data": consulta}, timeout=120)
            except httpx.HTTPError as erro:
                log.warning("Overpass %s falhou: %s", servidor, erro)
                continue
            if r.status_code == 200:
                break
            log.warning("Overpass %s respondeu %s", servidor, r.status_code)
    if r is None or r.status_code != 200:
        raise ErroBusca("Os servidores do OpenStreetMap estão ocupados agora. Tente de novo em alguns minutos.")
    resultados = []
    for el in r.json().get("elements", []):
        t = el.get("tags", {})
        nome = t.get("name") or t.get("brand")
        if not nome:
            continue
        rua = " ".join(x for x in [t.get("addr:street", ""), t.get("addr:housenumber", "")] if x)
        endereco = ", ".join(x for x in [rua, t.get("addr:suburb", ""), t.get("addr:postcode", "")] if x)
        resultados.append({
            "empresa": nome,
            "telefone": t.get("phone") or t.get("contact:phone") or "",
            "whatsapp": t.get("contact:whatsapp") or "",
            "email": t.get("email") or t.get("contact:email") or "",
            "site": t.get("website") or t.get("contact:website") or "",
            "instagram": t.get("contact:instagram") or "",
            "linkedin": t.get("contact:linkedin") or "",
            "cnpj": t.get("ref:vatin", "").replace("BR", "") if "ref:vatin" in t else "",
            "endereco": endereco,
            "cidade": t.get("addr:city") or cidade,
            "estado": (t.get("addr:state") or uf)[:2].upper() if len(t.get("addr:state", "")) == 2 else uf,
            "tipo_empresa": tipo,
            "fonte_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
            "origem": "Prospecção: OpenStreetMap",
        })
    return resultados[: int(limite) * 2]


def buscar_google(cidade: str, uf: str, raio_km: int, limite: int, tipo: str) -> list[dict]:
    if not config.GOOGLE_PLACES_API_KEY:
        return []
    campos = ("places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
              "places.websiteUri,places.googleMapsUri,places.businessStatus,nextPageToken")
    pedido = {"textQuery": f"{TEXTO_GOOGLE.get(tipo, tipo.lower() or 'escritório de contabilidade')} em {cidade} {uf}",
              "languageCode": "pt-BR", "regionCode": "BR", "pageSize": 20}
    resultados, token = [], None
    with _cliente() as c:
        while len(resultados) < limite:
            if token:
                pedido["pageToken"] = token
            r = c.post("https://places.googleapis.com/v1/places:searchText", json=pedido,
                       headers={"X-Goog-Api-Key": config.GOOGLE_PLACES_API_KEY, "X-Goog-FieldMask": campos})
            if r.status_code in (401, 403):
                raise ErroBusca("A chave do Google Places foi recusada. Confira GOOGLE_PLACES_API_KEY no .env.")
            r.raise_for_status()
            dados = r.json()
            for p in dados.get("places", []):
                if p.get("businessStatus") == "CLOSED_PERMANENTLY":
                    continue
                resultados.append({
                    "empresa": p.get("displayName", {}).get("text", ""),
                    "telefone": p.get("nationalPhoneNumber", ""),
                    "site": p.get("websiteUri", ""),
                    "endereco": p.get("formattedAddress", ""),
                    "cidade": cidade, "estado": uf, "tipo_empresa": tipo,
                    "fonte_url": p.get("googleMapsUri", ""),
                    "origem": "Prospecção: Google Places",
                })
            token = dados.get("nextPageToken")
            if not token:
                break
            time.sleep(1.5)
    return resultados


# ---------------------------------------------------------------- Enriquecimento

_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_INSTAGRAM = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})/?", re.I)
_RE_LINKEDIN = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9_%-]+/?", re.I)
_RE_WHATS = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=|whatsapp\.com/send\?phone=)\+?(\d{10,13})", re.I)
_IGNORAR_INSTAGRAM = {"p", "explore", "reel", "reels", "stories", "accounts", "tv"}


def dados_do_site(site: str) -> dict:
    """Lê a página inicial (e a de contato, se houver) e devolve o que estiver publicado lá."""
    url = util.normalizar_site(site)
    if not url:
        return {}
    achados: dict = {}
    textos = []
    try:
        with httpx.Client(timeout=10, follow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (compatible; MS-Prospeccao/1.0)"}) as c:
            r = c.get(url)
            if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
                return {}
            textos.append(r.text[:800_000])
            contato = re.search(r'href="([^"]*contato[^"]*)"', r.text, re.I)
            if contato:
                try:
                    r2 = c.get(urljoin(str(r.url), contato.group(1)))
                    if r2.status_code < 400:
                        textos.append(r2.text[:400_000])
                except httpx.HTTPError:
                    pass
    except httpx.HTTPError:
        return {}
    html = "\n".join(textos)
    dominio_site = util.dominio(url)
    emails = [e.lower() for e in _RE_EMAIL.findall(html)
              if not e.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"))
              and "sentry" not in e.lower() and "exemplo" not in e.lower() and "example" not in e.lower()]
    # Prefere e-mail do próprio domínio.
    emails.sort(key=lambda e: 0 if dominio_site and e.endswith(dominio_site) else 1)
    if emails:
        achados["email"] = emails[0]
    for nome in _RE_INSTAGRAM.findall(html):
        if nome.lower() not in _IGNORAR_INSTAGRAM:
            achados["instagram"] = "@" + nome
            break
    m = _RE_LINKEDIN.search(html)
    if m:
        achados["linkedin"] = m.group(0)
    m = _RE_WHATS.search(html)
    if m and util.normalizar_telefone(m.group(1)):
        achados["whatsapp"] = m.group(1)
    cnpjs = util.achar_cnpjs(html)
    if cnpjs:
        achados["cnpj"] = cnpjs[0]
    texto_simples = util.chave_texto(re.sub(r"<[^>]+>", " ", html))
    if texto_simples.count("empresa") >= 3:
        achados["atende_empresas"] = True
    return achados


PALAVRAS_GENERICAS = {"contabil", "contabilidade", "contabeis", "assessoria", "consultoria", "escritorio",
                      "servicos", "empresarial", "ltda", "eireli", "grupo", "associados", "solucoes", "gestao"}


def _tokens(texto: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", util.chave_texto(texto)) if len(t) >= 4 and t not in PALAVRAS_GENERICAS}


def descobrir_site(empresa: str, email: str, cnpj: str = "") -> str:
    """Testa o domínio do e-mail da empresa como site. Só aceita se o site responder E (o nome do
    domínio combinar com o nome do escritório OU a página mostrar o CNPJ). Nunca chuta."""
    dom = util.dominio_empresarial(email)
    if not dom or dom in util.DOMINIOS_GENERICOS:
        return ""
    rotulo = util.chave_texto(dom.split(".")[0])
    combina_nome = any(t in rotulo for t in _tokens(empresa))
    for url in (f"https://www.{dom}", f"https://{dom}", f"http://www.{dom}"):
        try:
            with httpx.Client(timeout=8, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0 (compatible; MS-Prospeccao/1.0)"}) as c:
                r = c.get(url)
        except httpx.HTTPError:
            continue
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
            continue
        if util.dominio(str(r.url)).removeprefix("www.") != dom:
            return ""  # redirecionou para outro site (ex.: provedor, página de domínio à venda)
        cnpj_na_pagina = bool(cnpj) and util.normalizar_cnpj(cnpj) in util.achar_cnpjs(r.text[:800_000])
        return url if (combina_nome or cnpj_na_pagina) else ""
    return ""


def dados_do_cnpj(cnpj: str) -> dict:
    """Dados abertos da Receita Federal pela BrasilAPI."""
    d = util.normalizar_cnpj(cnpj)
    if not util.cnpj_valido(d):
        return {}
    try:
        with _cliente() as c:
            r = c.get(f"https://brasilapi.com.br/api/cnpj/v1/{d}", timeout=20)
    except httpx.HTTPError:
        return {}
    if r.status_code != 200:
        return {}
    j = r.json()
    socios = [f"{s.get('nome_socio', '').title()} ({s.get('qualificacao_socio', '')})".strip()
              for s in j.get("qsa") or [] if s.get("nome_socio")]
    rua = " ".join(x for x in [j.get("descricao_tipo_de_logradouro", ""), j.get("logradouro", ""),
                               j.get("numero", "")] if x)
    dados = {
        "empresa": j.get("nome_fantasia") or j.get("razao_social") or "",
        "endereco": ", ".join(x for x in [rua, j.get("bairro", ""), j.get("cep", "")] if x).title(),
        "cidade": (j.get("municipio") or "").title(), "estado": j.get("uf") or "",
        "telefone": j.get("ddd_telefone_1") or "",
        "email": (j.get("email") or "").lower(),
        "socios": "\n".join(socios), "porte": j.get("porte") or "",
        "especialidade": (j.get("cnae_fiscal_descricao") or "")[:120],
        "multiplos_socios": len(socios) > 1,
        "situacao": j.get("descricao_situacao_cadastral", ""),
        "fonte_url": f"https://brasilapi.com.br/api/cnpj/v1/{d}",
    }
    return dados


def enriquecer_lead(db, lead: Lead, usuario: Usuario | None = None) -> list[str]:
    """Completa os campos vazios com dados públicos (site e CNPJ). Nunca sobrescreve o que já existe."""
    alterados, fontes = [], []
    if lead.site:
        achados = dados_do_site(lead.site)
        if achados:
            mudou = preencher(lead, achados, so_vazios=True)
            if mudou:
                alterados += mudou
                fontes.append(f"site {lead.site}")
    if lead.cnpj:
        receita = dados_do_cnpj(lead.cnpj)
        if receita:
            situacao = receita.pop("situacao", "")
            receita.pop("fonte_url", None)
            receita.pop("empresa", None)  # o nome que a pessoa conhece é o atual
            mudou = preencher(lead, receita, so_vazios=True)
            if mudou:
                alterados += mudou
                fontes.append("dados abertos da Receita Federal (BrasilAPI)")
            if situacao and situacao.upper() != "ATIVA":
                historico(db, lead.id, "sistema", f"Atenção: situação cadastral do CNPJ na Receita: {situacao}.", usuario)
    lead.enriquecido_em = agora()
    if alterados:
        limpar_campos(lead)
        score.atualizar(db, lead)
        historico(db, lead.id, "sistema",
                  f"Dados públicos encontrados ({', '.join(sorted(set(alterados)))}). Fonte: {'; '.join(fontes)}.", usuario)
    return alterados


# ---------------------------------------------------------------- Busca completa (em segundo plano)

def interpretar_pedido(texto: str) -> dict:
    """'Quero encontrar 100 escritórios contábeis de alto potencial em São Paulo' → campos do formulário."""
    resultado = {}
    numero = re.search(r"\b(\d{1,4})\b", texto)
    if numero:
        resultado["quantidade"] = int(numero.group(1))
    uf = re.search(r"\b([A-Z]{2})\b", texto)
    if uf and uf.group(1) in config.UFS:
        resultado["estado"] = uf.group(1)
    cidade = re.search(r"\bem\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ú' .-]+?)(?:\s*[-/,]\s*[A-Z]{2}\b|\s*$|\.)", texto.strip())
    if cidade:
        resultado["cidade"] = cidade.group(1).strip()
    capitais = {"sao paulo": "SP", "rio de janeiro": "RJ", "recife": "PE", "belo horizonte": "MG",
                "salvador": "BA", "fortaleza": "CE", "curitiba": "PR", "porto alegre": "RS", "brasilia": "DF",
                "goiania": "GO", "manaus": "AM", "belem": "PA", "florianopolis": "SC", "vitoria": "ES",
                "natal": "RN", "joao pessoa": "PB", "maceio": "AL", "aracaju": "SE", "teresina": "PI",
                "sao luis": "MA", "campo grande": "MS", "cuiaba": "MT", "olinda": "PE", "jaboatao dos guararapes": "PE",
                "caruaru": "PE", "campinas": "SP"}
    if "cidade" in resultado and "estado" not in resultado:
        uf_capital = capitais.get(util.chave_texto(resultado["cidade"]))
        if uf_capital:
            resultado["estado"] = uf_capital
    if "alto potencial" in texto.lower() or "melhores" in texto.lower():
        resultado["ordenar"] = "score"
    return resultado


def _encontrar_e_cadastrar(busca_id: int) -> list[int] | None:
    """Etapa 1: procura nas fontes, elimina duplicados e cadastra. None = a busca terminou com erro."""
    with sessao() as db:
        busca = db.get(Busca, busca_id)
        usuario = db.get(Usuario, busca.usuario_id) if busca.usuario_id else None
        busca.status, busca.etapa = "buscando", "Procurando escritórios nas fontes públicas..."
        db.commit()
        try:
            encontrados = []
            fontes = busca.fontes.split(",")
            categoria = busca.categoria or "contabil"
            if "receita" in fontes:
                encontrados += base_receita.buscar(db, busca.cidade, busca.estado, busca.quantidade, [categoria])
            # O mapa (OSM) só tem marcação para contabilidade; o Google busca pelo nome da categoria.
            if "osm" in fontes and categoria == "contabil":
                encontrados += buscar_osm(busca.cidade, busca.estado, busca.raio_km, busca.quantidade, busca.tipo_empresa)
            if "google" in fontes:
                encontrados += buscar_google(busca.cidade, busca.estado, busca.raio_km, busca.quantidade, busca.tipo_empresa)
            for item in encontrados:
                item.setdefault("categoria", categoria)
        except ErroBusca as erro:
            busca.status, busca.erro, busca.concluido_em = "erro", str(erro), agora()
            return None
        except httpx.HTTPError as erro:
            log.warning("Busca %s falhou: %s", busca_id, erro)
            busca.status, busca.concluido_em = "erro", agora()
            busca.erro = "Não consegui falar com a fonte de dados (internet ou serviço fora do ar). Tente de novo."
            return None
        busca.encontrados = len(encontrados)
        busca.etapa = "Eliminando duplicados e cadastrando..."
        db.commit()
        novos: list[Lead] = []
        for dados in encontrados:
            if len(novos) >= busca.quantidade:
                break
            dados["busca_id"] = busca.id
            lead, motivo = criar_lead(db, dados, usuario, origem=dados.pop("origem"))
            if motivo:
                busca.duplicados += 1
                continue
            if lead:
                lead.busca_id = busca.id
                novos.append(lead)
        busca.novos = len(novos)
        if busca.enriquecer and novos:
            busca.status = "enriquecendo"
            busca.etapa = f"Buscando e-mail, redes sociais e CNPJ nos sites (0 de {len(novos)})..."
        db.flush()
        return [l.id for l in novos]


def _usuario_da_busca(db, busca_id: int) -> Usuario | None:
    busca = db.get(Busca, busca_id)
    return db.get(Usuario, busca.usuario_id) if busca and busca.usuario_id else None


def _etapa_sem_site(busca_id: int, estado: dict, prazo: float) -> bool:
    """Etapa 2: procura o site pelo domínio do e-mail (5 por vez)."""
    if "sem_site" not in estado:
        with sessao() as db:
            estado.update(sem_site=[l.id for l in (db.get(Lead, i) for i in estado["novos"])
                                    if l and not l.site and util.dominio_empresarial(l.email)], i=0)
            if estado["sem_site"]:
                db.get(Busca, busca_id).etapa = f"Procurando o site pelo e-mail de {len(estado['sem_site'])} escritórios..."
    with ThreadPoolExecutor(max_workers=5) as grupo:
        for lote, proximo in trabalhos.em_lotes(estado["sem_site"], estado["i"], 5, prazo):
            with sessao() as db:
                usuario = _usuario_da_busca(db, busca_id)
                leads = [l for l in (db.get(Lead, i) for i in lote) if l]
                # Os sites são lidos em paralelo; o banco só é usado nesta linha de execução.
                sites = list(grupo.map(lambda l: descobrir_site(l.empresa, l.email, l.cnpj), leads))
                for lead, site in zip(leads, sites):
                    if site:
                        lead.site = site
                        historico(db, lead.id, "sistema", f"Site confirmado pelo domínio do e-mail: {site}.", usuario)
            estado["i"] = proximo
    return estado["i"] >= len(estado["sem_site"])


def _etapa_sites(busca_id: int, estado: dict, prazo: float) -> bool:
    """Etapa 3: lê os sites (e-mail, redes sociais, CNPJ), 5 por vez."""
    if "com_site" not in estado:
        with sessao() as db:
            estado.update(com_site=[l.id for l in (db.get(Lead, i) for i in estado["novos"]) if l and l.site], j=0)
    total = len(estado["com_site"])
    with ThreadPoolExecutor(max_workers=5) as grupo:
        for lote, proximo in trabalhos.em_lotes(estado["com_site"], estado["j"], 5, prazo):
            with sessao() as db:
                usuario = _usuario_da_busca(db, busca_id)
                leads = [l for l in (db.get(Lead, i) for i in lote) if l]
                for lead, achados in zip(leads, list(grupo.map(lambda l: dados_do_site(l.site), leads))):
                    if achados:
                        mudou = preencher(lead, achados, so_vazios=True)
                        if mudou:
                            historico(db, lead.id, "sistema",
                                      f"Dados encontrados no site {lead.site}: {', '.join(mudou)}.", usuario)
                db.get(Busca, busca_id).etapa = f"Buscando e-mail, redes sociais e CNPJ nos sites ({proximo} de {total})..."
            estado["j"] = proximo
    return estado["j"] >= total


def _etapa_cnpj(busca_id: int, estado: dict, prazo: float) -> bool:
    """Etapa 4: completa com os dados abertos da Receita (BrasilAPI) e recalcula o score."""
    estado.setdefault("k", 0)
    for lote, proximo in trabalhos.em_lotes(estado["novos"], estado["k"], 5, prazo):
        with sessao() as db:
            usuario = _usuario_da_busca(db, busca_id)
            for lead in (db.get(Lead, i) for i in lote):
                if lead is None:
                    continue
                if lead.cnpj:
                    receita = dados_do_cnpj(lead.cnpj)
                    for campo in ("situacao", "fonte_url", "empresa"):
                        receita.pop(campo, None)
                    if receita and preencher(lead, receita, so_vazios=True):
                        historico(db, lead.id, "sistema",
                                  "Dados completados com os dados abertos da Receita Federal (BrasilAPI).", usuario)
                lead.enriquecido_em = agora()
                limpar_campos(lead)
                score.atualizar(db, lead)
        estado["k"] = proximo
    return estado["k"] >= len(estado["novos"])


def etapa_busca(busca_id: int, _usuario_id, estado: dict, prazo: float) -> bool:
    """Uma busca em etapas (ver app/trabalhos.py): cadastrar → sem_site → sites → cnpj → filtro de tamanho."""
    if estado.setdefault("fase", "cadastrar") == "cadastrar":
        novos = _encontrar_e_cadastrar(busca_id)
        if novos is None:
            return True
        with sessao() as db:
            enriquecer = db.get(Busca, busca_id).enriquecer
        estado.update(novos=novos, fase="sem_site" if enriquecer and novos else "final")
    for nome, funcao, seguinte in (("sem_site", _etapa_sem_site, "sites"), ("sites", _etapa_sites, "cnpj"),
                                   ("cnpj", _etapa_cnpj, "final")):
        if estado["fase"] == nome:
            if not funcao(busca_id, estado, prazo):
                return False
            estado["fase"] = seguinte
    with sessao() as db:
        busca = db.get(Busca, busca_id)
        # Filtro de tamanho: só elimina quem tem tamanho CONHECIDO fora da faixa.
        for lead in (db.get(Lead, i) for i in estado["novos"]):
            tamanho = lead.funcionarios if lead else None
            if tamanho is not None and ((busca.tamanho_min and tamanho < busca.tamanho_min)
                                        or (busca.tamanho_max and tamanho > busca.tamanho_max)):
                lead.status = "Perdido"
                lead.motivo_perda = "Sem fit"
                busca.fora_do_tamanho += 1
        busca.status, busca.etapa, busca.concluido_em = "concluida", "Pronto!", agora()
    return True


def executar_busca(busca_id: int) -> None:
    """A busca inteira de uma vez (testes e scripts)."""
    estado: dict = {}
    while not etapa_busca(busca_id, None, estado, float("inf")):
        pass


def _busca_falhou(busca_id: int, _erro: str) -> None:
    with sessao() as db:
        busca = db.get(Busca, busca_id)
        if busca:
            busca.status, busca.concluido_em = "erro", agora()
            busca.erro = "Erro inesperado. Tente de novo; se repetir, avise o suporte (o erro ficou no registro do sistema)."


trabalhos.tipo("busca", _busca_falhou)(etapa_busca)


def iniciar_busca_em_segundo_plano(busca_id: int) -> None:
    trabalhos.iniciar("busca", busca_id)


def leads_da_busca(db, busca_id: int) -> list[Lead]:
    return list(db.execute(select(Lead).where(Lead.busca_id == busca_id).order_by(Lead.score.desc(), Lead.id))
                .scalars())
