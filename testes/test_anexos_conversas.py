"""Conversas: fotos e áudios dentro da mensagem (24/11/2026, pedido da Maria: "faça com que whatsapp leads também
consiga ler imagens e reproduzir áudios"). O WhatsApp Leads baixa a foto, a figurinha e o áudio e manda pela ponte
(/api/ponte/anexo/<id_wl>); a conversa mostra a foto e toca o áudio (/conversas/anexo/<id>), só para quem vê o número."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import conexoes
from app.banco import agora, gravar_config, sessao
from app.main import app
from app.modelos import AnexoWhatsApp, MensagemWhatsApp, Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de

TOKEN = "token-ponte-anexos"
SENHA = "senhaAnexos123"
TELEFONE = "81955509001"
PONTE = {"x-token": TOKEN}
FOTO = b"\xff\xd8\xff\xe0" + b"foto" * 100
AUDIO = b"ID3" + bytes(range(256)) * 4


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
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _hora(**antes) -> str:
    return (agora() - timedelta(**antes)).strftime("%Y-%m-%d %H:%M:%S")


def _pela_ponte(cliente, numero: str, mensagens: list[dict]) -> list[int]:
    """O computador do WhatsApp Leads manda a cópia das conversas (como em /api/ponte/retorno). Devolve os id_wl."""
    inicio = cliente.post("/api/ponte/troca", headers=PONTE, json={"status": {}}).json()["desde_conversas"]
    for i, m in enumerate(mensagens, start=1):
        m.update({"id": inicio + i, "erro": "", "telefone": "+55" + TELEFONE, "nome": "Contato Anexo",
                  "conexao": numero, "status": "recebida" if m["direcao"] == "entrada" else "enviada"})
    cliente.post("/api/ponte/retorno", headers=PONTE, json={
        "confirmados": [], "novidades": {},
        "conversas": {"mensagens": mensagens, "status": [], "ultimo_id": inicio + len(mensagens)}})
    return [m["id"] for m in mensagens]


def _anexo(cliente, id_wl: int, dados: bytes, tipo: str, token: str = TOKEN):
    return cliente.post(f"/api/ponte/anexo/{id_wl}", content=dados, headers={"x-token": token, "content-type": tipo})


def test_fotos_e_audios_nas_conversas(cliente, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    pid = _usuario("paula.anexos@teste.com.br", "Paula Anexos")
    _usuario("rui.anexos@teste.com.br", "Rui Anexos")
    numero = f"u{pid}"
    id_foto, id_audio, id_meu_audio, _ = _pela_ponte(cliente, numero, [
        {"direcao": "entrada", "texto": "[imagem] Segue a foto do documento", "origem": "", "criado_em": _hora(hours=1)},
        {"direcao": "entrada", "texto": "[áudio]", "origem": "", "criado_em": _hora(minutes=50)},
        {"direcao": "saida", "texto": "[áudio]", "origem": "celular", "criado_em": _hora(minutes=40)},
        {"direcao": "entrada", "texto": "Obrigado!", "origem": "", "criado_em": _hora(minutes=30)}])
    paula = _entrar("paula.anexos@teste.com.br")
    antes = paula.get(f"/conversas/api/conversa/{TELEFONE}?numero={numero}").json()
    assert all(m["anexo"] == "" for m in antes["mensagens"])  # a mensagem chega antes da foto

    # a ponte: só com a senha, só os tipos que a tela mostra, só de mensagem que já chegou
    assert _anexo(cliente, id_foto, FOTO, "image/jpeg", token="errado").status_code == 403
    assert _anexo(cliente, id_foto, b"%PDF-1.4", "application/pdf").status_code == 415
    assert _anexo(cliente, id_foto, b"", "image/jpeg").status_code == 413
    assert _anexo(cliente, 99_000_001, FOTO, "image/jpeg").status_code == 409  # o computador manda de novo depois
    assert _anexo(cliente, id_foto, FOTO, "image/jpeg").status_code == 200
    assert _anexo(cliente, id_audio, AUDIO, "audio/mpeg").status_code == 200
    assert _anexo(cliente, id_meu_audio, AUDIO, "audio/mpeg").status_code == 200
    with sessao() as db:
        m = db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.id_wl == id_foto)).scalars().one()
        guardado = db.execute(select(AnexoWhatsApp).where(AnexoWhatsApp.id_wl == id_foto)).scalars().one()
        assert m.anexo == "imagem" and guardado.tipo == "image/jpeg" and guardado.tamanho == len(FOTO)
        assert guardado.tenant_id == m.tenant_id  # da mesma AR da mensagem

    # a conversa: a foto e os áudios dentro das mensagens (a marca muda: a conversa aberta se redesenha)
    depois = paula.get(f"/conversas/api/conversa/{TELEFONE}?numero={numero}").json()
    assert depois["marca"] != antes["marca"]
    por_texto = {(m["direcao"], m["texto"]): m for m in depois["mensagens"]}
    foto = por_texto[("entrada", "[imagem] Segue a foto do documento")]
    assert foto["anexo"] == "imagem" and foto["anexo_url"] == f"/conversas/anexo/{foto['id']}"
    audio, meu_audio = por_texto[("entrada", "[áudio]")], por_texto[("saida", "[áudio]")]
    assert audio["anexo"] == "audio" and meu_audio["anexo"] == "audio"  # o que saiu pelo celular do número também
    r = paula.get(foto["anexo_url"])
    assert r.status_code == 200 and r.content == FOTO and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"].startswith("private") and r.headers["x-content-type-options"] == "nosniff"
    # o áudio aos pedaços (o Safari do iPhone só toca assim)
    r = paula.get(audio["anexo_url"], headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == AUDIO[:10] and r.headers["content-range"] == f"bytes 0-9/{len(AUDIO)}"
    r = paula.get(audio["anexo_url"], headers={"Range": "bytes=-5"})
    assert r.status_code == 206 and r.content == AUDIO[-5:]
    r = paula.get(audio["anexo_url"], headers={"Range": "bytes=10-"})
    assert r.status_code == 206 and r.content == AUDIO[10:]
    assert paula.get(audio["anexo_url"], headers={"Range": f"bytes={len(AUDIO)}-"}).status_code == 416
    r = paula.get(audio["anexo_url"])
    assert r.status_code == 200 and r.content == AUDIO and r.headers["accept-ranges"] == "bytes"
    assert 'class="audio"' in paula.get(f"/conversas?telefone={TELEFONE}&numero={numero}").text

    # quem não vê o número da Paula não vê a foto nem ouve o áudio
    rui = _entrar("rui.anexos@teste.com.br")
    assert rui.get(foto["anexo_url"]).status_code == 404 and rui.get(audio["anexo_url"]).status_code == 404
    so_texto = por_texto[("entrada", "Obrigado!")]  # mensagem sem foto nem áudio: nada para mostrar
    assert so_texto["anexo"] == "" and so_texto["anexo_url"] == ""
    assert paula.get(f"/conversas/anexo/{so_texto['id']}").status_code == 404


def test_anexos_saem_com_o_prazo_da_conversa_e_ficam_fora_do_backup(cliente):
    from app.leads_servico import apagar_conversas_antigas
    from fazer_backup import FORA_DO_BACKUP

    assert "anexos_whatsapp" in FORA_DO_BACKUP
    with sessao() as db:
        velho = AnexoWhatsApp(id_wl=98_000_001, tipo="image/jpeg", dados=FOTO, tamanho=len(FOTO),
                              criado_em=agora() - timedelta(days=800))
        novo = AnexoWhatsApp(id_wl=98_000_002, tipo="image/jpeg", dados=FOTO, tamanho=len(FOTO))
        db.add_all([velho, novo])
        db.flush()
        ids = (velho.id, novo.id)
    with sessao() as db:
        gravar_config(db, "guarda_conversas_meses", "12")
        apagar_conversas_antigas(db)
        gravar_config(db, "guarda_conversas_meses", "0")
    with sessao() as db:
        restam = set(db.execute(select(AnexoWhatsApp.id).where(AnexoWhatsApp.id.in_(ids))).scalars())
    assert restam == {ids[1]}
