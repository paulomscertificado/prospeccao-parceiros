"""Lead Enrichment da IA SDR: pesquisa pública e PERFIL DO PARCEIRO.

1. Lê até 6 páginas públicas do site (início, sobre, serviços/produtos, parceiros, integrações, contato).
2. Extrai por regras: redes sociais, e-mail, WhatsApp, CNPJ, sinais de programa de parceiros,
   integrações, público B2B, serviços ligados a certificado digital, número de clientes citado.
3. Com IA: monta o perfil (segmento, público, produtos, serviços, clientes, parceiros, integrações,
   diferenciais, motivo do potencial, fit) usando SOMENTE o texto lido. Números só são aceitos se o
   trecho de evidência aparecer de verdade no texto (trava contra invenção).
Sem site, o perfil usa só os dados da Receita/BrasilAPI e da categoria.
"""

import json
import logging
import re
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx

from . import config, ia, score, util
from .banco import agora
from .leads_servico import cnpj_inativo, historico, limpar_campos, preencher
from .prospeccao import dados_do_cnpj, dados_do_site, descobrir_site

log = logging.getLogger(__name__)

PAGINAS_INTERESSE = re.compile(r"sobre|quem-somos|quem_somos|empresa|servi|solu|produto|parceir|integra|contato|clientes",
                               re.I)
SINAIS_PARCEIROS = ["seja um parceiro", "seja parceiro", "programa de parceiros", "programa de parceria", "revenda",
                    "revendedor", "afiliado", "indique e ganhe", "parceiros comerciais", "canal de parceiros"]
SINAIS_INTEGRACAO = ["integração", "integracao", "api", "integrado com", "integra com", "marketplace de apps"]
SINAIS_B2B = ["empresas", "pmes", "pequenas e médias", "pequenas empresas", "condomínios", "condominios",
              "escritórios", "clientes empresariais", "b2b", "síndicos", "sindicos", "franqueados", "associados"]
SINAIS_CERTIFICADO = ["nota fiscal", "nf-e", "nfe", "nfs-e", "esocial", "e-social", "sped", "folha de pagamento",
                      "obrigações acessórias", "obrigacoes acessorias", "certificado digital", "receita federal",
                      "abertura de empresa", "contabilidade", "imposto", "fiscal", "tributári"]
SINAIS_COMERCIAL = ["fale com vendas", "fale com um consultor", "time comercial", "equipe comercial",
                    "solicite uma demonstração", "solicite uma demonstracao", "agende uma demonstração", "consultor comercial"]
RE_CLIENTES = re.compile(r"(?:mais de|\+)\s*(\d{1,3}(?:[.\s]\d{3})*|\d+)\s*(?:mil\s+)?(clientes|empresas|condom[ií]nios|"
                         r"escrit[óo]rios|usu[áa]rios)", re.I)


def _texto_visivel(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    texto = unescape(re.sub(r"(?s)<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", texto).strip()


def ler_site(site: str, max_paginas: int = 6) -> dict:
    """Devolve {"paginas": [url...], "texto": texto visível concatenado, "html": html bruto concatenado}."""
    url = util.normalizar_site(site)
    if not url:
        return {}
    cabecalho = {"User-Agent": "Mozilla/5.0 (compatible; MS-Prospeccao/1.0)"}
    paginas, textos, htmls = [], [], []
    try:
        with httpx.Client(timeout=10, follow_redirects=True, headers=cabecalho) as c:
            r = c.get(url)
            if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
                return {}
            base = str(r.url)
            paginas.append(base)
            htmls.append(r.text[:600_000])
            textos.append(_texto_visivel(r.text[:600_000]))
            dominio = urlparse(base).netloc
            links = []
            for href in re.findall(r'href=["\']([^"\'#]+)["\']', r.text, re.I):
                completo = urljoin(base, href)
                if urlparse(completo).netloc == dominio and PAGINAS_INTERESSE.search(href) and completo not in links:
                    links.append(completo)
            for link in links[: max_paginas - 1]:
                try:
                    r2 = c.get(link)
                except (httpx.HTTPError, ValueError):  # link/redirecionamento inválido no site: pula
                    continue
                if r2.status_code < 400 and "html" in r2.headers.get("content-type", "html"):
                    paginas.append(link)
                    htmls.append(r2.text[:400_000])
                    textos.append(_texto_visivel(r2.text[:400_000]))
    except (httpx.HTTPError, ValueError):  # site fora do ar ou com endereço inválido: segue sem ele
        return {}
    return {"paginas": paginas, "texto": "\n".join(textos)[:60_000], "html": "\n".join(htmls)}


def sinais_por_regras(texto: str) -> dict:
    t = util.chave_texto(texto)

    def tem(lista):
        return [s for s in lista if util.chave_texto(s) in t]

    clientes = None
    evidencia = ""
    for m in RE_CLIENTES.finditer(texto):
        numero = int(re.sub(r"\D", "", m.group(1)) or 0)
        if "mil" in m.group(0).lower() and numero < 1000:
            numero *= 1000
        if numero and (clientes is None or numero > clientes):
            clientes, evidencia = numero, m.group(0)
    return {
        "programa_parceiros": bool(tem(SINAIS_PARCEIROS)), "sinais_parceiros": tem(SINAIS_PARCEIROS),
        "integracoes": bool(tem(SINAIS_INTEGRACAO)),
        "atende_empresas": len(tem(SINAIS_B2B)) >= 1, "publico_sinais": tem(SINAIS_B2B),
        "possibilidade_indicacao": len(tem(SINAIS_CERTIFICADO)) >= 1, "servicos_certificado": tem(SINAIS_CERTIFICADO),
        "equipe_comercial": bool(tem(SINAIS_COMERCIAL)),
        "clientes_estimados": clientes, "evidencia_clientes": evidencia,
    }


ESQUEMA_PERFIL = {
    "type": "object",
    "properties": {
        "segmento": {"type": "string"},
        "publico": {"type": "string"},
        "produtos": {"type": "array", "items": {"type": "string"}},
        "servicos": {"type": "array", "items": {"type": "string"}},
        "clientes_estimados": {"type": ["integer", "null"]},
        "evidencia_clientes": {"type": "string"},
        "perfil_clientes": {"type": "string"},
        "relacionamento_recorrente": {"type": "boolean"},
        "atende_empresas": {"type": "boolean"},
        "programa_parceiros": {"type": "boolean"},
        "integracoes": {"type": "array", "items": {"type": "string"}},
        "tecnologias": {"type": "array", "items": {"type": "string"}},
        "diferenciais": {"type": "array", "items": {"type": "string"}},
        "responsaveis": {"type": "array", "items": {"type": "string"}},
        "pagina_contato": {"type": "string"},
        "motivo_para_indicar_certificado": {"type": "string"},
        "fit": {"type": "string", "enum": config.FITS},
        "motivo_potencial": {"type": "string"},
        "categoria_sugerida": {"type": "string"},
    },
    "required": ["segmento", "publico", "produtos", "servicos", "clientes_estimados", "evidencia_clientes",
                 "perfil_clientes", "relacionamento_recorrente", "atende_empresas", "programa_parceiros",
                 "integracoes", "tecnologias", "diferenciais", "responsaveis", "pagina_contato",
                 "motivo_para_indicar_certificado", "fit", "motivo_potencial", "categoria_sugerida"],
    "additionalProperties": False,
}


def perfil_com_ia(db, lead, texto: str, codigos_categorias: list[str]) -> dict:
    pedido = (
        "Monte o PERFIL DO PARCEIRO desta empresa usando SOMENTE o texto do site e os dados abaixo. "
        "Se uma informação não aparecer, use string vazia, lista vazia ou null. NÃO deduza números: "
        "clientes_estimados só pode ser preenchido se o texto disser explicitamente (copie o trecho exato em "
        "evidencia_clientes). responsaveis só se o site citar nomes e cargos.\n"
        "Pergunta central: esta empresa tem algum motivo para indicar certificados digitais aos próprios clientes?\n"
        f"categoria_sugerida deve ser um destes códigos: {', '.join(codigos_categorias)}.\n\n"
        f"DADOS: empresa {lead.empresa}; cidade {lead.cidade}/{lead.estado}; categoria atual "
        f"{lead.categoria.nome if lead.categoria else 'não definida'}; porte {lead.porte or 'não informado'}.\n\n"
        f"TEXTO DO SITE:\n\"\"\"{texto[:25_000]}\"\"\"")
    return ia.perguntar(db, pedido, ESQUEMA_PERFIL, max_tokens=3000)


def _validar_perfil(perfil: dict, texto: str) -> dict:
    """Trava contra invenção: descarta números sem evidência literal no texto e nomes que não aparecem."""
    t = util.chave_texto(texto)
    evidencia = util.chave_texto(perfil.get("evidencia_clientes") or "")
    if perfil.get("clientes_estimados") and (not evidencia or evidencia not in t):
        perfil["clientes_estimados"] = None
        perfil["evidencia_clientes"] = ""
    perfil["responsaveis"] = [r for r in perfil.get("responsaveis", [])
                              if util.chave_texto(r.split("(")[0].split("-")[0]).strip() in t]
    return perfil


def pesquisar_lead(db, lead, usuario=None, usar_ia: bool = True) -> dict:
    """Pesquisa pública + perfil + score. Grava no lead e devolve o perfil."""
    from sqlalchemy import select

    from .modelos import Categoria

    if lead.status == "Novo":
        lead.status = "Pesquisando"
    fontes = []
    if not lead.site and lead.email:
        site = descobrir_site(lead.empresa, lead.email, lead.cnpj)
        if site:
            lead.site = site
            fontes.append(f"site confirmado pelo e-mail ({site})")
    leitura = ler_site(lead.site) if lead.site else {}
    texto = leitura.get("texto", "")
    if leitura:
        fontes.append("site: " + ", ".join(leitura["paginas"][:6]))
        contatos = dados_do_site(lead.site)
        preencher(lead, contatos, so_vazios=True)
    if lead.cnpj and not lead.socios:
        receita = dados_do_cnpj(lead.cnpj)
        if receita:
            situacao = receita.pop("situacao", "")
            for chave in ("fonte_url", "empresa", "especialidade"):
                receita.pop(chave, None)
            preencher(lead, receita, so_vazios=True)
            fontes.append("dados abertos da Receita (BrasilAPI)")
            cnpj_inativo(db, lead, situacao, usuario)
    if not lead.responsavel and lead.socios:
        # Quadro societário público da Receita: o sócio-administrador é o contato mais provável.
        socios = [s for s in lead.socios.splitlines() if s.strip()]
        escolhido = next((s for s in socios if "administrador" in s.lower()), socios[0] if len(socios) == 1 else "")
        if escolhido:
            lead.responsavel = escolhido.split("(")[0].strip()[:120]
            lead.cargo = lead.cargo or (escolhido.split("(")[1].rstrip(")")[:80] if "(" in escolhido else "")
    sinais = sinais_por_regras(texto) if texto else {}
    perfil = {
        # Sem IA, o segmento fica vazio: a categoria vem da Receita e não confirma o ramo sozinha.
        "segmento": "", "publico": ", ".join(sinais.get("publico_sinais", [])),
        "produtos": [], "servicos": sinais.get("servicos_certificado", []),
        "clientes_estimados": sinais.get("clientes_estimados"), "evidencia_clientes": sinais.get("evidencia_clientes", ""),
        "perfil_clientes": "", "relacionamento_recorrente": bool(lead.categoria and lead.categoria.recorrente),
        "atende_empresas": sinais.get("atende_empresas", False), "programa_parceiros": sinais.get("programa_parceiros", False),
        "integracoes": ["menciona integrações"] if sinais.get("integracoes") else [], "tecnologias": [],
        "diferenciais": [], "responsaveis": [], "pagina_contato": next((p for p in leitura.get("paginas", []) if "contato" in p), ""),
        "motivo_para_indicar_certificado": lead.categoria.motivo if lead.categoria else "",
        "motivo_potencial": "", "categoria_sugerida": lead.categoria.codigo if lead.categoria else "",
        "fonte": "regras",
    }
    if texto and usar_ia and ia.disponivel():
        codigos = [c for (c,) in db.execute(select(Categoria.codigo).where(Categoria.ativa.is_(True)))]
        try:
            perfil_ia = _validar_perfil(perfil_com_ia(db, lead, texto, codigos), texto)
            perfil.update(perfil_ia)
            perfil["fonte"] = "ia"
        except ia.ErroDaIA as erro:
            log.warning("Perfil por IA falhou (%s): %s", lead.empresa, erro)
    perfil["fontes"] = fontes
    perfil["paginas_lidas"] = leitura.get("paginas", [])
    perfil["pesquisado_em"] = agora().strftime("%d/%m/%Y %H:%M")
    # Grava o que foi encontrado nos campos do lead (só quando vazio).
    if perfil.get("clientes_estimados") and not lead.qtd_clientes_estimada:
        lead.qtd_clientes_estimada = int(perfil["clientes_estimados"])
    lead.atende_empresas = lead.atende_empresas or bool(perfil.get("atende_empresas"))
    lead.programa_parceiros = lead.programa_parceiros or bool(perfil.get("programa_parceiros"))
    lead.possibilidade_indicacao = lead.possibilidade_indicacao or bool(
        perfil.get("servicos") and sinais.get("possibilidade_indicacao")) or bool(
        perfil.get("fonte") == "ia" and perfil.get("motivo_para_indicar_certificado"))
    lead.equipe_comercial = lead.equipe_comercial or bool(sinais.get("equipe_comercial"))
    if perfil.get("segmento") and not lead.especialidade:
        lead.especialidade = perfil["segmento"][:120]
    sugerida = perfil.get("categoria_sugerida")
    if sugerida and perfil.get("fonte") == "ia" and (not lead.categoria or sugerida != lead.categoria.codigo):
        cat = db.execute(select(Categoria).where(Categoria.codigo == sugerida)).scalars().first()
        # Troca só para uma categoria mais aderente (ex.: "ERP" que o site mostra ser emissor de NF-e).
        if cat and (not lead.categoria or lead.categoria.codigo == "outros" or cat.aderencia > lead.categoria.aderencia):
            lead.categoria = cat
    if perfil.get("fonte") != "ia":
        perfil.pop("fit", None)  # sem IA o fit é calculado pelas regras do score
    lead.perfil = json.dumps(perfil, ensure_ascii=False)
    lead.pesquisado_em = agora()
    limpar_campos(lead)
    score.atualizar(db, lead)
    lead.motivo_potencial = perfil.get("motivo_potencial") or montar_motivo(lead, perfil)
    if lead.id:
        historico(db, lead.id, "sistema", f"Pesquisa pública concluída. Fit: {lead.fit}; score {lead.score}. "
                                          f"Fontes: {'; '.join(fontes) or 'dados cadastrados'}.", usuario)
    return perfil


def montar_motivo(lead, perfil: dict) -> str:
    """Motivo do potencial por regras, só com fatos encontrados."""
    partes = []
    if lead.categoria and lead.categoria.motivo:
        partes.append(lead.categoria.motivo)
    if perfil.get("clientes_estimados"):
        partes.append(f"O site cita \"{perfil.get('evidencia_clientes')}\".")
    if lead.programa_parceiros:
        partes.append("O site menciona programa de parceiros/revenda.")
    if perfil.get("servicos"):
        partes.append("Serviços ligados a certificado: " + ", ".join(perfil["servicos"][:4]) + ".")
    return " ".join(partes) or "Poucas informações públicas encontradas."
