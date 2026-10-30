"""E-mail pelo próprio domínio e servidor (permissão email.outro_dominio: gestor e admin)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import arquivo_env, config, contas_email
from app.banco import sessao
from app.integracoes import dns_email, email_imap, email_smtp
from app.main import app
from app.modelos import ContaEmail, ExcecaoPermissao, Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de

SENHA = "senhaDominio123"
SMTP_FALSO = []


class SmtpFalso:
    """Servidor de envio de mentira: guarda onde conectou e quem enviou."""

    def __init__(self, host, porta, **k):
        SMTP_FALSO.append(("conectou", host, porta))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, **k):
        pass

    def login(self, usuario, senha):
        SMTP_FALSO.append(("login", usuario, senha))

    def send_message(self, msg):
        SMTP_FALSO.append(("enviou", msg["From"], msg["To"]))


@pytest.fixture(autouse=True)
def arrumar(monkeypatch):
    monkeypatch.setattr(arquivo_env, "carregar_do_banco", lambda forcar=False: None)
    monkeypatch.setattr(config, "EMAIL_DOMINIO", "mscertificados.com.br")
    monkeypatch.setattr(email_smtp.smtplib, "SMTP", SmtpFalso)
    monkeypatch.setattr(email_smtp.smtplib, "SMTP_SSL", SmtpFalso)

    def sem_internet(*a, **k):
        raise OSError("teste sem internet")

    monkeypatch.setattr(email_imap.imaplib, "IMAP4_SSL", sem_internet)
    monkeypatch.setattr(dns_email, "_mx", lambda d: ["mail.protection.outlook.com"])
    monkeypatch.setattr(dns_email, "_txt", lambda nome: ["v=spf1 include:spf.protection.outlook.com -all"]
                        if nome == "contabil-gestor.com.br" else [])
    SMTP_FALSO.clear()


def _pessoa(email, perfil) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if u is None:
            u = Usuario(nome=email.split("@")[0].title(), email=email, senha_hash=resumir_senha(SENHA), perfil=perfil)
            db.add(u)
            db.flush()
        return u.id


def _entrar(email) -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _salvar(c: TestClient, **dados):
    return c.post("/email/minha", data={"csrf": csrf_de(c.get("/email").text), "nome_remetente": "Teste", **dados})


def _conta_de(uid) -> ContaEmail | None:
    with sessao() as db:
        c = db.execute(select(ContaEmail).where(ContaEmail.dono_id == uid)).scalars().first()
        if c is not None:
            db.expunge(c)
        return c


def test_gestor_cadastra_dominio_e_servidor_proprios_e_envia_por_ele(cliente):
    uid = _pessoa("gestor.dominio@teste.com.br", "gestor")
    c = _entrar("gestor.dominio@teste.com.br")
    pagina = c.get("/email").text
    assert "Outro provedor" in pagina
    _salvar(c, provedor="outro", endereco="joao@contabil-gestor.com.br", senha="Senha Forte 1",
            smtp_host="smtp.office365.com", smtp_porta="587", imap_host="outlook.office365.com", imap_porta="993",
            ler_respostas="on")
    conta = _conta_de(uid)
    assert conta and conta.dominio_livre and conta.smtp_host == "smtp.office365.com" and conta.smtp_porta == 587
    assert conta.imap_host == "outlook.office365.com"
    with sessao() as db:
        email_smtp.enviar("lead@cliente.com.br", "Oi", "Olá", conta=db.get(ContaEmail, conta.id))
    assert ("conectou", "smtp.office365.com", 587) in SMTP_FALSO
    assert ("login", "joao@contabil-gestor.com.br", "Senha Forte 1") in SMTP_FALSO  # senha livre (não só app Google)
    assert any(p[0] == "enviou" and "joao@contabil-gestor.com.br" in p[1] for p in SMTP_FALSO)
    # a tela confere o SPF/DKIM/DMARC do domínio dele
    pagina = c.get("/email").text
    assert "O domínio contabil-gestor.com.br está pronto" in pagina and "Microsoft 365" in pagina


def test_sem_a_permissao_continua_so_o_dominio_da_ms(cliente):
    uid = _pessoa("func.dominio@teste.com.br", "funcionario")
    c = _entrar("func.dominio@teste.com.br")
    assert "Outro provedor" not in c.get("/email").text
    _salvar(c, endereco="func@outraempresa.com.br", senha="abcdefghijklmnop")
    _salvar(c, provedor="outro", endereco="func@mscertificados.com.br", senha="qualquer",
            smtp_host="smtp.outraempresa.com.br", smtp_porta="587")
    assert _conta_de(uid) is None  # nenhuma das duas foi aceita (o servidor confere, não só a tela)


def test_dominio_gratuito_e_servidor_interno_sao_recusados(cliente):
    uid = _pessoa("gestor2.dominio@teste.com.br", "gestor")
    c = _entrar("gestor2.dominio@teste.com.br")
    _salvar(c, endereco="fulano@gmail.com", senha="abcdefghijklmnop")
    assert _conta_de(uid) is None
    for host in ("localhost", "127.0.0.1", "10.0.0.5", "smtp.interno.local", "semponto"):
        _salvar(c, provedor="outro", endereco="g2@contabil-gestor2.com.br", senha="x", smtp_host=host,
                smtp_porta="587")
        assert _conta_de(uid) is None, host
    _salvar(c, provedor="outro", endereco="g2@contabil-gestor2.com.br", senha="x", smtp_host="smtp.hostinger.com",
            smtp_porta="2000")
    assert _conta_de(uid) is None  # porta que não é de envio de e-mail


def test_permissao_retirada_bloqueia_o_envio_de_fora(cliente):
    uid = _pessoa("gestor3.dominio@teste.com.br", "gestor")
    c = _entrar("gestor3.dominio@teste.com.br")
    _salvar(c, provedor="outro", endereco="g3@contabil-gestor3.com.br", senha="x", smtp_host="smtp.hostinger.com",
            smtp_porta="465")
    conta = _conta_de(uid)
    assert conta and conta.smtp_porta == 465
    with sessao() as db:
        db.add(ExcecaoPermissao(usuario_id=uid, permissao="email.outro_dominio", efeito="negar"))
    try:
        with sessao() as db:
            with pytest.raises(email_smtp.ErroEmail, match="domínio"):
                email_smtp.enviar("lead@cliente.com.br", "Oi", "Olá", conta=db.get(ContaEmail, conta.id))
        assert not any(p[0] == "enviou" for p in SMTP_FALSO)
    finally:
        with sessao() as db:
            db.execute(delete(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == uid))


def test_gestor_com_google_da_ms_continua_igual(cliente):
    uid = _pessoa("gestor4.dominio@teste.com.br", "gestor")
    c = _entrar("gestor4.dominio@teste.com.br")
    _salvar(c, provedor="google", endereco="gestor4@mscertificados.com.br", senha="abcd efgh ijkl mnop")
    conta = _conta_de(uid)
    assert conta and not conta.dominio_livre and conta.smtp_host == contas_email.GOOGLE["smtp_host"]
    assert "está pronto para não cair no spam" not in c.get("/email").text  # o da MS fica em Configurações
