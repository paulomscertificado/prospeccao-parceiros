"""Testes do e-mail de envio das campanhas (domínio @mscertificados.com.br). Nada sai de verdade."""

import pytest
from sqlalchemy import select

from app import arquivo_env, config
from app.banco import sessao
from app.integracoes import dns_email, email_smtp
from app.leads_servico import criar_lead
from app.modelos import Lead, Usuario

CHAVES = ["SMTP_HOST", "SMTP_PORTA", "SMTP_USUARIO", "SMTP_SENHA", "SMTP_REMETENTE", "SMTP_TLS", "SMTP_RESPONDER_PARA",
          "IMAP_HOST", "IMAP_PORTA", "IMAP_USUARIO", "IMAP_SENHA"]


@pytest.fixture()
def env_temporario(tmp_path, monkeypatch):
    """O .env de verdade nunca é tocado; config e variáveis voltam ao normal no fim."""
    arquivo = tmp_path / ".env"
    arquivo.write_text("# teste\nSMTP_HOST=\nOUTRA_CHAVE=fica\n", encoding="utf-8")
    monkeypatch.setattr(arquivo_env, "ARQUIVO", arquivo)
    for chave in CHAVES:
        monkeypatch.setenv(chave, "")
        atributo = arquivo_env.CAMPOS[chave][0]
        monkeypatch.setattr(config, atributo, getattr(config, atributo))
    monkeypatch.setattr(config, "EMAIL_DOMINIO", "mscertificados.com.br")
    return arquivo


class SMTPFalso:
    enviados = []

    def __init__(self, host, porta, timeout=30):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, usuario, senha):
        self.usuario = usuario

    def send_message(self, msg):
        SMTPFalso.enviados.append((self.usuario, msg))


def _csrf(cliente):
    return cliente.get("/minha-conta").text.split('name="csrf" content="')[1].split('"')[0]


def test_so_aceita_remetente_do_dominio(cliente, env_temporario):
    csrf = _csrf(cliente)
    cliente.post("/configuracoes/email", data={"csrf": csrf, "endereco": "fulano@gmail.com", "senha": "abcd efgh ijkl mnop"})
    assert "fulano@gmail.com" not in env_temporario.read_text(encoding="utf-8")
    assert not email_smtp.configurado()
    # Mesmo editando o .env à mão, o envio recusa remetente de outro domínio
    config.SMTP_HOST, config.SMTP_REMETENTE, config.SMTP_SENHA = "smtp.gmail.com", "x@outrodominio.com", "x"
    with pytest.raises(email_smtp.ErroEmail, match="@mscertificados.com.br"):
        email_smtp.enviar("alguem@exemplo.com", "oi", "oi")


def test_configura_google_workspace_e_envia_teste(cliente, env_temporario, monkeypatch):
    monkeypatch.setattr(email_smtp.smtplib, "SMTP", SMTPFalso)
    SMTPFalso.enviados = []
    monkeypatch.setattr(dns_email, "verificar", lambda d: {"provedor": "Google", "google": True, "itens": []})
    csrf = _csrf(cliente)
    cliente.post("/configuracoes/email", data={
        "csrf": csrf, "endereco": "Parcerias@MSCertificados.com.br", "nome": "MS Certificação Digital – Parcerias",
        "senha": "abcd efgh ijkl mnop", "provedor": "google", "ler_respostas": "on"})
    texto = env_temporario.read_text(encoding="utf-8")
    assert "SMTP_HOST=smtp.gmail.com" in texto and "SMTP_SENHA=abcdefghijklmnop" in texto
    assert 'SMTP_REMETENTE="MS Certificação Digital – Parcerias <parcerias@mscertificados.com.br>"' in texto
    assert "IMAP_HOST=imap.gmail.com" in texto and "OUTRA_CHAVE=fica" in texto  # o resto do .env continua igual
    assert config.SMTP_HOST == "smtp.gmail.com" and email_smtp.configurado()  # vale na hora, sem reiniciar
    pagina = cliente.get("/configuracoes?aba=email").text
    assert "parcerias@mscertificados.com.br" in pagina and "abcdefghijklmnop" not in pagina  # senha nunca aparece
    cliente.post("/configuracoes/email/testar", data={"csrf": csrf, "para": "maria@exemplo.com"})
    usuario, msg = SMTPFalso.enviados[-1]
    assert usuario == "parcerias@mscertificados.com.br"
    assert "parcerias@mscertificados.com.br" in msg["From"] and "Parcerias" in msg["From"]
    assert msg["To"] == "maria@exemplo.com" and "mailto:parcerias@mscertificados.com.br" in msg["List-Unsubscribe"]
    # Salvar de novo sem senha mantém a senha atual
    cliente.post("/configuracoes/email", data={"csrf": csrf, "endereco": "parcerias@mscertificados.com.br",
                                               "senha": "", "provedor": "google"})
    assert config.SMTP_SENHA == "abcdefghijklmnop"


def test_descadastro_em_um_clique(cliente, monkeypatch):
    monkeypatch.setattr(config, "URL_PUBLICA", "https://parceiros.mscertificados.com.br")
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        lead, _ = criar_lead(db, {"empresa": "Contábil Descadastro", "email": "x@descadastro-teste.com.br"}, admin)
        lead_id = lead.id
    link = email_smtp.link_descadastro(lead_id)
    assert link.startswith("https://parceiros.mscertificados.com.br/descadastrar/")
    assert "Descadastre-se em 1 clique" in email_smtp.rodape(lead_id)
    caminho = link.replace(config.URL_PUBLICA, "")
    assert cliente.get(caminho).status_code == 200  # abrir o link só pergunta
    with sessao() as db:
        assert not db.get(Lead, lead_id).opt_out
    assert cliente.post(caminho).status_code == 200
    with sessao() as db:
        assert db.get(Lead, lead_id).opt_out
    assert cliente.post(f"/descadastrar/{lead_id}/assinaturaerrada").status_code == 404
    monkeypatch.setattr(config, "URL_PUBLICA", "http://localhost:8001")
    assert email_smtp.link_descadastro(lead_id) == "" and "palavra SAIR" in email_smtp.rodape(lead_id)


def test_verificacao_do_dns(monkeypatch):
    respostas = {
        ("mscertificados.com.br", "MX"): [{"type": 15, "data": "1 aspmx.l.google.com."}],
        ("mscertificados.com.br", "TXT"): [{"type": 16, "data": "v=spf1 include:_spf.google.com ~all"}],
    }

    class Resposta:
        def __init__(self, dados):
            self.dados = dados

        def json(self):
            return {"Answer": self.dados} if self.dados else {}

    monkeypatch.setattr(dns_email.httpx, "get", lambda url, params, timeout: Resposta(respostas.get((params["name"], params["type"]))))
    r = dns_email.verificar("mscertificados.com.br")
    situacao = {nome: ok for nome, ok, _, _ in r["itens"]}
    assert r["google"] and situacao == {"SPF": True, "DKIM": False, "DMARC": False}
    assert "Autenticar e-mail" in r["itens"][1][3] and "_dmarc.mscertificados.com.br" in r["itens"][2][3]


def test_senha_normal_do_google_e_recusada_com_explicacao(cliente, env_temporario, monkeypatch):
    csrf = _csrf(cliente)
    r = cliente.post("/configuracoes/email", data={"csrf": csrf, "endereco": "contato@mscertificados.com.br",
                                                   "senha": "Senha12Conta", "provedor": "google"})
    assert "16 letras" in r.text and "12 caracteres" in r.text
    assert "SMTP_SENHA=Senha12Conta" not in env_temporario.read_text(encoding="utf-8")


def test_google_fechando_a_conexao_vira_aviso_de_senha(cliente, env_temporario, monkeypatch):
    import smtplib

    class SMTPQueDesliga(SMTPFalso):
        def login(self, usuario, senha):
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr(email_smtp.smtplib, "SMTP", SMTPQueDesliga)
    config.SMTP_HOST, config.SMTP_PORTA, config.SMTP_SENHA = "smtp.gmail.com", 587, "senhaerrada"
    config.SMTP_REMETENTE = "MS <contato@mscertificados.com.br>"
    with pytest.raises(email_smtp.ErroEmail, match="senha de app \(16 letras\) foi criada ESTANDO LOGADO"):
        email_smtp.enviar("alguem@exemplo.com", "oi", "oi")


def test_email_de_envio_apelido_entra_com_a_conta_dona(cliente, env_temporario, monkeypatch):
    monkeypatch.setattr(email_smtp.smtplib, "SMTP", SMTPFalso)
    SMTPFalso.enviados = []
    monkeypatch.setattr(dns_email, "verificar", lambda d: {"provedor": "Google", "google": True, "itens": []})
    csrf = _csrf(cliente)
    cliente.post("/configuracoes/email", data={"csrf": csrf, "endereco": "contato@mscertificados.com.br",
                                               "usuario_login": "paulo@mscertificados.com.br",
                                               "senha": "abcd efgh ijkl mnop", "provedor": "google", "ler_respostas": "on"})
    texto = env_temporario.read_text(encoding="utf-8")
    assert "SMTP_USUARIO=paulo@mscertificados.com.br" in texto and "IMAP_USUARIO=paulo@mscertificados.com.br" in texto
    assert "contato@mscertificados.com.br" in texto  # o remetente continua o contato@
    cliente.post("/configuracoes/email/testar", data={"csrf": csrf, "para": "maria@exemplo.com"})
    usuario, msg = SMTPFalso.enviados[-1]
    assert usuario == "paulo@mscertificados.com.br" and "contato@mscertificados.com.br" in msg["From"]
    assert 'value="paulo@mscertificados.com.br"' in cliente.get("/configuracoes?aba=email").text
