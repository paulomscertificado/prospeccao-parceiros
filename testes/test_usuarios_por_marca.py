"""Configurações > Usuários separados por marca (AR): o Admin Master vê um quadro por marca e cria a pessoa nova na
marca do quadro; quem é de uma marca vê só o quadro dela. Permissões ficam dentro das Configurações."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.banco import sessao
from app.main import app
from app.modelos import Equipe, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de


def _ars() -> dict:
    with sessao() as db:
        return dict(db.execute(select(Tenant.slug, Tenant.id)).all())


def test_master_ve_um_quadro_por_marca_e_cria_na_marca_do_quadro(cliente, csrf):
    ars = _ars()
    pagina = cliente.get("/configuracoes?aba=usuarios").text
    assert "<h2>AR MS Certificados</h2>" in pagina and "<h2>Grupo Certy</h2>" in pagina
    assert 'name="ar" value="%s"' % ars["grupo-certy"] in pagina  # o "+ Nova pessoa" de cada quadro leva a marca
    cliente.post("/configuracoes/usuarios/0", data={
        "csrf": csrf, "ar": str(ars["grupo-certy"]), "nome": "Nova do Grupo", "email": "nova.grupo@exemplo.com.br",
        "perfil": "vendedor", "ativo": "on", "senha": "Senha-forte-123", "equipe_id": ""})
    with sessao() as db:
        nova = db.execute(select(Usuario).where(Usuario.email == "nova.grupo@exemplo.com.br")).scalars().one()
        assert nova.tenant_id == ars["grupo-certy"]  # pelo e-mail iria para a AR MS: vale a marca do quadro


def test_master_precisa_escolher_a_marca_e_nao_mistura_equipe(cliente, csrf):
    ars = _ars()
    r = cliente.post("/configuracoes/usuarios/0", data={
        "csrf": csrf, "nome": "Sem Marca", "email": "sem.marca@exemplo.com.br", "perfil": "vendedor", "ativo": "on",
        "senha": "Senha-forte-123", "equipe_id": ""})
    assert "Escolha em qual marca" in r.text
    with sessao() as db:
        equipe_ms = Equipe(nome="Equipe só da MS", tenant_id=ars["ms"])
        db.add(equipe_ms)
        db.flush()
        equipe_id = equipe_ms.id
    r = cliente.post("/configuracoes/usuarios/0", data={
        "csrf": csrf, "ar": str(ars["grupo-certy"]), "nome": "Equipe Errada", "email": "equipe.errada@exemplo.com.br",
        "perfil": "vendedor", "ativo": "on", "senha": "Senha-forte-123", "equipe_id": str(equipe_id)})
    assert "é de outra marca" in r.text
    with sessao() as db:
        assert db.execute(select(Usuario).where(Usuario.email.in_(
            ["sem.marca@exemplo.com.br", "equipe.errada@exemplo.com.br"]))).first() is None


def test_admin_da_marca_ve_so_o_quadro_dela(cliente):
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    with sessao() as db:
        db.add(Usuario(nome="Admin do Quadro", email="admin.quadro@grupocerty.com.br", perfil="admin",
                       senha_hash=resumir_senha(SENHA), empresa_nome="Grupo Certy"))
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": "admin.quadro@grupocerty.com.br",
                           "senha": SENHA})
    pagina = c.get("/configuracoes?aba=usuarios").text
    assert "<h2>Grupo Certy</h2>" in pagina and "<h2>AR MS Certificados</h2>" not in pagina
    assert "Admin do Quadro" in pagina
    menu = c.get("/").text
    assert 'href="/permissoes"' not in menu  # Permissões fica dentro de Configurações
