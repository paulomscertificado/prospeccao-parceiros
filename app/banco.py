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

# White label, Fase 2 parte 2: as configurações que cada AR tem as suas (documento do plano, "Configurações: plataforma,
# AR ou pessoa"). Sem valor próprio, a AR usa o da plataforma. As outras chaves são da plataforma: só o Admin Master
# muda (proteção dos números, alertas, módulos, base da Receita, estado da ponte...). Renovação e Empresas novas ficam
# da plataforma até as decisões da CNPJá e da planilha por AR.
CHAVES_DA_AR = frozenset({
    "empresa_nome", "link_parceria", "texto_comissao", "programa_parceria", "limite_diario_whatsapp",
    "limite_diario_email", "horas_entre_contatos_whatsapp", "horas_entre_contatos_email", "pular_fim_de_semana",
    "alertas_vencimento", "dias_parceiro_parado", "dias_lead_parado", "dias_retencao_perdidos", "prioridade_canais",
    "limite_hora_email", "limite_hora_whatsapp", "limite_diario_campanha", "limite_diario_dominio",
    "horario_envio_inicio", "horario_envio_fim", "enviar_email_automatico", "sdr_resposta_automatica",
    "dias_sem_resposta", "enviar_whatsapp_automatico", "whatsapp_sozinho_padrao", "whatsapp_convite",
    "notificar_por_email", "score_pesos", "score_faixas", "receita_oculta"})


def _ar_da_config(db: Session) -> int | None:
    """A AR cujas configurações valem agora: a que a rotina escolheu (usar_config_da_ar) ou a da pessoa da tela."""
    if "ar_config" in db.info:
        return db.info["ar_config"]
    if db.info.get("ar_ligado"):
        ar = db.info.get("ar")
        return ar if ar and ar > 0 else None
    return None


def usar_config_da_ar(db: Session, ar: int | None) -> None:
    """Rotinas (filas, respostas): daqui em diante as configurações lidas nesta sessão são as da AR `ar` (a do registro
    que está sendo tratado). None = volta ao normal."""
    if ar is None:
        db.info.pop("ar_config", None)
    else:
        db.info["ar_config"] = ar


def algum_valor(db: Session, chave: str, valor: str) -> bool:
    """A plataforma ou alguma AR usa este valor? (filas: só param de vez se nenhuma AR quer o envio)"""
    from .modelos import ConfiguracaoAR

    anterior = db.info.pop("ar_config", None)
    try:
        if ler_config(db, chave) == valor:
            return True
    finally:
        if anterior is not None:
            db.info["ar_config"] = anterior
    return db.execute(select(ConfiguracaoAR.tenant_id).where(ConfiguracaoAR.chave == chave,
                                                             ConfiguracaoAR.valor == valor).limit(1)).first() is not None


def _valores_da_ar(db: Session, ar: int) -> dict:
    """Os valores próprios da AR, lidos UMA vez por sessão (cada tela abre a sua): sem isso, cada leitura de
    configuração da AR seria uma consulta a mais (tráfego do Supabase)."""
    cache = db.info.setdefault("config_ar", {})
    if ar not in cache:
        from .modelos import ConfiguracaoAR

        cache[ar] = dict(db.execute(select(ConfiguracaoAR.chave, ConfiguracaoAR.valor)
                                    .where(ConfiguracaoAR.tenant_id == ar)).all())
    return cache[ar]


def ler_config(db: Session, chave: str) -> str:
    from .modelos import Configuracao

    if chave in CHAVES_DA_AR:
        ar = _ar_da_config(db)
        if ar:
            valores = _valores_da_ar(db, ar)
            if chave in valores:
                return valores[chave]
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
    from .modelos import Configuracao, ConfiguracaoAR

    if not isinstance(valor, str):
        valor = json.dumps(valor, ensure_ascii=False)
    if chave in CHAVES_DA_AR:
        ar = _ar_da_config(db)
        if ar:  # pessoa de uma AR (ou rotina tratando um registro da AR): o valor fica só nela
            proprio = db.get(ConfiguracaoAR, (ar, chave))
            if proprio is None:
                db.add(ConfiguracaoAR(tenant_id=ar, chave=chave, valor=valor))
            else:
                proprio.valor = valor
            if ar in db.info.get("config_ar", {}):
                db.info["config_ar"][ar][chave] = valor
            return
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
        if motor.dialect.name == "postgresql":
            # várias cópias da nuvem sobem juntas depois de uma publicação: uma migra por vez, as outras esperam
            con.execute(text("SELECT pg_advisory_xact_lock(724501)"))
            inspetor = inspect(con)
        for tabela in Base.metadata.tables.values():
            if not inspetor.has_table(tabela.name):
                continue
            existentes = {c["name"] for c in inspetor.get_columns(tabela.name)}
            for coluna in tabela.columns:
                if coluna.name in existentes:
                    continue
                tipo = coluna.type.compile(dialect=motor.dialect)
                # Postgres: IF NOT EXISTS evita erro quando duas cópias na nuvem migram ao mesmo tempo
                se_nao_existe = "IF NOT EXISTS " if motor.dialect.name == "postgresql" else ""
                con.execute(text(f'ALTER TABLE {tabela.name} ADD COLUMN {se_nao_existe}"{coluna.name}" {tipo}'
                                 f'{_valor_padrao_sql(coluna)}'))
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


def migrar_conversas_com_nono(db: Session) -> int:
    """Cópia das conversas do WhatsApp: celular guardado sem o 9 (como o WhatsApp entrega os números antigos)
    passa a ter o 9, igual ao que se digita na tela Conversas (util.com_nono_digito). Sem isso, a mensagem enviada
    pela tela ia para outra conversa e não aparecia. Pode rodar de novo: só mexe no que ainda está sem o 9."""
    from sqlalchemy import text

    from .modelos import ContatoWhatsApp

    sem_nove = "length(telefone) = 10 AND substr(telefone, 3, 1) IN ('6', '7', '8', '9')"
    total = db.execute(text("UPDATE mensagens_whatsapp SET telefone = substr(telefone, 1, 2) || '9' || "
                            f"substr(telefone, 3) WHERE {sem_nove}")).rowcount or 0
    for contato in db.execute(select(ContatoWhatsApp).where(text(sem_nove))).scalars().all():
        novo = contato.telefone[:2] + "9" + contato.telefone[2:]
        existente = db.get(ContatoWhatsApp, novo)
        if existente is None:
            db.add(ContatoWhatsApp(telefone=novo, nome=contato.nome, atualizado_em=contato.atualizado_em))
        elif not existente.nome:
            existente.nome = contato.nome
        db.delete(contato)
    return total


def criar_tabelas() -> None:
    from . import base_receita, bases_importadas, modelos  # noqa: F401  (registra as tabelas)

    if motor.dialect.name == "postgresql":
        from sqlalchemy import text

        # várias cópias da nuvem sobem juntas: uma cria as tabelas novas por vez (senão "already exists")
        with motor.begin() as con:
            con.execute(text("SELECT pg_advisory_xact_lock(724501)"))
            Base.metadata.create_all(con)
    else:
        Base.metadata.create_all(motor)
    migrar_colunas()
    from . import ars

    with motor.begin() as con:  # white label: as ARs de hoje existem desde o início (isolamento.py)
        ars.garantir_ars(con)
    with sessao() as db:
        if motor.dialect.name == "postgresql":
            from sqlalchemy import text

            # uma cópia da nuvem por vez cria os dados iniciais (antes duas juntas criaram cadências em dobro)
            db.execute(text("SELECT pg_advisory_xact_lock(724502)"))
        modelos.dados_iniciais(db)
        from . import autorizacao

        autorizacao.preparar(db)
        migrar_status(db)
        base_receita.ajustar_base_antiga(db)
        migrar_conversas_com_nono(db)


_banco_pronto = False
_trava_preparo = threading.Lock()


def _versao_do_esquema() -> str:
    from . import base_receita, bases_importadas, modelos  # noqa: F401

    from . import config, modelos_segmento

    partes = sorted(f"{t.name}.{c.name}" for t in Base.metadata.tables.values() for c in t.columns)
    # dados padrão também contam: segmento ou modelo novo faz a nuvem preparar o banco de novo
    partes += [c["codigo"] for c in config.CATEGORIAS_PADRAO] + sorted(modelos_segmento.SEGMENTOS)
    from .autorizacao import CATALOGO

    partes += [f"{p.codigo}:{p.padrao}" for p in CATALOGO]  # permissão nova: a nuvem dá o padrão aos papéis
    partes += ["dados:conversas-com-nono"]  # ajuste de dados novo (migrar_conversas_com_nono): roda uma vez na nuvem
    partes += ["dados:cadencias-sem-repeticao"]  # modelos._remover_cadencias_repetidas: roda uma vez na nuvem
    from .modelos import CADENCIAS_SDR_EXTRAS

    partes += [f"cadencia:{nome}" for nome, _, _ in CADENCIAS_SDR_EXTRAS]  # cadência nova: a nuvem cria na publicação
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

from . import isolamento  # noqa: E402,F401  (registra o filtro e a AR das linhas novas)
