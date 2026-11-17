"""E-mail das campanhas em HTML com a marca da AR (pedido da Maria em 16/11/2026): sem visual escolhido, a IA SDR e as
Empresas novas mandam do 2º e-mail em diante um HTML leve com o logo e a cor da marca; o 1º e-mail para cada empresa
continua só em texto. Fica desligado até ligar em Configurações > Geral (depois de ver a prévia em Campanhas > Visuais)."""

from datetime import date, timedelta

from sqlalchemy import select

from app import campanhas, config, visual
from app.banco import gravar_config, sessao
from app.integracoes import email_smtp
from app.modelos import Campanha, Lead, Tarefa, Usuario

TEXTO = ("Olá, Ana!\n\nToque {n}: fale com a gente em https://wa.me/5581999990000.\n\n"
         "Atenciosamente,\nPaulo\nEmpresa Teste")


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _campanha(db, tipo: str, empresa: str, email: str) -> tuple[Lead, list[Tarefa]]:
    admin = _admin(db)
    camp = Campanha(nome=f"HTML marca {empresa}", tipo=tipo, status="ativa", usuario_id=admin.id, canais="email")
    lead = Lead(empresa=empresa, email=email, vendedor_id=admin.id, responsavel="Ana")
    db.add_all([camp, lead])
    db.flush()
    toques = []
    for n, dias in enumerate((0, 5, 12), start=1):
        t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="email", hora="09:00",
                   data=date.today() + timedelta(days=dias), status="pendente", assunto=f"Assunto {n}",
                   mensagem=TEXTO.format(n=n))
        db.add(t)
        toques.append(t)
    db.flush()
    return lead, toques


def _ligar(db, ligado: bool):
    gravar_config(db, visual.CHAVE_HTML_DA_MARCA, "1" if ligado else "0")
    db.flush()


def test_desligado_os_emails_saem_so_em_texto(cliente):
    with sessao() as db:
        _ligar(db, False)
        lead, toques = _campanha(db, "parceiros", "Html Marca Desligado Ltda", "desligado@html-marca-teste.com.br")
        assert visual.html_do_email(db, toques[1], lead, None, toques[1].mensagem, "https://x/sair") == ""
        db.rollback()


def test_ligado_o_html_com_a_marca_vem_do_segundo_email_em_diante(cliente, monkeypatch):
    with sessao() as db:
        _ligar(db, True)
        lead, toques = _campanha(db, "empresas_novas", "Html Marca Novas Ltda", "novas@html-marca-teste.com.br")
        sair = "https://prospeccao.exemplo.com.br/descadastrar/1/abc"
        assert visual.html_do_email(db, toques[0], lead, None, toques[0].mensagem, sair) == ""  # o 1º: só texto
        html = visual.html_do_email(db, toques[1], lead, None, toques[1].mensagem, sair)
        assert "Toque 2" in html and 'role="presentation"' in html and "Arial" in html
        assert '<a href="https://wa.me/5581999990000"' in html  # o endereço do texto vira link
        assert sair in html and "Não quer mais receber" in html  # o descadastro (obrigatório) no rodapé
        assert "<script" not in html and html.count("<img") <= 1  # leve: no máximo o logo
        assert visual.html_do_email(db, toques[2], lead, None, toques[2].mensagem, sair)  # o 3º também
        # o 1º e-mail foi cancelado antes de sair: o 2º passa a ser o primeiro (vai só em texto)
        toques[0].status = "cancelada"
        db.flush()
        assert visual.html_do_email(db, toques[1], lead, None, toques[1].mensagem, sair) == ""
        toques[0].status = "pendente"
        db.flush()

        # IA SDR também; a Renovação não (ela manda a arte do aviso)
        lead_sdr, sdr = _campanha(db, "parceiros", "Html Marca Sdr Ltda", "sdr@html-marca-teste.com.br")
        assert visual.html_do_email(db, sdr[1], lead_sdr, None, sdr[1].mensagem, sair)
        lead_renov, renov = _campanha(db, "renovacao", "Html Marca Renovacao Ltda", "renov@html-marca-teste.com.br")
        assert visual.html_do_email(db, renov[1], lead_renov, None, renov[1].mensagem, sair) == ""

        # no envio de verdade, o e-mail sai com as duas versões (texto e o HTML com a marca)
        enviados = []
        monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **k: enviados.append((corpo, k)) or "<id@x>")
        monkeypatch.setattr(campanhas, "conta_do_toque", lambda *a, **k: None)
        assert campanhas._enviar_email_da_tarefa(db, toques[1], _admin(db), "Enviada") == ""
        corpo, extra = enviados[-1]
        assert "Toque 2" in corpo and "Toque 2" in extra["html"] and 'role="presentation"' in extra["html"]
        db.rollback()


def test_logo_e_cor_da_marca(monkeypatch):
    monkeypatch.setattr(config, "URL_PUBLICA", "https://prospeccao.exemplo.com.br")
    assert visual._logo_para_email({"logo_url": "/marca/logo/1/abc?v=2"}) == \
        "https://prospeccao.exemplo.com.br/marca/logo/1/abc?v=2"
    assert visual._logo_para_email({"logo_url": ""}) == ""
    monkeypatch.setattr(config, "URL_PUBLICA", "http://localhost:8001")
    assert visual._logo_para_email({"logo_url": "/marca/logo/1/abc?v=2"}) == ""  # sem internet: vai o nome
    assert visual._cor("#E86A1F") == "#E86A1F" and visual._cor("vermelho") == visual.COR_PADRAO
    assert visual._cor('#fff" onload="x') == visual.COR_PADRAO


def test_tela_de_visuais_mostra_a_previa_e_se_esta_ligado(cliente):
    with sessao() as db:
        _ligar(db, False)
    pagina = cliente.get("/visuais").text
    assert "E-mail com a marca (padrão)" in pagina and "Desligado" in pagina and "srcdoc=" in pagina
    assert "do 2º e-mail em" in pagina
    with sessao() as db:
        _ligar(db, True)
    assert "Ligado" in cliente.get("/visuais").text
    assert "e-mail em HTML com a marca" in cliente.get("/configuracoes").text
    with sessao() as db:
        _ligar(db, False)
