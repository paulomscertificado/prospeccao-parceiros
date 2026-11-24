"""Área de mensagens da campanha com o HTML de cada e-mail e a regra "1º toque em texto, do 2º em diante só o HTML"
(pedidos da Maria em 23/11/2026: "mostre também as mensagens montadas em HTML que serão usadas" e "você envia o
primeiro toque em texto e no segundo toque o HTML apenas, e segue com HTML")."""

import html as html_lib
from datetime import date

from sqlalchemy import select

from app import cadencias, campanhas, sdr, visual
from app.banco import gravar_config, sessao
from app.integracoes import email_smtp
from app.modelos import Cadencia, Campanha, Lead, Mensagem, Tarefa, Usuario, VisualCampanha

# a arte que é o e-mail inteiro (como a "Escritorios contabeis"): não tem {{mensagem}}
INTEIRA = ("<html><head><title>Parceria</title><style>.x{color:#0E3B66}</style></head><body>"
           "<h1>Parceria para a {{empresa}}</h1><p>Olá, {{nome}}! Conheça a parceria da arte.</p>"
           "<a href=\"https://exemplo.com.br/parceria?a=1&amp;b=2\">Quero conhecer →</a>"
           "<p><a href=\"https://mscertificados.com.br\">mscertificados.com.br</a></p></body></html>")
MOLDURA = "<html><body><h1>Topo da moldura</h1><div>{{mensagem}}</div></body></html>"  # recebe o texto do toque
CADENCIA = "Leve – 3 toques em 12 dias (D1, D5, D12)"


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _campanha(db, nome: str, html: str | None, status: str = "pendente", camp_status: str = "ativa",
              email: str = "lead@html-mensagens.com.br") -> tuple[Campanha, Lead, list[Tarefa]]:
    """Campanha da IA SDR com 1 empresa e os 3 toques da cadência leve (e-mail e WhatsApp em cada um)."""
    admin = _admin(db)
    arte = None
    if html is not None:
        arte = VisualCampanha(nome=f"Arte {nome}", usar_em="sdr", html=html)
        db.add(arte)
        db.flush()
    camp = Campanha(nome=nome, status=camp_status, usuario_id=admin.id, canais="whatsapp,email",
                    visual_id=arte.id if arte else None, visual_canais="email" if arte else "",
                    visual_toques="seguintes")
    lead = Lead(empresa=f"{nome} Ltda", whatsapp="81975552001", email=email, vendedor_id=admin.id, responsavel="Ana")
    db.add_all([camp, lead])
    db.flush()
    cad = db.execute(select(Cadencia).where(Cadencia.nome == CADENCIA)).scalar_one()
    cadencias.aplicar(db, cad, [lead], admin, date.today(), camp.id, {lead.id: sdr.mensagens_por_regras(db, lead, admin)},
                      ["whatsapp", "email"], status)
    emails = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.canal == "email")
                        .order_by(Tarefa.data, Tarefa.id)).scalars().all()
    return camp, lead, emails


def test_texto_do_html():
    texto = visual.texto_do_html(INTEIRA.replace("{{empresa}}", "Cntz").replace("{{nome}}", "Ana"))
    assert texto.startswith("Parceria para a Cntz\nOlá, Ana! Conheça a parceria da arte.")
    assert "color:" not in texto and "<" not in texto
    assert "Quero conhecer → (https://exemplo.com.br/parceria?a=1&b=2)" in texto  # o endereço do botão vai junto
    assert "mscertificados.com.br (" not in texto  # o link que já mostra o endereço não se repete


def test_cada_toque_sai_em_texto_ou_html_e_do_2o_em_diante_so_o_html(cliente, monkeypatch):
    enviados = []
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **k: enviados.append((corpo, k["html"])) or "<id@x>")
    monkeypatch.setattr(campanhas, "conta_do_toque", lambda *a, **k: None)
    with sessao() as db:
        gravar_config(db, visual.CHAVE_HTML_DA_MARCA, "0")
        camp, lead, emails = _campanha(db, "Html Inteira", INTEIRA, email="inteira@html-mensagens.com.br")
        tipos = visual.html_dos_toques(db, camp, emails)
        assert [tipos[t.id]["tipo"] for t in emails] == ["texto", "arte", "arte"]
        assert tipos[emails[1].id] == {"tipo": "arte", "nome": "Arte Html Inteira", "inteira": True}

        # o 1º toque vai em texto
        assert campanhas._enviar_email_da_tarefa(db, emails[0], _admin(db), "Enviada") == ""
        corpo, html = enviados[-1]
        assert html == "" and corpo == emails[0].mensagem
        # do 2º em diante, só o HTML: a versão em texto é a da própria arte, não o texto do toque
        assert campanhas._enviar_email_da_tarefa(db, emails[1], _admin(db), "Enviada") == ""
        corpo, html = enviados[-1]
        assert "Parceria para a Html Inteira" in html and "Conheça a parceria da arte" in corpo
        assert emails[1].mensagem.splitlines()[0] not in corpo and "(https://exemplo.com.br/parceria?a=1&b=2)" in corpo
        registro = db.execute(select(Mensagem).where(Mensagem.tarefa_id == emails[1].id)).scalars().one()
        assert registro.corpo == corpo  # o histórico guarda o que a empresa recebeu

        # arte que recebe o texto do toque ({{mensagem}}): o texto vai dentro do HTML e também na versão em texto
        camp2, _, emails2 = _campanha(db, "Html Moldura", MOLDURA, email="moldura@html-mensagens.com.br")
        assert visual.html_dos_toques(db, camp2, emails2)[emails2[1].id]["inteira"] is False
        assert campanhas._enviar_email_da_tarefa(db, emails2[1], _admin(db), "Enviada") == ""
        corpo, html = enviados[-1]
        assert "Topo da moldura" in html and corpo == emails2[1].mensagem

        # sem arte e com o e-mail com a marca: 1º em texto, depois a marca
        gravar_config(db, visual.CHAVE_HTML_DA_MARCA, "1")
        camp3, _, emails3 = _campanha(db, "Html Marca", None, email="marca@html-mensagens.com.br")
        assert [visual.html_dos_toques(db, camp3, emails3)[t.id]["tipo"] for t in emails3] == ["texto", "marca", "marca"]
        gravar_config(db, visual.CHAVE_HTML_DA_MARCA, "0")
        assert {visual.html_dos_toques(db, camp3, emails3)[t.id]["tipo"] for t in emails3} == {"texto"}
        camp3.tipo = "renovacao"  # a Renovação tem a arte do aviso: a área não marca nada
        assert visual.html_dos_toques(db, camp3, emails3) == {}
        db.rollback()


def test_area_de_mensagens_mostra_o_html_e_a_previa(cliente):
    with sessao() as db:
        camp, lead, emails = _campanha(db, "Html Tela", INTEIRA, status="rascunho", camp_status="aguardando_aprovacao",
                                       email="tela@html-mensagens.com.br")
        zap = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.canal == "whatsapp")).scalars().first()
        db.commit()
        cid, ids, zid, arte_id = camp.id, [t.id for t in emails], zap.id, camp.visual_id
    pagina = html_lib.unescape(cliente.get(f"/campanhas/{cid}").text)
    assert "o 1º toque vai em texto e, do 2º em diante, vai só o HTML" in pagina
    assert pagina.count("🎨 HTML: Arte Html Tela") == 2 and "só texto" in pagina
    assert f'data-src="/campanhas/{cid}/toque/{ids[1]}/html"' in pagina
    assert f'data-src="/campanhas/{cid}/toque/{ids[0]}/html"' not in pagina  # o 1º vai só em texto: nada a mostrar
    assert "Este e-mail vai só com a arte “Arte Html Tela” em HTML" in pagina

    previa = cliente.get(f"/campanhas/{cid}/toque/{ids[1]}/html")
    assert previa.status_code == 200 and "Parceria para a Html Tela" in previa.text and "Olá, Ana!" in previa.text
    assert "/descadastrar/exemplo" in previa.text  # clicar na prévia não tira a empresa da lista
    assert previa.headers["x-frame-options"] == "SAMEORIGIN" and "sandbox" in previa.headers["content-security-policy"]
    assert "charset=utf-8" in previa.headers["content-type"]  # a arte sem <meta charset> sai com os acentos certos
    assert "vai só em texto" in cliente.get(f"/campanhas/{cid}/toque/{ids[0]}/html").text
    assert cliente.get(f"/campanhas/{cid}/toque/{zid}/html").status_code == 404  # toque de WhatsApp
    assert cliente.get(f"/campanhas/{cid + 999999}/toque/{ids[1]}/html").status_code == 404
    with sessao() as db:  # sai do caminho dos outros testes
        db.get(Campanha, cid).status = "cancelada"
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars():
            t.status = "cancelada"
        db.get(VisualCampanha, arte_id).ativo = False
