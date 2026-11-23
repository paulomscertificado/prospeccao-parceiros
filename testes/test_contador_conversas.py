"""Número vermelho do menu Conversas (pedido da Maria em 23/11/2026: "assim como oportunidades tem um contador de
mensagens coloque também em conversas e api oficial"): as mensagens recebidas que ninguém leu nos números que a pessoa
vê. Abrir a conversa na tela ou responder pelo celular (ou por uma tela Conversas) marca como lida; resposta da IA, da
automação ou da campanha não. O da API Oficial já existia (test_tela_api_oficial)."""

import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import banco, conexoes, config
from app.banco import sessao
from app.integracoes import whatsapp_leads
from app.main import app
from app.modelos import MensagemWhatsApp, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

TOKEN = "token-ponte-contador"
CAB = {"x-token": TOKEN}


@pytest.fixture()
def nuvem(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    whatsapp_leads._cache["status"] = None
    yield
    whatsapp_leads._cache["status"] = None


def _usuario(email: str, nome: str, perfil: str) -> int:
    with sessao() as db:
        ms = db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar()
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if u is None:
            u = Usuario(nome=nome, email=email, perfil=perfil, senha_hash=resumir_senha(SENHA), tenant_id=ms)
            db.add(u)
            db.flush()
        return u.id


def _entrar(email: str) -> TestClient:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _contador(html: str) -> int:
    achado = re.search(r'<span class="contador" id="contador-conversas"([^>]*)>(\d+)</span>', html)
    assert achado, "o menu não tem o número das Conversas"
    return 0 if "hidden" in achado.group(1) else int(achado.group(2))


def _mensagem(id_wl: int, numero: str, telefone: str, direcao: str, texto: str, origem: str, minuto: int) -> dict:
    return {"id": id_wl, "direcao": direcao, "texto": texto, "erro": "", "origem": origem, "nome": "Contato Contador",
            "status": "recebida" if direcao == "entrada" else "enviada", "telefone": telefone, "conexao": numero,
            "criado_em": f"2026-11-23 10:{minuto:02d}:00"}


def _retorno(cliente, mensagens: list) -> None:
    cliente.post("/api/ponte/retorno", headers=CAB, json={"confirmados": [], "novidades": {}, "conversas": {
        "mensagens": mensagens, "status": [], "ultimo_id": max(m["id"] for m in mensagens)}})


def test_contador_das_conversas_no_menu(cliente, nuvem):
    fid = _usuario("func.contador@teste.com.br", "Fátima Contador", "funcionario")
    _usuario("vend.contador@teste.com.br", "Vítor Sem Número", "vendedor")
    with sessao() as db:
        conexoes.minha(db, db.get(Usuario, fid), criar=True)
    numero = f"u{fid}"
    vendedor = _entrar("vend.contador@teste.com.br")
    antes_do_vendedor = _contador(vendedor.get("/leads").text)

    inicio = cliente.post("/api/ponte/troca", headers=CAB, json={"status": {}}).json()["desde_conversas"]
    a, b, c = "+5581955550001", "+5581955550002", "+5581955550003"
    _retorno(cliente, [
        _mensagem(inicio + 1, numero, a, "entrada", "Oi, tudo bem?", "", 0),
        _mensagem(inicio + 2, numero, a, "entrada", "Quero renovar", "", 1),
        _mensagem(inicio + 3, numero, a, "saida", "Mensagem da campanha", "sdr", 2),  # não é gente: continua não lida
        _mensagem(inicio + 4, numero, b, "entrada", "Bom dia", "", 3),
        _mensagem(inicio + 5, numero, b, "saida", "Bom dia! Já te ajudo", "celular", 4),  # respondeu pelo celular
        _mensagem(inicio + 6, numero, c, "entrada", "Mensagem antiga", "historico", 5)])  # histórico já vem lido

    f = _entrar("func.contador@teste.com.br")
    assert _contador(f.get("/leads").text) == 2  # as duas da conversa A
    assert _contador(vendedor.get("/leads").text) == antes_do_vendedor  # o número não é dele: não conta

    # abriu a conversa A na tela: ficam lidas, a lista já traz o total novo e o número some do menu
    f.get(f"/conversas/api/conversa/81955550001?numero={numero}")
    assert f.get("/conversas/api/lista").json()["nao_lidas_total"] == 0
    assert _contador(f.get("/leads").text) == 0
    # mensagem nova depois da resposta pelo celular: conta de novo
    _retorno(cliente, [_mensagem(inicio + 7, numero, b, "entrada", "Obrigado!", "", 6)])
    assert _contador(f.get("/leads").text) == 1


def test_ajuste_de_uma_vez_marca_as_conversas_ja_respondidas(cliente):
    """Na publicação, a recebida que alguém já respondeu pelo celular fica lida (o número do menu não começa com as
    conversas respondidas pelo celular); a que chegou depois da resposta e a que só a IA respondeu continuam."""
    base = 990_000_000  # id_wl só destes registros

    def guardar(db, id_wl: int, telefone: str, direcao: str, origem: str, minuto: int) -> MensagemWhatsApp:
        m = MensagemWhatsApp(id_wl=base + id_wl, telefone=telefone, conexao="u990001", direcao=direcao, texto="x",
                             origem=origem, criado_em=datetime(2026, 11, 20, 9, minuto), lida=direcao == "saida")
        db.add(m)
        return m

    with sessao() as db:
        respondida = guardar(db, 1, "81955551001", "entrada", "", 0)
        guardar(db, 2, "81955551001", "saida", "celular", 1)
        depois = guardar(db, 3, "81955551001", "entrada", "", 2)  # chegou depois da resposta
        so_ia = guardar(db, 4, "81955551002", "entrada", "", 0)
        guardar(db, 5, "81955551002", "saida", "ia", 1)  # só a IA respondeu: não conta como lida
        db.flush()
        assert banco.marcar_conversas_respondidas(db) >= 1
        for m in (respondida, depois, so_ia):
            db.refresh(m)
        assert respondida.lida and not depois.lida and not so_ia.lida
        assert banco.marcar_conversas_respondidas(db) == 0  # pode rodar de novo: nada mais muda
        indices = {nome for (nome,) in db.execute(text("SELECT name FROM sqlite_master WHERE type = 'index'"))}
    assert "ix_mensagens_whatsapp_nao_lidas" in indices  # o número do menu conta pelo índice das não lidas
