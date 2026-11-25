"""Conversas: "Apagar conversa" (25/11/2026, pedido da Maria: "faça a funcionalidade de deletar a conversa com o
determinado número"). As mensagens com o contato por aquele número saem do sistema para toda a equipe, com as fotos, os
áudios e os arquivos, e o WhatsApp Leads apaga a cópia de lá (comando "apagar_conversa" da ponte). A mensagem que ainda
está saindo fica; o contato, a ficha do lead e o nome escolhido continuam. Só quem tem a permissão conversas.apagar
(administrador e gestor por padrão), nos números que vê."""

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import conexoes
from app.banco import ler_config, sessao
from app.leads_servico import limpar_campos
from app.main import app
from app.modelos import (AnexoWhatsApp, ComandoWhatsApp, ContatoWhatsApp, Historico, Lead, LogAuditoria,
                         MensagemWhatsApp, Usuario)
from app.seguranca import limite_pedidos, resumir_senha
from conftest import csrf_de

TOKEN = "token-ponte-apagar-conversa"
SENHA = "senhaConversa123"
TELEFONE = "81955509001"   # a conversa que vai ser apagada
OUTRO = "81955509002"      # outro contato, pelo mesmo número
PONTE = {"x-token": TOKEN}
JPEG = b"\xff\xd8\xff" + b"foto-da-conversa" * 8


def _usuario(email: str, nome: str, perfil: str) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if not u:
            u = Usuario(nome=nome, email=email, perfil=perfil, senha_hash=resumir_senha(SENHA))
            db.add(u)
            db.flush()
        conexoes.minha(db, u, criar=True)
        return u.id


def _entrar(email: str) -> tuple[TestClient, dict]:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c, {"x-csrf-token": csrf_de(c.get("/conversas").text)}


def _pela_ponte(cliente, mensagens: list[dict]) -> list[int]:
    """O computador do WhatsApp Leads manda a cópia das conversas (como em /api/ponte/retorno). Devolve os id_wl."""
    inicio = cliente.post("/api/ponte/troca", headers=PONTE, json={"status": {}}).json()["desde_conversas"]
    for i, m in enumerate(mensagens, start=1):
        m.update({"id": inicio + i, "erro": "", "nome": "Contato Conversa", "origem": m.get("origem", "manual"),
                  "criado_em": f"2026-11-25 10:{i:02d}:00", "telefone": "+55" + m["telefone"]})
    cliente.post("/api/ponte/retorno", headers=PONTE, json={
        "confirmados": [], "novidades": {},
        "conversas": {"mensagens": mensagens, "status": [], "ultimo_id": inicio + len(mensagens)}})
    return [m["id"] for m in mensagens]


def _ids_da_conversa(telefone: str, numero: str) -> set:
    with sessao() as db:
        return set(db.execute(select(MensagemWhatsApp.id_wl).where(MensagemWhatsApp.telefone == telefone,
                                                                   MensagemWhatsApp.conexao == numero)).scalars())


def test_apagar_conversa(cliente, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    gid = _usuario("gil.conversa@teste.com.br", "Gil Conversa", "gestor")
    fid = _usuario("fabio.conversa@teste.com.br", "Fábio Conversa", "funcionario")
    do_gil, do_fabio = f"u{gid}", f"u{fid}"
    with sessao() as db:  # o lead do contato e o nome escolhido para ele: continuam depois de apagar
        lead = Lead(empresa="Contábil Apagar Conversa", whatsapp="(81) 95550-9001")
        db.add(lead)
        limpar_campos(lead)
        db.add(ContatoWhatsApp(telefone=TELEFONE, nome="Dona da Conversa"))
        db.flush()
        lead_id = lead.id
    recebida, enviada, saindo, pelo_fabio, de_outro = _pela_ponte(cliente, [
        {"telefone": TELEFONE, "conexao": do_gil, "direcao": "entrada", "texto": "📷 Foto do documento",
         "status": "recebida", "origem": ""},
        {"telefone": TELEFONE, "conexao": do_gil, "direcao": "saida", "texto": "Recebi, obrigado!", "status": "enviada"},
        {"telefone": TELEFONE, "conexao": do_gil, "direcao": "saida", "texto": "Ainda vai sair", "status": "na_fila"},
        {"telefone": TELEFONE, "conexao": do_fabio, "direcao": "entrada", "texto": "Pelo número do Fábio",
         "status": "recebida", "origem": ""},
        {"telefone": OUTRO, "conexao": do_gil, "direcao": "entrada", "texto": "Outro contato", "status": "recebida",
         "origem": ""}])
    r = cliente.post(f"/api/ponte/anexo/{recebida}", headers={**PONTE, "content-type": "image/jpeg"}, content=JPEG)
    assert r.status_code == 200
    with sessao() as db:
        assert db.execute(select(AnexoWhatsApp).where(AnexoWhatsApp.id_wl == recebida)).first()
    versao = ler_config_versao()

    # o funcionário vê as conversas, mas não tem o botão nem pode apagar (nem a do próprio número)
    fabio, csrf_fabio = _entrar("fabio.conversa@teste.com.br")
    assert 'id="apagar-conversa"' not in fabio.get("/conversas").text
    r = fabio.post("/conversas/api/apagar-conversa", headers=csrf_fabio, json={"telefone": TELEFONE, "numero": do_fabio})
    assert r.status_code == 403 and _ids_da_conversa(TELEFONE, do_fabio) == {pelo_fabio}

    # o gestor tem o botão; número que ele não vê: não acha a conversa
    gil, csrf_gil = _entrar("gil.conversa@teste.com.br")
    assert 'id="apagar-conversa"' in gil.get("/conversas").text
    r = gil.post("/conversas/api/apagar-conversa", headers=csrf_gil, json={"telefone": TELEFONE, "numero": "u999999"})
    assert r.status_code == 404

    # apaga: saem a recebida (com a foto) e a enviada; a que ainda vai sair fica, e as outras conversas também
    r = gil.post("/conversas/api/apagar-conversa", headers=csrf_gil,
                 json={"telefone": "(81) 95550-9001", "numero": do_gil})
    assert r.status_code == 200 and r.json() == {"ok": True, "apagadas": 2, "ficaram": 1}
    assert _ids_da_conversa(TELEFONE, do_gil) == {saindo}
    assert _ids_da_conversa(TELEFONE, do_fabio) == {pelo_fabio} and _ids_da_conversa(OUTRO, do_gil) == {de_outro}
    with sessao() as db:
        assert db.execute(select(AnexoWhatsApp).where(AnexoWhatsApp.id_wl == recebida)).first() is None
        pedido = db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.acao == "apagar_conversa")
                            .order_by(ComandoWhatsApp.id.desc())).scalars().first()
        assert json.loads(pedido.dados) == {"telefone": "55" + TELEFONE, "conexao": do_gil, "ate_id": enviada}
        assert pedido.usuario_id == gid and pedido.status == "aguardando"
        log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "apagou_conversa_whatsapp")
                         .order_by(LogAuditoria.id.desc())).scalars().first()
        assert log.usuario_id == gid and "2 mensagens" in log.detalhes and TELEFONE not in log.detalhes  # mascarado
        assert db.execute(select(Historico).where(Historico.lead_id == lead_id,
                                                  Historico.descricao.like("Conversa do WhatsApp apagada%"))).first()
        assert db.get(Lead, lead_id) is not None and db.get(ContatoWhatsApp, TELEFONE).nome == "Dona da Conversa"
    assert ler_config_versao() != versao  # as listas abertas tiram a conversa

    # o pedido vai para o WhatsApp Leads na próxima troca e volta feito
    troca = cliente.post("/api/ponte/troca", headers=PONTE, json={"status": {}}).json()
    levado = [c for c in troca["comandos"] if c["acao"] == "apagar_conversa"]
    assert levado and levado[0]["dados"]["ate_id"] == enviada
    cliente.post("/api/ponte/retorno", headers=PONTE, json={
        "confirmados": [], "novidades": {}, "comandos": [{"id": levado[0]["id"], "erro": ""}]})
    with sessao() as db:
        assert db.get(ComandoWhatsApp, levado[0]["id"]).status == "feito"

    # a foto da mensagem apagada não fica tentando subir: 410 (a de uma mensagem que ainda não chegou continua 409)
    r = cliente.post(f"/api/ponte/anexo/{recebida}", headers={**PONTE, "content-type": "image/jpeg"}, content=JPEG)
    assert r.status_code == 410
    r = cliente.post(f"/api/ponte/anexo/{de_outro + 50}", headers={**PONTE, "content-type": "image/jpeg"}, content=JPEG)
    assert r.status_code == 409

    # só a que ainda vai sair ficou: não há mais o que apagar
    r = gil.post("/conversas/api/apagar-conversa", headers=csrf_gil, json={"telefone": TELEFONE, "numero": do_gil})
    assert r.status_code == 409 and "não tem mensagens" in r.json()["erro"]


def ler_config_versao() -> str:
    with sessao() as db:
        return ler_config(db, "wl_conversas_versao")
