"""Conversas: o "Ver conversa" (Oportunidades) abre pelo número em que a conversa está, e a conversa avisa quando o
contato também conversou por outro número (24/11/2026, pedido da Maria: a resposta do Diego chegou pelo WhatsApp do
Paulo Lucas, mas a tela abria o número principal, onde só havia a 1ª mensagem, e a da Milena abria vazia)."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import conexoes
from app.banco import sessao
from app.main import app
from app.modelos import Usuario
from app.rotas import conversas
from app.seguranca import resumir_senha
from conftest import csrf_de

TOKEN = "token-ponte-conversa-numero"
SENHA = "senhaConversa123"
TELEFONE = "81955507001"


def _usuario(email: str, nome: str) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if not u:
            u = Usuario(nome=nome, email=email, perfil="funcionario", senha_hash=resumir_senha(SENHA))
            db.add(u)
            db.flush()
        conexoes.minha(db, u, criar=True)
        return u.id


def _entrar(email: str) -> TestClient:
    c = TestClient(app)
    pagina = c.get("/login")
    c.post("/login", data={"csrf": csrf_de(pagina.text), "email": email, "senha": SENHA})
    return c


def _mensagens_pela_ponte(cliente, mensagens: list[dict]) -> None:
    """O computador do WhatsApp Leads manda a cópia das conversas (como em /api/ponte/retorno)."""
    cab = {"x-token": TOKEN}
    inicio = cliente.post("/api/ponte/troca", headers=cab, json={"status": {}}).json()["desde_conversas"]
    for i, m in enumerate(mensagens, start=1):
        m.update({"id": inicio + i, "erro": "", "telefone": "+55" + TELEFONE, "nome": "Diego Teste"})
    cliente.post("/api/ponte/retorno", headers=cab, json={
        "confirmados": [], "novidades": {},
        "conversas": {"mensagens": mensagens, "status": [], "ultimo_id": inicio + len(mensagens)}})


def test_ver_conversa_abre_pelo_numero_da_conversa_e_avisa_dos_outros(cliente, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    pid = _usuario("paula.conversa@teste.com.br", "Paula Conversa")
    numero_dela = f"u{pid}"
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.email == "admin@teste.com.br")).scalars().first()
        padrao = conversas._numero_padrao(db, admin)
    assert padrao and padrao != numero_dela  # sem a correção, o "Ver conversa" abria neste número (vazio)
    # 1ª mensagem pelo número padrão; dias depois, a campanha e a resposta pelo número da Paula
    _mensagens_pela_ponte(cliente, [
        {"direcao": "saida", "texto": "Primeira mensagem pelo número padrão", "status": "enviada", "origem": "sdr",
         "criado_em": "2026-11-17 15:42:00", "conexao": padrao},
        {"direcao": "saida", "texto": "Mensagem da campanha pelo número da Paula", "status": "enviada",
         "origem": "sdr", "criado_em": "2026-11-24 08:51:00", "conexao": numero_dela},
        {"direcao": "entrada", "texto": "Resposta do Diego", "status": "recebida", "origem": "",
         "criado_em": "2026-11-24 09:15:00", "conexao": numero_dela}])

    # "Ver conversa" (sem o número): a tela abre pelo número da Paula, onde está a resposta
    pagina = cliente.get(f"/conversas?telefone={TELEFONE}")
    assert f'let numeroAtual = "{numero_dela}"' in pagina.text
    # com o número no endereço (o aviso de mensagem nova manda): vale o do endereço
    assert f'let numeroAtual = "{padrao}"' in cliente.get(f"/conversas?telefone={TELEFONE}&numero={padrao}").text
    # sem número na consulta: a conversa vem do número em que ela está
    d = cliente.get(f"/conversas/api/conversa/{TELEFONE}").json()
    assert d["numero"] == numero_dela and "Resposta do Diego" in [m["texto"] for m in d["mensagens"]]
    assert d["outros_numeros"] == [padrao]  # e avisa que o contato também conversou pelo número padrão
    # aberta pelo número padrão: só a 1ª mensagem, e o aviso leva ao número da Paula
    d = cliente.get(f"/conversas/api/conversa/{TELEFONE}?numero={padrao}").json()
    assert [m["texto"] for m in d["mensagens"]] == ["Primeira mensagem pelo número padrão"]
    assert d["outros_numeros"] == [numero_dela]
    assert 'id="c-outros"' in pagina.text and "Este contato também tem conversa pelo" in pagina.text

    # quem não vê o número padrão não fica sabendo dele: só o próprio número, sem aviso
    paula = _entrar("paula.conversa@teste.com.br")
    assert f'let numeroAtual = "{numero_dela}"' in paula.get(f"/conversas?telefone={TELEFONE}&numero={padrao}").text
    d = paula.get(f"/conversas/api/conversa/{TELEFONE}?numero={padrao}").json()
    assert d["numero"] == numero_dela and d["outros_numeros"] == []
    assert "Primeira mensagem pelo número padrão" not in [m["texto"] for m in d["mensagens"]]


def test_contato_sem_conversa_abre_pelo_numero_padrao(cliente):
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.email == "admin@teste.com.br")).scalars().first()
        padrao = conversas._numero_padrao(db, admin)
    pagina = cliente.get("/conversas?telefone=81955507999")
    assert f'let numeroAtual = "{padrao}"' in pagina.text
    d = cliente.get("/conversas/api/conversa/81955507999").json()
    assert d["numero"] == padrao and d["mensagens"] == [] and d["outros_numeros"] == []
