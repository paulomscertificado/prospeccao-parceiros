"""Visual das campanhas (nov/2026): HTML no e-mail e imagem no WhatsApp, para a IA SDR e as Empresas novas."""

import hashlib
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import cadencias, campanhas, config, empresas_novas, sdr, visual
from app.banco import ler_config, sessao
from app.integracoes import email_smtp, whatsapp_leads
from app.main import app
from app.modelos import (ArquivoVisual, Cadencia, Campanha, Configuracao, Lead, PonteWhatsApp, Tarefa, Usuario,
                         VisualCampanha)
from conftest import csrf_de

PNG = b"\x89PNG\r\n\x1a\n" + b"visual-de-teste" * 10
HTML = ("<html><body><h1 onclick=\"alert(1)\">Parceria {{empresa}}</h1><script>alert(2)</script>"
        "<div>{{mensagem}}</div><img src=\"javascript:alert(3)\"></body></html>")


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _visual(db, nome="Visual Teste", usar_em="sdr,empresas_novas", html=HTML, imagem=PNG) -> VisualCampanha:
    v = VisualCampanha(nome=nome, usar_em=usar_em, html=visual.limpar_html(html))
    if imagem:
        visual.guardar_imagem(v, imagem, "folheto.png")
    db.add(v)
    db.flush()
    return v


def test_cadastro_previa_e_imagens_publicas(cliente):
    pagina = cliente.get("/visuais").text
    assert "Visuais das campanhas" in pagina and "Novo visual" in pagina
    r = cliente.post("/visuais/novo", data={"csrf": csrf_de(pagina), "nome": "Folheto parceria", "usar_sdr": "on",
                                            "html": HTML}, files={"imagem": ("folheto.png", PNG, "image/png")})
    assert "criado. Agora ele aparece para escolher nas campanhas" in r.text
    with sessao() as db:
        v = db.execute(select(VisualCampanha).where(VisualCampanha.nome == "Folheto parceria")).scalar_one()
        assert v.usar_em == "sdr" and v.imagem_hash == hashlib.sha256(PNG).hexdigest() and v.imagem_tipo == "image/png"
        assert "<script" not in v.html and "onclick" not in v.html and "javascript:" not in v.html  # limpo
        vid = v.id
    tela = cliente.get(f"/visuais/{vid}").text
    assert 'sandbox=""' in tela and "srcdoc=" in tela and "Escritório Exemplo" in tela  # prévia com dados de exemplo
    assert cliente.get(f"/visuais/{vid}/imagem").content == PNG
    # imagens do HTML: endereço público (o programa de e-mail do lead abre sem login)
    r = cliente.post(f"/visuais/{vid}/arquivos", data={"csrf": csrf_de(tela)},
                     files=[("arquivos", ("Logo MS.png", PNG, "image/png")),
                            ("arquivos", ("virus.exe", b"MZ nada de imagem", "application/octet-stream"))])
    assert "1 imagem(ns) guardada(s)" in r.text and "virus.exe: O arquivo não é uma imagem" in r.text
    with sessao() as db:
        arquivo = db.execute(select(ArquivoVisual).where(ArquivoVisual.visual_id == vid)).scalar_one()
        assert arquivo.nome == "logo-ms.png"
        aid = arquivo.id
    anonimo = TestClient(app)
    r = anonimo.get(f"/visual/arquivo/{aid}/logo-ms.png")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert anonimo.get(f"/visual/arquivo/{aid}/outro-nome.png").status_code == 404
    assert anonimo.get(f"/visuais/{vid}", follow_redirects=False).status_code in (302, 303)  # a tela pede login
    grande = b"\x89PNG\r\n\x1a\n" + b"x" * (visual.LIMITE_IMAGEM + 10)
    r = cliente.post(f"/visuais/{vid}", data={"csrf": csrf_de(tela), "nome": "Folheto parceria", "usar_sdr": "on",
                                              "ativo": "on", "html": HTML}, files={"imagem": ("g.png", grande, "image/png")})
    assert "o máximo é 1 MB" in r.text


def test_html_do_email_monta_o_texto_e_o_descadastro():
    v = VisualCampanha(nome="x", html="<html><body><p>Oi {{nome}} da {{empresa}}</p>{{mensagem}}</body></html>")
    html = visual.montar_html(v, "Olá, Ana!\n\nLinha 1\nLinha <2>", {"nome": "Ana", "empresa": "A&B"},
                              "https://exemplo/descadastrar/1/x")
    assert "Oi Ana da A&amp;B" in html and "Linha 1<br>Linha &lt;2&gt;" in html
    assert html.index("descadastrar/1/x") < html.index("</body>")  # sem {{descadastro}}: rodapé entra antes do fim
    v.html = "<div>{{mensagem}}</div><footer>{{descadastro}}</footer>"
    html = visual.montar_html(v, "Oi", {}, "")
    assert "responda com a palavra SAIR" in html and html.count("SAIR") == 1


def test_toques_marcados_e_envio_por_email_e_whatsapp(cliente, monkeypatch):
    with sessao() as db:
        admin = _admin(db)
        v = _visual(db, nome="Visual Envio")
        camp = Campanha(nome="Campanha Visual", status="ativa", usuario_id=admin.id, canais="whatsapp,email",
                        visual_id=v.id, visual_canais="email,whatsapp", visual_toques="seguintes")
        db.add(camp)
        db.flush()
        cad = db.execute(select(Cadencia).where(Cadencia.nome == "Leve – 3 toques em 12 dias (D1, D5, D12)")).scalar_one()
        frio = Lead(empresa="Visual Frio Ltda", whatsapp="81975550001", email="frio@visual-teste.com.br",
                    vendedor_id=admin.id, responsavel="Ana")
        conversou = Lead(empresa="Visual Conversou Ltda", whatsapp="81975550002", email="ok@visual-teste.com.br",
                         vendedor_id=admin.id, consentimento=True)
        db.add_all([frio, conversou])
        db.flush()
        textos = {l.id: sdr.mensagens_por_regras(db, l, admin) for l in (frio, conversou)}
        cadencias.aplicar(db, cad, [frio, conversou], admin, date.today(), camp.id, textos, ["whatsapp", "email"], "pendente")
        toques = db.execute(select(Tarefa).where(Tarefa.lead_id == frio.id, Tarefa.canal == "whatsapp")
                            .order_by(Tarefa.data, Tarefa.id)).scalars().all()
        assert [t.com_visual for t in toques] == [False, True, True]  # do 2º toque em diante
        segundo = toques[1]

        # e-mail: sai com as duas versões (texto e HTML do visual)
        enviados = []
        monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **k: enviados.append(k) or "<id@x>")
        monkeypatch.setattr(campanhas, "conta_do_toque", lambda *a, **k: None)
        email = db.execute(select(Tarefa).where(Tarefa.lead_id == frio.id, Tarefa.canal == "email",
                                                Tarefa.com_visual.is_(True))).scalars().first()
        assert campanhas._enviar_email_da_tarefa(db, email, admin, "Enviada") == ""
        assert "Parceria Visual Frio" in enviados[-1]["html"] and "<script" not in enviados[-1]["html"]

        # WhatsApp: imagem só para quem já conversou com a MS
        filas = []
        monkeypatch.setattr(whatsapp_leads, "enviar", lambda *a, **k: filas.append(k.get("midia_id")) or "p1")
        monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
        sdr.enviar_whatsapp_conectado(db, segundo.mensagem, admin, lead=frio, tarefa=segundo, conexao="visual-numero")
        zap_ok = db.execute(select(Tarefa).where(Tarefa.lead_id == conversou.id, Tarefa.canal == "whatsapp",
                                                 Tarefa.com_visual.is_(True))).scalars().first()
        msg = sdr.enviar_whatsapp_conectado(db, zap_ok.mensagem, admin, lead=conversou, tarefa=zap_ok,
                                            conexao="visual-numero")
        assert filas == [None, v.id]  # frio: só texto; quem já conversou: com a imagem
        assert msg.assunto == "[com imagem: Visual Envio]"
        db.rollback()


@pytest.fixture()
def ponte(monkeypatch):
    monkeypatch.setattr(config, "NA_NUVEM", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", "token-visual")
    whatsapp_leads._cache["status"] = None
    yield
    whatsapp_leads._cache["status"] = None
    with sessao() as db:
        db.execute(delete(Configuracao).where(Configuracao.chave == "wl_status"))


def test_ponte_leva_a_imagem_para_o_whatsapp_leads(cliente, ponte):
    cab = {"x-token": "token-visual"}
    status = {"conectado": True, "tipo": "teste", "estado": "Conectado", "numero": "5581900000000"}
    cliente.post("/api/ponte/troca", json={"status": status}, headers=cab)
    with sessao() as db:
        v = _visual(db, nome="Visual Ponte")
        db.add(PonteWhatsApp(telefone="81975550003", nome="Lead", texto="Olá com imagem", midia_id=v.id))
        db.commit()
        vid, hash_ = v.id, v.imagem_hash
    envios = cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()["envios"]
    com_imagem = [e for e in envios if e["texto"] == "Olá com imagem"][0]
    assert com_imagem["midia"] == {"id": vid, "hash": hash_, "tipo": "image/png"}
    r = cliente.get(f"/api/ponte/midia/{vid}", headers=cab)
    assert r.status_code == 200 and r.content == PNG
    assert cliente.get(f"/api/ponte/midia/{vid}", headers={"x-token": "errado"}).status_code == 403


def test_escolha_nas_duas_areas(cliente, monkeypatch):
    with sessao() as db:
        so_sdr = _visual(db, nome="Só IA SDR", usar_em="sdr")
        so_novas = _visual(db, nome="Só Empresas novas", usar_em="empresas_novas")
        db.commit()
        ids = (so_sdr.id, so_novas.id)
    nova = cliente.get("/campanhas/nova").text
    assert 'name="visual_id"' in nova and "Só IA SDR" in nova and "Só Empresas novas" not in nova
    monkeypatch.setattr(campanhas, "gerar_em_segundo_plano", lambda *a, **k: None)
    cliente.post("/campanhas/nova", data={
        "csrf": csrf_de(nova), "nome": "Campanha Com Visual", "cidade": "Recife", "estado": "PE", "quantidade": "5",
        "categorias": ["contabil"], "canais": ["email"], "tom": "consultivo", "objetivo": "Encontrar parceiros",
        "visual_id": str(ids[0]), "visual_email": "on", "visual_toques": "todos"})
    with sessao() as db:
        camp = db.execute(select(Campanha).where(Campanha.nome == "Campanha Com Visual")).scalars().first()
        assert (camp.visual_id, camp.visual_canais, camp.visual_toques) == (ids[0], "email", "todos")
        assert "Só IA SDR · e-mail · em todos os toques" == visual.resumo_da_campanha(db, camp)
    novas = cliente.get("/empresas-novas").text
    assert "Só Empresas novas" in novas and "Só IA SDR" not in novas
    cliente.post("/empresas-novas/configurar", data={
        "csrf": csrf_de(novas), "ufs": ["PE"], "canal_whatsapp": "on", "maximo_dia": "10", "hora": "07:30",
        "visual_id": str(ids[1]), "visual_whatsapp": "on", "visual_toques": "seguintes"})
    with sessao() as db:
        assert ler_config(db, "novas_visual_id") == str(ids[1]) and ler_config(db, "novas_visual_canais") == "whatsapp"
        camp = empresas_novas.criar_campanha(db, [{"empresa": "Nova Visual Ltda", "cnpj": "12345678000199",
                                                    "whatsapp": "81975550004", "email": ""}], _admin(db), "teste visual")
        assert (camp.visual_id, camp.visual_canais) == (ids[1], "whatsapp")
        for chave in ("novas_visual_id", "novas_visual_canais", "novas_visual_toques"):
            db.execute(delete(Configuracao).where(Configuracao.chave == chave))
        camp.status = "cancelada"
