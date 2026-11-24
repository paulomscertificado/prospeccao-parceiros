"""Área "Testar antes de aprovar" da campanha (pedido da Maria em 23/11/2026): o teste do 1º contato chegou só em texto
e parecia que o HTML não saía. A tela avisa em que toque o HTML do e-mail (a arte ou o e-mail com a marca) e a imagem
do WhatsApp começam, oferece "Todos os 4 toques" e, depois do envio, diz quantos foram com o HTML ou por que não foi."""

import html as html_lib
from datetime import date

from sqlalchemy import select

from app import cadencias, campanhas, sdr, visual
from app.banco import gravar_config, sessao
from app.integracoes import email_smtp
from app.modelos import Cadencia, Campanha, Lead, Tarefa, Usuario, VisualCampanha
from conftest import csrf_de

HTML = "<html><body><h1>Parceria {{empresa}}</h1><div>{{mensagem}}</div></body></html>"
PNG = b"\x89PNG\r\n\x1a\n" + b"teste-da-campanha" * 10


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _visual(db, nome: str, ativo: bool = True) -> VisualCampanha:
    v = VisualCampanha(nome=nome, usar_em="sdr,empresas_novas", html=HTML, ativo=ativo)
    visual.guardar_imagem(v, PNG, "arte.png")
    db.add(v)
    db.flush()
    return v


def _campanha(db, nome: str, tipo: str = "parceiros", arte: VisualCampanha | None = None,
              canais: str = "email,whatsapp", toques: str = "seguintes", email_html: bool = True) -> Campanha:
    camp = Campanha(nome=nome, tipo=tipo, status="aguardando_aprovacao", usuario_id=_admin(db).id,
                    canais="whatsapp,email", visual_id=arte.id if arte else None, visual_canais=canais if arte else "",
                    visual_toques=toques, email_html=email_html)
    db.add(camp)
    db.flush()
    return camp


def _ligar_marca(db, ligado: bool):
    gravar_config(db, visual.CHAVE_HTML_DA_MARCA, "1" if ligado else "0")
    db.flush()


def test_aviso_de_cada_campanha(cliente):
    with sessao() as db:
        _ligar_marca(db, False)
        arte = _visual(db, "Arte Aviso Teste")
        seguintes = visual.dicas_do_teste(db, _campanha(db, "Aviso seguintes", arte=arte))
        assert (seguintes["email_desde"], seguintes["email"]) == (
            2, 'A arte "Arte Aviso Teste" vai do 2º toque em diante: o 1º contato sai só em texto.')
        assert seguintes["whatsapp_desde"] == 2 and seguintes["whatsapp"].startswith(
            'A imagem da arte "Arte Aviso Teste" vai do 2º toque em diante') and "já conversou" in seguintes["whatsapp"]
        todos = visual.dicas_do_teste(db, _campanha(db, "Aviso todos", arte=arte, toques="todos"))
        assert (todos["email_desde"], todos["email"]) == (1, 'A arte "Arte Aviso Teste" vai em todos os e-mails.')
        so_email = visual.dicas_do_teste(db, _campanha(db, "Aviso só e-mail", arte=arte, canais="email"))
        assert (so_email["whatsapp_desde"], so_email["whatsapp"]) == (0, "")
        # sem arte e sem o e-mail com a marca: só texto, e onde se escolhe a arte
        sem = visual.dicas_do_teste(db, _campanha(db, "Aviso sem arte"))
        assert sem["email_desde"] == 0 and "saem só em texto" in sem["email"] and "passo 4 da Nova campanha" in sem["email"]
        assert "na tela Empresas novas" in visual.dicas_do_teste(db, _campanha(db, "Aviso novas", tipo="empresas_novas"))["email"]
        desligada = visual.dicas_do_teste(db, _campanha(db, "Aviso arte desligada", arte=_visual(db, "Arte Off", ativo=False)))
        assert (desligada["email_desde"], desligada["whatsapp_desde"]) == (0, 0)
        # o e-mail com a marca liberado: do 2º e-mail em diante (sem arte); desmarcado na campanha, só texto
        _ligar_marca(db, True)
        marca = visual.dicas_do_teste(db, _campanha(db, "Aviso marca"))
        assert (marca["email_desde"], marca["email"]) == (
            2, "O e-mail com a marca vai do 2º e-mail em diante: o 1º contato sai só em texto.")
        assert visual.dicas_do_teste(db, _campanha(db, "Aviso marca desmarcada", email_html=False))["email_desde"] == 0
        assert visual.dicas_do_teste(db, _campanha(db, "Aviso marca passada"), marca_ligada=False)["email_desde"] == 0
        # a Renovação tem o teste próprio (tela Renovação): nada a dizer aqui
        assert visual.dicas_do_teste(db, _campanha(db, "Aviso renovação", tipo="renovacao")) == {
            "email": "", "email_desde": 0, "whatsapp": "", "whatsapp_desde": 0}
        db.rollback()


def test_o_que_a_tela_diz_depois_do_teste(cliente):
    with sessao() as db:
        _ligar_marca(db, False)
        camp = _campanha(db, "Depois seguintes", arte=_visual(db, "Arte Depois Teste"))
        assert visual.depois_do_teste(db, camp, "email", 1, 0) == ("", (
            'O teste foi só em texto porque o 1º contato sai assim: a arte "Arte Depois Teste" vai do 2º toque em '
            'diante. Para ver, teste de novo escolhendo "Todos os 4 toques" em "Quais toques".'))
        assert visual.depois_do_teste(db, camp, "email", 3, 2, True) == ("2 com o HTML; o 1º contato vai só em texto", "")
        assert visual.depois_do_teste(db, camp, "email", 1, 1) == ("com o HTML", "")
        assert visual.depois_do_teste(db, camp, "whatsapp", 2, 2, True) == ("todos com a imagem", "")
        assert visual.depois_do_teste(db, camp, "whatsapp", 1, 0)[1].startswith("O teste foi só em texto")
        assert visual.depois_do_teste(db, camp, "email", 3, 0, True) == ("", "")  # já foi com todos os toques
        assert visual.depois_do_teste(db, camp, "email", 0, 0) == ("", "")
        sem = _campanha(db, "Depois sem arte")
        junto, alerta = visual.depois_do_teste(db, sem, "email", 1, 0)
        assert junto == "" and alerta.startswith("Os e-mails desta campanha saem só em texto")
        assert visual.depois_do_teste(db, sem, "whatsapp", 1, 0) == ("", "")  # WhatsApp sem imagem: nada a dizer
        db.rollback()


def test_tela_e_envio_do_teste(cliente, monkeypatch):
    with sessao() as db:
        admin = _admin(db)
        arte = _visual(db, "Arte Tela Teste")
        camp = _campanha(db, "Campanha Tela Teste", arte=arte)
        lead = Lead(empresa="Tela Teste Ltda", whatsapp="81975551001", email="lead@teste-da-campanha.com.br",
                    vendedor_id=admin.id, responsavel="Ana")
        db.add(lead)
        db.flush()
        cad = db.execute(select(Cadencia).where(Cadencia.nome == "Leve – 3 toques em 12 dias (D1, D5, D12)")).scalar_one()
        cadencias.aplicar(db, cad, [lead], admin, date.today(), camp.id, {lead.id: sdr.mensagens_por_regras(db, lead, admin)},
                          ["whatsapp", "email"], "rascunho")
        db.commit()
        cid, vid = camp.id, arte.id
    pagina = cliente.get(f"/campanhas/{cid}").text
    assert 'data-desde-email="2"' in pagina and 'id="botao-todos-toques"' in pagina and 'id="toques-teste"' in pagina
    assert 'A arte "Arte Tela Teste" vai do 2º toque em diante: o 1º contato sai só em texto.' in html_lib.unescape(pagina)

    enviados = []
    monkeypatch.setattr(campanhas.contas_email, "para_enviar", lambda *a, **k: None)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **k: enviados.append(k.get("html")) or "<id@x>")
    dados = {"csrf": csrf_de(pagina), "campanha_teste": str(cid), "canal_teste": "email",
             "email_teste": "eu@teste-da-campanha.com.br", "empresas": "1"}
    r = html_lib.unescape(cliente.post(f"/campanhas/{cid}/testar", data={**dados, "toques": "primeiro"}).text)
    assert enviados == [""]  # o 1º contato: só texto
    assert "1 e-mail(s) para eu@teste-da-campanha.com.br. Nenhum lead recebeu nada." in r
    assert ('O teste foi só em texto porque o 1º contato sai assim: a arte "Arte Tela Teste" vai do 2º toque em diante. '
            'Para ver, teste de novo escolhendo "Todos os 4 toques"') in r
    enviados.clear()
    r = html_lib.unescape(cliente.post(f"/campanhas/{cid}/testar", data={**dados, "toques": "todos"}).text)
    assert len(enviados) == 3 and enviados[0] == "" and all("Parceria Tela Teste" in h for h in enviados[1:])
    assert "3 e-mail(s) para eu@teste-da-campanha.com.br (2 com o HTML; o 1º contato vai só em texto)." in r
    assert "O teste foi só em texto" not in r
    with sessao() as db:  # o teste não muda a campanha; depois, sai do caminho dos outros testes
        camp = db.get(Campanha, cid)
        assert camp.status == "aguardando_aprovacao"
        camp.status = "cancelada"
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars():
            t.status = "cancelada"
        db.get(VisualCampanha, vid).ativo = False


def test_arte_sem_o_nome_do_responsavel():
    """A arte "Escritorios contabeis" começa com "Olá, {{nome}}!": sem o nome, saía "Olá, ! Tudo bem?" (23/11/2026)."""
    arte = VisualCampanha(nome="x", html="<p>Olá, {{nome}}! Tudo bem? Oi {{nome}}, como vai? Conheci a {{empresa}}.</p>")
    assert "<p>Olá! Tudo bem? Oi, como vai? Conheci a Empresa X.</p>" in visual.montar_html(
        arte, "", {"nome": "", "empresa": "Empresa X"})
    assert "<p>Olá, Ana! Tudo bem? Oi Ana, como vai? Conheci a Empresa X.</p>" in visual.montar_html(
        arte, "", {"nome": "Ana", "empresa": "Empresa X"})


def test_nova_campanha_avisa_quando_nenhuma_arte_foi_escolhida(cliente):
    """As campanhas 115 e 116 saíram sem a arte: o campo virou "Sua arte (visual)" e "Nenhuma arte" mostra um aviso."""
    with sessao() as db:
        vid = _visual(db, "Arte Nova Campanha Teste").id
    pagina = html_lib.unescape(cliente.get("/campanhas/nova").text)
    assert "Sua arte (visual)" in pagina and '<option value="">Nenhuma arte</option>' in pagina
    aviso = pagina[pagina.index('id="sem-arte"'):]
    assert aviso.split(">", 1)[0].count("hidden") == 0  # nada escolhido: o aviso aparece
    assert "Nenhuma arte escolhida:" in aviso and "os e-mails não levam a sua arte" in aviso
    with sessao() as db:
        db.get(VisualCampanha, vid).ativo = False
