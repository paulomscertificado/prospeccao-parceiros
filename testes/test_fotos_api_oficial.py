"""Fotos que os contatos mandam para o número oficial (pedido da Maria em 23/11/2026, depois da arte dos avisos na
tela API Oficial: "Sim, fazer"). O webhook guarda o id da mídia; o relógio baixa da Meta (o id vale só 7 dias) e guarda
em imagens_oficiais; a tela mostra a foto dentro da mensagem, com a legenda, e o aviso na tela diz "📷 Imagem". O token
só vai para a Meta. A Meta é imitada: nada sai de verdade."""

import json

from sqlalchemy import func, select

from app import whatsapp_oficial
from app.banco import sessao
from app.integracoes import whatsapp_cloud
from app.modelos import ImagemOficial, MensagemOficial
from test_tela_api_oficial import _evento
from test_whatsapp_oficial import _assinado, _conta_da_ms

JPEG = b"\xff\xd8\xff\xe0" + b"1" * 5000
URL_DA_META = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid="


class _Resposta:  # imita a resposta do httpx
    def __init__(self, status: int = 200, dados: dict | None = None, conteudo: bytes = b""):
        self.status_code, self._dados = status, dados
        self.content = json.dumps(dados).encode() if dados is not None else conteudo
        self.text, self.headers = self.content.decode("latin-1"), {}

    def json(self):
        if self._dados is None:
            raise ValueError("não é JSON")
        return self._dados


def _meta(monkeypatch, situacao: int = 200, endereco: str = URL_DA_META, tamanho: int | None = None) -> list:
    """A Meta imitada: o id da mídia dá o endereço (e o tamanho); o endereço dá a foto (ou a situação de erro)."""
    chamadas = []

    def pedir(metodo, url, **kw):
        chamadas.append((metodo, url, kw))
        if url.startswith("https://graph.facebook.com/"):
            mid = url.rsplit("/", 1)[-1]
            return _Resposta(dados={"url": endereco + mid, "mime_type": "image/jpeg", "id": mid,
                                    "file_size": tamanho or len(JPEG), "messaging_product": "whatsapp"})
        return _Resposta(situacao, conteudo=JPEG if situacao == 200 else b"erro")

    monkeypatch.setattr(whatsapp_cloud.httpx, "request", pedir)
    return chamadas


def _mensagem(db, wamid: str) -> MensagemOficial:
    return db.execute(select(MensagemOficial).where(MensagemOficial.wamid == wamid)).scalars().one()


def _foto(telefone: str, wamid: str, midia: str, legenda: str = "", nome: str = "Contato Foto") -> dict:
    imagem = {"id": midia, "mime_type": "image/jpeg", "sha256": "abc"}
    if legenda:
        imagem["caption"] = legenda
    return {"from": telefone, "id": wamid, "type": "image", "image": imagem, "nome": nome}


def test_foto_do_contato_aparece_na_conversa_com_a_legenda(cliente, monkeypatch):
    _conta_da_ms()
    with sessao() as db:
        maior = db.execute(select(func.max(MensagemOficial.id))).scalar() or 0
    evento = _evento([_foto("5581995558001", "wamid.FOTO-1", "midia-foto-1", "Segue o meu RG", "Joana Foto"),
                      {"from": "5581995558001", "id": "wamid.FIGURINHA-1", "type": "sticker",
                       "sticker": {"id": "midia-figurinha-1", "mime_type": "image/webp", "animated": False}}])
    assert _assinado(cliente, evento).status_code == 200
    with sessao() as db:
        foto, figurinha = _mensagem(db, "wamid.FOTO-1"), _mensagem(db, "wamid.FIGURINHA-1")
        assert foto.tipo == "midia" and foto.midia_id == "midia-foto-1" and foto.texto == "Segue o meu RG"
        assert figurinha.midia_id == "midia-figurinha-1" and figurinha.texto == "[sticker]"
        fid, gid = foto.id, figurinha.id
    # o aviso na tela do computador: "📷" e a legenda (não "[image]")
    novas = cliente.get(f"/novidades?o={maior}").json()["novas"]
    assert {n["texto"] for n in novas if n["tipo"] == "oficial"} >= {"📷 Segue o meu RG", "📷 Figurinha"}
    # antes de o relógio baixar, a tela avisa que a foto já vem
    tela = cliente.get("/oficial?telefone=81995558001").text
    assert "Imagem: aparece aqui em instantes" in tela and "Segue o meu RG" in tela
    chamadas = _meta(monkeypatch)
    with sessao() as db:
        assert whatsapp_oficial.baixar_imagens_recebidas(db, maximo=50) >= 2
        db.commit()
        imagens = {i.mensagem_id: i for i in db.execute(select(ImagemOficial).where(
            ImagemOficial.mensagem_id.in_([fid, gid]))).scalars()}
        assert set(imagens) == {fid, gid}
        assert imagens[fid].imagem == JPEG and imagens[fid].tipo == "image/jpeg" and imagens[fid].wamid == "wamid.FOTO-1"
        assert _mensagem(db, "wamid.FOTO-1").midia_tentativas == 0
    assert all(url.startswith(("https://graph.facebook.com/", URL_DA_META)) for _, url, _ in chamadas)
    tela = cliente.get("/oficial?telefone=81995558001").text
    assert f'<img class="foto" src="/oficial/imagem/{fid}"' in tela and "Segue o meu RG" in tela
    assert "aparece aqui em instantes" not in tela and "📷 Figurinha" in tela  # a lista, como no WhatsApp
    r = cliente.get(f"/oficial/imagem/{fid}")
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    chamadas.clear()
    with sessao() as db:  # já baixadas: não baixa de novo
        whatsapp_oficial.baixar_imagens_recebidas(db, maximo=50)
        db.commit()
    assert not [1 for _, url, _ in chamadas if url.endswith(("midia-foto-1", "midia-figurinha-1"))]


def test_foto_que_a_meta_nao_entrega_para_depois_das_tentativas(cliente, monkeypatch):
    _conta_da_ms()
    assert _assinado(cliente, _evento([_foto("5581995558002", "wamid.FOTO-2", "midia-foto-2")])).status_code == 200
    _meta(monkeypatch, situacao=404)
    with sessao() as db:
        for _ in range(whatsapp_oficial.TENTATIVAS_DA_FOTO + 2):
            whatsapp_oficial.baixar_imagens_recebidas(db, maximo=50)
            db.commit()
        foto = _mensagem(db, "wamid.FOTO-2")
        assert foto.midia_tentativas == whatsapp_oficial.TENTATIVAS_DA_FOTO  # parou de tentar
        assert db.execute(select(ImagemOficial.id).where(ImagemOficial.mensagem_id == foto.id)).first() is None
    tela = cliente.get("/oficial?telefone=81995558002").text
    assert "Imagem: a Meta não entregou, não dá para ver aqui" in tela


def test_token_so_vai_para_a_meta_e_foto_grande_demais_nao_e_baixada(cliente, monkeypatch):
    _conta_da_ms()
    assert _assinado(cliente, _evento([_foto("5581995558003", "wamid.FOTO-3", "midia-foto-3")])).status_code == 200
    chamadas = _meta(monkeypatch, endereco="https://exemplo-de-fora.com/arquivo?mid=")
    with sessao() as db:
        whatsapp_oficial.baixar_imagens_recebidas(db, maximo=50)
        db.commit()
        assert _mensagem(db, "wamid.FOTO-3").midia_tentativas == 1
    assert not [url for _, url, _ in chamadas if "exemplo-de-fora" in url]  # o token nunca saiu da Meta
    chamadas = _meta(monkeypatch, tamanho=20_000_000)
    with sessao() as db:
        whatsapp_oficial.baixar_imagens_recebidas(db, maximo=50)
        db.commit()
        assert _mensagem(db, "wamid.FOTO-3").midia_tentativas == whatsapp_oficial.TENTATIVAS_DA_FOTO  # nem tenta de novo
    assert not [url for _, url, _ in chamadas if url.startswith(URL_DA_META)]


def test_legenda_e_id_da_midia_no_webhook():
    recebidas, _ = whatsapp_cloud.ler_webhook({"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "1"},
        "messages": [{"from": "5581900000001", "id": "w1", "type": "image", "image": {"id": "m1", "caption": " Olá "}},
                     {"from": "5581900000001", "id": "w2", "type": "image", "image": {"id": "m2"}},
                     {"from": "5581900000001", "id": "w3", "type": "audio", "audio": {"id": "m3"}},
                     {"from": "5581900000001", "id": "w4", "type": "text", "text": {"body": "oi"}}]}}]}]})
    assert [(r["texto"], r["midia_id"]) for r in recebidas] == [("Olá", "m1"), ("[image]", "m2"), ("[audio]", ""),
                                                                ("oi", "")]
