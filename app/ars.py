"""ARs (marcas) da plataforma white label — Fase 1: a AR entra nos dados (docs/white-label.md).

Cada linha das 36 tabelas da AR ganha a coluna tenant_id (modelos.DaAR). Aqui ficam:
- as duas ARs de hoje (AR MS Certificados e Grupo Certy) e a AR de cada pessoa (pela "empresa representada");
- as regras de preenchimento, tabela por tabela: a linha vai para a AR de quem é dono dela (lead → vendedor,
  campanha → quem criou, conversa → o número, histórico → o lead...);
- `preencher` (só onde está vazio, em lotes), `contagem` (quantas linhas em cada AR) e `conferir` (nenhuma linha
  sem AR, nenhuma ligação cruzando ARs).
Até a Fase 2 ninguém lê o tenant_id: telas, filas e envios funcionam como antes. Quem roda a migração é o
migrar_ar.py (primeiro no banco de teste); depois disso a rotina de hora em hora preenche as linhas novas.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select, text

log = logging.getLogger(__name__)

AR_MS, AR_CERTY = "ms", "grupo-certy"
ARS_INICIAIS = {AR_MS: "AR MS Certificados", AR_CERTY: "Grupo Certy"}

# Decididas em 14/11/2026 ("sim, vão para AR MS; leads sem dono também"):
PADRAO = {"do_master": AR_MS,   # os 381 leads e as 29 campanhas do Paulo Marinho (Admin Master)
          "sem_dono": AR_MS}    # os 237 leads sem vendedor (e o que não tem dono nenhum)

LIGADO = "ar_preenchimento"  # configuração gravada pelo migrar_ar.py: liga o preenchimento de hora em hora
LOTE = 5000
GRANDES = {"mensagens_whatsapp", "historico", "tarefas"}  # depois de preencher, VACUUM no Postgres

# As 36 tabelas com tenant_id. "obrigatoria": toda linha precisa de AR. "condicional": vazio só em casos
# permitidos (Admin Master, papel do sistema). "plataforma": vazio = modelo da plataforma (até a Fase 2).
OBRIGATORIAS = ["equipes", "leads", "historico", "oportunidades", "campanhas", "certificados", "parceiros",
                "clientes", "produtos", "vendas", "tarefas", "mensagens", "buscas", "buscas_cnpja",
                "buscas_cnpja_empresas", "visuais_campanha", "visuais_arquivos", "conexoes_whatsapp",
                "contas_email", "mensagens_whatsapp", "contatos_whatsapp", "ponte_whatsapp", "artes_aviso",
                "comandos_whatsapp", "trabalhos", "base_conhecimento"]
CONDICIONAIS = {
    "usuarios": "tenant_id IS NULL AND master = FALSE",
    "papeis": "tenant_id IS NULL AND sistema = FALSE",
    "permissoes_papel": "tenant_id IS NULL AND papel_id IN (SELECT id FROM papeis WHERE sistema = FALSE)",
    "excecoes_permissao": "tenant_id IS NULL AND usuario_id NOT IN (SELECT id FROM usuarios WHERE master = TRUE)",
    "notificacoes": "tenant_id IS NULL AND usuario_id NOT IN (SELECT id FROM usuarios WHERE master = TRUE)",
    "logs": ("tenant_id IS NULL AND usuario_id IS NOT NULL "
             "AND usuario_id NOT IN (SELECT id FROM usuarios WHERE master = TRUE)"),
}
PLATAFORMA = ["templates", "cadencias", "passos_cadencia", "configuracoes"]
TABELAS = OBRIGATORIAS + list(CONDICIONAIS) + PLATAFORMA
SEM_ID = {"conexoes_whatsapp", "contatos_whatsapp", "configuracoes"}  # chave que não é número: sem lotes

# Ligações que não podem cruzar ARs (filho, coluna, pai)
LIGACOES = [("historico", "lead_id", "leads"), ("oportunidades", "lead_id", "leads"),
            ("tarefas", "lead_id", "leads"), ("tarefas", "campanha_id", "campanhas"),
            ("mensagens", "lead_id", "leads"), ("mensagens", "campanha_id", "campanhas"),
            ("certificados", "campanha_id", "campanhas"), ("buscas_cnpja_empresas", "busca_id", "buscas_cnpja"),
            ("visuais_arquivos", "visual_id", "visuais_campanha"), ("clientes", "parceiro_id", "parceiros"),
            ("vendas", "cliente_id", "clientes"), ("leads", "vendedor_id", "usuarios"),
            ("campanhas", "usuario_id", "usuarios"), ("excecoes_permissao", "usuario_id", "usuarios")]


def slug_da_pessoa(empresa_nome: str | None, email: str | None) -> str:
    """A AR de quem não é o Admin Master: Grupo Certy pela empresa representada (ou e-mail do Grupo); senão, a MS."""
    if "certy" in (empresa_nome or "").lower() or "grupocerty" in (email or "").lower():
        return AR_CERTY
    return AR_MS


def garantir_ars(con) -> dict[str, int]:
    """Cria as ARs de hoje se faltarem. Devolve {slug: id}."""
    from .banco import agora

    for slug, nome in ARS_INICIAIS.items():
        if con.execute(text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug}).first() is None:
            con.execute(text("INSERT INTO tenants (slug, nome, cnpj, situacao, plano, criado_em) "
                             "VALUES (:s, :n, '', 'ativa', '', :c)"), {"s": slug, "n": nome, "c": agora()})
    return {slug: id_ for id_, slug in con.execute(text("SELECT id, slug FROM tenants"))}


# ---------------------------------------------------------------- Expressões SQL das regras

def _caso(coluna: str, mapa: dict, senao: str) -> str:
    """CASE <coluna> WHEN <chave> THEN <ar> ... ELSE <senao> END (chaves numéricas ou textos)."""
    partes = []
    for chave, ar in mapa.items():
        if ar is None:
            continue
        valor = str(int(chave)) if isinstance(chave, int) else "'" + str(chave).replace("'", "''") + "'"
        partes.append(f"WHEN {valor} THEN {int(ar)}")
    return f"CASE {coluna} {' '.join(partes)} ELSE {senao} END" if partes else senao


def _pai(pai: str, coluna: str, filho: str) -> str:
    return f"(SELECT p.tenant_id FROM {pai} p WHERE p.id = {filho}.{coluna})"


def _atualizar(con, tabela: str, expressao: str, gravar: bool) -> None:
    """Preenche o tenant_id vazio da tabela com a expressão, em lotes de ids (gravando a cada lote)."""
    base = (f"UPDATE {tabela} SET tenant_id = ({expressao}) "
            f"WHERE tenant_id IS NULL AND ({expressao}) IS NOT NULL")
    if tabela in SEM_ID:
        con.execute(text(base))
        if gravar:
            con.commit()
        return
    menor, maior = con.execute(text(f"SELECT MIN(id), MAX(id) FROM {tabela} WHERE tenant_id IS NULL")).one()
    if menor is None:
        return
    inicio = menor - 1
    while inicio < maior:
        con.execute(text(base + " AND id > :a AND id <= :b"), {"a": inicio, "b": inicio + LOTE})
        if gravar:
            con.commit()  # lotes pequenos: o Supabase não devolve o espaço de alterações grandes
        inicio += LOTE


def preencher(con, decisoes: dict | None = None, gravar: bool = True, limpar: bool = False) -> dict[str, int]:
    """Põe a AR em toda linha que ainda não tem, tabela por tabela, na ordem das dependências. Não mexe no que já
    tem AR. `gravar=False` não faz commit (o ensaio desfaz tudo no fim). Devolve {slug: id} das ARs."""
    d = {**PADRAO, **(decisoes or {})}
    ids = garantir_ars(con)
    ms, do_master, sem_dono = ids[AR_MS], ids[d["do_master"]], ids[d["sem_dono"]]

    # 1. Pessoas: a AR pela empresa representada; o Admin Master é da plataforma (fica vazio)
    pessoa: dict[int, int | None] = {}   # a AR da própria pessoa
    dono: dict[int, int | None] = {}     # a AR das coisas de que a pessoa é dona (as do Master: decisão)
    for uid, master, empresa, email, atual in con.execute(text(
            "SELECT id, master, empresa_nome, email, tenant_id FROM usuarios")).all():
        alvo = atual if atual is not None else (None if master else ids[slug_da_pessoa(empresa, email)])
        if atual is None and alvo is not None:
            con.execute(text("UPDATE usuarios SET tenant_id = :t WHERE id = :i"), {"t": alvo, "i": uid})
        pessoa[uid] = alvo
        dono[uid] = do_master if master and alvo is None else alvo
    if gravar:
        con.commit()
    de_quem = lambda col, senao: _caso(col, dono, senao)  # noqa: E731
    da_pessoa = lambda col: _caso(col, pessoa, "NULL")  # noqa: E731

    regras = [
        ("equipes", f"COALESCE((SELECT MIN(u.tenant_id) FROM usuarios u WHERE u.equipe_id = equipes.id), {ms})"),
        ("papeis", f"CASE WHEN sistema = TRUE THEN NULL ELSE {ms} END"),
        ("permissoes_papel", _pai("papeis", "papel_id", "permissoes_papel")),
        ("excecoes_permissao", da_pessoa("usuario_id")),
        ("leads", f"CASE WHEN vendedor_id IS NULL THEN {sem_dono} ELSE {de_quem('vendedor_id', str(sem_dono))} END"),
        ("historico", _pai("leads", "lead_id", "historico")),
        ("oportunidades", _pai("leads", "lead_id", "oportunidades")),
        ("notificacoes", da_pessoa("usuario_id")),
        ("campanhas", f"CASE WHEN tipo = 'renovacao' THEN {ms} WHEN usuario_id IS NULL THEN {sem_dono} "
                      f"ELSE {de_quem('usuario_id', str(sem_dono))} END"),
        ("certificados", f"COALESCE({_pai('campanhas', 'campanha_id', 'certificados')}, "
                         f"{_pai('leads', 'lead_id', 'certificados')}, {ms})"),
        ("parceiros", f"COALESCE({de_quem('vendedor_id', 'NULL')}, {ms})"),
        ("clientes", f"COALESCE({_pai('parceiros', 'parceiro_id', 'clientes')}, {ms})"),
        ("produtos", str(ms)),
        ("vendas", f"COALESCE({_pai('clientes', 'cliente_id', 'vendas')}, {de_quem('vendedor_id', 'NULL')}, {ms})"),
        ("tarefas", f"COALESCE({_pai('leads', 'lead_id', 'tarefas')}, {_pai('campanhas', 'campanha_id', 'tarefas')}, "
                    f"{_pai('certificados', 'certificado_id', 'tarefas')}, {_pai('clientes', 'cliente_id', 'tarefas')}, "
                    f"{de_quem('usuario_id', 'NULL')}, {sem_dono})"),
        ("mensagens", f"COALESCE({_pai('leads', 'lead_id', 'mensagens')}, "
                      f"{_pai('campanhas', 'campanha_id', 'mensagens')}, {de_quem('usuario_id', 'NULL')}, {sem_dono})"),
        ("buscas", f"CASE WHEN usuario_id IS NULL THEN {sem_dono} ELSE {de_quem('usuario_id', str(sem_dono))} END"),
        ("buscas_cnpja", f"COALESCE({_pai('campanhas', 'campanha_id', 'buscas_cnpja')}, "
                         f"{de_quem('usuario_id', 'NULL')}, {ms})"),
        ("buscas_cnpja_empresas", _pai("buscas_cnpja", "busca_id", "buscas_cnpja_empresas")),
        ("visuais_campanha", f"COALESCE({de_quem('usuario_id', 'NULL')}, {ms})"),
        ("visuais_arquivos", _pai("visuais_campanha", "visual_id", "visuais_arquivos")),
        ("conexoes_whatsapp", f"COALESCE({de_quem('dono_id', 'NULL')}, {ms})"),
        ("contas_email", f"CASE WHEN principal = TRUE THEN {ms} ELSE COALESCE({de_quem('dono_id', 'NULL')}, {ms}) END"),
    ]
    for tabela, expressao in regras:
        _atualizar(con, tabela, expressao, gravar)

    # 2. WhatsApp: cada conversa e cada mensagem da ponte ficam com a AR do número por onde passaram
    numeros = {cid: t for cid, t in con.execute(text("SELECT id, tenant_id FROM conexoes_whatsapp"))}
    do_numero = lambda col: _caso(col, numeros, "NULL")  # noqa: E731
    regras = [
        ("mensagens_whatsapp", f"COALESCE({do_numero('conexao')}, {ms})"),
        ("contatos_whatsapp", "COALESCE((SELECT m.tenant_id FROM mensagens_whatsapp m WHERE m.telefone = "
                              f"contatos_whatsapp.telefone ORDER BY m.id DESC LIMIT 1), {ms})"),
        ("ponte_whatsapp", f"COALESCE({do_numero('conexao')}, {de_quem('usuario_id', 'NULL')}, {ms})"),
        ("artes_aviso", f"COALESCE({_pai('ponte_whatsapp', 'ponte_id', 'artes_aviso')}, "
                        f"{_pai('tarefas', 'tarefa_id', 'artes_aviso')}, {ms})"),
        ("comandos_whatsapp", f"COALESCE({de_quem('usuario_id', 'NULL')}, {ms})"),
        ("trabalhos", "COALESCE(CASE WHEN tipo IN ('campanha', 'personalizar') THEN (SELECT c.tenant_id FROM "
                      "campanhas c WHERE c.id = trabalhos.ref_id) WHEN tipo = 'busca' THEN (SELECT b.tenant_id FROM "
                      f"buscas b WHERE b.id = trabalhos.ref_id) END, {de_quem('usuario_id', 'NULL')}, {ms})"),
        ("base_conhecimento", str(ms)),
        ("logs", da_pessoa("usuario_id")),
    ]
    for tabela, expressao in regras:
        _atualizar(con, tabela, expressao, gravar)
    if gravar and limpar and con.dialect.name == "postgresql":
        _limpar(con, GRANDES)
    return ids


def _limpar(con, tabelas) -> None:
    """VACUUM depois de muitas alterações (o espaço das linhas antigas volta a ser usado pela tabela)."""
    try:
        with con.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as livre:
            for t in tabelas:
                livre.exec_driver_sql(f"VACUUM (ANALYZE) {t}")
    except Exception:  # noqa: BLE001 - a limpeza é um extra: o autovacuum do Postgres faz o mesmo depois
        log.warning("VACUUM depois do preenchimento não rodou (o autovacuum cuida disso)", exc_info=True)


# ---------------------------------------------------------------- Contagem e conferência

def contagem(con) -> dict[str, dict[str, int]]:
    """{tabela: {slug da AR ou "plataforma": quantas linhas}} das 36 tabelas."""
    nomes = {id_: slug for id_, slug in con.execute(text("SELECT id, slug FROM tenants"))}
    resultado = {}
    for t in TABELAS:
        resultado[t] = {(nomes.get(ar, f"AR {ar}") if ar is not None else "plataforma"): n
                        for ar, n in con.execute(text(f"SELECT tenant_id, COUNT(*) FROM {t} GROUP BY tenant_id"))}
    return resultado


def conferir(con) -> dict:
    """O portão da Fase 1: nenhuma linha sem AR (onde ela é obrigatória) e nenhuma ligação cruzando ARs."""
    sem_ar = {}
    for t in OBRIGATORIAS:
        n = con.execute(text(f"SELECT COUNT(*) FROM {t} WHERE tenant_id IS NULL")).scalar() or 0
        if n:
            sem_ar[t] = n
    for t, condicao in CONDICIONAIS.items():
        n = con.execute(text(f"SELECT COUNT(*) FROM {t} WHERE {condicao}")).scalar() or 0
        if n:
            sem_ar[t] = n
    cruzadas = {}
    for filho, coluna, pai in LIGACOES:
        n = con.execute(text(
            f"SELECT COUNT(*) FROM {filho} f JOIN {pai} p ON p.id = f.{coluna} WHERE f.tenant_id IS NOT NULL "
            "AND p.tenant_id IS NOT NULL AND f.tenant_id <> p.tenant_id")).scalar() or 0
        if n:
            cruzadas[f"{filho}.{coluna} → {pai}"] = n
    return {"sem_ar": sem_ar, "cruzadas": cruzadas, "ok": not sem_ar and not cruzadas}


# ---------------------------------------------------------------- Depois da migração: as linhas novas

def preencher_novos() -> bool:
    """Rotina de hora em hora: depois que o migrar_ar.py aplicou a migração (configuração `ar_preenchimento`),
    põe a AR nas linhas criadas desde então. Até a Fase 2 é assim que as linhas novas ganham AR."""
    from .banco import motor

    with motor.connect() as con:
        ligado = con.execute(text("SELECT valor FROM configuracoes WHERE chave = :c"), {"c": LIGADO}).scalar()
        if not ligado:
            return False
        try:
            decisoes = json.loads(ligado)
        except ValueError:
            decisoes = {}
        preencher(con, {k: v for k, v in decisoes.items() if k in PADRAO}, gravar=True)
        con.commit()
    return True


# ---------------------------------------------------------------- Fase 6 (LGPD): exportar e apagar uma AR

def _tabelas_da_ar():
    """As tabelas com a coluna da AR, na ordem das dependências (as 36 + configurações e entradas do Admin Master)."""
    from .banco import Base
    from . import base_receita, bases_importadas, modelos  # noqa: F401  (registra as tabelas)

    return [t for t in Base.metadata.sorted_tables if "tenant_id" in t.c]


def exportar(origem, ar_id: int, destino) -> dict[str, int]:
    """Copia para o banco `destino` (um SQLite novo) SÓ as linhas da AR: as tabelas dela, a própria AR, as
    configurações e as entradas do Admin Master nela. É o que a AR recebe quando pede os dados ou sai da plataforma
    (LGPD: a AR é a controladora dos dados). Nada da plataforma nem de outra AR vai junto."""
    from .banco import Base
    from .modelos import Tenant

    Base.metadata.create_all(destino)
    contagem = {}
    with origem.connect() as o, destino.begin() as d:
        ar = [dict(r._mapping) for r in o.execute(select(Tenant.__table__).where(Tenant.id == ar_id))]
        if not ar:
            raise ValueError(f"AR {ar_id} não existe")
        d.execute(Tenant.__table__.insert(), ar)
        for t in _tabelas_da_ar():
            linhas = [dict(r._mapping) for r in o.execute(select(t).where(t.c.tenant_id == ar_id))]
            if linhas:
                d.execute(t.insert(), linhas)
            contagem[t.name] = len(linhas)
    return contagem


# ligações em ciclo dentro da AR (lead ↔ busca ↔ pessoa ↔ parceiro): desfeitas antes de apagar
CICLOS = (("leads", "busca_id"), ("leads", "parceiro_id"), ("parceiros", "lead_id"), ("usuarios", "parceiro_id"),
          ("usuarios", "papel_id"), ("usuarios", "equipe_id"))


def apagar(con, ar_id: int) -> dict[str, int]:
    """Apaga TODAS as linhas da AR e a própria AR (Fase 6, LGPD). Não toca nas outras ARs nem no que é da plataforma
    (só linhas com tenant_id = ar_id). Quem chama faz o commit (o apagar_ar.py, depois de exportar e confirmar)."""
    for tabela, coluna in CICLOS:
        con.execute(text(f"UPDATE {tabela} SET {coluna} = NULL WHERE tenant_id = :ar"), {"ar": ar_id})
    # filhos antes dos pais; as tabelas do ciclo por último, nesta ordem (a ordenação automática não dá conta do ciclo)
    fim = ("leads", "buscas", "parceiros", "usuarios")
    tabelas = _tabelas_da_ar()
    por_nome = {t.name: t for t in tabelas}
    ordem = [t for t in reversed(tabelas) if t.name not in fim] + [por_nome[n] for n in fim]
    contagem = {}
    for t in ordem:
        contagem[t.name] = con.execute(t.delete().where(t.c.tenant_id == ar_id)).rowcount or 0
    con.execute(text("DELETE FROM tenants WHERE id = :ar"), {"ar": ar_id})
    return contagem
