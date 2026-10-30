"""Verificação em 2 etapas (código do celular) para administrador e gestor."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config, dois_fatores
from app.banco import sessao
from app.main import app
from app.modelos import Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de

SENHA = "senhaGestor123"


@pytest.fixture()
def com_2fa(monkeypatch):
    monkeypatch.setattr(config, "EXIGIR_2FA", True)


def _criar(email: str, perfil: str) -> int:
    with sessao() as db:
        u = Usuario(nome=f"Pessoa {perfil}", email=email, senha_hash=resumir_senha(SENHA), perfil=perfil)
        db.add(u)
        db.flush()
        return u.id


def _senha(c: TestClient, email: str):
    return c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA},
                  follow_redirects=False)


def _segredo(uid: int) -> str:
    with sessao() as db:
        return dois_fatores.segredo_de(db.get(Usuario, uid))


def test_codigo_totp_bate_com_o_padrao():
    # vetor do RFC 6238 (segredo "12345678901234567890", instante 59 s → 94287082, 6 últimos dígitos)
    import base64

    segredo = base64.b32encode(b"12345678901234567890").decode()
    assert dois_fatores.codigo(segredo, dois_fatores.passo_atual(59)) == "287082"
    passo = dois_fatores.passo_atual()
    assert dois_fatores.conferir(segredo, dois_fatores.codigo(segredo, passo)) == passo
    assert dois_fatores.conferir(segredo, dois_fatores.codigo(segredo, passo), ultimo_passo=passo) is None  # já usado
    assert dois_fatores.conferir(segredo, "12345") is None


def test_gestor_configura_entra_com_codigo_e_recuperacao(cliente, com_2fa):
    uid = _criar("gestor.2fa@teste.com.br", "gestor")
    with TestClient(app) as c:
        r = _senha(c, "gestor.2fa@teste.com.br")
        assert r.headers["location"] == "/login/ativar-codigo"
        assert c.get("/", follow_redirects=False).headers["location"] == "/login"  # sem o código, não entra
        pagina = c.get("/login/ativar-codigo").text
        assert "<svg" in pagina and "Google Authenticator" in pagina
        chave = re.search(r'class="chave-2fa">([A-Z2-7 ]+)<', pagina).group(1).replace(" ", "")
        csrf = csrf_de(pagina)
        errado = c.post("/login/ativar-codigo", data={"csrf": csrf, "codigo": "000000"}).text
        assert "Código errado" in errado and chave in errado.replace(" ", "")  # mesma chave: a pessoa só redigita
        passo = dois_fatores.passo_atual()
        r = c.post("/login/ativar-codigo", data={"csrf": csrf, "codigo": dois_fatores.codigo(chave, passo)})
        codigos = re.findall(r"<span>([A-Z0-9]{4}-[A-Z0-9]{4})</span>", r.text)
        assert len(codigos) == 8
        assert c.get("/", follow_redirects=False).status_code == 200
        c.get("/sair")

        # Login de novo: pede o código; o mesmo código (já usado) não vale
        assert _senha(c, "gestor.2fa@teste.com.br").headers["location"] == "/login/codigo"
        csrf = csrf_de(c.get("/login/codigo").text)
        r = c.post("/login/codigo", data={"csrf": csrf, "codigo": dois_fatores.codigo(chave, passo)})
        assert r.status_code == 401
        r = c.post("/login/codigo", data={"csrf": csrf, "codigo": dois_fatores.codigo(chave, passo + 1),
                                          "lembrar": "on"}, follow_redirects=False)
        assert r.status_code == 303 and dois_fatores.COOKIE_APARELHO in r.headers.get("set-cookie", "")
        c.get("/sair")

        # Computador lembrado: entra só com a senha
        assert _senha(c, "gestor.2fa@teste.com.br").headers["location"] == "/"
        c.get("/sair")
        c.cookies.delete(dois_fatores.COOKIE_APARELHO)

        # Código de recuperação: vale uma vez
        _senha(c, "gestor.2fa@teste.com.br")
        csrf = csrf_de(c.get("/login/codigo").text)
        r = c.post("/login/codigo", data={"csrf": csrf, "codigo": codigos[0].lower()}, follow_redirects=False)
        assert r.status_code == 303
        c.get("/sair")
        _senha(c, "gestor.2fa@teste.com.br")
        csrf = csrf_de(c.get("/login/codigo").text)
        assert c.post("/login/codigo", data={"csrf": csrf, "codigo": codigos[0]}).status_code == 401
    with sessao() as db:
        assert dois_fatores.codigos_restantes(db.get(Usuario, uid)) == 7
    assert _segredo(uid) == chave


def test_vendedor_nao_precisa_e_admin_zera_o_2fa(cliente, csrf, com_2fa):
    _criar("vendedor.2fa@teste.com.br", "vendedor")
    with TestClient(app) as c:
        assert _senha(c, "vendedor.2fa@teste.com.br").headers["location"] == "/"
    uid = _criar("gestor.zerar@teste.com.br", "gestor")
    with sessao() as db:
        u = db.get(Usuario, uid)
        dois_fatores.ativar(u, dois_fatores.novo_segredo(), dois_fatores.passo_atual())
    pagina = cliente.get("/configuracoes?aba=usuarios").text
    assert f'action="/configuracoes/usuarios/{uid}/zerar-2fa"' in pagina
    cliente.post(f"/configuracoes/usuarios/{uid}/zerar-2fa", data={"csrf": csrf})
    with sessao() as db:
        u = db.get(Usuario, uid)
        assert not u.totp_ativo and u.totp_segredo == ""
    with TestClient(app) as c:  # zerado: no próximo login lê um QR code novo
        assert _senha(c, "gestor.zerar@teste.com.br").headers["location"] == "/login/ativar-codigo"


def test_sessao_antiga_de_gestor_precisa_entrar_de_novo(cliente, com_2fa):
    """Sessão aberta antes do 2FA ser exigido (sem a marca "2fa"): volta para o login."""
    import time
    from types import SimpleNamespace

    from app.seguranca import PrecisaLogin, usuario_logado

    uid = _criar("gestor.antigo@teste.com.br", "gestor")
    with sessao() as db:
        versao = db.get(Usuario, uid).versao_sessao
        antiga = SimpleNamespace(session={"usuario_id": uid, "versao": versao, "ultimo_uso": int(time.time())},
                                 state=SimpleNamespace())
        with pytest.raises(PrecisaLogin):
            usuario_logado(antiga, db)
        nova = SimpleNamespace(session={"usuario_id": uid, "versao": versao, "ultimo_uso": int(time.time()),
                                        "2fa": True}, state=SimpleNamespace())
        assert usuario_logado(nova, db).id == uid
