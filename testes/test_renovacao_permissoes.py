"""A Renovação com permissões próprias (26/11/2026, pedido da Maria: "o módulo de renovação não está aparecendo" nas
Exceções por pessoa). Antes ela vinha dentro de campanhas.configurar, junto com as Empresas novas (busca paga na CNPJá);
agora tem o grupo Renovação (ver e mexer), que aparece nos Papéis e nas Exceções, e dá para liberar só a Renovação a um
vendedor. A separação não dá nem tira acesso de ninguém (autorizacao._separar_renovacao)."""

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import autorizacao
from app.banco import gravar_config, sessao
from app.main import app
from app.modelos import ExcecaoPermissao, Papel, PermissaoPapel, Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de, ligar_modulos

SENHA = "SenhaRenovPerm123"
EMAIL = "vendedora.renovacao@teste.com.br"


def _vendedora() -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == EMAIL)).scalars().first()
        if u is None:
            u = Usuario(nome="Vendedora Renovação", email=EMAIL, perfil="vendedor", senha_hash=resumir_senha(SENHA))
            db.add(u)
            db.flush()
        return u.id


def _liberar(uid: int, *permissoes: str) -> None:
    with sessao() as db:
        db.execute(delete(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == uid))
        for p in permissoes:
            db.add(ExcecaoPermissao(usuario_id=uid, permissao=p, efeito="permitir", motivo="teste da Renovação"))


def _entrar() -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": EMAIL, "senha": SENHA})
    return c


def test_renovacao_aparece_nos_papeis_e_nas_excecoes(cliente):
    ligar_modulos("campanhas")
    uid = _vendedora()
    pagina = " ".join(cliente.get(f"/permissoes?aba=usuarios&pessoa={uid}").text.split())
    assert "Renovação · Ver a Renovação (certificados que vão vencer, avisos e campanhas)" in pagina
    assert "Renovação · Mexer na Renovação" in pagina
    assert "Configurar as Empresas novas (busca paga na CNPJá, textos e avisos)" in pagina
    assert "Configurar a Renovação e as Empresas novas" not in pagina
    with sessao() as db:  # administrador e gestor continuam com a Renovação; funcionário e vendedor, sem
        for codigo, tem in (("admin", True), ("gestor", True), ("funcionario", False), ("vendedor", False)):
            papel = db.execute(select(Papel).where(Papel.codigo == codigo)).scalar_one()
            dele = set(db.execute(select(PermissaoPapel.permissao).where(PermissaoPapel.papel_id == papel.id)).scalars())
            assert (set(autorizacao.RENOVACAO) <= dele) is tem, codigo
            assert ("campanhas.configurar" in dele) is tem, codigo


def test_vendedora_so_com_a_renovacao(cliente):
    ligar_modulos("campanhas")
    uid = _vendedora()
    _liberar(uid)
    c = _entrar()
    assert c.get("/renovacao").status_code == 403
    _liberar(uid, "renovacao.ver")  # só ver: abre a tela, sem as áreas de mexer
    c = _entrar()
    tela = c.get("/renovacao")
    assert tela.status_code == 200 and "1. Testar os avisos" not in tela.text
    assert c.get("/empresas-novas").status_code == 403  # a Renovação não dá as Empresas novas (busca paga)
    csrf = csrf_de(tela.text)
    assert c.post("/renovacao/testar", data={"csrf": csrf}).status_code == 403
    assert 'href="/renovacao"' in c.get("/").text  # o item do menu aparece para ela
    _liberar(uid, "renovacao.ver", "renovacao.gerenciar")  # ver e mexer: as áreas aparecem
    c = _entrar()
    assert "1. Testar os avisos" in c.get("/renovacao").text
    assert c.get("/empresas-novas").status_code == 403
    _liberar(uid)


def test_separacao_nao_da_nem_tira_acesso(cliente):
    with sessao() as db:
        com = Papel(codigo="p_renov_com", nome="Papel Renov Com", base="vendedor", sistema=False)
        sem = Papel(codigo="p_renov_sem", nome="Papel Renov Sem", base="gestor", sistema=False)
        db.add_all([com, sem])
        db.flush()
        db.add(PermissaoPapel(papel_id=com.id, permissao="campanhas.configurar", escopo="tudo"))
        # papel de gestor sem campanhas.configurar: o padrão do catálogo daria as novas a ele (o gestor tem)
        db.add_all([PermissaoPapel(papel_id=sem.id, permissao=p, escopo="tudo") for p in autorizacao.RENOVACAO])
        uid = _vendedora()
        db.execute(delete(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == uid))
        db.add(ExcecaoPermissao(usuario_id=uid, permissao="campanhas.configurar", efeito="negar", motivo="teste"))
        gravar_config(db, "permissoes_renovacao_separada", "0")
        db.flush()
        autorizacao._separar_renovacao(db, {com.codigo: com, sem.codigo: sem})
        db.flush()

        def do_papel(papel):
            return {r.permissao: r.escopo for r in db.execute(select(PermissaoPapel).where(
                PermissaoPapel.papel_id == papel.id)).scalars()}

        assert do_papel(com) == {"campanhas.configurar": "tudo", "renovacao.ver": "tudo", "renovacao.gerenciar": "tudo"}
        assert do_papel(sem) == {}
        excecoes = {(e.permissao, e.efeito) for e in db.execute(select(ExcecaoPermissao).where(
            ExcecaoPermissao.usuario_id == uid)).scalars()}
        assert excecoes == {("campanhas.configurar", "negar"), ("renovacao.ver", "negar"),
                            ("renovacao.gerenciar", "negar")}
        # uma vez só: o que o administrador mudar depois fica
        db.execute(delete(PermissaoPapel).where(PermissaoPapel.papel_id == com.id,
                                                PermissaoPapel.permissao == "renovacao.gerenciar"))
        autorizacao._separar_renovacao(db, {com.codigo: com, sem.codigo: sem})
        assert "renovacao.gerenciar" not in do_papel(com)
        db.execute(delete(PermissaoPapel).where(PermissaoPapel.papel_id.in_((com.id, sem.id))))
        db.execute(delete(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == uid))
        db.delete(com)
        db.delete(sem)
