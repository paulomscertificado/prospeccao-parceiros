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
os.environ["CONFERIR_DOMINIO_EMAIL"] = "0"                    # testes nunca consultam o DNS de verdade
os.environ["LISTA_EXCLUSAO_CNPJA"] = "0"                       # nunca fala com a CNPJá de verdade
os.environ["ESPACAR_ENVIOS"] = "0"                             # a regra de 3-4 min tem teste próprio
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


def no_horario_de_envio(monkeypatch):
    """Finge que agora é horário de envio para a fila (mensagens.dentro_do_horario) E para a previsão de saída da Minha
    fila (campanhas.JanelaDeEnvio): sem a segunda, depois das 18 h ou no fim de semana a previsão manda o toque para o
    próximo horário e o teste passa ou falha conforme a hora em que roda."""
    from app import campanhas, mensagens

    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    monkeypatch.setattr(campanhas.JanelaDeEnvio, "proxima",
                        lambda self, momento, renovacao=False, canal="whatsapp": momento)


def ligar_modulos(*modulos: str, ligado: bool = True):
    from app import autorizacao
    from app.banco import gravar_config, sessao

    with sessao() as db:
        for m in modulos:
            gravar_config(db, autorizacao.MODULOS[m][1], "1" if ligado else "0")


@pytest.fixture()
def csrf(cliente):
    return csrf_de(cliente.get("/minha-conta").text)


# Desde 24/11/2026 toda a Renovação é de cada marca: o que um teste salva pela tela (quadro 4, textos, importação) fica
# na AR MS ou no Grupo Certy. Antes ficava na plataforma, e cada teste limpava o dele; agora, depois de cada teste,
# as marcas voltam a usar o da plataforma (o dono, o número, a API oficial, o calendário e a arte já eram de cada marca
# antes e os testes deles cuidam disso).
RENOVACAO_DA_MARCA = ("renov_ativo", "renov_hora", "renov_maximo_dia", "renov_canais", "renov_arte", "renov_email_html",
                      "renov_dias", "renov_hora_inicio", "renov_hora_fim", "renov_feriados", "renov_ativo_desde",
                      "renov_mensagens", "renov_ultima_rodada", "renov_ultimo_resultado", "renov_ultima_importacao")


@pytest.fixture(autouse=True)
def _renovacao_das_marcas_limpa():
    yield
    from sqlalchemy import delete
    from sqlalchemy.exc import OperationalError, ProgrammingError

    from app.banco import sessao
    from app.modelos import ConfiguracaoAR

    try:
        with sessao() as db:
            db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.chave.in_(RENOVACAO_DA_MARCA)))
    except (OperationalError, ProgrammingError):  # o banco ainda não foi criado (teste que não usa o sistema)
        pass
