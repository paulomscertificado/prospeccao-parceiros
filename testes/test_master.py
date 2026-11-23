"""White label, Fase 3: o painel /master e o que é da plataforma (o portão da Fase 3: admin de uma AR não alcança outra
AR nem o /master, nem muda o que vale para todas as ARs)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import autorizacao
from app.banco import ler_config, sessao, usar_config_da_ar
from app.main import app
from app.modelos import (AcessoMaster, Cadencia, Categoria, ConfiguracaoAR, Lead, Papel, PermissaoPapel, Template,
                         Tenant, Usuario)
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de


def _zerar_limite():
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)


def _entrar(email: str) -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


@pytest.fixture(scope="module")
def cenario(cliente):
    with sessao() as db:
        ars = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}
        certy = Usuario(nome="Admin da Certy (master)", email="admin.master@grupocerty.com.br", perfil="admin",
                        senha_hash=resumir_senha(SENHA), empresa_nome="Grupo Certy")
        db.add(certy)
        db.flush()
        lead_ms = Lead(empresa="Lead MS do painel", tenant_id=ars["ms"])
        lead_certy = Lead(empresa="Lead Certy do painel", tenant_id=ars["grupo-certy"])
        db.add_all([lead_ms, lead_certy])
        db.flush()
        return {"ars": ars, "certy": certy.email, "lead_ms": lead_ms.id, "lead_certy": lead_certy.id}


def _foto_plataforma():
    with sessao() as db:
        papel = db.execute(select(Papel).where(Papel.codigo == "vendedor")).scalars().one()
        return (sorted((r.permissao, r.escopo) for r in db.execute(
                    select(PermissaoPapel).where(PermissaoPapel.papel_id == papel.id)).scalars()),
                sorted((t.id, t.nome, t.corpo) for t in db.execute(select(Template).where(
                    Template.tenant_id.is_(None))).scalars()),
                sorted((c.id, c.nome, c.ativa) for c in db.execute(select(Cadencia)).scalars()),
                sorted((c.id, c.nome) for c in db.execute(select(Categoria)).scalars()),
                db.execute(select(Tenant.id, Tenant.situacao).order_by(Tenant.id)).all())


def test_admin_de_ar_nao_alcanca_o_master_nem_o_que_e_da_plataforma(cenario):
    _zerar_limite()
    try:
        c = _entrar(cenario["certy"])
        token = csrf_de(c.get("/minha-conta").text)
        antes = _foto_plataforma()
        assert c.get("/master").status_code == 404 and "Painel master" not in c.get("/").text
        for caminho, dados in [(f"/master/entrar/{cenario['ars']['ms']}", {"motivo": "tentar entrar na MS"}),
                               ("/master/ar/nova", {"nome": "AR pirata", "slug": "ar-pirata"}),
                               (f"/master/ar/{cenario['ars']['ms']}/situacao", {"acao": "suspender"}),
                               (f"/master/ar/{cenario['ars']['ms']}/modulos", {})]:
            assert c.post(caminho, data={"csrf": token, **dados}, follow_redirects=False).status_code == 404
        with sessao() as db:
            vendedor = db.execute(select(Papel.id).where(Papel.codigo == "vendedor")).scalar()
            modelo = db.execute(select(Template.id).where(Template.tenant_id.is_(None)).limit(1)).scalar()
            cadencia = db.execute(select(Cadencia.id).where(Cadencia.tenant_id.is_(None)).limit(1)).scalar()
            categoria = db.execute(select(Categoria.id).limit(1)).scalar()
        r = c.post(f"/permissoes/papel/{vendedor}", data={"csrf": token, "p__leads.ver": "tudo"})
        assert autorizacao.MSG_DA_PLATAFORMA in r.text
        c.post(f"/templates/{modelo}", data={"csrf": token, "nome": "Mudado pela AR", "canal": "email",
                                             "corpo": "Texto da AR"})
        c.post(f"/cadencias/{cadencia}", data={"csrf": token, "nome": "Mudada pela AR"})
        c.post(f"/categorias/{categoria}", data={"csrf": token, "nome": "Mudada pela AR"})
        c.post("/permissoes/modulos", data={"csrf": token})  # desligaria todos os módulos
        assert _foto_plataforma() == antes  # nada da plataforma mudou
        # o que é da AR continua: ela cria um modelo próprio, que nasce na AR dela
        c.post("/templates/0", data={"csrf": token, "nome": "Modelo próprio da Certy", "canal": "email",
                                     "corpo": "Olá"})
        with sessao() as db:
            proprio = db.execute(select(Template).where(Template.nome == "Modelo próprio da Certy")).scalars().one()
            assert proprio.tenant_id == cenario["ars"]["grupo-certy"]
            db.delete(proprio)
    finally:
        _zerar_limite()


def test_admin_master_entra_numa_ar_com_motivo_e_sai(cliente, csrf, cenario):
    _zerar_limite()
    try:
        assert "Grupo Certy" in cliente.get("/master").text
        r = cliente.post(f"/master/entrar/{cenario['ars']['grupo-certy']}", data={"csrf": csrf, "motivo": "abc"})
        assert "Escreva o motivo" in r.text  # sem motivo, não entra
        cliente.post(f"/master/entrar/{cenario['ars']['grupo-certy']}",
                     data={"csrf": csrf, "motivo": "conferir a campanha da Certy"})
        assert cliente.get(f"/leads/{cenario['lead_ms']}").status_code == 404  # dentro da Certy: só a Certy
        r = cliente.get(f"/leads/{cenario['lead_certy']}")
        assert r.status_code == 200 and "Você está dentro da" in r.text
        with sessao() as db:
            acesso = db.execute(select(AcessoMaster).order_by(AcessoMaster.id.desc())).scalars().first()
            assert acesso.motivo == "conferir a campanha da Certy" and acesso.fim is None
        cliente.post("/master/sair", data={"csrf": csrf})
        assert cliente.get(f"/leads/{cenario['lead_ms']}").status_code == 200  # fora: a plataforma toda
        with sessao() as db:
            assert db.get(AcessoMaster, acesso.id).fim is not None
    finally:
        _zerar_limite()


def test_ar_suspensa_nao_entra_e_modulos_sao_de_cada_ar(cliente, csrf, cenario):
    _zerar_limite()
    certy = cenario["ars"]["grupo-certy"]
    try:
        c = _entrar(cenario["certy"])
        assert c.get("/leads").status_code == 200
        cliente.post(f"/master/ar/{certy}/situacao", data={"csrf": csrf, "acao": "suspender"})
        r = c.get("/leads")
        assert "suspenso" in r.text and "Lead Certy do painel" not in r.text
        cliente.post(f"/master/ar/{certy}/situacao", data={"csrf": csrf, "acao": "reativar"})
        # módulos: desliga a Agenda só no Grupo Certy
        dados = {f"m__{m}": "on" for m in autorizacao.MODULOS if m != "agenda"}
        cliente.post(f"/master/ar/{certy}/modulos", data={"csrf": csrf, **dados})
        with sessao() as db:
            usar_config_da_ar(db, certy)
            assert ler_config(db, "mostrar_agenda") == "0"
            usar_config_da_ar(db, cenario["ars"]["ms"])
            assert ler_config(db, "mostrar_agenda") != "0"
    finally:
        _zerar_limite()
        with sessao() as db:
            db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.tenant_id == certy))
            db.get(Tenant, certy).situacao = "ativa"


def test_papel_com_o_mesmo_nome_em_duas_ars(cliente, csrf, cenario):
    """O código do papel é único no sistema todo: a 2ª AR que cria "Supervisor" ganha outro código, sem erro."""
    _zerar_limite()
    try:
        cliente.post(f"/master/entrar/{cenario['ars']['ms']}", data={"csrf": csrf, "motivo": "criar papel na MS"})
        cliente.post("/permissoes/papel/novo", data={"csrf": csrf, "nome": "Supervisor Comercial",
                                                     "copiar_de": "vendedor"})
        cliente.post("/master/sair", data={"csrf": csrf})
        c = _entrar(cenario["certy"])
        r = c.post("/permissoes/papel/novo", data={"csrf": csrf_de(c.get("/minha-conta").text),
                                                   "nome": "Supervisor Comercial", "copiar_de": "vendedor"})
        assert r.status_code == 200
        with sessao() as db:
            papeis = db.execute(select(Papel).where(Papel.nome == "Supervisor Comercial")).scalars().all()
            assert sorted(p.tenant_id for p in papeis) == sorted(cenario["ars"].values())
            assert len({p.codigo for p in papeis}) == 2
            for p in papeis:
                db.execute(delete(PermissaoPapel).where(PermissaoPapel.papel_id == p.id))
                db.delete(p)
    finally:
        _zerar_limite()


def test_nova_ar_apelido_sai_do_nome(cliente, csrf):
    """O apelido da AR (vira o endereço) sai do nome ou do que a pessoa escreveu: sem acento, minúsculo e com hífen.
    Antes a tela recusava "Certifica Recife" e o navegador não avisava antes (pedido da Maria em 23/11/2026)."""
    _zerar_limite()
    criadas = ["certificacao-recife-cia", "ar-de-teste-do-apelido"]
    try:
        r = cliente.post("/master/ar/nova", data={"csrf": csrf, "nome": "  Certificação   Recife & Cia ", "slug": ""})
        assert "criada (apelido certificacao-recife-cia)" in r.text
        r = cliente.post("/master/ar/nova", data={"csrf": csrf, "nome": "Outra AR", "slug": "AR de Teste do Apelido"})
        assert "criada (apelido ar-de-teste-do-apelido)" in r.text
        r = cliente.post("/master/ar/nova", data={"csrf": csrf, "nome": "Certificação Recife & Cia", "slug": " "})
        assert "Já existe uma AR com o apelido" in r.text  # a mesma AR duas vezes, não
        r = cliente.post("/master/ar/nova", data={"csrf": csrf, "nome": "?", "slug": "!"})
        assert "pelo menos 2 letras" in r.text
        with sessao() as db:
            novas = {t.slug: t.nome for t in db.execute(select(Tenant).where(Tenant.slug.in_(criadas))).scalars()}
        assert novas == {"certificacao-recife-cia": "Certificação Recife & Cia", "ar-de-teste-do-apelido": "Outra AR"}
        tela = cliente.get("/master").text
        assert 'pattern="[a-z0-9][a-z0-9-]' not in tela and "Vercel" not in tela  # o navegador não barra mais
    finally:
        _zerar_limite()
        with sessao() as db:
            db.execute(delete(Tenant).where(Tenant.slug.in_(criadas)))
