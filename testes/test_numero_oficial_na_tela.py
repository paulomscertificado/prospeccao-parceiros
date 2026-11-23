"""O número da API oficial na tela WhatsApp (pedido da Maria em 23/11/2026: "a API não aparece aqui por quê? pois
preciso compartilhar as conversas com a equipe"). É da empresa, não de uma pessoa: aparece com quem da AR vê as
conversas no menu API Oficial (a permissão "Ver as conversas da API oficial do WhatsApp"); a outra AR não vê."""

import re

from sqlalchemy import select

from app import config
from app.banco import sessao
from app.integracoes import whatsapp_leads
from app.modelos import ExcecaoPermissao, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA
from test_whatsapp_oficial import _admin, _ars, _conta_da_ms, _entrar, _zerar_limite

EMAIL_ADMIN = "admin.numero.oficial@ms-tela-teste.com.br"
EMAIL_CERTY = "admin.numero.oficial@grupocerty-tela.com.br"


def _pessoa(email: str, nome: str, perfil: str, ar: int) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if u is None:
            u = Usuario(nome=nome, email=email, perfil=perfil, senha_hash=resumir_senha(SENHA), tenant_id=ar)
            db.add(u)
            db.flush()
        return u.id


def _quem_ve(html: str) -> str:
    achado = re.search(r'class="pequeno quem-ve"><b>Quem vê as conversas \(\d+\):</b>(.*?)</div>', html, re.S)
    assert achado, "a tela não mostra quem vê as conversas do número oficial"
    return achado.group(1)


def test_numero_oficial_aparece_com_quem_ve_as_conversas(cliente, monkeypatch):
    _zerar_limite()
    _conta_da_ms()
    ms, certy = _ars()
    _admin(EMAIL_ADMIN, "MS Certificação Digital")
    _pessoa("vendedora.ve.oficial@ms-tela-teste.com.br", "Vitória Vê Oficial", "vendedor", ms)
    negada = _pessoa("vendedor.sem.oficial@ms-tela-teste.com.br", "Bruno Sem Oficial", "vendedor", ms)
    _pessoa("vendedora.certy@grupocerty-tela.com.br", "Carla Certy Tela", "vendedor", certy)
    with sessao() as db:  # exceção NEGAR: essa pessoa não vê as conversas do número oficial
        if not db.execute(select(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == negada)).first():
            db.add(ExcecaoPermissao(usuario_id=negada, permissao="oficial.ver", efeito="negar", tenant_id=ms))

    admin = _entrar(EMAIL_ADMIN)
    tela = admin.get("/whatsapp").text
    assert "Número oficial (API da Meta)" in tela and "Não precisa compartilhar" in tela
    quem = _quem_ve(tela)
    assert "Vitória Vê Oficial" in quem and "Admin MS Certificação Digital" in quem
    assert "Bruno Sem Oficial" not in quem and "Carla Certy Tela" not in quem  # sem a permissão; outra AR
    assert 'href="/oficial">Abrir as conversas' in tela and 'href="#oficial">Configurar' in tela

    # com a ponte (o servidor de verdade), o cartão fica junto dos outros números
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    whatsapp_leads._cache["status"] = None
    assert "Número oficial (API da Meta)" in admin.get("/whatsapp").text
    monkeypatch.setattr(config, "WHATSAPP_PONTE", False)
    whatsapp_leads._cache["status"] = None

    # o Grupo Certy não tem API oficial: nada do número da MS
    _admin(EMAIL_CERTY, "Grupo Certy")
    assert "Número oficial (API da Meta)" not in _entrar(EMAIL_CERTY).get("/whatsapp").text

    # o Admin Master fora de uma AR vê o número e o caminho para configurar (dentro da AR)
    tela = cliente.get("/whatsapp").text
    assert "Número oficial (API da Meta)" in tela and "Vitória Vê Oficial" in _quem_ve(tela)
    assert "Para configurar: Painel master" in tela
