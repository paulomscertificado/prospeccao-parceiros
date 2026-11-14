"""White label, Fase 4: fila justa entre as ARs e avisos para quem é da AR (o portão da Fase 4: uma AR parada ou no
limite não atrasa as outras). A regra da Maria (um envio automático por vez, 3 a 4 minutos) continua: só muda quem
tem a vez."""
from datetime import date, timedelta

from sqlalchemy import delete, select

from app import alertas, campanhas
from app.banco import agora, gravar_config, ler_config, sessao, usar_config_da_ar
from app.mensagens import enviadas_hoje
from app.modelos import Campanha, ConfiguracaoAR, Lead, Mensagem, Tarefa, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA


def _ars(db) -> dict:
    return {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}


def test_a_vez_vai_para_a_ar_que_mandou_ha_mais_tempo(cliente):
    with sessao() as db:
        gravar_config(db, "revezamento:teste", {"1": "2026-11-14T10:00:00", "2": "2026-11-14T09:00:00"})
        linhas = [(10, 1), (11, 1), (20, 2), (30, 3)]  # (tarefa, AR); a AR 3 nunca mandou
        assert campanhas._revezar(db, "teste", linhas) == [30, 20, 10, 11]
        campanhas._anotar_vez(db, "teste", 3)
        assert campanhas._revezar(db, "teste", linhas) == [20, 10, 11, 30]  # a 3 acabou de mandar: vai para o fim
        db.rollback()


def test_limite_de_uma_ar_conta_so_os_envios_dela(cliente):
    with sessao() as db:
        ars = _ars(db)

        def contar(ar):
            usar_config_da_ar(db, ar)
            try:
                return enviadas_hoje(db, "email")
            finally:
                usar_config_da_ar(db, None)

        antes = {ar: contar(ar) for ar in ars.values()}
        for ar, quantos in ((ars["ms"], 3), (ars["grupo-certy"], 1)):
            for _ in range(quantos):
                db.add(Mensagem(canal="email", direcao="saida", status="enviada", corpo="x", tenant_id=ar))
        db.flush()
        assert contar(ars["ms"]) == antes[ars["ms"]] + 3  # cada AR conta só os dela
        assert contar(ars["grupo-certy"]) == antes[ars["grupo-certy"]] + 1
        db.rollback()


def test_ar_no_limite_nao_atrasa_a_outra(cliente, monkeypatch):
    """O portão da Fase 4: a AR MS chegou ao limite diário de e-mails; o e-mail do Grupo Certy sai na mesma rodada."""
    from app.integracoes import email_smtp

    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    enviados = []
    monkeypatch.setattr(campanhas, "conta_do_toque", lambda db, t, u=None: None)
    monkeypatch.setattr(campanhas, "_enviar_email_da_tarefa",
                        lambda db, t, u, r, conta=None, registrar_erro_da_caixa=True: enviados.append(t.lead.empresa) or "")
    monkeypatch.setattr(campanhas, "_chave_pausa", lambda conta: "fila_email_pausada_ate:teste")
    with sessao() as db:
        ars = _ars(db)
        gravar_config(db, "enviar_email_automatico", "1")
        db.add(ConfiguracaoAR(tenant_id=ars["ms"], chave="limite_diario_email", valor="1"))  # MS: 1 por dia
        dono = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        ontem = date.today() - timedelta(days=1)
        for ar, nome, quantos in ((ars["ms"], "Fila MS", 3), (ars["grupo-certy"], "Fila Certy", 1)):
            camp = Campanha(nome=f"Campanha {nome}", status="ativa", usuario_id=dono.id, canais="email",
                            aprovado_em=agora(), tenant_id=ar)
            db.add(camp)
            db.flush()
            for i in range(quantos):
                lead = Lead(empresa=f"{nome} {i}", email=f"l{i}@{nome.replace(' ', '').lower()}.com.br",
                            status="Contatado", tenant_id=ar)
                db.add(lead)
                db.flush()
                db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="email", data=ontem,
                              hora="08:01", status="pendente", mensagem="Olá", tenant_id=ar))
        db.add(Mensagem(canal="email", direcao="saida", status="enviada", corpo="já saiu hoje", tenant_id=ars["ms"]))
        db.flush()
        campanhas.processar_fila(db, maximo=1000)
        assert "Fila Certy 0" in enviados  # o Grupo Certy sai...
        assert not [e for e in enviados if e.startswith("Fila MS")]  # ...e a MS, no limite dela, espera
        db.rollback()


def test_aviso_de_numero_vai_para_o_admin_da_ar_dele(cliente):
    with sessao() as db:
        ars = _ars(db)
        antes = ler_config(db, "alertas_emails")
        gravar_config(db, "alertas_emails", "")
        certy = Usuario(nome="Admin aviso Certy", email="aviso.admin@grupocerty.com.br", perfil="admin",
                        senha_hash=resumir_senha(SENHA), tenant_id=ars["grupo-certy"])
        ms = Usuario(nome="Admin aviso MS", email="aviso.admin@ms.com.br", perfil="admin",
                     senha_hash=resumir_senha(SENHA), tenant_id=ars["ms"])
        db.add_all([certy, ms])
        db.flush()
        master = db.execute(select(Usuario).where(Usuario.master.is_(True))).scalars().first()
        plataforma = alertas.destinatarios(db)
        assert master.email in plataforma and certy.email not in plataforma and ms.email not in plataforma
        da_certy = alertas.destinatarios(db, ars["grupo-certy"])
        assert master.email in da_certy and certy.email in da_certy and ms.email not in da_certy
        todos = alertas.destinatarios(db, todos=True)
        assert certy.email in todos and ms.email in todos
        db.rollback()
        gravar_config(db, "alertas_emails", antes)
        db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.chave == "nada"))
