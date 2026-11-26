"""Troca obrigatória da senha provisória (pedido da Maria em 26/11/2026: "toda vez que ele entrar no sistema pela
primeira vez, mande ele trocar a senha"). A senha que um administrador escolhe para outra pessoa (pessoa nova ou senha
nova em Configurações > Usuários, ou o redefinir_senha.bat) é provisória: logo depois do login (e do código do celular,
para quem precisa) a pessoa só abre a tela "Troque a sua senha" até escolher uma senha dela. Quem já usava o sistema e o
Admin Master (que escolheu a própria senha no /primeiro-acesso) não são obrigados."""

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app import banco, config, dois_fatores
from app.banco import sessao
from app.main import app
from app.modelos import LogAuditoria, Parceiro, Tenant, TentativaErrada, Usuario
from app.seguranca import limite_ar, limite_pedidos, limite_pessoa, resumir_senha, senha_confere
from conftest import csrf_de

PROVISORIA = "Provisoria123"
NOVA = "MinhaSenha456"
AR_ELETRONICA = "ar-eletronica-troca"  # uma 3ª marca, como a AR Eletronica do sistema no ar
# o que denuncia a MS numa tela (a regra da marca de cada AR: nada de "MS" fixo; ver test_marca_ar.py)
DA_MS = re.compile(r"mscertificados|MS Certifica|MS Parceiros|\b(?:da|na|pela|com a|para a|à|a|A)\s+MS\b")


@pytest.fixture(autouse=True)
def _sem_limite_de_pedidos():
    for limitador in (limite_pedidos, limite_pessoa, limite_ar):
        for chave in list(limitador._eventos):
            limitador.zerar(chave)


def _ars() -> dict:
    with sessao() as db:
        if db.execute(select(Tenant.id).where(Tenant.slug == AR_ELETRONICA)).first() is None:
            db.add(Tenant(slug=AR_ELETRONICA, nome="AR Eletronica (teste)"))
    with sessao() as db:
        return dict(db.execute(select(Tenant.slug, Tenant.id)).all())


def _dados(uid: int) -> dict:
    with sessao() as db:
        u = db.get(Usuario, uid)
        return {"provisoria": u.senha_provisoria, "hash": u.senha_hash, "versao": u.versao_sessao, "ar": u.tenant_id}


def _registros(uid: int, acao: str) -> list[tuple]:
    with sessao() as db:
        return db.execute(select(LogAuditoria.detalhes, LogAuditoria.tenant_id).where(
            LogAuditoria.entidade == "usuario", LogAuditoria.entidade_id == uid, LogAuditoria.acao == acao)).all()


def _criar_pela_tela(cliente, email: str, perfil: str = "vendedor", ar: str = "ms", **extra) -> int:
    """O Admin Master cria a pessoa em Configurações > Usuários, no quadro da marca dela."""
    r = cliente.post("/configuracoes/usuarios/0", data={
        "csrf": csrf_de(cliente.get("/minha-conta").text), "ar": str(_ars()[ar]), "nome": f"Pessoa Nova {perfil}",
        "email": email, "perfil": perfil, "ativo": "on", "senha": PROVISORIA, "equipe_id": "", **extra})
    assert "No primeiro login, o sistema pede para ela trocar essa senha por uma só dela." in r.text
    with sessao() as db:
        return db.execute(select(Usuario.id).where(Usuario.email == email)).scalar_one()


def _editar_pela_tela(cliente, uid: int, senha: str, **campos):
    with sessao() as db:
        u = db.get(Usuario, uid)
        dados = {"nome": u.nome, "email": u.email, "perfil": u.perfil, "ativo": "on" if u.ativo else ""}
    return cliente.post(f"/configuracoes/usuarios/{uid}", data={
        "csrf": csrf_de(cliente.get("/minha-conta").text), **dados, "senha": senha, **campos})


def _criar_direto(email: str, senha: str, perfil: str = "vendedor", ar: str = "ms") -> int:
    """Pessoa que já existia antes da troca obrigatória (a coluna nova nasce False para ela)."""
    tenant = _ars()[ar]
    with sessao() as db:
        u = Usuario(nome="Pessoa Antiga", email=email, senha_hash=resumir_senha(senha), perfil=perfil, tenant_id=tenant)
        db.add(u)
        db.flush()
        return u.id


def _linha_na_lista(pagina: str, email: str) -> str:
    """A linha da pessoa em Configurações > Usuários (nome, papel, equipe e situação)."""
    return re.search(r'<tr class="linha-usuario" data-busca="[^"]*' + re.escape(email) + r'">(.*?)</tr>', pagina,
                     re.S).group(1)


def _entrar(c: TestClient, email: str, senha: str = PROVISORIA):
    return c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": senha},
                  follow_redirects=False)


def _trocar(c: TestClient, nova: str, nova2: str | None = None):
    pagina = c.get("/trocar-senha", follow_redirects=False)
    assert pagina.status_code == 200, pagina.headers.get("location")
    return c.post("/trocar-senha", data={"csrf": csrf_de(pagina.text), "nova": nova,
                                         "nova2": nova if nova2 is None else nova2}, follow_redirects=False)


@pytest.mark.parametrize("perfil, ar", [("vendedor", "ms"), ("funcionario", "grupo-certy"), ("gestor", AR_ELETRONICA),
                                        ("admin", "grupo-certy")])
def test_pessoa_nova_troca_a_senha_logo_depois_do_primeiro_login(cliente, perfil, ar):
    email = f"nova.{perfil}.{ar}@troca.com.br"
    uid = _criar_pela_tela(cliente, email, perfil, ar)
    assert _dados(uid)["provisoria"] is True and _dados(uid)["ar"] == _ars()[ar]
    assert any("senha provisória" in d for d, _ in _registros(uid, "salvou_usuario"))
    with TestClient(app) as c, TestClient(app) as outro_navegador:
        r = _entrar(c, email)
        assert r.status_code == 303 and r.headers["location"] == "/trocar-senha"
        assert any("senha provisória" in d for d, _ in _registros(uid, "login"))
        # nenhuma outra tela abre antes da troca (nem as que a pessoa não poderia ver: a troca vem primeiro)
        for caminho in ("/", "/leads", "/campanhas", "/conversas", "/minha-conta", "/configuracoes?aba=usuarios",
                        "/notificacoes", "/master"):
            r = c.get(caminho, follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/trocar-senha", caminho
        r = c.post("/minha-conta/senha", data={"csrf": "x", "atual": PROVISORIA, "nova": NOVA, "nova2": NOVA},
                   headers={"x-csrf-token": csrf_de(c.get("/trocar-senha").text)}, follow_redirects=False)
        assert r.status_code == 403 and "Troque a sua senha" in r.json()["erro"]  # chamada da tela (JSON)
        assert _dados(uid)["provisoria"] is True

        pagina = c.get("/trocar-senha").text
        assert "Troque a sua senha." in pagina and email in pagina
        assert 'class="menu"' not in pagina and 'href="/leads"' not in pagina  # sem o menu do sistema
        assert DA_MS.search(pagina) is None

        # a mesma pessoa entrou em outro navegador com a senha recebida: depois da troca, ele sai
        assert _entrar(outro_navegador, email).headers["location"] == "/trocar-senha"

        # as regras de senha de sempre, e não pode ser a recebida
        r = _trocar(c, NOVA, "OutraSenha789")
        assert r.status_code == 400 and "As duas senhas não são iguais" in r.text
        r = _trocar(c, "curta12")
        assert r.status_code == 400 and "pelo menos 8 caracteres" in r.text
        r = _trocar(c, "somenteletras")
        assert r.status_code == 400 and "Use letras e números" in r.text
        r = _trocar(c, PROVISORIA)
        assert r.status_code == 400 and "diferente da senha que você recebeu" in r.text
        antes = _dados(uid)
        assert antes["provisoria"] is True and senha_confere(PROVISORIA, antes["hash"])

        r = _trocar(c, NOVA)
        assert r.status_code == 303 and r.headers["location"] == "/"
        depois = _dados(uid)
        assert depois["provisoria"] is False and depois["versao"] == antes["versao"] + 1
        assert senha_confere(NOVA, depois["hash"]) and not senha_confere(PROVISORIA, depois["hash"])
        assert depois["hash"].startswith("pbkdf2_sha256$")  # guardada como as outras
        conta = c.get("/minha-conta", follow_redirects=False)
        assert conta.status_code == 200 and "Sua senha nova já está valendo" in conta.text
        assert c.get("/", follow_redirects=False).status_code == 200
        assert c.get("/trocar-senha", follow_redirects=False).headers["location"] == "/"  # já trocou: não volta
        assert outro_navegador.get("/", follow_redirects=False).headers["location"] == "/login"

        # registro de atividades: na marca da pessoa
        assert [ar_do_registro for _, ar_do_registro in _registros(uid, "trocou_senha_provisoria")] == [_ars()[ar]]

        c.get("/sair")
        assert _entrar(c, email).status_code == 401  # a senha recebida não vale mais
        r = _entrar(c, email, NOVA)
        assert r.status_code == 303 and r.headers["location"] == "/"  # da 2ª vez, direto para o sistema


def test_parceiro_do_portal_tambem_troca_a_senha(cliente):
    with sessao() as db:
        parceiro = Parceiro(escritorio="Escritório da Troca de Senha", status="ATIVO", tenant_id=_ars()["ms"])
        db.add(parceiro)
        db.flush()
        parceiro_id = parceiro.id
    email = "parceiro.troca@troca.com.br"
    _criar_pela_tela(cliente, email, "parceiro", "ms", parceiro_id=str(parceiro_id))
    with TestClient(app) as c:
        assert _entrar(c, email).headers["location"] == "/trocar-senha"
        assert c.get("/portal", follow_redirects=False).headers["location"] == "/trocar-senha"
        assert _trocar(c, NOVA).headers["location"] == "/portal"
        assert c.get("/portal", follow_redirects=False).status_code == 200


def test_quem_ja_usa_e_o_master_nao_trocam_e_a_senha_redefinida_pelo_admin_vira_provisoria(cliente):
    with sessao() as db:  # o Admin Master escolheu a própria senha no /primeiro-acesso
        master = db.execute(select(Usuario).where(Usuario.master.is_(True))).scalars().first()
        assert master.senha_provisoria is False
    assert cliente.get("/", follow_redirects=False).status_code == 200
    assert cliente.get("/trocar-senha", follow_redirects=False).headers["location"] == "/"

    email = "ja.usa@troca.com.br"
    uid = _criar_direto(email, "SenhaAntiga123")
    assert _dados(uid)["provisoria"] is False
    with TestClient(app) as c:
        assert _entrar(c, email, "SenhaAntiga123").headers["location"] == "/"  # já usava: entra direto
        assert c.get("/minha-conta", follow_redirects=False).status_code == 200

        # o administrador muda só o nome: a senha continua sendo dela
        _editar_pela_tela(cliente, uid, "", nome="Pessoa Antiga Silva")
        assert _dados(uid)["provisoria"] is False
        assert c.get("/minha-conta", follow_redirects=False).status_code == 200

        # o administrador cria uma senha nova: a sessão aberta cai e, no próximo login, a pessoa troca
        r = _editar_pela_tela(cliente, uid, PROVISORIA)
        assert "A senha nova é provisória: no próximo login, o sistema pede para a pessoa trocar." in r.text
        assert _dados(uid)["provisoria"] is True
        assert any("senha provisória" in d for d, _ in _registros(uid, "salvou_usuario"))
        assert c.get("/minha-conta", follow_redirects=False).headers["location"] == "/login"
        assert _entrar(c, email, "SenhaAntiga123").status_code == 401
        assert _entrar(c, email).headers["location"] == "/trocar-senha"
        assert _trocar(c, NOVA).headers["location"] == "/"
    linha = _linha_na_lista(cliente.get("/configuracoes?aba=usuarios").text, email)
    assert "Pessoa Antiga Silva" in linha and "troca a senha no login" not in linha


def test_admin_que_troca_a_propria_senha_na_tela_de_usuarios_nao_fica_com_senha_provisoria(cliente):
    email = "admin.propria@troca.com.br"
    uid = _criar_direto(email, "SenhaAdmin123", perfil="admin", ar="grupo-certy")
    with TestClient(app) as c:
        assert _entrar(c, email, "SenhaAdmin123").headers["location"] == "/"
        pagina = c.get("/configuracoes?aba=usuarios").text
        assert "provisória: no primeiro login, o sistema pede para a pessoa trocar" in " ".join(pagina.split())
        r = _editar_pela_tela(c, uid, "OutraDoAdmin789")
        assert r.status_code in (200, 303)
    dados = _dados(uid)
    assert senha_confere("OutraDoAdmin789", dados["hash"]) and dados["provisoria"] is False


def test_lista_de_usuarios_mostra_quem_ainda_vai_trocar(cliente):
    _criar_pela_tela(cliente, "lista.troca@troca.com.br", "vendedor", "grupo-certy")
    linha = _linha_na_lista(cliente.get("/configuracoes?aba=usuarios").text, "lista.troca@troca.com.br")
    assert "troca a senha no login" in linha


def test_com_o_codigo_do_celular_a_troca_vem_depois_do_codigo(cliente, monkeypatch):
    monkeypatch.setattr(config, "EXIGIR_2FA", True)
    email = "gestor.troca.2fa@troca.com.br"
    uid = _criar_pela_tela(cliente, email, "gestor", "grupo-certy")
    with TestClient(app) as c:
        assert _entrar(c, email).headers["location"] == "/login/ativar-codigo"
        assert c.get("/trocar-senha", follow_redirects=False).headers["location"] == "/login"  # sem o código, não
        pagina = c.get("/login/ativar-codigo").text
        chave = re.search(r'class="chave-2fa">([A-Z2-7 ]+)<', pagina).group(1).replace(" ", "")
        passo = dois_fatores.passo_atual()
        r = c.post("/login/ativar-codigo", data={"csrf": csrf_de(pagina), "codigo": dois_fatores.codigo(chave, passo)})
        codigos = re.findall(r"<span>([A-Z0-9]{4}-[A-Z0-9]{4})</span>", r.text)
        assert len(codigos) == 8 and 'href="/trocar-senha"' in r.text  # "Já guardei, continuar" leva para a troca
        assert c.get("/", follow_redirects=False).headers["location"] == "/trocar-senha"
        assert _trocar(c, NOVA).headers["location"] == "/"
        assert c.get("/", follow_redirects=False).status_code == 200
        c.get("/sair")
        # da próxima vez: senha nova e código, direto para o sistema
        assert _entrar(c, email, NOVA).headers["location"] == "/login/codigo"
        r = c.post("/login/codigo", data={"csrf": csrf_de(c.get("/login/codigo").text),
                                          "codigo": dois_fatores.codigo(chave, passo + 1)}, follow_redirects=False)
        assert r.headers["location"] == "/"

    # o administrador cria outra senha (o código do celular continua ligado): primeiro o código, depois a troca
    _editar_pela_tela(cliente, uid, PROVISORIA)
    with TestClient(app) as c:
        assert _entrar(c, email).headers["location"] == "/login/codigo"
        assert c.get("/trocar-senha", follow_redirects=False).headers["location"] == "/login"
        r = c.post("/login/codigo", data={"csrf": csrf_de(c.get("/login/codigo").text), "codigo": codigos[0]},
                   follow_redirects=False)
        assert r.headers["location"] == "/trocar-senha"
        assert _trocar(c, "OutraNova789").headers["location"] == "/"
    assert _dados(uid)["provisoria"] is False


def test_a_trava_de_tentativas_vale_tambem_para_a_senha_provisoria(cliente):
    email = "trava.troca@troca.com.br"
    _criar_pela_tela(cliente, email)
    with TestClient(app) as c:
        for _ in range(5):
            r = _entrar(c, email, "errada-123")
        assert r.status_code == 429 and "Entrada travada por segurança" in r.text
        assert _entrar(c, email).status_code == 429  # travada vale também para a senha certa
    with sessao() as db:  # passam os 15 minutos
        for tentativa in db.execute(select(TentativaErrada)).scalars():
            tentativa.criado_em -= timedelta(minutes=16)
    with TestClient(app) as c:
        assert _entrar(c, email).headers["location"] == "/trocar-senha"


def test_redefinir_senha_bat_deixa_a_senha_provisoria(cliente, monkeypatch):
    import redefinir_senha

    email = "bat.troca@troca.com.br"
    uid = _criar_direto(email, "SenhaAntiga123", perfil="gestor", ar="grupo-certy")
    with sessao() as db:
        dois_fatores.ativar(db.get(Usuario, uid), dois_fatores.novo_segredo(), dois_fatores.passo_atual())
    monkeypatch.setattr("builtins.input", lambda *_: str(uid))
    monkeypatch.setattr("getpass.getpass", lambda *_: PROVISORIA)
    assert redefinir_senha.main(["--aqui"]) == 0  # o banco dos testes; o servidor tem os testes dele (test_redefinir_senha)
    with sessao() as db:
        u = db.get(Usuario, uid)
        assert u.senha_provisoria is True and not u.totp_ativo and senha_confere(PROVISORIA, u.senha_hash)
    assert _registros(uid, "redefiniu_senha")
    with TestClient(app) as c:
        assert _entrar(c, email).headers["location"] == "/trocar-senha"
        assert _trocar(c, NOVA).headers["location"] == "/"


def test_sem_login_a_troca_manda_para_a_entrada():
    with TestClient(app) as c:
        assert c.get("/trocar-senha", follow_redirects=False).headers["location"] == "/login"


def test_quando_a_coluna_nasce_so_quem_nunca_entrou_fica_com_a_senha_provisoria(monkeypatch, tmp_path):
    """A publicação cria a coluna no banco do sistema no ar: quem já entrou alguma vez não troca; quem foi cadastrado e
    nunca entrou está com a senha que o administrador escolheu e troca no primeiro login; o Admin Master, nunca."""
    motor_antigo = create_engine(f"sqlite:///{(tmp_path / 'antes.db').as_posix()}")
    with motor_antigo.begin() as con:
        con.execute(text("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nome VARCHAR(120), email VARCHAR(160), "
                         "senha_hash VARCHAR(200), perfil VARCHAR(20), ativo BOOLEAN, master BOOLEAN, "
                         "ultimo_login DATETIME)"))
        con.execute(text("INSERT INTO usuarios (id, nome, email, senha_hash, perfil, ativo, master, ultimo_login) "
                         "VALUES (1, 'Master', 'm@x.com', 'h', 'admin', 1, 1, NULL), "
                         "(2, 'Ja usa', 'u@x.com', 'h', 'vendedor', 1, 0, '2026-11-20 10:00:00'), "
                         "(3, 'Nunca entrou', 'n@x.com', 'h', 'vendedor', 1, 0, NULL)"))
    monkeypatch.setattr(banco, "motor", motor_antigo)
    try:
        assert "usuarios.senha_provisoria" in banco.migrar_colunas()
        with motor_antigo.connect() as con:
            assert dict(con.execute(text("SELECT id, senha_provisoria FROM usuarios")).all()) == {1: 0, 2: 0, 3: 1}
        with motor_antigo.begin() as con:  # a pessoa 3 trocou a senha
            con.execute(text("UPDATE usuarios SET senha_provisoria = 0 WHERE id = 3"))
        assert banco.migrar_colunas() == []  # a próxima publicação não marca ninguém de novo
        with motor_antigo.connect() as con:
            assert con.execute(text("SELECT senha_provisoria FROM usuarios WHERE id = 3")).scalar() == 0
    finally:
        motor_antigo.dispose()
