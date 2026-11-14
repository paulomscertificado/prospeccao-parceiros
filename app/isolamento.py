"""White label, Fase 2: cada AR vê e grava só o que é dela (docs/white-label.md).

Como funciona:
- Ao carregar o usuário logado (seguranca.usuario_logado), a sessão do banco da tela ganha a AR dele em
  `db.info["ar"]` (`ligar`). Admin Master: sem AR (vê a plataforma toda, até a Fase 3 trazer o "Entrar numa AR").
  Pessoa sem AR que não é o Admin Master: AR -1 (não vê nada: na dúvida, fecha).
- Toda consulta do ORM nessa sessão (listas, db.get, relações, update/delete do ORM) ganha o filtro da AR
  (`_filtrar`, evento do_orm_execute + with_loader_criteria). Tabelas com modelo da plataforma (vazio = de todos):
  a linha da AR OU a da plataforma.
- Tudo que é criado ganha a AR (`_ar_nas_novas`, evento before_flush): a da sessão; sem ela (rotinas, ponte do
  WhatsApp, Admin Master), a do registro "pai" (lead, campanha, número...) ou a do dono; sem nada, a AR MS (mesma regra
  da migração, app/ars.py). Rotinas e a ponte (sessões sem AR) continuam vendo tudo: trabalham para todas as ARs.
A rotina de hora em hora (ars.preencher_novos) segue como rede de segurança.
"""
from __future__ import annotations

import logging

from sqlalchemy import event, inspect, or_, select
from sqlalchemy.orm import Session, with_loader_criteria

log = logging.getLogger(__name__)

SEM_AR = -1  # pessoa sem AR (que não é o Admin Master): não enxerga nada
# Vazio = da plataforma, que todas as ARs veem (modelos, papéis do sistema, o Admin Master)
COM_PLATAFORMA = {"templates", "cadencias", "passos_cadencia", "papeis", "permissoes_papel", "usuarios"}
NUNCA = {"configuracoes"}  # chave única no sistema todo até a Fase 2b (configurações por AR): sem filtro e sem AR
SO_DA_PESSOA = {"notificacoes", "logs"}  # a AR da pessoa; a do Admin Master fica vazia
DA_CONEXAO = {"mensagens_whatsapp", "ponte_whatsapp"}  # a AR do número por onde passou

_ids_das_ars: dict[tuple, int] = {}
_cache_classes: list = []


def _do_sistema(db: Session) -> bool:
    """Só a sessão ligada ao banco do sistema (um banco à parte, como o dos testes da migração, fica de fora)."""
    from .banco import motor

    return getattr(db, "bind", None) is motor


def ligar(db: Session, usuario) -> None:
    """A sessão desta tela passa a enxergar só a AR do usuário."""
    if getattr(usuario, "master", False):
        db.info["ar"] = None
    else:
        db.info["ar"] = getattr(usuario, "tenant_id", None) or SEM_AR
    db.info["ar_ligado"] = True


def ar_da_sessao(db: Session) -> int | None:
    return db.info.get("ar") if db.info.get("ar_ligado") else None


def _classes():
    if _cache_classes:
        return _cache_classes
    from . import modelos

    estritas, com_plataforma = [], []
    for mapeador in modelos.Base.registry.mappers:
        cls = mapeador.class_
        if not issubclass(cls, modelos.DaAR) or cls.__tablename__ in NUNCA:
            continue
        (com_plataforma if cls.__tablename__ in COM_PLATAFORMA else estritas).append(cls)
    _cache_classes.extend([estritas, com_plataforma])
    return _cache_classes


@event.listens_for(Session, "do_orm_execute")
def _filtrar(estado) -> None:
    sessao_ = estado.session
    if not sessao_.info.get("ar_ligado") or not (estado.is_select or estado.is_update or estado.is_delete):
        return
    if estado.execution_options.get("sem_filtro_de_ar") or not _do_sistema(sessao_):
        return
    ar = sessao_.info.get("ar")
    if ar is None:  # Admin Master: a plataforma toda
        return
    estritas, com_plataforma = _classes()
    opcoes = [with_loader_criteria(cls, lambda c: c.tenant_id == ar, include_aliases=True) for cls in estritas]
    opcoes += [with_loader_criteria(cls, lambda c: or_(c.tenant_id == ar, c.tenant_id.is_(None)),
                                    include_aliases=True) for cls in com_plataforma]
    estado.statement = estado.statement.options(*opcoes)


# ---------------------------------------------------------------- O que é criado ganha a AR

def _id_da_ar(db: Session, slug: str) -> int | None:
    chave = (str(db.bind.url), slug)
    if chave not in _ids_das_ars:
        from .modelos import Tenant

        with db.no_autoflush:
            valor = db.execute(select(Tenant.id).where(Tenant.slug == slug)).scalar()
        if valor is None:
            return None
        _ids_das_ars[chave] = valor
    return _ids_das_ars[chave]


def _ar_de(db: Session, cls, id_, cache: dict) -> int | None:
    """A AR de um registro (lead, campanha, usuário...) pelo id, sem filtro (pode ser chamado por rotinas)."""
    if id_ is None:
        return None
    chave = (cls.__tablename__, id_)
    if chave not in cache:
        with db.no_autoflush:
            linha = db.execute(select(cls.tenant_id, *([cls.master] if cls.__tablename__ == "usuarios" else []))
                               .where(cls.id == id_).execution_options(sem_filtro_de_ar=True)).first()
        if linha is None:
            cache[chave] = None
        elif cls.__tablename__ == "usuarios" and linha[1]:  # Admin Master: as coisas dele vão para a AR MS
            cache[chave] = ("master", linha[0])
        else:
            cache[chave] = linha[0]
    return cache[chave]


def _ar_do_pai(db: Session, obj, cache: dict) -> int | None:
    """A AR que a linha nova herda: de um objeto ligado (relação) ou de uma chave estrangeira (lead_id, campanha_id,
    usuario_id...). Admin Master como dono: a AR MS (decisão de 14/11/2026, ars.PADRAO)."""
    from .modelos import DaAR, Usuario

    mapeador = inspect(obj).mapper
    dono_master = False
    for rel in mapeador.relationships:  # objetos já ligados (ainda sem o id preenchido)
        if rel.direction.name != "MANYTOONE":
            continue
        alvo = obj.__dict__.get(rel.key)
        if isinstance(alvo, DaAR):
            if isinstance(alvo, Usuario) and alvo.master:
                dono_master = True
                continue
            if alvo.tenant_id is not None:
                return alvo.tenant_id
    from . import modelos

    tabelas = {m.class_.__tablename__: m.class_ for m in modelos.Base.registry.mappers if issubclass(m.class_, DaAR)}
    for coluna in mapeador.local_table.columns:
        for fk in coluna.foreign_keys:
            pai = tabelas.get(fk.column.table.name)
            if pai is None:
                continue
            ar = _ar_de(db, pai, getattr(obj, mapeador.get_property_by_column(coluna).key, None), cache)
            if isinstance(ar, tuple):  # dono é o Admin Master
                dono_master = True
            elif ar is not None:
                return ar
    for nome in ("usuario_id", "dono_id", "vendedor_id", "responsavel_id"):  # dono sem chave estrangeira declarada
        if hasattr(obj, nome) and getattr(obj, nome) is not None:
            ar = _ar_de(db, Usuario, getattr(obj, nome), cache)
            if isinstance(ar, tuple):
                dono_master = True
            elif ar is not None:
                return ar
    return _id_da_ar(db, "ms") if dono_master else None


@event.listens_for(Session, "before_flush")
def _ar_nas_novas(db: Session, _contexto, _instancias) -> None:
    from . import ars
    from .modelos import ConexaoWhatsApp, DaAR, Usuario

    novas = [o for o in db.new if isinstance(o, DaAR) and getattr(o, "tenant_id", None) is None]
    if not novas or not _do_sistema(db):
        return
    contexto = ar_da_sessao(db)
    contexto = None if contexto == SEM_AR else contexto
    cache: dict = {}
    for obj in novas:
        tabela = obj.__tablename__
        if tabela in NUNCA:
            continue
        if tabela in COM_PLATAFORMA and tabela != "usuarios":
            obj.tenant_id = contexto  # modelo criado na tela: da AR; criado pelo sistema: da plataforma
            continue
        if tabela == "usuarios":
            if contexto is not None:
                obj.tenant_id = contexto
            elif not obj.master:
                obj.tenant_id = _id_da_ar(db, ars.slug_da_pessoa(obj.empresa_nome, obj.email))
            continue
        if tabela in SO_DA_PESSOA:
            ar = _ar_de(db, Usuario, getattr(obj, "usuario_id", None), cache)
            obj.tenant_id = None if isinstance(ar, tuple) else (ar if ar is not None else contexto)
            continue
        if contexto is not None:
            obj.tenant_id = contexto
            continue
        ar = None
        if tabela in DA_CONEXAO:
            with db.no_autoflush:
                ar = db.execute(select(ConexaoWhatsApp.tenant_id).where(ConexaoWhatsApp.id == obj.conexao)
                                .execution_options(sem_filtro_de_ar=True)).scalar()
        if ar is None:
            ar = _ar_do_pai(db, obj, cache)
        obj.tenant_id = ar if ar is not None else _id_da_ar(db, "ms")  # sem dono nenhum: AR MS (ars.PADRAO)
