"""Lead scoring da IA SDR: potencial de uma empresa virar PARCEIRA da MS (0 a 100+).

Os pesos e as faixas ficam no banco e o administrador altera em Configurações > Score.
Cada critério só pontua com informação encontrada (cadastro, Receita, site ou resposta do lead).
"""

import json

from sqlalchemy.orm import Session

from .banco import ler_config_json

# chave, descrição, peso padrão
CRITERIOS = [
    ("aderencia", "Aderência da categoria ao certificado digital", 25),
    ("recorrente", "Relacionamento recorrente com os clientes", 10),
    ("atende_empresas", "Clientes são empresas (B2B)", 10),
    ("clientes", "Mais de 100 clientes (estimado)", 10),
    ("tamanho", "Porte da empresa (mais de 5 funcionários ou EPP/demais)", 10),
    ("presenca_digital", "Presença digital (site + rede social)", 10),
    ("indicacao", "Possibilidade de indicação (serviços que usam certificado)", 10),
    ("programa_parceiros", "Já tem programa de parceiros/integrações", 10),
    ("volume", "Potencial de volume (base grande ou demanda recorrente)", 10),
    ("capacidade_comercial", "Capacidade comercial (equipe comercial)", 10),
    ("interesse", "Interesse demonstrado", 20),
    ("contato", "Contato direto disponível (WhatsApp ou e-mail)", 5),
]
FAIXAS_PADRAO = {"medio": 31, "alto": 61, "maxima": 81}
NOMES_POTENCIAL = ["Baixo potencial", "Médio potencial", "Alto potencial", "Prioridade máxima"]


def pesos(db: Session) -> dict[str, int]:
    guardados = ler_config_json(db, "score_pesos", {})
    return {chave: int(guardados.get(chave, padrao)) for chave, _, padrao in CRITERIOS}


def faixas(db: Session) -> dict[str, int]:
    guardadas = ler_config_json(db, "score_faixas", {})
    return {k: int(guardadas.get(k, v)) for k, v in FAIXAS_PADRAO.items()}


def perfil_de(lead) -> dict:
    try:
        return json.loads(lead.perfil) if lead.perfil else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def criterios_atendidos(lead) -> dict[str, float]:
    """Fração (0 a 1) de cada critério atendida pelo lead."""
    cat = lead.categoria
    perfil = perfil_de(lead)
    socios = [s for s in (lead.socios or "").splitlines() if s.strip()]
    clientes = lead.qtd_clientes_estimada or 0
    porte = (lead.porte or "").lower()
    aderencia = (cat.aderencia / 25) if cat else 0
    return {
        "aderencia": max(0.0, min(aderencia, 1.0)),
        "recorrente": 1.0 if (cat and cat.recorrente) or perfil.get("relacionamento_recorrente") else 0.0,
        "atende_empresas": 1.0 if lead.atende_empresas or perfil.get("atende_empresas") else 0.0,
        "clientes": 1.0 if clientes > 100 else 0.0,
        "tamanho": 1.0 if (lead.funcionarios or 0) > 5 or "pequeno porte" in porte or "demais" in porte
        or len(socios) > 2 else 0.0,
        "presenca_digital": 1.0 if lead.site and (lead.instagram or lead.linkedin) else (0.5 if lead.site else 0.0),
        "indicacao": 1.0 if lead.possibilidade_indicacao else 0.0,
        "programa_parceiros": 1.0 if lead.programa_parceiros else 0.0,
        "volume": 1.0 if clientes > 500 or (cat and cat.recorrente and cat.aderencia >= 20) else 0.0,
        "capacidade_comercial": 1.0 if lead.equipe_comercial else 0.0,
        "interesse": 1.0 if lead.demonstrou_interesse or (lead.etapa >= 3 and not lead.perdido) else 0.0,
        "contato": 1.0 if lead.whatsapp or lead.email else 0.0,
    }


def classificar(score: int, limites: dict[str, int]) -> str:
    if score >= limites["maxima"]:
        return NOMES_POTENCIAL[3]
    if score >= limites["alto"]:
        return NOMES_POTENCIAL[2]
    if score >= limites["medio"]:
        return NOMES_POTENCIAL[1]
    return NOMES_POTENCIAL[0]


def calcular_fit(lead, score: int, limites: dict[str, int]) -> str:
    """Muito alto / Alto / Médio / Baixo potencial ou Sem fit (motivo para indicar certificado?)."""
    perfil = perfil_de(lead)
    if perfil.get("fit") in ("Muito alto potencial", "Alto potencial", "Médio potencial", "Baixo potencial", "Sem fit"):
        return perfil["fit"]  # avaliação da pesquisa (IA), feita só com o que foi encontrado
    cat = lead.categoria
    if (not cat or cat.codigo == "outros") and not lead.atende_empresas and not lead.possibilidade_indicacao:
        return "Sem fit"
    if score >= limites["maxima"]:
        return "Muito alto potencial"
    if score >= limites["alto"]:
        return "Alto potencial"
    if score >= limites["medio"]:
        return "Médio potencial"
    return "Baixo potencial"


def calcular(db: Session, lead, _pesos=None, _faixas=None) -> tuple[int, str, list[tuple[str, int, bool]]]:
    """Devolve (score, potencial, [(motivo, pontos, atendido)])."""
    _pesos = _pesos or pesos(db)
    atendidos = criterios_atendidos(lead)
    detalhes, total = [], 0
    for chave, descricao, _ in CRITERIOS:
        pontos = round(_pesos[chave] * atendidos[chave])
        total += pontos
        detalhes.append((descricao, pontos if pontos else _pesos[chave], pontos > 0))
    return total, classificar(total, _faixas or faixas(db)), detalhes


def atualizar(db: Session, lead, _pesos=None, _faixas=None) -> None:
    limites = _faixas or faixas(db)
    lead.score, lead.potencial, _ = calcular(db, lead, _pesos, limites)
    lead.fit = calcular_fit(lead, lead.score, limites)


def recalcular_todos(db: Session) -> int:
    from sqlalchemy import select

    from .modelos import Lead

    p, f = pesos(db), faixas(db)
    total = 0
    for lead in db.execute(select(Lead)).scalars():
        atualizar(db, lead, p, f)
        total += 1
    return total


def classe_css(potencial: str) -> str:
    return {
        "Prioridade máxima": "selo-maxima", "Alto potencial": "selo-alto", "Muito alto potencial": "selo-maxima",
        "Médio potencial": "selo-medio", "Sem fit": "selo-erro",
    }.get(potencial, "selo-baixo")
