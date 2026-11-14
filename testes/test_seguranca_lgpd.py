"""Plano de segurança da plataforma (itens que faltavam, 14/11/2026): prazo de 2 horas na entrada do Admin Master numa
AR, limite de pedidos por pessoa, e-mail e telefone mascarados no registro de atividades e prazo de guarda da cópia
das conversas do WhatsApp (LGPD)."""
from datetime import timedelta

from sqlalchemy import func, select

from app import seguranca
from app.banco import agora, gravar_config, sessao
from app.leads_servico import apagar_conversas_antigas
from app.modelos import AcessoMaster, LogAuditoria, MensagemWhatsApp, Tenant
from conftest import csrf_de


def test_entrada_do_master_na_ar_tem_prazo(cliente, csrf, monkeypatch):
    from app.rotas import master

    with sessao() as db:
        certy = db.execute(select(Tenant.id).where(Tenant.slug == "grupo-certy")).scalar()
    r = cliente.post(f"/master/entrar/{certy}", data={"csrf": csrf, "motivo": "conferir o prazo da entrada"})
    assert "Você está dentro da" in r.text and "(até as " in r.text
    monkeypatch.setattr(master, "PRAZO_ENTRADA_SEG", -60)  # a próxima entrada já nasce vencida
    pagina = cliente.post(f"/master/entrar/{certy}", data={"csrf": csrf, "motivo": "conferir o prazo vencido"}).text
    assert "terminou (prazo de 2 horas)" in pagina and "Você está dentro da" not in pagina  # a tela seguinte já avisa
    assert "Você está dentro da" not in cliente.get("/").text
    with sessao() as db:  # a entrada foi fechada (registro do painel master)
        assert db.execute(select(func.count(AcessoMaster.id)).where(AcessoMaster.fim.is_(None))).scalar() == 0


def test_limite_de_pedidos_por_pessoa(cliente, monkeypatch):
    monkeypatch.setattr(seguranca, "limite_pessoa", seguranca.Limitador(maximo=2, janela_seg=60))
    pagina = cliente.get("/minha-conta").text
    respostas = [cliente.post("/minha-conta/empresa", data={"csrf": csrf_de(pagina), "nome": ""}) for _ in range(3)]
    assert "Muitas ações em pouco tempo" not in respostas[1].text
    assert "Muitas ações em pouco tempo" in respostas[2].text


def test_registro_de_atividades_mascara_email_e_telefone():
    with sessao() as db:
        seguranca.registrar_log(db, None, "teste_mascara", "teste", None,
                                "Conta maria.souza@grupocerty.com.br, WhatsApp (81) 99999-8888, CNPJ 12.345.678/0001-90")
    with sessao() as db:
        log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "teste_mascara")).scalars().one()
    assert log.detalhes == "Conta ma***@grupocerty.com.br, WhatsApp (81) *****-8888, CNPJ 12.345.678/0001-90"


def test_guarda_da_copia_das_conversas(cliente):
    with sessao() as db:
        velha = MensagemWhatsApp(id_wl=990001, telefone="81911112222", conexao="principal", direcao="entrada",
                                 texto="mensagem velha", criado_em=agora() - timedelta(days=400))
        nova = MensagemWhatsApp(id_wl=990002, telefone="81911112222", conexao="principal", direcao="entrada",
                                texto="mensagem nova", criado_em=agora() - timedelta(days=30))
        db.add_all([velha, nova])
        db.flush()
        ids = (velha.id, nova.id)
    with sessao() as db:  # sem prazo (o padrão): nada sai
        assert apagar_conversas_antigas(db) == 0
        gravar_config(db, "guarda_conversas_meses", "12")
    try:
        with sessao() as db:
            assert apagar_conversas_antigas(db) >= 1
        with sessao() as db:
            assert db.get(MensagemWhatsApp, ids[0]) is None and db.get(MensagemWhatsApp, ids[1]) is not None
            log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "apagou_conversas_antigas")
                             .order_by(LogAuditoria.id.desc())).scalars().first()
            assert log is not None and "mais de 12 meses" in log.detalhes
    finally:
        with sessao() as db:
            gravar_config(db, "guarda_conversas_meses", "0")
            db.query(MensagemWhatsApp).filter(MensagemWhatsApp.id.in_(ids)).delete()
