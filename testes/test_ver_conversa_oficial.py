"""Oportunidades: o "Ver conversa" de quem conversou pelo número oficial (API da Meta) abre a tela API Oficial (pedido
da Maria em 27/11/2026: "identifique por que quando eu clico em ver conversa não aparece nada pra mim": a cliente tocou
em "Quero renovar" no aviso que saiu pelo número oficial, e o botão abria a tela Conversas, que só tem os números QR).
A tela Conversas também avisa quando o contato conversou pelo número oficial, com o link para lá."""

from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import conexoes
from app.banco import sessao
from app.main import app
from app.modelos import Lead, Mensagem, MensagemOficial, Oportunidade, Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de

SENHA = "senhaVerConversa123"
EMAIL = "admin.verconversa@teste.com.br"


def _entrar() -> TestClient:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == EMAIL)).scalars().first()
        if not u:
            u = Usuario(nome="Admin Ver Conversa", email=EMAIL, perfil="admin", senha_hash=resumir_senha(SENHA))
            db.add(u)
            db.flush()
        conexoes.minha(db, u, criar=True)  # a tela Conversas pede um número de WhatsApp
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": EMAIL, "senha": SENHA})
    return c


def _lead_com_resposta(db, empresa: str, telefone: str, conexao: str) -> Lead:
    """Um lead que respondeu ao último WhatsApp que saiu para ele, pelo número `conexao`."""
    lead = Lead(empresa=empresa, whatsapp=telefone, status="Respondeu")
    db.add(lead)
    db.flush()
    db.add(Mensagem(lead_id=lead.id, canal="whatsapp", direcao="saida", status="enviada",
                    corpo="Aviso de vencimento de certificado digital.", conexao=conexao))
    db.add(Oportunidade(lead_id=lead.id, temperatura="quente", classificacao="QUER RENOVAR", canal="whatsapp",
                        status="nova", resposta="Quero renovar", resumo="O cliente quer renovar."))
    return lead


def test_ver_conversa_abre_a_tela_do_numero_em_que_o_cliente_conversou(cliente):
    c = _entrar()
    with sessao() as db:
        oficial = _lead_com_resposta(db, "CLIENTE OFICIAL VER CONVERSA LTDA", "(81) 98877-1001", "oficial:1")
        qr = _lead_com_resposta(db, "CLIENTE QR VER CONVERSA LTDA", "(81) 98877-1002", "principal")
        db.add(MensagemOficial(telefone="81988771001", direcao="saida", tipo="modelo", status="enviada",
                               texto="Aviso de vencimento de certificado digital.", lead_id=oficial.id))
        tel_oficial, tel_qr = oficial.whatsapp, qr.whatsapp
    pagina = c.get("/oportunidades").text
    assert f'href="/oficial?telefone={quote(tel_oficial)}"' in pagina  # pelo número oficial: tela API Oficial
    assert f'href="/conversas?telefone={quote(tel_oficial)}"' not in pagina
    assert f'href="/conversas?telefone={quote(tel_qr)}"' in pagina  # pelo número QR: tela Conversas, como antes
    assert f'href="/oficial?telefone={quote(tel_qr)}"' not in pagina
    # quem chega nas Conversas por outro caminho vê o aviso com o link para a tela API Oficial
    assert c.get("/conversas/api/conversa/81988771001").json()["no_oficial"] is True
    assert c.get("/conversas/api/conversa/81988771002").json()["no_oficial"] is False
    with sessao() as db:  # não deixa cartões nas telas dos outros testes
        for op in db.execute(select(Oportunidade).where(Oportunidade.lead_id.in_(
                select(Lead.id).where(Lead.empresa.like("CLIENTE % VER CONVERSA LTDA"))))).scalars():
            op.status = "descartada"
