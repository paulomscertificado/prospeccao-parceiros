"""Conversas: o 📎 para mandar arquivo (24/11/2026, pedido da Maria: "dê também a possibilidade de enviar arquivos").
O arquivo vai com o texto como legenda: espera em arquivos_envio até o WhatsApp Leads buscar (/api/ponte/arquivo/<id>);
confirmada a mensagem, vira o anexo dela e a conversa mostra o link (o PDF abre, o Word baixa) ou a foto."""

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import conexoes
from app.banco import sessao
from app.main import app
from app.modelos import AnexoWhatsApp, ArquivoEnvio, MensagemWhatsApp, PonteWhatsApp, Usuario
from app.rotas import conversas
from app.seguranca import resumir_senha
from conftest import csrf_de

TOKEN = "token-ponte-arquivo"
SENHA = "senhaArquivo123"
TELEFONE = "81955510001"
PONTE = {"x-token": TOKEN}
PDF = b"%PDF-1.4 proposta de teste" * 30
DOCX = b"PK\x03\x04 documento de teste" * 30
PNG = b"\x89PNG\r\n\x1a\n imagem de teste" * 30


def _usuario(email: str, nome: str) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if not u:
            u = Usuario(nome=nome, email=email, perfil="funcionario", senha_hash=resumir_senha(SENHA))
            db.add(u)
            db.flush()
        conexoes.minha(db, u, criar=True)
        return u.id


def _entrar(email: str) -> tuple[TestClient, dict]:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c, {"x-csrf-token": csrf_de(c.get("/conversas").text)}


def _mandar(c, cab, numero, nome, dados, tipo, texto=""):
    return c.post("/conversas/api/enviar-arquivo", headers=cab, files={"arquivo": (nome, dados, tipo)},
                  data={"telefone": TELEFONE, "numero": numero, "texto": texto})


def _ultimo_item(db) -> PonteWhatsApp:
    return db.execute(select(PonteWhatsApp).where(PonteWhatsApp.arquivo_id.is_not(None))
                      .order_by(PonteWhatsApp.id.desc())).scalars().first()


def _confirmar(cliente, item_id: int, id_wl: int, numero: str, texto: str, erro: str = "") -> None:
    """O WhatsApp Leads põe a mensagem na fila de lá (ou recusa) e manda a cópia da conversa."""
    desde = cliente.post("/api/ponte/troca", headers=PONTE, json={"status": {}}).json()["desde_conversas"]
    conversas_ = {"mensagens": [], "status": [], "ultimo_id": desde}
    if not erro:
        conversas_ = {"mensagens": [{"id": id_wl, "direcao": "saida", "texto": texto, "status": "na_fila", "erro": "",
                                     "origem": "manual", "criado_em": "2026-11-24 16:00:00", "conexao": numero,
                                     "telefone": "+55" + TELEFONE, "nome": "Cliente Arquivo"}],
                      "status": [], "ultimo_id": max(desde, id_wl)}
    cliente.post("/api/ponte/retorno", headers=PONTE, json={
        "confirmados": [{"id": item_id, "erro": erro} if erro else {"id": item_id, "id_wl": id_wl}],
        "novidades": {}, "conversas": conversas_})


def test_mandar_arquivo_pela_tela(cliente, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    pid = _usuario("paula.arquivo@teste.com.br", "Paula Arquivo")
    _usuario("rui.arquivo@teste.com.br", "Rui Arquivo")
    numero = f"u{pid}"
    cliente.post("/api/ponte/troca", headers=PONTE, json={"status": {
        "conectado": True, "conexoes": {numero: {"conectado": True, "estado_codigo": "conectado"}}}})
    paula, cab = _entrar("paula.arquivo@teste.com.br")
    assert 'id="arquivo"' in paula.get("/conversas").text  # o 📎 está na tela

    # o que não dá: tipo fora da lista, vazio, grande demais, número que a pessoa não vê
    assert _mandar(paula, cab, numero, "programa.exe", b"MZ", "application/octet-stream").status_code == 415
    assert _mandar(paula, cab, numero, "vazio.pdf", b"", "application/pdf").status_code == 400
    monkeypatch.setattr(conversas, "MAXIMO_ARQUIVO", 10)
    assert _mandar(paula, cab, numero, "grande.pdf", PDF, "application/pdf").status_code == 413
    monkeypatch.undo()
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    rui, cab_rui = _entrar("rui.arquivo@teste.com.br")
    assert _mandar(rui, cab_rui, numero, "proposta.pdf", PDF, "application/pdf").status_code == 403

    # o PDF com legenda: espera o WhatsApp Leads buscar
    r = _mandar(paula, cab, numero, "C:\\Users\\Paula\\Proposta MS.pdf", PDF, "application/pdf", texto="Segue a proposta")
    assert r.status_code == 200, r.text
    with sessao() as db:
        item = _ultimo_item(db)
        guardado = db.get(ArquivoEnvio, item.arquivo_id)
        assert item.manual and item.texto == "Segue a proposta" and item.conexao == numero
        assert guardado.nome == "Proposta MS.pdf" and guardado.tipo == "application/pdf"  # sem a pasta do computador
        assert guardado.hash == hashlib.sha256(PDF).hexdigest() and guardado.tamanho == len(PDF)
        item_pdf, arquivo_pdf = item.id, guardado.id
    saindo = paula.get(f"/conversas/api/conversa/{TELEFONE}?numero={numero}").json()["enviando"]
    assert [e["arquivo"] for e in saindo] == ["Proposta MS.pdf"]  # a tela mostra o 📎 enquanto sai

    # a ponte: o computador recebe o arquivo (com o hash para conferir) e baixa com a senha
    troca = cliente.post("/api/ponte/troca", headers=PONTE, json={"status": {}}).json()
    envio = next(e for e in troca["envios"] if e["id"] == item_pdf)
    assert envio["arquivo"] == {"id": arquivo_pdf, "hash": hashlib.sha256(PDF).hexdigest(), "tipo": "application/pdf",
                                "nome": "Proposta MS.pdf"}
    assert cliente.get(f"/api/ponte/arquivo/{arquivo_pdf}").status_code == 403
    baixado = cliente.get(f"/api/ponte/arquivo/{arquivo_pdf}", headers=PONTE)
    assert baixado.status_code == 200 and baixado.content == PDF

    # confirmado: o arquivo vira o anexo da mensagem e sai de arquivos_envio
    _confirmar(cliente, item_pdf, 99_100_001, numero, "[documento] Proposta MS.pdf\nSegue a proposta")
    with sessao() as db:
        assert db.get(ArquivoEnvio, arquivo_pdf) is None
        anexo = db.execute(select(AnexoWhatsApp).where(AnexoWhatsApp.id_wl == 99_100_001)).scalars().one()
        assert anexo.nome == "Proposta MS.pdf" and anexo.tipo == "application/pdf"
        assert db.execute(select(MensagemWhatsApp.anexo).where(MensagemWhatsApp.id_wl == 99_100_001)).scalar() == \
            "documento"
    d = paula.get(f"/conversas/api/conversa/{TELEFONE}?numero={numero}").json()
    doc = next(m for m in d["mensagens"] if m["anexo"] == "documento")
    assert doc["anexo_nome"] == "Proposta MS.pdf" and d["enviando"] == []
    r = paula.get(doc["anexo_url"])
    assert r.status_code == 200 and r.content == PDF and r.headers["content-disposition"].startswith("inline")
    assert "filename*=UTF-8''Proposta%20MS.pdf" in r.headers["content-disposition"]

    # Word: baixa (não abre no navegador); foto: aparece como foto
    assert _mandar(paula, cab, numero, "Contrato.docx", DOCX, "application/octet-stream").status_code == 200
    with sessao() as db:
        item_docx = _ultimo_item(db).id
    _confirmar(cliente, item_docx, 99_100_002, numero, "[documento] Contrato.docx")
    assert _mandar(paula, cab, numero, "foto.png", PNG, "image/png", texto="Olha a foto").status_code == 200
    with sessao() as db:
        item_png = _ultimo_item(db).id
    _confirmar(cliente, item_png, 99_100_003, numero, "🖼️ [imagem] Olha a foto")
    d = paula.get(f"/conversas/api/conversa/{TELEFONE}?numero={numero}").json()
    por_id = {m["texto"]: m for m in d["mensagens"]}
    word, foto = por_id["[documento] Contrato.docx"], por_id["🖼️ [imagem] Olha a foto"]
    assert word["anexo"] == "documento" and foto["anexo"] == "imagem"
    r = paula.get(word["anexo_url"])
    assert r.content == DOCX and r.headers["content-disposition"].startswith("attachment")
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")

    # o WhatsApp Leads recusou: o arquivo não fica guardado
    assert _mandar(paula, cab, numero, "outra.pdf", PDF, "application/pdf").status_code == 200
    with sessao() as db:
        item = _ultimo_item(db)
        item_erro, arquivo_erro = item.id, item.arquivo_id
    _confirmar(cliente, item_erro, 0, numero, "", erro="o arquivo chegou diferente (tente de novo)")
    with sessao() as db:
        assert db.get(ArquivoEnvio, arquivo_erro) is None and db.get(PonteWhatsApp, item_erro).status == "erro"
