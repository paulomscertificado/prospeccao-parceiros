"""Configurações organizadas: Permissões e WhatsApp ficam dentro das Configurações para quem as vê; quem não vê (ex.:
vendedor) continua com o WhatsApp no menu lateral e a tela aparece sozinha, sem o menu das Configurações."""
from fastapi.testclient import TestClient

from app.banco import sessao
from app.main import app
from app.modelos import Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de


def test_administrador_acha_o_whatsapp_dentro_das_configuracoes(cliente):
    lateral = cliente.get("/").text.split("<main")[0]  # o menu lateral vem antes do conteúdo
    assert 'href="/whatsapp"' not in lateral and 'href="/permissoes"' not in lateral and 'href="/email"' not in lateral
    assert 'class="config-item ativo" href="/email"' in cliente.get("/email").text
    assert 'href="/configuracoes"' in lateral
    pagina = cliente.get("/whatsapp").text
    assert 'class="config-item ativo" href="/whatsapp"' in pagina and "<h1>Configurações</h1>" in pagina


def test_vendedor_continua_com_o_whatsapp_no_menu_e_a_tela_sozinha(cliente):
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    with sessao() as db:
        if db.query(Usuario).filter(Usuario.email == "vendedor.menu@exemplo.com.br").first() is None:
            db.add(Usuario(nome="Vendedor do Menu", email="vendedor.menu@exemplo.com.br", perfil="vendedor",
                           senha_hash=resumir_senha(SENHA)))
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": "vendedor.menu@exemplo.com.br",
                           "senha": SENHA})
    lateral = c.get("/").text.split("<main")[0]
    assert 'href="/whatsapp"' in lateral and 'href="/email"' in lateral and 'href="/configuracoes"' not in lateral
    pagina = c.get("/whatsapp").text
    assert "<h1>WhatsApp</h1>" in pagina and 'class="config-menu"' not in pagina
