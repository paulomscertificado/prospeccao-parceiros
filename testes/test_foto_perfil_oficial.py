"""Foto do perfil do número oficial (pedido da Maria em 25/11/2026: o logo da empresa com "Canal oficial" no número da
API). O número não abre em celular nenhum: a foto muda pela tela Configurações > WhatsApp > API oficial. A imagem vira o
quadrado do meio em JPEG (até 640 x 640), sobe pelo app do token (envio em partes) e vai para o perfil do número; a tela
mostra a foto que está na Meta, baixada SEM o token. A Meta é imitada: nada sai de verdade."""

import io
import json

import pytest
from PIL import Image
from sqlalchemy import select

from app import whatsapp_oficial
from app.banco import sessao
from app.integracoes import whatsapp_cloud
from app.modelos import LogAuditoria
from conftest import csrf_de
from test_whatsapp_oficial import EMAIL_MS, NUMERO_ID, TOKEN, _admin, _conta_da_ms, _entrar, _zerar_limite

APP_ID = "1661680000000001"
URL_DA_FOTO = "https://pps.whatsapp.net/v/t61.24694-24/foto-do-perfil.jpg?oh=abc&oe=123"
CODIGO_DA_FOTO = "4::aW1hZ2VtLWRvLXBlcmZpbA=="


def _imagem(largura: int, altura: int, formato: str = "PNG") -> bytes:
    saida = io.BytesIO()
    Image.new("RGBA" if formato == "PNG" else "RGB", (largura, altura), (14, 59, 102)).save(saida, formato)
    return saida.getvalue()


class _Resposta:  # imita a resposta do httpx
    def __init__(self, status: int = 200, dados: dict | None = None, conteudo: bytes = b"",
                 tipo: str = "application/json"):
        self.status_code, self._dados = status, dados
        self.content = json.dumps(dados).encode() if dados is not None else conteudo
        self.text, self.headers = self.content.decode("latin-1"), {"content-type": tipo}

    def json(self):
        if self._dados is None:
            raise ValueError("não é JSON")
        return self._dados


def _meta(monkeypatch, recusa: dict | None = None) -> list:
    """A Meta imitada: o token é do app APP_ID; o envio em partes devolve o código da foto; o perfil guarda a foto e
    devolve o endereço dela (que entrega a foto só sem o token)."""
    chamadas, estado = [], {"enviada": b"", "no_perfil": b""}

    def pedir(metodo, url, **kw):
        chamadas.append((metodo, url, kw))
        if url.endswith("/debug_token"):
            return _Resposta(dados={"data": {"app_id": APP_ID, "is_valid": True}})
        if url.endswith(f"/{APP_ID}/uploads"):
            return _Resposta(dados={"id": "upload:SESSAO123"})
        if url.endswith("/upload:SESSAO123"):
            estado["enviada"] = kw.get("content") or b""
            return _Resposta(dados={"h": CODIGO_DA_FOTO})
        if url.endswith(f"/{NUMERO_ID}/whatsapp_business_profile"):
            if metodo == "POST":
                if recusa:
                    return _Resposta(400, {"error": recusa})
                estado["no_perfil"] = estado["enviada"]
                return _Resposta(dados={"success": True})
            dados = {"messaging_product": "whatsapp", "about": "Olá"}
            if estado["no_perfil"]:
                dados["profile_picture_url"] = URL_DA_FOTO
            return _Resposta(dados={"data": [dados]})
        if url == URL_DA_FOTO:
            if "Authorization" in (kw.get("headers") or {}):
                return _Resposta(400, {"error": {"message": "o token não devia vir para cá"}})
            return _Resposta(conteudo=estado["no_perfil"], tipo="image/jpeg")
        return _Resposta(404, {"error": {"message": f"não imitado: {metodo} {url}"}})

    monkeypatch.setattr(whatsapp_cloud.httpx, "request", pedir)
    return chamadas


def test_troca_a_foto_do_perfil_pela_tela(cliente, monkeypatch):
    _zerar_limite()
    _admin(EMAIL_MS, "MS Certificação Digital")
    _conta_da_ms()
    chamadas = _meta(monkeypatch)
    c = _entrar(EMAIL_MS)
    tela = c.get("/whatsapp").text
    assert "Foto do perfil no WhatsApp" in tela and 'action="/whatsapp/oficial/foto"' in tela
    assert c.get("/whatsapp/oficial/foto").status_code == 404  # ainda sem foto na Meta: a tela mostra "Sem foto"
    png = _imagem(1024, 1024)  # como a imagem da Maria: PNG quadrado de 1024 x 1024
    r = c.post("/whatsapp/oficial/foto", data={"csrf": csrf_de(tela)},
               files={"arquivo": ("canal-oficial.png", png, "image/png")})
    assert "Foto do perfil trocada na Meta" in r.text, r.text[:500]
    # o envio em partes vai pelo app do token, com a foto em JPEG de 640 x 640
    sessao_envio = [kw for m, u, kw in chamadas if m == "POST" and u.endswith(f"/{APP_ID}/uploads")]
    envio = [kw for m, u, kw in chamadas if u.endswith("/upload:SESSAO123")]
    assert len(sessao_envio) == 1 and len(envio) == 1
    assert sessao_envio[0]["params"]["file_type"] == "image/jpeg"
    assert sessao_envio[0]["params"]["file_length"] == len(envio[0]["content"])
    assert envio[0]["headers"] == {"Authorization": f"OAuth {TOKEN}", "file_offset": "0"}
    with Image.open(io.BytesIO(envio[0]["content"])) as foto:
        assert foto.format == "JPEG" and foto.size == (640, 640)
    perfil = [kw for m, u, kw in chamadas if m == "POST" and u.endswith(f"/{NUMERO_ID}/whatsapp_business_profile")]
    assert [kw["json"] for kw in perfil] == [{"messaging_product": "whatsapp", "profile_picture_handle": CODIGO_DA_FOTO}]
    # a tela mostra a foto que ficou na Meta (o endereço da foto é público: o token não vai para lá)
    r = c.get("/whatsapp/oficial/foto")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == envio[0]["content"]
    assert r.headers["cache-control"] == "no-store"
    baixadas = [kw for m, u, kw in chamadas if u == URL_DA_FOTO]
    assert baixadas and all("Authorization" not in (kw.get("headers") or {}) for kw in baixadas)
    with sessao() as db:
        log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "trocou_foto_whatsapp_oficial")
                         .order_by(LogAuditoria.id.desc())).scalars().first()
        assert log is not None and NUMERO_ID in log.detalhes and "canal-oficial.png" in log.detalhes


def test_imagem_que_nao_serve_nem_vai_para_a_meta(cliente, monkeypatch):
    _zerar_limite()
    _admin(EMAIL_MS, "MS Certificação Digital")
    _conta_da_ms()
    chamadas = _meta(monkeypatch)
    c = _entrar(EMAIL_MS)
    tela = c.get("/whatsapp").text
    casos = ((b"isto nao e uma imagem", "não é uma imagem que dê para usar"),
             (_imagem(150, 400), "pequena demais (150 x 400)"),
             (b"\x89PNG\r\n" + b"0" * whatsapp_oficial.FOTO_MAXIMO_ARQUIVO, "passou de 5 MB"))
    for conteudo, esperado in casos:
        r = c.post("/whatsapp/oficial/foto", data={"csrf": csrf_de(tela)},
                   files={"arquivo": ("foto.png", conteudo, "image/png")})
        assert "A foto não foi trocada" in r.text and esperado in r.text, (esperado, r.text[:400])
    assert chamadas == []


def test_recusa_da_meta_aparece_explicada_e_fica_no_registro(cliente, monkeypatch):
    _zerar_limite()
    _admin(EMAIL_MS, "MS Certificação Digital")
    _conta_da_ms()
    _meta(monkeypatch, recusa={"message": "(#100) Param profile_picture_handle is not valid", "code": 100})
    c = _entrar(EMAIL_MS)
    tela = c.get("/whatsapp").text
    r = c.post("/whatsapp/oficial/foto", data={"csrf": csrf_de(tela)},
               files={"arquivo": ("logo.jpg", _imagem(800, 800, "JPEG"), "image/jpeg")})
    assert "A foto não foi trocada" in r.text and "profile_picture_handle is not valid" in r.text
    assert c.get("/whatsapp/oficial/foto").status_code == 404  # nada mudou no perfil
    with sessao() as db:
        assert db.execute(select(LogAuditoria).where(LogAuditoria.acao == "foto_whatsapp_oficial_recusada")).scalars().first()


def test_quadrado_do_meio_com_fundo_branco_e_sem_aumentar():
    retangulo = Image.new("RGBA", (1200, 800), (0, 0, 0, 0))  # fundo transparente
    retangulo.paste((200, 0, 0, 255), (500, 300, 700, 500))   # um quadrado vermelho bem no meio
    saida = io.BytesIO()
    retangulo.save(saida, "PNG")
    with Image.open(io.BytesIO(whatsapp_oficial.preparar_foto(saida.getvalue()))) as foto:
        assert foto.size == (640, 640) and foto.mode == "RGB"
        vermelho, canto = foto.getpixel((320, 320)), foto.getpixel((5, 5))
        assert vermelho[0] > 170 and vermelho[1] < 40 and min(canto) > 245  # o meio ficou; o transparente virou branco
    with Image.open(io.BytesIO(whatsapp_oficial.preparar_foto(_imagem(300, 200, "JPEG")))) as foto:
        assert foto.size == (200, 200)  # menor que 640: só o corte, sem aumentar (ficaria borrada)


@pytest.mark.parametrize("endereco", ["http://pps.whatsapp.net/foto.jpg", "https://exemplo.com/foto.jpg",
                                      "https://pps.whatsapp.net.exemplo.com/foto.jpg"])
def test_so_baixa_a_foto_dos_servidores_da_meta(endereco, monkeypatch):
    monkeypatch.setattr(whatsapp_cloud.httpx, "request", lambda *a, **k: pytest.fail("não podia baixar"))
    with pytest.raises(whatsapp_cloud.ErroWhatsApp):
        whatsapp_cloud.baixar_foto_do_perfil(endereco)
