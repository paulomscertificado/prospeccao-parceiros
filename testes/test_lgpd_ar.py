"""White label, Fase 6: exportar e apagar uma AR (LGPD) e "quem agiu como quem" no histórico.

O portão da Fase 6: exportar e apagar uma AR de teste sem tocar nas outras ARs nem no que é da plataforma."""
from datetime import date

from sqlalchemy import create_engine, func, select

from app import ars
from app.banco import motor, sessao
from app.modelos import (AcessoMaster, Campanha, ConexaoWhatsApp, ConfiguracaoAR, Lead, LogAuditoria,
                         MensagemWhatsApp, Tarefa, Template, Tenant, Usuario)
from app.seguranca import resumir_senha
from conftest import SENHA


def _contar(ar_id=None) -> dict:
    with motor.connect() as con:
        return {t.name: con.execute(select(func.count()).select_from(t).where(
            t.c.tenant_id.is_(None) if ar_id is None else t.c.tenant_id == ar_id)).scalar()
            for t in ars._tabelas_da_ar()}


def _ar_de_teste() -> int:
    with sessao() as db:
        ar = Tenant(slug="ar-teste-lgpd", nome="AR de teste LGPD")
        db.add(ar)
        db.flush()
        pessoa = Usuario(nome="Pessoa da AR de teste", email="pessoa@ar-teste-lgpd.com.br", perfil="vendedor",
                         senha_hash=resumir_senha(SENHA), tenant_id=ar.id)
        db.add(pessoa)
        db.flush()
        lead = Lead(empresa="Lead da AR de teste", vendedor_id=pessoa.id, tenant_id=ar.id)
        camp = Campanha(nome="Campanha da AR de teste", usuario_id=pessoa.id, tenant_id=ar.id)
        db.add_all([lead, camp, ConexaoWhatsApp(id=f"u{pessoa.id}", nome="Número de teste", dono_id=pessoa.id,
                                                tenant_id=ar.id)])
        db.flush()
        db.add_all([Tarefa(data=date.today(), lead_id=lead.id, campanha_id=camp.id, tenant_id=ar.id),
                    MensagemWhatsApp(id_wl=998877, telefone="81977776666", conexao=f"u{pessoa.id}",
                                     direcao="entrada", texto="oi", tenant_id=ar.id),
                    ConfiguracaoAR(tenant_id=ar.id, chave="horario_envio_inicio", valor="09:00"),
                    AcessoMaster(usuario_id=1, tenant_id=ar.id, motivo="teste")])
        return ar.id


def test_exportar_e_apagar_uma_ar_sem_tocar_nas_outras(cliente, tmp_path):
    ar_id = _ar_de_teste()
    with sessao() as db:
        outras = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug)) if i != ar_id}
        modelos_da_plataforma = db.execute(select(func.count(Template.id)).where(Template.tenant_id.is_(None))).scalar()
    antes = {s: _contar(i) for s, i in outras.items()}
    plataforma = _contar(None)
    # exportar: só as linhas da AR de teste
    destino = create_engine(f"sqlite:///{(tmp_path / 'exportacao.db').as_posix()}")
    contagem = ars.exportar(motor, ar_id, destino)
    assert contagem["usuarios"] == 1 and contagem["leads"] == 1 and contagem["mensagens_whatsapp"] == 1
    assert contagem["configuracoes_ar"] == 1 and contagem["acessos_master"] == 1
    with destino.connect() as con:
        assert con.execute(select(Tenant.slug)).scalars().all() == ["ar-teste-lgpd"]
        for t in ars._tabelas_da_ar():
            assert con.execute(select(func.count()).select_from(t).where(t.c.tenant_id != ar_id)).scalar() == 0, t
    destino.dispose()
    # apagar: a AR de teste some inteira; as outras e a plataforma ficam iguais
    with motor.begin() as con:
        apagadas = ars.apagar(con, ar_id)
    assert sum(apagadas.values()) >= 8
    assert sum(_contar(ar_id).values()) == 0
    with sessao() as db:
        assert db.get(Tenant, ar_id) is None
        assert db.execute(select(func.count(Template.id)).where(Template.tenant_id.is_(None))).scalar() == \
            modelos_da_plataforma
    assert {s: _contar(i) for s, i in outras.items()} == antes
    assert _contar(None) == plataforma


def test_apagar_ar_tem_travas():
    import apagar_ar

    assert apagar_ar.main(["ms"]) == 1  # a AR MS nunca é apagada por aqui
    assert apagar_ar.main(["grupo-certy"]) == 1  # sem a exportação de hoje, nada acontece
    with sessao() as db:
        assert db.execute(select(Tenant.id).where(Tenant.slug == "grupo-certy")).first() is not None


def test_o_que_o_master_faz_dentro_da_ar_fica_no_historico_dela(cliente, csrf):
    with sessao() as db:
        certy = db.execute(select(Tenant.id).where(Tenant.slug == "grupo-certy")).scalar()
    cliente.post(f"/master/entrar/{certy}", data={"csrf": csrf, "motivo": "ajustar o horário da Certy"})
    try:
        cliente.post("/configuracoes/geral", data={"csrf": csrf, "horario_envio_inicio": "08:45"})
        with sessao() as db:
            log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "salvou_configuracoes")
                             .order_by(LogAuditoria.id.desc())).scalars().first()
            assert log.tenant_id == certy and log.detalhes.startswith("[Admin Master dentro da AR]")
            usuario_master = db.execute(select(Usuario).where(Usuario.master.is_(True))).scalars().first()
            assert log.usuario_id == usuario_master.id
    finally:
        cliente.post("/master/sair", data={"csrf": csrf})
        with sessao() as db:
            db.query(ConfiguracaoAR).filter(ConfiguracaoAR.tenant_id == certy).delete()
