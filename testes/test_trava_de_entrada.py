"""Trava da entrada (pedido da Maria em 26/11/2026: a Thamires errou a senha, a entrada travou e nem ela nem a Maria
sabiam da trava). 5 erros em 15 minutos travam por 15 minutos, contados no banco (iguais em todos os processos do
servidor: na memória de cada um eram até 10 erros); a tela avisa quantas tentativas restam e, travada, a partir de que
horas tentar de novo e o contato do suporte da plataforma (Configurações > Marca, do Admin Master)."""

import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import config, dois_fatores, marca
from app.banco import gravar_config, sessao
from app.main import app
from app.modelos import TentativaErrada, Usuario
from app.seguranca import _resumo_da_tentativa, registrar_tentativa_errada, resumir_senha
from conftest import SENHA as SENHA_DO_MASTER
from conftest import csrf_de

SENHA = "SenhaDaTrava123"


def _criar(email: str, perfil: str = "vendedor") -> None:
    with sessao() as db:
        if db.execute(select(Usuario).where(Usuario.email == email)).scalars().first() is None:
            db.add(Usuario(nome="Pessoa da Trava", email=email, senha_hash=resumir_senha(SENHA), perfil=perfil))


def _entrar(c: TestClient, email: str, senha: str):
    return c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": senha},
                  follow_redirects=False)


def _passar_o_tempo(minutos: int) -> None:
    with sessao() as db:
        for tentativa in db.execute(select(TentativaErrada)).scalars():
            tentativa.criado_em -= timedelta(minutes=minutos)


def _erros_guardados(chave: str) -> int:
    with sessao() as db:
        return db.execute(select(func.count()).select_from(TentativaErrada)
                          .where(TentativaErrada.chave == _resumo_da_tentativa(chave))).scalar_one()


def test_avisa_as_tentativas_trava_com_a_hora_e_destrava_depois(cliente):
    email = "pessoa.trava@teste.com.br"
    _criar(email)
    with TestClient(app) as c:
        entrada = " ".join(c.get("/login").text.split())
        assert "depois de 5 tentativas erradas seguidas a entrada fica travada por 15 minutos" in entrada
        avisos = []
        for _ in range(4):
            r = _entrar(c, email, "senha-errada-1")
            assert r.status_code == 401 and "E-mail ou senha incorretos." in r.text
            avisos.append(r.text)
        assert "Você ainda tem 4 tentativas. Depois de 5 erros seguidos, a entrada fica travada por 15 minutos" in avisos[0]
        assert "Você ainda tem 2 tentativas" in avisos[2]
        assert "Atenção: resta só 1 tentativa. Se errar de novo, a entrada fica travada por 15 minutos" in avisos[3]
        r = _entrar(c, email, "senha-errada-1")  # o 5º erro trava
        assert r.status_code == 429, r.text[:300]
        texto = " ".join(r.text.split())
        assert "Entrada travada por segurança: foram 5 tentativas com e-mail ou senha errados." in texto
        assert re.search(r"Tente de novo a partir das \d\d:\d\d \(daqui a 1[45] minutos\) ou fale com o suporte da "
                         r"plataforma\.", texto), texto[:600]
        r = _entrar(c, email, SENHA)  # travada, nem a senha certa entra (é a proteção contra quem tenta adivinhar)
        assert r.status_code == 429 and "Entrada travada por segurança" in r.text
    assert _erros_guardados(f"testclient|{email}") == 5
    with sessao() as db:  # no banco só o resumo: nem o e-mail nem o IP
        assert all(len(ch) == 64 and "@" not in ch for ch in db.execute(select(TentativaErrada.chave)).scalars())
    _passar_o_tempo(16)
    with TestClient(app) as c:
        r = _entrar(c, email, SENHA)
        assert r.status_code == 303 and r.headers["location"] == "/"
    assert _erros_guardados(f"testclient|{email}") == 0  # entrou: os erros de antes não contam mais


def test_os_erros_de_outro_processo_do_servidor_tambem_contam(cliente):
    """Com 2 processos no servidor, cada um contava só os seus erros (até 10 antes de travar)."""
    email = "outro.processo@teste.com.br"
    _criar(email)
    with sessao() as db:  # como se os 5 erros tivessem passado pelo outro processo
        for _ in range(5):
            registrar_tentativa_errada(db, f"testclient|{email}")
    with TestClient(app) as c:
        r = _entrar(c, email, SENHA)
        assert r.status_code == 429 and "Entrada travada por segurança" in r.text
    _passar_o_tempo(16)


def test_contato_do_suporte_na_tela_de_entrada_e_na_trava(cliente):
    with TestClient(app) as master:  # o Admin Master, fora das ARs: nome e suporte da plataforma
        _entrar(master, "admin@teste.com.br", SENHA_DO_MASTER)
        tela = master.get("/configuracoes?aba=marca").text
        assert 'name="plataforma_suporte"' in tela and "Nome e suporte da plataforma" in tela
        nome = re.search(r'name="plataforma_nome" maxlength="60" value="([^"]*)"', tela).group(1)
        r = master.post("/configuracoes/marca", data={"csrf": csrf_de(tela), "plataforma_nome": nome,
                                                      "plataforma_suporte": "  WhatsApp (81) 3333-0000  "})
        assert "Nome e suporte da plataforma salvos" in r.text
    try:
        with TestClient(app) as c:
            entrada = " ".join(c.get("/login").text.split())
            assert "ou fale com o suporte da plataforma: <b>WhatsApp (81) 3333-0000</b>." in entrada
            email = "suporte.trava@teste.com.br"
            _criar(email)
            for _ in range(5):
                r = _entrar(c, email, "senha-errada-2")
            assert "ou fale com o suporte da plataforma: WhatsApp (81) 3333-0000." in " ".join(r.text.split())
    finally:
        with sessao() as db:
            gravar_config(db, "plataforma_suporte", "")
        marca.esquecer()
        _passar_o_tempo(16)


def test_codigo_do_celular_tambem_avisa_e_trava(cliente, monkeypatch):
    monkeypatch.setattr(config, "EXIGIR_2FA", True)
    email = "gestor.trava@teste.com.br"
    _criar(email, "gestor")
    with TestClient(app) as c:
        assert _entrar(c, email, SENHA).headers["location"] == "/login/ativar-codigo"
        pagina = c.get("/login/ativar-codigo").text
        chave = re.search(r'class="chave-2fa">([A-Z2-7 ]+)<', pagina).group(1).replace(" ", "")
        csrf = csrf_de(pagina)
        for vez in range(4):
            r = c.post("/login/ativar-codigo", data={"csrf": csrf, "codigo": "000000"})
            esperado = "resta só 1 tentativa" if vez == 3 else f"Você ainda tem {4 - vez} tentativas"
            assert "Código errado" in r.text and esperado in r.text, (vez, r.text[:400])
        r = c.post("/login/ativar-codigo", data={"csrf": csrf, "codigo": "000000"})
        texto = " ".join(r.text.split())
        assert "Entrada travada por segurança: foram 5 códigos errados." in texto
        assert "entrando de novo com e-mail e senha, ou fale com o suporte da plataforma" in texto
        certo = dois_fatores.codigo(chave, dois_fatores.passo_atual())  # travada: nem o código certo vale
        r = c.post("/login/ativar-codigo", data={"csrf": csrf, "codigo": certo})
        assert "Entrada travada por segurança" in r.text
        assert c.get("/", follow_redirects=False).headers["location"] == "/login"
    _passar_o_tempo(16)
