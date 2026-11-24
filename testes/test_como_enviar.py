"""Nova campanha e Empresas novas: "Como enviar a campanha" (pedido da Maria em 23/11/2026: "organize melhor a área de
criação de campanhas, pois está bem confuso com relação ao HTML, crie um botão de como ele pode enviar a campanha":
WhatsApp e e-mail com HTML, WhatsApp apenas com HTML, e-mail apenas com HTML ou apenas mensagens de texto; "e quando for
HTML coloque para ele selecionar o modelo que vai usar naquele envio")."""

import html as html_lib

from sqlalchemy import delete, select

from app import campanhas, visual
from app.banco import gravar_config, ler_config, sessao
from app.modelos import Campanha, Configuracao, VisualCampanha
from conftest import csrf_de

HTML = "<html><body><h1>Modelo</h1>{{mensagem}}</body></html>"
PNG = b"\x89PNG\r\n\x1a\n" + b"como-enviar" * 10
CHAVES_NOVAS = ("novas_email_html", "novas_visual_id", "novas_visual_canais", "novas_visual_toques", "novas_ativo",
                "novas_ufs", "novas_canais", "novas_maximo_dia", "novas_hora", "novas_sem_individual", "novas_dono_id",
                "novas_excluir_listas")


def _arte(db, nome: str, usar_em: str = "sdr,empresas_novas", imagem: bool = True) -> VisualCampanha:
    arte = VisualCampanha(nome=nome, usar_em=usar_em, html=HTML)
    if imagem:
        visual.guardar_imagem(arte, PNG, "arte.png")
    db.add(arte)
    db.flush()
    return arte


def test_cada_botao_grava_o_envio_certo(cliente):
    with sessao() as db:
        gravar_config(db, visual.CHAVE_HTML_DA_MARCA, "1")
        arte, so_novas = _arte(db, "Arte Como Enviar"), _arte(db, "Arte Só Novas", usar_em="empresas_novas")

        def escolha(**formulario):
            return visual.escolha_do_envio(db, formulario, "sdr")

        assert escolha(envio_html="whatsapp_email", visual_id=str(arte.id)) == (arte.id, "email,whatsapp", "seguintes", False)
        assert escolha(envio_html="whatsapp", visual_id=str(arte.id), visual_toques="todos") == (arte.id, "whatsapp", "todos", False)
        assert escolha(envio_html="email", visual_id=str(arte.id)) == (arte.id, "email", "seguintes", False)
        assert escolha(envio_html="email", visual_id="marca") == (None, "", "seguintes", True)  # o e-mail com a marca
        assert escolha(envio_html="texto", visual_id=str(arte.id)) == (None, "", "seguintes", False)  # nada de HTML
        assert escolha(envio_html="email", visual_id="") is None  # HTML sem modelo: a tela pede para escolher
        assert escolha(envio_html="whatsapp", visual_id="marca") is None  # a marca só serve para o e-mail
        assert escolha(envio_html="email", visual_id=str(so_novas.id)) is None  # modelo de outra área
        gravar_config(db, visual.CHAVE_HTML_DA_MARCA, "0")
        assert escolha(envio_html="email", visual_id="marca") is None  # módulo da marca desligado

        # o que vem marcado na tela, a partir do que está gravado
        assert visual.envio_atual(db, arte.id, "email,whatsapp", "todos", False) == {
            "modo": "whatsapp_email", "modelo": str(arte.id), "toques": "todos"}
        assert visual.envio_atual(db, arte.id, "whatsapp", "seguintes", True)["modo"] == "whatsapp"
        assert visual.envio_atual(db, arte.id, "email", "seguintes", True)["modo"] == "email"
        assert visual.envio_atual(db, None, "", "seguintes", True)["modo"] == "texto"  # sem o módulo da marca
        gravar_config(db, visual.CHAVE_HTML_DA_MARCA, "1")
        assert visual.envio_atual(db, None, "", "seguintes", True) == {"modo": "email", "modelo": "marca",
                                                                       "toques": "seguintes"}
        assert visual.envio_atual(db, None, "", "seguintes", False)["modo"] == "texto"
        db.rollback()


def test_nova_campanha_e_empresas_novas_com_os_botoes(cliente, monkeypatch):
    monkeypatch.setattr(campanhas, "gerar_em_segundo_plano", lambda *a, **k: None)
    with sessao() as db:
        arte_id = _arte(db, "Arte Botões Envio").id
        sem_imagem_id = _arte(db, "Arte Sem Imagem Envio", imagem=False).id
    nova = cliente.get("/campanhas/nova").text
    for valor, titulo in (("whatsapp_email", "WhatsApp e e-mail com HTML"), ("whatsapp", "WhatsApp apenas com HTML"),
                          ("email", "E-mail apenas com HTML"), ("texto", "Apenas mensagens de texto")):
        assert f'name="envio_html" value="{valor}"' in nova and titulo in nova
    assert "Como enviar a campanha" in nova and "Modelo de HTML deste envio" in nova
    assert f'value="{arte_id}" data-previa="/visuais/{arte_id}" data-html="1" data-imagem="1"' in nova
    assert f'value="{sem_imagem_id}" data-previa="/visuais/{sem_imagem_id}" data-html="1" data-imagem=""' in nova
    try:
        base = {"csrf": csrf_de(nova), "cidade": "Recife", "estado": "PE", "quantidade": "5", "categorias": ["contabil"],
                "canais": ["whatsapp", "email"], "tom": "consultivo", "objetivo": "Encontrar parceiros"}
        cliente.post("/campanhas/nova", data={**base, "nome": "Envio Zap Email", "envio_html": "whatsapp_email",
                                              "visual_id": str(arte_id), "visual_toques": "seguintes"})
        r = cliente.post("/campanhas/nova", data={**base, "nome": "Envio Sem Modelo", "envio_html": "email", "visual_id": ""})
        assert "Escolha o modelo de HTML deste envio" in html_lib.unescape(r.text)
        with sessao() as db:
            zap = db.execute(select(Campanha).where(Campanha.nome == "Envio Zap Email")).scalars().one()
            assert (zap.visual_id, zap.visual_canais, zap.visual_toques, zap.email_html) == (
                arte_id, "email,whatsapp", "seguintes", False)
            assert db.execute(select(Campanha).where(Campanha.nome == "Envio Sem Modelo")).first() is None
        # a próxima Nova campanha vem com a escolha da última
        assert 'name="envio_html" value="whatsapp_email" required checked' in cliente.get("/campanhas/nova").text
        cliente.post("/campanhas/nova", data={**base, "nome": "Envio Texto", "envio_html": "texto",
                                              "visual_id": str(arte_id)})
        with sessao() as db:
            texto = db.execute(select(Campanha).where(Campanha.nome == "Envio Texto")).scalars().one()
            assert (texto.visual_id, texto.visual_canais, texto.email_html) == (None, "", False)
        assert 'name="envio_html" value="texto" required checked' in cliente.get("/campanhas/nova").text

        # Empresas novas: o mesmo bloco, gravado na configuração das campanhas diárias
        novas = cliente.get("/empresas-novas").text
        assert "Como enviar as campanhas" in novas and 'name="envio_html" value="whatsapp"' in novas
        configuracao = {"csrf": csrf_de(novas), "ufs": ["PE"], "canal_whatsapp": "on", "maximo_dia": "10",
                        "hora": "07:30"}
        r = cliente.post("/empresas-novas/configurar", data={**configuracao, "envio_html": "whatsapp", "visual_id": ""})
        assert "Escolha o modelo de HTML do envio" in html_lib.unescape(r.text)
        cliente.post("/empresas-novas/configurar", data={**configuracao, "envio_html": "whatsapp",
                                                         "visual_id": str(arte_id), "visual_toques": "todos"})
        with sessao() as db:
            assert [ler_config(db, c) for c in ("novas_visual_id", "novas_visual_canais", "novas_visual_toques",
                                                "novas_email_html")] == [str(arte_id), "whatsapp", "todos", "0"]
        assert 'name="envio_html" value="whatsapp" required checked' in cliente.get("/empresas-novas").text
    finally:
        with sessao() as db:  # sai do caminho dos outros testes
            for chave in CHAVES_NOVAS:
                db.execute(delete(Configuracao).where(Configuracao.chave == chave))
            for camp in db.execute(select(Campanha).where(Campanha.nome.like("Envio %"))).scalars():
                camp.status = "cancelada"
            for vid in (arte_id, sem_imagem_id):
                db.get(VisualCampanha, vid).ativo = False
