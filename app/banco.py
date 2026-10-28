"""Conexão com o banco (SQLite local ou PostgreSQL em produção) e configurações gravadas no banco."""

import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


_opcoes = {}
if config.DATABASE_URL.startswith("sqlite"):
    _opcoes["connect_args"] = {"check_same_thread": False, "timeout": 30}

else:
    # Na nuvem cada cópia do sistema abre poucas conexões (use o endereço "pooled" do Neon/Supabase).
    # Sem "prepared statements": o pooler do Supabase (porta 6543, modo transação) não aceita.
    _opcoes.update(pool_size=3, max_overflow=5, pool_recycle=300, connect_args={"prepare_threshold": None})

motor = create_engine(config.DATABASE_URL, pool_pre_ping=True, **_opcoes)

if config.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(motor, "connect")
    def _ajustar_sqlite(conexao, _):
        cur = conexao.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

FabricaSessao = sessionmaker(bind=motor, expire_on_commit=False)


def obter_db():
    """Dependência do FastAPI: uma sessão do banco por pedido."""
    db = FabricaSessao()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def sessao():
    """Para rotinas fora das telas (tarefas em segundo plano, scripts)."""
    db = FabricaSessao()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def agora() -> datetime:
    return datetime.now().replace(microsecond=0)


# ---------------------------------------------------------------- Configurações no banco

def ler_config(db: Session, chave: str) -> str:
    from .modelos import Configuracao

    item = db.get(Configuracao, chave)
    if item is not None:
        return item.valor
    return config.CONFIG_PADRAO.get(chave, "")


def ler_config_int(db: Session, chave: str, padrao: int = 0) -> int:
    try:
        return int(float(ler_config(db, chave)))
    except ValueError:
        return padrao


def ler_config_json(db: Session, chave: str, padrao):
    texto = ler_config(db, chave)
    if not texto:
        return padrao
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return padrao


def gravar_config(db: Session, chave: str, valor) -> None:
    from .modelos import Configuracao

    if not isinstance(valor, str):
        valor = json.dumps(valor, ensure_ascii=False)
    item = db.get(Configuracao, chave)
    if item is None:
        db.add(Configuracao(chave=chave, valor=valor))
    else:
        item.valor = valor


def _valor_padrao_sql(coluna) -> str:
    padrao = coluna.default.arg if coluna.default is not None and not callable(coluna.default.arg) else None
    if padrao is None:
        return ""
    if isinstance(padrao, bool):
        return f" DEFAULT {int(padrao)}" if motor.dialect.name == "sqlite" else f" DEFAULT {str(padrao).upper()}"
    if isinstance(padrao, (int, float)):
        return f" DEFAULT {padrao}"
    return " DEFAULT '" + str(padrao).replace("'", "''") + "'"


def migrar_colunas() -> list[str]:
    """Acrescenta nas tabelas existentes as colunas novas do código (atualização de versão sem perder dados)."""
    from sqlalchemy import inspect, text

    inspetor = inspect(motor)
    adicionadas = []
    with motor.begin() as con:
        for tabela in Base.metadata.tables.values():
            if not inspetor.has_table(tabela.name):
                continue
            existentes = {c["name"] for c in inspetor.get_columns(tabela.name)}
            for coluna in tabela.columns:
                if coluna.name in existentes:
                    continue
                tipo = coluna.type.compile(dialect=motor.dialect)
                con.execute(text(f'ALTER TABLE {tabela.name} ADD COLUMN "{coluna.name}" {tipo}{_valor_padrao_sql(coluna)}'))
                adicionadas.append(f"{tabela.name}.{coluna.name}")
    return adicionadas


def migrar_status(db: Session) -> int:
    """Status da versão 1 do CRM → status do CRM da IA SDR."""
    from .modelos import Lead

    total = 0
    for antigo, (novo, motivo) in config.MIGRACAO_STATUS.items():
        for lead in db.execute(select(Lead).where(Lead.status == antigo)).scalars():
            lead.status = novo
            if motivo and not lead.motivo_perda:
                lead.motivo_perda = motivo
            total += 1
    return total


def criar_tabelas() -> None:
    from . import base_receita, modelos  # noqa: F401  (registra as tabelas)

    Base.metadata.create_all(motor)
    migrar_colunas()
    with sessao() as db:
        modelos.dados_iniciais(db)
        migrar_status(db)
        base_receita.ajustar_base_antiga(db)


_banco_pronto = False
_trava_preparo = threading.Lock()


def _versao_do_esquema() -> str:
    from . import base_receita, modelos  # noqa: F401

    from . import config, modelos_segmento

    partes = sorted(f"{t.name}.{c.name}" for t in Base.metadata.tables.values() for c in t.columns)
    # dados padrão também contam: segmento ou modelo novo faz a nuvem preparar o banco de novo
    partes += [c["codigo"] for c in config.CATEGORIAS_PADRAO] + sorted(modelos_segmento.SEGMENTOS)
    return hashlib.sha256("|".join(partes).encode()).hexdigest()[:16]


def proteger_tabelas() -> int:
    """Supabase: liga o RLS (sem regras = ninguém entra) e tira o acesso das chaves públicas (anon/authenticated) em
    todas as tabelas. O sistema entra como dono do banco, que não depende do RLS. Devolve quantas tabelas viu."""
    if not config.DATABASE_URL.startswith("postgres"):
        return 0
    with motor.begin() as con:
        tabelas = [t for (t,) in con.exec_driver_sql(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
        papeis = {r for (r,) in con.exec_driver_sql(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")}
        for t in tabelas:
            con.exec_driver_sql(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY')
            for papel in papeis:
                con.exec_driver_sql(f'REVOKE ALL ON public."{t}" FROM {papel}')
        for papel in papeis:  # tabelas criadas no futuro também nascem fechadas para as chaves públicas
            con.exec_driver_sql(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {papel}")
            con.exec_driver_sql(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {papel}")
            con.exec_driver_sql(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {papel}")
    return len(tabelas)


def preparar_banco_na_nuvem() -> None:
    """Na nuvem: cria/atualiza as tabelas uma vez por versão do sistema (e não a cada cópia que liga)."""
    global _banco_pronto
    if _banco_pronto:
        return
    with _trava_preparo:
        if _banco_pronto:
            return
        versao = _versao_do_esquema()
        try:
            with sessao() as db:
                pronta = ler_config(db, "versao_esquema") == versao
        except Exception:  # noqa: BLE001 - banco novo, ainda sem tabelas
            pronta = False
        if not pronta:
            criar_tabelas()
            proteger_tabelas()
            with sessao() as db:
                gravar_config(db, "versao_esquema", versao)
        _banco_pronto = True


def primeiro(db: Session, consulta):
    return db.execute(consulta).scalars().first()


def todos(db: Session, consulta):
    return list(db.execute(consulta).scalars().all())


__all__ = ["Base", "motor", "obter_db", "sessao", "agora", "ler_config", "gravar_config", "select"]
