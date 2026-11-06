"""Bases de dados importadas (listas de empresas), separadas da base da Receita.

Exemplo: a lista "contabilidades e adm cond PE & MG" exportada da CNPJá (planilha .xlsx com as abas
"Estabelecimentos", "Atividades" e "Sócios"). Cada lista vira uma "base" que o usuário escolhe na tela Nova campanha
e em "Encontrar novos parceiros", no lugar da base da Receita (ou junto com ela).

- Tabelas: `bases_dados` (a lista: nome, origem, total) e `bases_empresas` (as empresas, com as mesmas colunas da
  base da Receita, para a busca e a contagem funcionarem do mesmo jeito: ver base_receita.buscar/contar).
- Identificação de uma base nas telas e nas campanhas: "receita" ou "lista:<id>".
- Só entram empresas com situação "Ativa". O segmento (categoria) é calculado pelas regras das categorias
  (CNAE + palavras); quem não combina com nenhuma fica em "outros".
- LGPD (minimização, igual à base da Receita): dos sócios guardamos só o nome e o cargo de UMA pessoa (o
  sócio-administrador ou equivalente) e a quantidade de sócios. CPF e faixa etária não são guardados.
- A base da Receita pode ser escondida dos usuários (Configurações > Integrações): config "receita_oculta" = "1".
"""

import io
import logging
import re
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, delete, func, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from . import base_receita, util
from .banco import Base, gravar_config, ler_config

log = logging.getLogger(__name__)

RECEITA = "receita"
PREFIXO = "lista:"
LOTE = 2000


class BaseDados(Base):
    __tablename__ = "bases_dados"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160))
    origem: Mapped[str] = mapped_column(String(80), default="CNPJá")
    arquivo: Mapped[str] = mapped_column(String(200), default="")
    total: Mapped[int] = mapped_column(Integer, default=0)
    estados: Mapped[str] = mapped_column(String(120), default="")  # "MG 25.000 · PE 8.000"
    criado_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class EmpresaBase(Base):
    """Uma empresa de uma base importada. Mesmas colunas (e nomes) da EmpresaReceita."""
    __tablename__ = "bases_empresas"
    __table_args__ = (UniqueConstraint("base_id", "cnpj", name="uq_bases_empresas_cnpj"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("bases_dados.id", ondelete="CASCADE"), index=True)
    cnpj: Mapped[str] = mapped_column(String(14), index=True)
    cnpj_basico: Mapped[str] = mapped_column(String(8), default="")
    nome_fantasia: Mapped[str] = mapped_column(String(200), default="")
    razao_social: Mapped[str] = mapped_column(String(200), default="")
    cnae: Mapped[str] = mapped_column(String(7), default="")
    cnae_descricao: Mapped[str] = mapped_column(String(200), default="")
    categoria: Mapped[str] = mapped_column(String(40), default="", index=True)
    uf: Mapped[str] = mapped_column(String(2), index=True, default="")
    municipio: Mapped[str] = mapped_column(String(120), default="")
    municipio_chave: Mapped[str] = mapped_column(String(120), index=True, default="")
    endereco: Mapped[str] = mapped_column(String(250), default="")
    bairro: Mapped[str] = mapped_column(String(120), default="")
    cep: Mapped[str] = mapped_column(String(8), default="")
    telefone: Mapped[str] = mapped_column(String(12), default="")
    telefone2: Mapped[str] = mapped_column(String(12), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    inicio_atividade: Mapped[date | None] = mapped_column(Date, nullable=True)
    matriz: Mapped[int] = mapped_column(Integer, default=1)
    porte: Mapped[str] = mapped_column(String(40), default="")
    socio_admin: Mapped[str] = mapped_column(String(120), default="")
    socio_cargo: Mapped[str] = mapped_column(String(40), default="")
    socios_qtd: Mapped[int] = mapped_column(Integer, default=0)
    regime: Mapped[str] = mapped_column(String(30), default="")


class ErroImportacao(Exception):
    """Texto pronto para mostrar na tela."""


# ---------------------------------------------------------------- Escolha da base (telas e campanhas)

def receita_oculta(db) -> bool:
    return ler_config(db, "receita_oculta") == "1"


def esconder_receita(db, esconder: bool) -> None:
    gravar_config(db, "receita_oculta", "1" if esconder else "0")


def listas(db) -> list[BaseDados]:
    return list(db.execute(select(BaseDados).order_by(BaseDados.nome)).scalars())


def opcoes(db) -> list[dict]:
    """Bases que o usuário pode escolher: {"id", "nome", "total"}. A da Receita sai da lista quando está oculta
    (ou quando nunca foi importada e já existe uma lista)."""
    itens = []
    if not receita_oculta(db):
        total = base_receita.resumo(db)["total"]
        if total or not listas(db):
            itens.append({"id": RECEITA, "nome": "Base da Receita Federal", "total": total})
    itens += [{"id": f"{PREFIXO}{b.id}", "nome": b.nome, "total": b.total} for b in listas(db)]
    return itens


def escolher(db, pedida: str = "") -> str:
    """A base pedida, se o usuário pode usá-la; senão a primeira disponível."""
    disponiveis = [o["id"] for o in opcoes(db)]
    if pedida in disponiveis:
        return pedida
    return disponiveis[0] if disponiveis else RECEITA


def _id_lista(base: str) -> int | None:
    if base and base.startswith(PREFIXO) and base[len(PREFIXO):].isdigit():
        return int(base[len(PREFIXO):])
    return None


def e_lista(base: str) -> bool:
    return _id_lista(base) is not None


def nome(db, base: str) -> str:
    lista_id = _id_lista(base)
    if lista_id is None:
        return "base da Receita"
    b = db.get(BaseDados, lista_id)
    return f"lista \"{b.nome}\"" if b else "lista apagada"


def disponivel(db, base: str) -> bool:
    lista_id = _id_lista(base)
    if lista_id is None:
        return base_receita.disponivel(db)
    return db.execute(select(EmpresaBase.id).where(EmpresaBase.base_id == lista_id).limit(1)).first() is not None


def buscar(db, base: str, cidade: str, uf: str, limite: int, categorias: list[str] | None = None,
           cnaes: list[str] | None = None) -> list[dict]:
    """Mesma busca (e mesma ordem) da base da Receita, na base escolhida."""
    lista_id = _id_lista(base)
    if lista_id is None:
        return base_receita.buscar(db, cidade, uf, limite, categorias, cnaes=cnaes)
    b = db.get(BaseDados, lista_id)
    return base_receita.buscar(db, cidade, uf, limite, categorias, so_matriz=False, cnaes=cnaes, modelo=EmpresaBase,
                               filtro=EmpresaBase.base_id == lista_id,
                               origem=f"Prospecção: lista {b.nome if b else lista_id} ({b.origem if b else 'importada'})")


def contar(db, base: str, uf: str = "", cidade: str = "") -> dict[str, int]:
    lista_id = _id_lista(base)
    if lista_id is None:
        return base_receita.contar(db, uf, cidade)
    return base_receita.contar(db, uf, cidade, modelo=EmpresaBase, filtro=EmpresaBase.base_id == lista_id,
                               so_matriz=False)


def apagar(db, lista_id: int) -> str:
    b = db.get(BaseDados, lista_id)
    if b is None:
        return ""
    db.execute(delete(EmpresaBase).where(EmpresaBase.base_id == lista_id))
    db.delete(b)
    return b.nome


# ---------------------------------------------------------------- Leitura da planilha da CNPJá

def _chave(texto) -> str:
    return re.sub(r"[^a-z0-9]+", " ", util.chave_texto(str(texto or ""))).strip()


def _valor(v) -> str:
    """Célula como texto; "-" (vazio na CNPJá) vira vazio."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    texto = str(v).strip()
    return "" if texto in ("-", "--") else texto


def _data(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    texto = _valor(v)
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def _telefone(v) -> str:
    digitos = util.so_digitos(_valor(v))
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    return digitos if len(digitos) in (10, 11) else ""


def _linhas(aba):
    """Linhas da aba como dicionários, a partir do cabeçalho (a linha que começa com "CNPJ"). A CNPJá põe um
    título na primeira linha."""
    cabecalho = None
    for linha in aba.iter_rows(values_only=True):
        if cabecalho is None:
            if linha and _chave(linha[0]) == "cnpj":
                cabecalho = [_chave(c) for c in linha]
            continue
        if not linha or not linha[0]:
            continue
        yield {cabecalho[i]: v for i, v in enumerate(linha) if i < len(cabecalho)}
    if cabecalho is None:
        raise ErroImportacao(f"Não achei o cabeçalho (coluna \"CNPJ\") na aba \"{aba.title}\".")


def _aba(planilha, *nomes):
    for aba in planilha.worksheets:
        if _chave(aba.title) in nomes:
            return aba
    return None


def _responsaveis(aba) -> tuple[dict[str, tuple[str, str]], dict[str, int]]:
    """Por CNPJ: (nome, cargo) do sócio mais indicado (pessoa física) e a quantidade de sócios."""
    escolhido: dict[str, tuple[int, str, str]] = {}
    quantidade: dict[str, int] = {}
    if aba is None:
        return {}, {}
    for s in _linhas(aba):
        cnpj = util.normalizar_cnpj(_valor(s.get("cnpj")))
        if not cnpj:
            continue
        quantidade[cnpj] = quantidade.get(cnpj, 0) + 1
        codigo = util.so_digitos(_valor(s.get("qualificacao codigo"))).zfill(2)
        nome_socio = _valor(s.get("nome"))
        if codigo not in base_receita.CARGOS_RESPONSAVEL or not nome_socio \
                or "fisica" not in _chave(s.get("tipo")):
            continue
        ordem = base_receita.ORDEM_CARGO[codigo]
        if cnpj not in escolhido or ordem < escolhido[cnpj][0]:
            escolhido[cnpj] = (ordem, base_receita._titulo(nome_socio)[:120], base_receita.CARGOS_RESPONSAVEL[codigo])
    return {c: (n, cargo) for c, (_o, n, cargo) in escolhido.items()}, quantidade


def ler_planilha_cnpja(conteudo: bytes | str) -> tuple[list[dict], dict]:
    """Empresas ATIVAS da planilha exportada da CNPJá (bytes do arquivo ou caminho). Devolve (empresas, resumo)."""
    from openpyxl import load_workbook

    try:
        origem = conteudo if isinstance(conteudo, str) else io.BytesIO(conteudo)
        planilha = load_workbook(origem, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        raise ErroImportacao("Não consegui abrir o arquivo. Envie a planilha .xlsx exportada da CNPJá.") from None
    try:
        estab = _aba(planilha, "estabelecimentos") or planilha.worksheets[0]
        responsaveis, socios = _responsaveis(_aba(planilha, "socios", "socios e administradores"))
        empresas, vistos = [], set()
        resumo = {"lidas": 0, "inativas": 0, "repetidas": 0, "sem_cnpj": 0}
        for e in _linhas(estab):
            resumo["lidas"] += 1
            cnpj = util.normalizar_cnpj(_valor(e.get("cnpj")))
            if len(cnpj) != 14:
                resumo["sem_cnpj"] += 1
                continue
            situacao = _chave(e.get("situacao cadastral"))
            if situacao and situacao != "ativa":
                resumo["inativas"] += 1
                continue
            if cnpj in vistos:
                resumo["repetidas"] += 1
                continue
            vistos.add(cnpj)
            cidade = _valor(e.get("cidade"))
            endereco = " ".join(x for x in (_valor(e.get("logradouro")), _valor(e.get("numero")),
                                            _valor(e.get("complemento"))) if x)
            responsavel = responsaveis.get(cnpj, ("", ""))
            emails = [p for p in re.split(r"[\s;,/]+", _valor(e.get("e mail")).lower()) if util.email_valido(p)]
            empresas.append({
                "cnpj": cnpj, "cnpj_basico": cnpj[:8],
                "nome_fantasia": _valor(e.get("nome fantasia"))[:200], "razao_social": _valor(e.get("razao social"))[:200],
                "cnae": util.so_digitos(_valor(e.get("atividade principal codigo"))).zfill(7)[:7]
                if _valor(e.get("atividade principal codigo")) else "",
                "cnae_descricao": _valor(e.get("atividade principal"))[:200],
                "uf": _valor(e.get("estado")).upper()[:2], "municipio": cidade[:120],
                "municipio_chave": util.chave_texto(cidade)[:120], "endereco": endereco[:250],
                "bairro": _valor(e.get("bairro"))[:120], "cep": util.so_digitos(_valor(e.get("cep")))[:8],
                "telefone": _telefone(e.get("telefone principal")), "telefone2": _telefone(e.get("telefone secundario")),
                "email": emails[0][:160] if emails else "", "inicio_atividade": _data(e.get("data de abertura")),
                "matriz": 0 if _chave(e.get("tipo")) == "filial" else 1, "porte": _valor(e.get("porte"))[:40],
                "socio_admin": responsavel[0], "socio_cargo": responsavel[1], "socios_qtd": socios.get(cnpj, 0),
                "regime": "",
            })
    finally:
        planilha.close()
    if not empresas and not resumo["lidas"]:
        raise ErroImportacao("A planilha não tem empresas (confira se é a exportação da CNPJá, aba Estabelecimentos).")
    return empresas, resumo


def importar(db, nome_lista: str, conteudo: bytes | str, arquivo: str = "", usuario_id: int | None = None,
             origem: str = "CNPJá") -> dict:
    """Cria a lista (ou troca as empresas de uma lista com o mesmo nome) a partir da planilha da CNPJá."""
    nome_lista = (nome_lista or "").strip()[:160]
    if not nome_lista:
        raise ErroImportacao("Dê um nome para a lista (ex.: contabilidades e adm cond PE & MG).")
    empresas, resumo = ler_planilha_cnpja(conteudo)
    regras = base_receita.carregar_regras(db)
    for e in empresas:
        e["categoria"] = base_receita.classificar(regras, e["cnae"], f"{e['nome_fantasia']} {e['razao_social']}") \
            or "outros"
    b = db.execute(select(BaseDados).where(BaseDados.nome == nome_lista)).scalars().first()
    if b is None:
        b = BaseDados(nome=nome_lista, origem=origem, criado_por_id=usuario_id)
        db.add(b)
        db.flush()
    else:
        db.execute(delete(EmpresaBase).where(EmpresaBase.base_id == b.id))
    for e in empresas:
        e["base_id"] = b.id
    for i in range(0, len(empresas), LOTE):
        db.execute(insert(EmpresaBase), empresas[i:i + LOTE])
    por_uf: dict[str, int] = {}
    for e in empresas:
        por_uf[e["uf"]] = por_uf.get(e["uf"], 0) + 1
    b.total, b.arquivo, b.origem, b.atualizado_em = len(empresas), (arquivo or "")[:200], origem, datetime.now()
    b.estados = " · ".join(f"{uf} {n:,}".replace(",", ".") for uf, n in sorted(por_uf.items(), key=lambda x: -x[1]))[:120]
    resumo.update(importadas=len(empresas), base_id=b.id, nome=b.nome)
    log.info("Lista %s importada: %s", b.nome, resumo)
    return resumo


def recontar(db) -> None:
    """Total de cada lista (depois de apagar empresas à mão, por exemplo)."""
    for b in listas(db):
        b.total = db.execute(select(func.count()).select_from(EmpresaBase).where(EmpresaBase.base_id == b.id)).scalar() or 0
