"""Prepara um banco temporário para os testes (não mexe nos dados reais em dados/)."""

import os
import re
import sys
import tempfile
from pathlib import Path

PASTA_TESTE = tempfile.mkdtemp(prefix="pp_teste_")
os.environ["PP_PASTA_DADOS"] = PASTA_TESTE
os.environ["DATABASE_URL"] = f"sqlite:///{Path(PASTA_TESTE, 'teste.db').as_posix()}"
os.environ["ANTHROPIC_API_KEY"] = ""          # testes nunca chamam a IA de verdade
os.environ["GOOGLE_PLACES_API_KEY"] = ""
os.environ["WHATSAPP_TOKEN"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["EXIGIR_2FA"] = "0"                                 # os testes do 2FA ligam só neles
os.environ["WHATSAPP_LEADS_TOKEN"] = ""                       # nunca fala com o WhatsApp Leads de verdade
os.environ["WHATSAPP_LEADS_PASTA"] = str(Path(PASTA_TESTE, "sem-whatsapp-leads"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SENHA = "senhaTeste123"


def csrf_de(html: str) -> str:
    m = re.search(r'name="csrf" content="([^"]+)"', html) or re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "token CSRF não encontrado na página"
    return m.group(1)


@pytest.fixture(scope="session")
def cliente():
    with TestClient(app) as c:
        pagina = c.get("/primeiro-acesso")
        c.post("/primeiro-acesso", data={"csrf": csrf_de(pagina.text), "nome": "Maria Admin",
                                         "email": "admin@teste.com.br", "senha": SENHA, "senha2": SENHA})
        ligar_modulos("vendas", "agenda")  # na MS vêm desligados; os testes passam por todas as telas
        yield c


def ligar_modulos(*modulos: str, ligado: bool = True):
    from app import autorizacao
    from app.banco import gravar_config, sessao

    with sessao() as db:
        for m in modulos:
            gravar_config(db, autorizacao.MODULOS[m][1], "1" if ligado else "0")


@pytest.fixture()
def csrf(cliente):
    return csrf_de(cliente.get("/minha-conta").text)
