"""White label, Fase 1: a AR entra nos dados (app/ars.py). Cada teste usa um banco próprio, separado do banco dos
outros testes, com pessoas da MS, do Grupo Certy e o Admin Master."""
import tempfile
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app import ars
from app.banco import Base, gravar_config, sessao
from app.modelos import (Campanha, Conhecimento, ConexaoWhatsApp, ContaEmail, ContatoWhatsApp, Historico, Lead,
                         LogAuditoria, Mensagem, MensagemWhatsApp, Notificacao, Papel, Tarefa, Tenant, Trabalho,
                         Usuario)


@pytest.fixture()
def banco():
    """Banco SQLite novo, com as tabelas de hoje e um pouco de tudo."""
    pasta = tempfile.mkdtemp(prefix="pp_ars_")
    motor = create_engine(f"sqlite:///{Path(pasta, 'ars.db').as_posix()}")
    Base.metadata.create_all(motor)
    ids = {}
    with Session(motor) as db:
        pessoas = {
            "master": Usuario(nome="Paulo Marinho", email="paulo@ms.com.br", senha_hash="x", perfil="admin",
                              master=True),
            "ms": Usuario(nome="Vendedor MS", email="vend@ms.com.br", senha_hash="x",
                          empresa_nome="MS Certificação Digital"),
            "certy": Usuario(nome="Vendedora Certy", email="vend@gmail.com", senha_hash="x",
                             empresa_nome="Grupo Certy"),
            "gestora": Usuario(nome="Gestora Certy", email="atendimento@grupocerty.com.br", senha_hash="x",
                               perfil="gestor"),
            "caio": Usuario(nome="Admin sem empresa", email="admin2@ms.com.br", senha_hash="x", perfil="admin"),
        }
        db.add_all(pessoas.values())
        db.flush()
        u = {k: v.id for k, v in pessoas.items()}
        leads = {"ms": Lead(empresa="Lead do MS", vendedor_id=u["ms"]),
                 "certy": Lead(empresa="Lead da Certy", vendedor_id=u["certy"]),
                 "master": Lead(empresa="Lead do Paulo", vendedor_id=u["master"]),
                 "sem_dono": Lead(empresa="Lead sem dono")}
        db.add_all(leads.values())
        db.flush()
        campanhas = {"certy": Campanha(nome="Campanha Certy", usuario_id=u["certy"]),
                     "master": Campanha(nome="Empresas novas", usuario_id=u["master"], tipo="empresas_novas"),
                     "renov": Campanha(nome="Renovação", usuario_id=u["certy"], tipo="renovacao")}
        db.add_all(campanhas.values())
        db.flush()
        tarefas = {"certy": Tarefa(data=date.today(), lead_id=leads["certy"].id, campanha_id=campanhas["certy"].id),
                   "so_campanha": Tarefa(data=date.today(), campanha_id=campanhas["master"].id),
                   "cruzada": Tarefa(data=date.today(), lead_id=leads["ms"].id, campanha_id=campanhas["certy"].id)}
        db.add_all(tarefas.values())
        db.add_all([Historico(lead_id=leads["certy"].id, tipo="nota"),
                    Mensagem(canal="email", lead_id=leads["certy"].id),
                    ConexaoWhatsApp(id="principal", nome="Principal", dono_id=u["master"]),
                    ConexaoWhatsApp(id=f"u{u['certy']}", nome="Certy", dono_id=u["certy"]),
                    MensagemWhatsApp(id_wl=1, telefone="81999990001", conexao="principal", direcao="entrada"),
                    MensagemWhatsApp(id_wl=2, telefone="81999990002", conexao=f"u{u['certy']}", direcao="entrada"),
                    MensagemWhatsApp(id_wl=3, telefone="81999990003", conexao="u999", direcao="entrada"),
                    ContatoWhatsApp(telefone="81999990002", nome="Cliente da Certy"),
                    ContaEmail(principal=True, nome="Comercial"),
                    ContaEmail(nome="Atendimento Certy", dono_id=u["gestora"]),
                    Papel(codigo="vendedor-x", nome="Vendedor (sistema)", sistema=True),
                    Papel(codigo="supervisor", nome="Supervisor"),
                    Trabalho(tipo="campanha", ref_id=campanhas["certy"].id),
                    Conhecimento(pergunta="Quanto custa?", resposta="Depende."),
                    LogAuditoria(acao="entrou", usuario_id=u["master"]),
                    LogAuditoria(acao="entrou", usuario_id=u["certy"]),
                    Notificacao(usuario_id=u["master"], texto="oi"),
                    Notificacao(usuario_id=u["certy"], texto="oi")])
        db.commit()
        ids.update(u=u, leads={k: v.id for k, v in leads.items()}, camp={k: v.id for k, v in campanhas.items()},
                   tarefas={k: v.id for k, v in tarefas.items()})
    yield motor, ids
    motor.dispose()


def _ar(motor, modelo, filtro):
    with Session(motor) as db:
        linha = db.execute(select(modelo.tenant_id).where(filtro)).scalar()
        if linha is None:
            return None
        return db.execute(select(Tenant.slug).where(Tenant.id == linha)).scalar()


def test_ensaio_desfaz_tudo(banco):
    motor, _ = banco
    with motor.connect() as con:
        ars.preencher(con, gravar=False)
        previa = ars.contagem(con)
        con.rollback()
    assert previa["leads"] == {"ms": 3, "grupo-certy": 1}  # MS, Paulo (decisão: AR MS) e sem dono; 1 da Certy
    assert previa["mensagens_whatsapp"] == {"ms": 2, "grupo-certy": 1}
    with motor.connect() as con:  # nada ficou gravado
        assert con.execute(text("SELECT COUNT(*) FROM tenants")).scalar() == 0
        assert con.execute(text("SELECT COUNT(*) FROM leads WHERE tenant_id IS NOT NULL")).scalar() == 0


def test_preencher_segue_o_dono_de_cada_linha(banco):
    motor, ids = banco
    u, leads, camp, tarefas = ids["u"], ids["leads"], ids["camp"], ids["tarefas"]
    with motor.connect() as con:
        ars.preencher(con)
    assert _ar(motor, Usuario, Usuario.id == u["master"]) is None  # Admin Master: da plataforma
    assert [_ar(motor, Usuario, Usuario.id == u[k]) for k in ("ms", "certy", "gestora", "caio")] == \
        ["ms", "grupo-certy", "grupo-certy", "ms"]
    assert [_ar(motor, Lead, Lead.id == leads[k]) for k in ("ms", "certy", "master", "sem_dono")] == \
        ["ms", "grupo-certy", "ms", "ms"]
    assert [_ar(motor, Campanha, Campanha.id == camp[k]) for k in ("certy", "master", "renov")] == \
        ["grupo-certy", "ms", "ms"]  # Renovação = planilha da MS, mesmo criada por outra pessoa
    assert _ar(motor, Tarefa, Tarefa.id == tarefas["certy"]) == "grupo-certy"
    assert _ar(motor, Tarefa, Tarefa.id == tarefas["so_campanha"]) == "ms"  # sem lead: a AR da campanha
    assert _ar(motor, Historico, Historico.lead_id == leads["certy"]) == "grupo-certy"
    assert _ar(motor, Mensagem, Mensagem.lead_id == leads["certy"]) == "grupo-certy"
    assert _ar(motor, ConexaoWhatsApp, ConexaoWhatsApp.id == f"u{u['certy']}") == "grupo-certy"
    assert _ar(motor, ConexaoWhatsApp, ConexaoWhatsApp.id == "principal") == "ms"
    assert [_ar(motor, MensagemWhatsApp, MensagemWhatsApp.id_wl == i) for i in (1, 2, 3)] == \
        ["ms", "grupo-certy", "ms"]  # conversa vai com o número; número desconhecido fica na MS
    assert _ar(motor, ContatoWhatsApp, ContatoWhatsApp.telefone == "81999990002") == "grupo-certy"
    assert _ar(motor, ContaEmail, ContaEmail.principal.is_(True)) == "ms"
    assert _ar(motor, ContaEmail, ContaEmail.dono_id == u["gestora"]) == "grupo-certy"
    assert _ar(motor, Papel, Papel.sistema.is_(True)) is None and _ar(motor, Papel, Papel.codigo == "supervisor") == "ms"
    assert _ar(motor, Trabalho, Trabalho.ref_id == camp["certy"]) == "grupo-certy"
    assert _ar(motor, Conhecimento, Conhecimento.id.is_not(None)) == "ms"
    assert _ar(motor, LogAuditoria, LogAuditoria.usuario_id == u["master"]) is None
    assert _ar(motor, Notificacao, Notificacao.usuario_id == u["certy"]) == "grupo-certy"
    with motor.connect() as con:  # rodar de novo não muda nada
        antes = ars.contagem(con)
        ars.preencher(con)
        assert ars.contagem(con) == antes


def test_conferir_acha_ligacao_cruzando_ars(banco):
    motor, ids = banco
    with motor.connect() as con:
        ars.preencher(con)
        resultado = ars.conferir(con)
        assert not resultado["ok"] and resultado["sem_ar"] == {}
        assert resultado["cruzadas"] == {"tarefas.campanha_id → campanhas": 1,  # lead da MS em campanha da Certy
                                         "campanhas.usuario_id → usuarios": 1}  # Renovação (MS) criada pela Certy
        con.execute(text("DELETE FROM tarefas WHERE id = :i"), {"i": ids["tarefas"]["cruzada"]})
        con.execute(text("UPDATE campanhas SET usuario_id = :u WHERE id = :c"),
                    {"u": ids["u"]["ms"], "c": ids["camp"]["renov"]})
        con.execute(text("UPDATE leads SET tenant_id = NULL WHERE id = :i"), {"i": ids["leads"]["sem_dono"]})
        assert ars.conferir(con)["sem_ar"] == {"leads": 1}
        ars.preencher(con)
        assert ars.conferir(con)["ok"]


def test_decisoes_do_master_e_dos_sem_dono(banco):
    motor, ids = banco
    with motor.connect() as con:
        ars.preencher(con, {"do_master": ars.AR_CERTY, "sem_dono": ars.AR_CERTY})
    leads, camp = ids["leads"], ids["camp"]
    assert [_ar(motor, Lead, Lead.id == leads[k]) for k in ("ms", "master", "sem_dono")] == \
        ["ms", "grupo-certy", "grupo-certy"]
    assert _ar(motor, Campanha, Campanha.id == camp["master"]) == "grupo-certy"
    assert _ar(motor, Usuario, Usuario.id == ids["u"]["master"]) is None  # o Master continua da plataforma


def test_linhas_novas_so_ganham_ar_depois_da_migracao(cliente):
    """No banco dos testes (o do sistema): antes do migrar_ar.py aplicar, a rotina de hora em hora não mexe."""
    with sessao() as db:
        db.add(Lead(empresa="Lead novo da rotina"))
    assert ars.preencher_novos() is False
    with sessao() as db:
        assert db.execute(select(Lead.tenant_id).where(Lead.empresa == "Lead novo da rotina")).scalar() is None
        gravar_config(db, ars.LIGADO, '{"do_master": "ms", "sem_dono": "ms"}')
    try:
        assert ars.preencher_novos() is True
        with sessao() as db:
            ar = db.execute(select(Lead.tenant_id).where(Lead.empresa == "Lead novo da rotina")).scalar()
            assert db.get(Tenant, ar).slug == "ms"
    finally:
        with sessao() as db:
            db.execute(text("DELETE FROM configuracoes WHERE chave = :c"), {"c": ars.LIGADO})


def test_migrar_ar_nunca_confunde_teste_com_nuvem(tmp_path):
    import migrar_ar

    nuvem = "postgresql://postgres.abc:senha1@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    teste = "postgresql://postgres.xyz:senha2@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    arquivo = tmp_path / "supabase_teste.txt"
    arquivo.write_text(f"DATABASE_URL={teste}\n", encoding="utf-8")
    assert migrar_ar.endereco(arquivo).startswith("postgresql+psycopg://postgres.xyz:")
    assert migrar_ar.endereco(tmp_path / "nao_existe.txt") == ""
    assert not migrar_ar.mesmo_banco(migrar_ar.endereco(arquivo), nuvem)
    assert migrar_ar.mesmo_banco(nuvem.replace("senha1", "outra"), "postgresql+psycopg://" + nuvem.split("://")[1])
    assert migrar_ar.opcoes(["aplicar", "--nuvem", "--master=grupo-certy"]) == \
        ("aplicar", "nuvem", {"do_master": "grupo-certy"})
    assert migrar_ar.opcoes([]) == ("ensaio", "teste", {})
