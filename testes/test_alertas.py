"""Auditoria de 11/11/2026, P0.2: avisos por e-mail quando algo para (ponte do WhatsApp, número desconectado, rotina
com erro, e-mails falhando, agendador parado), sem repetir, com lembrete a cada 12 h e e-mail de "resolvido"."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import alertas
from app.banco import agora, gravar_config, ler_config, sessao
from app.modelos import Lead, Mensagem, Notificacao
from conftest import csrf_de


@pytest.fixture()
def caixa(monkeypatch):
    """Liga os avisos (no teste não é nuvem) e guarda os e-mails em vez de enviar."""
    from app.integracoes import email_smtp

    enviados = []
    monkeypatch.setattr(alertas.config, "ALERTAS_LIGADOS", True)
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **_: enviados.append((para, assunto, corpo)))
    with sessao() as db:
        gravar_config(db, alertas.ESTADO, {})
        gravar_config(db, alertas.FALHAS, {})
    yield enviados
    with sessao() as db:  # não deixa problema aberto para os outros testes
        gravar_config(db, alertas.ESTADO, {})
        gravar_config(db, alertas.FALHAS, {})
        gravar_config(db, "wl_status", "")


def _relogio(monkeypatch, momento):
    monkeypatch.setattr(alertas, "agora", lambda: momento)


def test_ponte_parada_avisa_uma_vez_lembra_e_avisa_quando_volta(cliente, caixa, monkeypatch):
    monkeypatch.setattr(alertas.config, "WHATSAPP_PONTE", True)
    inicio = agora()
    with sessao() as db:
        gravar_config(db, "wl_status", {"conectado": True, "visto_em": (inicio - timedelta(minutes=20)).isoformat()})
    _relogio(monkeypatch, inicio)
    assert alertas.verificar()["novos"] == 1
    assert caixa[0][0] == "admin@teste.com.br" and "computador do WhatsApp Leads não responde" in caixa[0][1]
    assert "ligar_nuvem.bat" in caixa[0][2] and "/whatsapp" in caixa[0][2]
    assert alertas.verificar()["novos"] == 0 and len(caixa) == 1  # não repete a cada 5 minutos
    _relogio(monkeypatch, inicio + timedelta(hours=12, minutes=1))
    assert alertas.verificar()["lembretes"] == 1 and caixa[-1][1].startswith("[Prospecção MS] ⚠️ Continua:")
    with sessao() as db:  # o computador voltou
        gravar_config(db, "wl_status", {"conectado": True, "conexoes": {},
                                        "visto_em": (inicio + timedelta(hours=12, minutes=1)).isoformat()})
        assert db.execute(select(Notificacao).where(Notificacao.texto.like("%não responde%"))).first()
    assert alertas.verificar()["resolvidos"] == 1 and "Resolvido" in caixa[-1][1] and "durou" in caixa[-1][2]
    with sessao() as db:
        assert alertas.ativos(db) == []


def test_numero_desconectado_espera_15_minutos(cliente, caixa, monkeypatch):
    monkeypatch.setattr(alertas.config, "WHATSAPP_PONTE", True)
    inicio = agora()
    with sessao() as db:
        lead = Lead(empresa="Aviso Numero Ltda", whatsapp="81973000001")
        db.add(lead)
        db.flush()
        db.add(Mensagem(lead_id=lead.id, canal="whatsapp", corpo="Oi", status="enviada", direcao="saida",
                        conexao="u-aviso", criado_em=inicio - timedelta(days=1)))
        gravar_config(db, "wl_status", {"conectado": True, "visto_em": inicio.isoformat(),
                                        "conexoes": {"principal": {"conectado": True},
                                                     "u-aviso": {"conectado": False, "estado": "Desconectado"},
                                                     "u-sem-uso": {"conectado": False}}})
    _relogio(monkeypatch, inicio)
    assert alertas.verificar()["novos"] == 0  # pode ser só uma queda rápida
    _relogio(monkeypatch, inicio + timedelta(minutes=16))
    with sessao() as db:
        gravar_config(db, "wl_status", {"conectado": True, "visto_em": (inicio + timedelta(minutes=16)).isoformat(),
                                        "conexoes": {"principal": {"conectado": True},
                                                     "u-aviso": {"conectado": False, "estado": "Desconectado"},
                                                     "u-sem-uso": {"conectado": False}}})
    assert alertas.verificar()["novos"] == 1
    assert "WhatsApp desconectado: u-aviso" in caixa[0][1]  # o número sem uso não gera aviso
    assert len(caixa) == 1
    # número que o computador não conhece sai pelo principal: é o principal que precisa estar conectado
    with sessao() as db:
        db.add(Mensagem(lead_id=lead.id, canal="whatsapp", corpo="Oi", status="enviada", direcao="saida",
                        conexao="u-desconhecido", criado_em=inicio - timedelta(days=1)))
        gravar_config(db, "wl_status", {"conectado": True, "visto_em": (inicio + timedelta(minutes=16)).isoformat(),
                                        "conexoes": {"principal": {"conectado": False, "estado": "Desconectado"},
                                                     "u-aviso": {"conectado": True}}})
        problemas = alertas.problemas_agora(db)
        assert "numero:principal" in problemas and "numero:u-desconhecido" not in problemas
        assert "numero:u-aviso" not in problemas


def test_rotina_com_erro_seguido_e_emails_falhando(cliente, caixa):
    for _ in range(2):
        alertas.falhou("fila_email", RuntimeError("SMTP recusou a senha"))
    assert alertas.verificar()["novos"] == 0  # 2 falhas ainda não avisam
    alertas.falhou("fila_email", RuntimeError("SMTP recusou a senha"))
    assert alertas.verificar()["novos"] == 1
    assert "Erro repetido na fila de e-mails" in caixa[-1][1] and "SMTP recusou a senha" in caixa[-1][2]
    alertas.funcionou("fila_email")
    assert alertas.verificar()["resolvidos"] == 1

    with sessao() as db:
        lead = Lead(empresa="Aviso Email Falha Ltda", email="x@aviso-falha.com.br")
        db.add(lead)
        db.flush()
        for _ in range(5):
            db.add(Mensagem(lead_id=lead.id, canal="email", corpo="Oi", status="falhou", direcao="saida"))
    assert alertas.verificar()["novos"] == 1 and "E-mails da fila não estão saindo" in caixa[-1][1]
    with sessao() as db:
        for m in db.execute(select(Mensagem).where(Mensagem.lead_id == lead.id)).scalars():
            m.status = "enviada"


def test_agendador_parado_avisa_quando_volta(cliente, caixa, monkeypatch):
    inicio = agora()
    with sessao() as db:
        gravar_config(db, alertas.ULTIMA_RODADA, (inicio - timedelta(hours=19)).isoformat(timespec="seconds"))
    _relogio(monkeypatch, inicio)
    alertas.marcar_rodada()
    assert "agendador ficou parado" in caixa[-1][1] and "19 h" in caixa[-1][2]
    alertas.marcar_rodada()  # rodada seguinte (1 minuto depois): nada de novo
    assert len(caixa) == 1
    with sessao() as db:
        assert ler_config(db, alertas.ULTIMA_RODADA).startswith(inicio.isoformat()[:16])


def test_tela_mostra_os_avisos_e_manda_teste(cliente, caixa):
    pagina = cliente.get("/configuracoes?aba=integracoes").text
    assert "Avisos de problema por e-mail" in pagina and "admin@teste.com.br" in pagina
    r = cliente.post("/configuracoes/alertas/teste", data={"csrf": csrf_de(pagina)})
    assert "E-mail de teste enviado para admin@teste.com.br" in r.text
    assert caixa[-1][1] == "[Prospecção MS] Teste dos avisos de problema"
    with sessao() as db:  # lista própria em Configurações
        gravar_config(db, "alertas_emails", "maria@exemplo.com.br; paulo@exemplo.com.br")
        assert alertas.destinatarios(db) == ["maria@exemplo.com.br", "paulo@exemplo.com.br"]
        gravar_config(db, "alertas_emails", "")
