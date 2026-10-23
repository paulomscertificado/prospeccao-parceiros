"""Base de CNPJs da Receita Federal (dados abertos), só com as empresas das CATEGORIAS de parceiros.

A Receita publica todo mês os arquivos "Estabelecimentos0.zip" ... "Estabelecimentos9.zip",
"Empresas0.zip" ..., "Socios0.zip" ..., "Simples.zip" e "Municipios.zip" (ver docs/configuracao.md). Esta rotina lê os arquivos
direto do .zip, sem descompactar, e guarda só os estabelecimentos ATIVOS cuja atividade principal
(CNAE) combina com alguma categoria cadastrada (Configurações > Categorias):
  - CNAE na lista "cnaes" da categoria → entra;
  - CNAE na lista "cnaes_com_palavra" → só entra se o nome fantasia tiver uma das palavras-chave.
São dados públicos e oficiais (CNPJ, nome, endereço, telefone e e-mail informados à Receita).

LGPD (minimização): dos arquivos de sócios guardamos só o NOME e o cargo de UMA pessoa (o sócio-administrador
ou equivalente, que é o contato natural da empresa) e a QUANTIDADE de sócios. CPF, idade, data de entrada e
os demais sócios não são guardados. Do Simples, só o regime atual (MEI / Simples Nacional / fora do Simples).
"""

import csv
import io
import logging
import re
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Date, DateTime, Integer, String, delete, func, insert, select, text
from sqlalchemy.orm import Mapped, mapped_column

from . import util
from .banco import Base, gravar_config, ler_config, sessao

log = logging.getLogger(__name__)

# Qualificações (tabela Qualificacoes.zip) aceitas como responsável, da mais para a menos indicada.
CARGOS_RESPONSAVEL = {"49": "Sócio-administrador", "05": "Administrador", "65": "Titular", "50": "Empresário",
                      "28": "Sócio-gerente", "16": "Presidente", "10": "Diretor", "43": "Responsável"}
ORDEM_CARGO = {codigo: i for i, codigo in enumerate(CARGOS_RESPONSAVEL)}
PORTES = {"01": "Micro empresa", "03": "Empresa de pequeno porte", "05": "Demais", "00": "Não informado"}
LOTE = 5000
csv.field_size_limit(10_000_000)


class EmpresaReceita(Base):
    __tablename__ = "base_receita"
    cnpj: Mapped[str] = mapped_column(String(14), primary_key=True)
    cnpj_basico: Mapped[str] = mapped_column(String(8), index=True)
    nome_fantasia: Mapped[str] = mapped_column(String(200), default="")
    razao_social: Mapped[str] = mapped_column(String(200), default="")
    cnae: Mapped[str] = mapped_column(String(7), default="")
    categoria: Mapped[str] = mapped_column(String(40), default="", index=True)
    uf: Mapped[str] = mapped_column(String(2), index=True)
    municipio: Mapped[str] = mapped_column(String(120), default="")
    municipio_chave: Mapped[str] = mapped_column(String(120), index=True, default="")
    endereco: Mapped[str] = mapped_column(String(250), default="")
    bairro: Mapped[str] = mapped_column(String(120), default="")
    cep: Mapped[str] = mapped_column(String(8), default="")
    telefone: Mapped[str] = mapped_column(String(12), default="")
    telefone2: Mapped[str] = mapped_column(String(12), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    inicio_atividade: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    matriz: Mapped[int] = mapped_column(Integer, default=1)
    porte: Mapped[str] = mapped_column(String(40), default="")
    socio_admin: Mapped[str] = mapped_column(String(120), default="")  # nome do responsável (pessoa física)
    socio_cargo: Mapped[str] = mapped_column(String(40), default="")
    socios_qtd: Mapped[int] = mapped_column(Integer, default=0)
    regime: Mapped[str] = mapped_column(String(30), default="")
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ErroBase(Exception):
    pass


# ---------------------------------------------------------------- Regras das categorias

@dataclass
class Regra:
    codigo: str
    cnaes: set
    cnaes_com_palavra: set
    palavras: list


def carregar_regras(db) -> list[Regra]:
    from .modelos import Categoria

    regras = []
    for c in db.execute(select(Categoria).where(Categoria.ativa.is_(True)).order_by(Categoria.prioridade)).scalars():
        regras.append(Regra(c.codigo, set(c.lista("cnaes")), set(c.lista("cnaes_com_palavra")),
                            [util.chave_texto(p) for p in c.lista("palavras_chave")]))
    return regras


def classificar(regras: list[Regra], cnae: str, nome: str) -> str:
    """Código da primeira categoria (por prioridade) que combina com o CNAE e o nome. Vazio = nenhuma."""
    nome_chave = None
    for r in regras:
        if cnae in r.cnaes:
            return r.codigo
        if cnae in r.cnaes_com_palavra:
            if nome_chave is None:
                nome_chave = util.chave_texto(nome)
            if any(p in nome_chave for p in r.palavras):
                return r.codigo
    return ""


# ---------------------------------------------------------------- Leitura dos arquivos

PALAVRAS_MINUSCULAS = {"de", "da", "do", "das", "dos", "e"}


def _titulo(texto: str) -> str:
    """"RIO DE JANEIRO" → "Rio de Janeiro"."""
    palavras = texto.strip().title().split()
    return " ".join(p.lower() if i and p.lower() in PALAVRAS_MINUSCULAS else p for i, p in enumerate(palavras))


def _primeiro_email(texto: str) -> str:
    """Às vezes a Receita traz dois e-mails no mesmo campo: fica o primeiro válido."""
    for parte in re.split(r"[\s;,/]+", texto.strip().lower()):
        if util.email_valido(parte):
            return parte[:160]
    return ""


def _linhas_do_zip(arquivo: Path, filtro=None):
    """Linhas do CSV dentro do .zip. O filtro (texto da linha → bool) descarta linhas antes de
    separar as colunas: os arquivos têm dezenas de milhões de linhas e só queremos poucas."""
    with zipfile.ZipFile(arquivo) as z:
        for nome in z.namelist():
            with z.open(nome) as bruto:
                texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
                yield from csv.reader(texto if filtro is None else filter(filtro, texto), delimiter=";", quotechar='"')


def _arquivos(pasta: Path, prefixo: str) -> list[Path]:
    return sorted(p for p in pasta.iterdir() if p.suffix.lower() == ".zip" and p.name.lower().startswith(prefixo))


def _anotar(texto: str):
    with sessao() as db:
        gravar_config(db, "receita_status", texto)


def importar_pasta(pasta: str) -> int:
    """Lê os .zip da Receita na pasta e recria a base local. Devolve quantas empresas foram guardadas."""
    pasta_p = Path(pasta.strip().strip('"'))
    if not pasta_p.is_dir():
        raise ErroBase(f"A pasta \"{pasta}\" não existe.")
    estabelecimentos = _arquivos(pasta_p, "estabelecimento")
    if not estabelecimentos:
        raise ErroBase("Não encontrei os arquivos Estabelecimentos*.zip nessa pasta.")
    municipios = {}
    for arq in _arquivos(pasta_p, "municipio"):
        for linha in _linhas_do_zip(arq):
            if len(linha) >= 2:
                municipios[linha[0].strip()] = _titulo(linha[1])
    if not municipios:
        raise ErroBase("Não encontrei o arquivo Municipios.zip nessa pasta (ele traz os nomes das cidades).")

    from .banco import motor

    EmpresaReceita.__table__.create(motor, checkfirst=True)
    with sessao() as db:
        regras = carregar_regras(db)
    todos_cnaes = set().union(*(r.cnaes | r.cnaes_com_palavra for r in regras)) if regras else set()
    if not todos_cnaes:
        raise ErroBase("Nenhuma categoria ativa tem CNAE cadastrado (Configurações > Categorias).")

    def interessa(linha: str) -> bool:
        partes = linha.split('";"', 12)
        return len(partes) > 11 and partes[11] in todos_cnaes

    agora = datetime.now()
    total = 0
    por_categoria: dict[str, int] = {}
    basicos: set[str] = set()
    with sessao() as db:
        db.execute(delete(EmpresaReceita))
    for n, arq in enumerate(estabelecimentos, start=1):
        _anotar(f"Lendo {arq.name} ({n} de {len(estabelecimentos)})... {total} empresas até agora")
        lote = []
        for c in _linhas_do_zip(arq, interessa):
            if len(c) < 28 or c[5] != "02":
                continue
            categoria = classificar(regras, c[11], c[4])
            if not categoria:
                continue
            cidade = municipios.get(c[20].strip(), "")
            rua = " ".join(x for x in (_titulo(c[13]), _titulo(c[14]), c[15].strip()) if x)
            complemento = _titulo(c[16])
            lote.append({
                "cnpj": c[0] + c[1] + c[2], "cnpj_basico": c[0], "nome_fantasia": _titulo(c[4])[:200], "razao_social": "",
                "cnae": c[11], "categoria": categoria, "uf": c[19].strip().upper(), "municipio": cidade,
                "municipio_chave": util.chave_texto(cidade),
                "endereco": (rua + (f", {complemento}" if complemento else ""))[:250], "bairro": _titulo(c[17])[:120],
                "cep": c[18].strip()[:8], "telefone": util.so_digitos(c[21] + c[22])[:12],
                "telefone2": util.so_digitos(c[23] + c[24])[:12], "email": _primeiro_email(c[27]),
                "inicio_atividade": util.para_data(f"{c[10][:4]}-{c[10][4:6]}-{c[10][6:8]}") if len(c[10]) == 8 else None,
                "matriz": 1 if c[3] == "1" else 0, "porte": "", "atualizado_em": agora,
            })
            por_categoria[categoria] = por_categoria.get(categoria, 0) + 1
            basicos.add(c[0])
            if len(lote) >= LOTE:
                with sessao() as db:
                    db.execute(insert(EmpresaReceita), lote)
                total += len(lote)
                lote = []
        if lote:
            with sessao() as db:
                db.execute(insert(EmpresaReceita), lote)
            total += len(lote)
    # Razão social e porte ficam nos arquivos Empresas*.zip (opcionais).
    empresas = _arquivos(pasta_p, "empresa")
    for n, arq in enumerate(empresas, start=1):
        _anotar(f"Lendo razão social em {arq.name} ({n} de {len(empresas)})...")
        dados = []
        for c in _linhas_do_zip(arq, lambda linha: linha[1:9] in basicos):
            if len(c) >= 6 and c[0] in basicos:
                dados.append({"b": c[0], "r": _titulo(c[1])[:200], "p": PORTES.get(c[5].strip(), "")})
        for i in range(0, len(dados), LOTE):
            with sessao() as db:
                db.execute(text("UPDATE base_receita SET razao_social = :r, porte = :p WHERE cnpj_basico = :b"),
                           dados[i:i + LOTE])
    _importar_socios(pasta_p, basicos)
    _importar_simples(pasta_p, basicos)
    log.info("Leads completados com responsável/regime da Receita: %s", completar_leads())
    with sessao() as db:
        gravar_config(db, "receita_status", "")
        gravar_config(db, "receita_atualizada_em", agora.strftime("%d/%m/%Y %H:%M"))
        gravar_config(db, "receita_total", str(total))
        gravar_config(db, "receita_por_categoria", por_categoria)
    log.info("Base da Receita importada: %s empresas %s", total, por_categoria)
    return total


def _importar_socios(pasta: Path, basicos: set[str]) -> int:
    """Socios*.zip (opcionais): o responsável (sócio-administrador ou equivalente, pessoa física) e quantos sócios
    a empresa tem. Colunas: cnpj_basico; tipo (1 PJ, 2 PF, 3 estrangeiro); nome; CPF mascarado; qualificação; ..."""
    arquivos = _arquivos(pasta, "socio")
    if not arquivos:
        return 0
    escolhido: dict[str, tuple] = {}  # basico -> (ordem, data_entrada, nome, cargo)
    quantidade: dict[str, int] = {}
    for n, arq in enumerate(arquivos, start=1):
        _anotar(f"Lendo responsáveis em {arq.name} ({n} de {len(arquivos)})...")
        for c in _linhas_do_zip(arq, lambda linha: linha[1:9] in basicos):
            if len(c) < 6 or c[0] not in basicos:
                continue
            quantidade[c[0]] = quantidade.get(c[0], 0) + 1
            if c[1] != "2" or c[4] not in ORDEM_CARGO or not c[2].strip():
                continue  # só pessoa física com cargo de gestão
            candidato = (ORDEM_CARGO[c[4]], c[5] or "99999999", _titulo(c[2])[:120], CARGOS_RESPONSAVEL[c[4]])
            if c[0] not in escolhido or candidato < escolhido[c[0]]:
                escolhido[c[0]] = candidato  # cargo mais indicado; empate: quem entrou primeiro
    dados = [{"b": b, "n": escolhido[b][2] if b in escolhido else "", "c": escolhido[b][3] if b in escolhido else "",
              "q": q} for b, q in quantidade.items()]
    for i in range(0, len(dados), LOTE):
        with sessao() as db:
            db.execute(text("UPDATE base_receita SET socio_admin = :n, socio_cargo = :c, socios_qtd = :q "
                            "WHERE cnpj_basico = :b"), dados[i:i + LOTE])
    log.info("Responsáveis da Receita: %s empresas com responsável, %s com sócios", len(escolhido), len(quantidade))
    return len(escolhido)


def completar_leads() -> int:
    """Leads que já existiam e estão na base: preenche responsável/cargo (se vazios) e o regime."""
    from . import score
    from .leads_servico import historico
    from .modelos import Lead

    total = 0
    with sessao() as db:
        for lead in db.execute(select(Lead).where(Lead.cnpj != "")).scalars():
            e = db.get(EmpresaReceita, util.normalizar_cnpj(lead.cnpj))
            if e is None:
                continue
            mudou = []
            if not lead.responsavel and e.socio_admin:
                lead.responsavel, lead.cargo = e.socio_admin, lead.cargo or e.socio_cargo
                mudou.append(f"responsável ({e.socio_cargo.lower()})")
            if e.regime and lead.regime != e.regime:
                lead.regime = e.regime
                mudou.append(f"regime: {e.regime}")
            if (e.socios_qtd or 0) > 1 and not lead.multiplos_socios:
                lead.multiplos_socios = True
                mudou.append("mais de um sócio")
            if mudou:
                score.atualizar(db, lead)
                historico(db, lead.id, "sistema", "Dados públicos da Receita: " + ", ".join(mudou) + ".", None)
                total += 1
    return total


def regime_simples(opcao_simples: str, opcao_mei: str) -> str:
    if opcao_mei.strip().upper() == "S":
        return "MEI"
    if opcao_simples.strip().upper() == "S":
        return "Simples Nacional"
    return "Fora do Simples"


def _importar_simples(pasta: Path, basicos: set[str]) -> int:
    """Simples.zip (opcional): cnpj_basico; opção Simples (S/N); datas; opção MEI (S/N); datas."""
    arquivos = _arquivos(pasta, "simples")
    total = 0
    for arq in arquivos:
        _anotar(f"Lendo Simples Nacional / MEI em {arq.name}...")
        dados = [{"b": c[0], "r": regime_simples(c[1], c[4])}
                 for c in _linhas_do_zip(arq, lambda linha: linha[1:9] in basicos)
                 if len(c) >= 5 and c[0] in basicos]
        for i in range(0, len(dados), LOTE):
            with sessao() as db:
                db.execute(text("UPDATE base_receita SET regime = :r WHERE cnpj_basico = :b"), dados[i:i + LOTE])
        total += len(dados)
    return total


def importar_em_segundo_plano(pasta: str) -> None:
    def _rodar():
        try:
            importar_pasta(pasta)
        except ErroBase as erro:
            _anotar(f"Erro: {erro}")
        except Exception as erro:  # noqa: BLE001
            log.exception("Erro ao importar a base da Receita")
            _anotar(f"Erro inesperado ({erro}). Veja dados/sistema.log.")

    threading.Thread(target=_rodar, daemon=True, name="base-receita").start()


def ajustar_base_antiga(db) -> None:
    """A versão 1 só guardava contabilidade e não tinha a coluna categoria: marca essas linhas."""
    try:
        db.execute(text("UPDATE base_receita SET categoria = 'contabil' "
                        "WHERE (categoria IS NULL OR categoria = '') AND cnae IN ('6920601', '6920602')"))
    except Exception:  # noqa: BLE001 - tabela ainda não existe
        pass


# ---------------------------------------------------------------- Consultas

def resumo(db) -> dict:
    try:
        total = db.execute(select(func.count()).select_from(EmpresaReceita)).scalar() or 0
    except Exception:  # noqa: BLE001 - tabela ainda não criada
        total = 0
    return {"total": total, "atualizada_em": ler_config(db, "receita_atualizada_em"),
            "status": ler_config(db, "receita_status")}


def disponivel(db) -> bool:
    return resumo(db)["total"] > 0


def contar(db, uf: str = "", cidade: str = "") -> dict[str, int]:
    """Quantidade de empresas ativas (matrizes) por categoria: Brasil, UF ou cidade."""
    consulta = select(EmpresaReceita.categoria, func.count()).where(EmpresaReceita.matriz == 1)
    if uf:
        consulta = consulta.where(EmpresaReceita.uf == uf)
    if cidade:
        consulta = consulta.where(EmpresaReceita.municipio_chave == util.chave_texto(cidade))
    try:
        return {c or "": n for c, n in db.execute(consulta.group_by(EmpresaReceita.categoria)).all()}
    except Exception:  # noqa: BLE001
        return {}


def buscar(db, cidade: str, uf: str, limite: int, categorias: list[str] | None = None,
           so_matriz: bool = True) -> list[dict]:
    """Empresas da cidade (das categorias pedidas): primeiro as que têm no nome as palavras da categoria
    (ex.: "condom" em administradoras), depois as com mais contatos e as mais antigas."""
    from .modelos import Categoria

    palavras = []
    if categorias:
        for c in db.execute(select(Categoria).where(Categoria.codigo.in_(categorias))).scalars():
            palavras += [util.chave_texto(p) for p in c.lista("palavras_chave")]
    consulta = select(EmpresaReceita).where(EmpresaReceita.uf == uf)
    if cidade:
        chave = util.chave_texto(cidade)
        existe = db.execute(select(EmpresaReceita.cnpj).where(EmpresaReceita.uf == uf,
                                                              EmpresaReceita.municipio_chave == chave).limit(1)).first()
        if existe:
            consulta = consulta.where(EmpresaReceita.municipio_chave == chave)
        else:  # não é uma cidade do estado: procura como bairro (ex.: "Boa Viagem", em Recife)
            consulta = consulta.where(EmpresaReceita.bairro.ilike(cidade.strip()))
    if categorias:
        consulta = consulta.where(EmpresaReceita.categoria.in_(categorias))
    if so_matriz:
        consulta = consulta.where(EmpresaReceita.matriz == 1)
    if palavras:
        from sqlalchemy import or_

        filtro = or_(*[EmpresaReceita.nome_fantasia.ilike(f"%{p}%") for p in palavras],
                     *[EmpresaReceita.razao_social.ilike(f"%{p}%") for p in palavras])
        primeiro = db.execute(consulta.where(filtro).limit(max(limite * 10, 100))).scalars().all()
        resto = db.execute(consulta.where(~filtro).limit(max(limite * 10, 100))).scalars().all()
        linhas = list(primeiro) + list(resto)
    else:
        linhas = db.execute(consulta.limit(max(limite * 20, 200))).scalars().all()

    def ordem(e):
        nome = util.chave_texto(f"{e.nome_fantasia} {e.razao_social}")
        return (0 if any(p in nome for p in palavras) else 1,
                -(bool(e.email) + bool(e.telefone) + bool(e.telefone2)), e.inicio_atividade or datetime.max.date())

    linhas = sorted(linhas, key=ordem)
    resultados = []
    for e in linhas[: limite * 3]:
        celular = next((t for t in (e.telefone, e.telefone2) if len(t) == 11 and t[2] == "9"), "")
        resultados.append({
            "empresa": e.nome_fantasia or e.razao_social or f"Empresa CNPJ {util.formatar_cnpj(e.cnpj)}",
            "cnpj": e.cnpj, "telefone": e.telefone or e.telefone2,
            "whatsapp": "",  # celular informado à Receita não garante WhatsApp: o vendedor confirma
            "email": e.email, "endereco": ", ".join(x for x in (e.endereco, e.bairro, e.cep) if x),
            "cidade": e.municipio, "estado": e.uf, "porte": e.porte, "categoria": e.categoria or "outros",
            # Responsável e regime vêm do quadro de sócios e do Simples (dados públicos da Receita)
            "responsavel": e.socio_admin, "cargo": e.socio_cargo, "regime": e.regime,
            "multiplos_socios": (e.socios_qtd or 0) > 1,
            "observacoes": (f"Celular informado à Receita: {util.formatar_telefone(celular)} (confirmar se é WhatsApp). "
                            if celular else "") + (f"Em atividade desde {e.inicio_atividade:%Y}." if e.inicio_atividade else ""),
            "fonte_url": f"https://brasilapi.com.br/api/cnpj/v1/{e.cnpj}",
            "origem": "Prospecção: base da Receita Federal",
        })
    return resultados
