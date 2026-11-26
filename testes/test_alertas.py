"""Auditoria de 11/11/2026, P0.2: avisos por e-mail quando algo para (ponte do WhatsApp, número desconectado, rotina
com erro, e-mails falhando, agendador parado, API de licenças do Assinador MS), sem repetir, com lembrete a cada 12 h
e e-mail de "resolvido"."""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import delete, select

from app import alertas
from app.banco import agora, gravar_config, ler_config, ler_config_json, sessao
from app.modelos import Lead, Mensagem, Notificacao, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de


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
        gravar_config(db, alertas.LICENCAS, {})
    yield enviados
    with sessao() as db:  # não deixa problema aberto para os outros testes
        gravar_config(db, alertas.ESTADO, {})
        gravar_config(db, alertas.FALHAS, {})
        gravar_config(db, alertas.LICENCAS, {})
        gravar_config(db, "wl_status", "")


class _ApiDeLicencasFalsa:
    """Finge a API de licenças do Assinador MS (os testes nunca falam com o servidor de verdade)."""
    URL = "http://127.0.0.1:8040/api/v1/ready"

    def __init__(self):
        self.situacao = "no_ar"
        self.pedidos: list[str] = []

    def get(self, url, **_):
        self.pedidos.append(url)
        if self.situacao == "parada":  # serviço desligado: ninguém atende na porta
            raise httpx.ConnectError("[Errno 111] Connection refused")
        if self.situacao == "lenta":
            raise httpx.ReadTimeout("timed out")
        if self.situacao == "sem_banco":  # o processo responde, mas o banco das licenças não
            return httpx.Response(503, json={"error": {"code": "SERVICE_UNAVAILABLE"}})
        if self.situacao == "pagina":  # 200, mas não é o /ready (outra coisa na porta)
            return httpx.Response(200, text="<html>Bem-vindo</html>")
        return httpx.Response(200, json={"status": "ready"})


@pytest.fixture()
def api_licencas(monkeypatch):
    falsa = _ApiDeLicencasFalsa()
    monkeypatch.setattr(alertas.config, "LICENCAS_READY_URL", falsa.URL)
    monkeypatch.setattr(alertas.httpx, "get", falsa.get)
    return falsa


def _da_api(caixa) -> list:
    return [e for e in caixa if "Assinador MS" in e[1]]


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
    assert alertas.verificar()["lembretes"] == 1 and caixa[-1][1].startswith("[Prospecção] ⚠️ Continua:")
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
    assert caixa[-1][1] == "[Prospecção] Teste dos avisos de problema"
    with sessao() as db:  # lista própria em Configurações
        gravar_config(db, "alertas_emails", "maria@exemplo.com.br; paulo@exemplo.com.br")
        assert alertas.destinatarios(db) == ["maria@exemplo.com.br", "paulo@exemplo.com.br"]
        gravar_config(db, "alertas_emails", "")


# ---------------------------------------------------------------- API de licenças do Assinador MS (26/11/2026)

def test_api_de_licencas_caiu_avisa_so_a_ms_e_avisa_quando_volta(cliente, caixa, api_licencas, monkeypatch):
    """A API de licenças (mesmo servidor) parou: aviso só na 2ª conferência seguida sem resposta, só para a MS (Admin
    Master e administradores da AR MS; o de outra AR não recebe nem vê), sem repetir a cada 5 minutos, lembrete em 12 h
    e e-mail quando volta."""
    with sessao() as db:
        ids = {slug: id_ for id_, slug in db.execute(select(Tenant.id, Tenant.slug))}
        certy = Usuario(nome="Admin licencas Certy", email="licencas.admin@grupocerty.com.br", perfil="admin",
                        senha_hash=resumir_senha(SENHA), tenant_id=ids["grupo-certy"])
        ms = Usuario(nome="Admin licencas MS", email="licencas.admin@ms.com.br", perfil="admin",
                     senha_hash=resumir_senha(SENHA), tenant_id=ids["ms"])
        db.add_all([certy, ms])
        db.flush()
        id_certy, id_ms = certy.id, ms.id
        master = db.execute(select(Usuario.email).where(Usuario.master.is_(True))).scalars().first()
    try:
        inicio = agora()
        _relogio(monkeypatch, inicio)
        alertas.verificar()  # no ar: nada
        api_licencas.situacao = "parada"
        alertas.verificar()  # 1ª conferência sem resposta: pode ser só uma reinicialização
        assert not _da_api(caixa)
        with sessao() as db:
            contagem = ler_config_json(db, alertas.LICENCAS, {})
            assert contagem["seguidas"] == 1 and contagem["erro"] == "o serviço não atende: parece parado"
            assert "licencas" not in {a["chave"] for a in alertas.ativos(db)}

        _relogio(monkeypatch, inicio + timedelta(minutes=5))
        api_licencas.situacao = "sem_banco"
        assert alertas.verificar()["novos"] >= 1  # 2ª seguida: avisa
        avisos = _da_api(caixa)
        assert avisos and all("Assinador MS: o servidor de licenças não responde" in a for _, a, _ in avisos)
        corpo = avisos[0][2]
        assert f"Desde {inicio:%d/%m às %H:%M}" in corpo and "erro 503" in corpo and "72 horas" in corpo
        assert "assinador-licencas" in corpo and "/configuracoes?aba=integracoes#avisos" in corpo
        para = {destino for destino, _, _ in avisos}
        assert master in para and "licencas.admin@ms.com.br" in para
        assert "licencas.admin@grupocerty.com.br" not in para  # outra AR não recebe
        with sessao() as db:
            no_sino = set(db.execute(select(Notificacao.usuario_id).where(
                Notificacao.texto.like("%servidor de licenças%"))).scalars())
            assert id_ms in no_sino and id_certy not in no_sino
            aberto = next(a for a in alertas.ativos(db) if a["chave"] == "licencas")
            assert aberto["ar"] == ids["ms"] and aberto["avisado_em"]
            assert "licencas" in {a["chave"] for a in alertas.ativos(db, ids["ms"])}
            assert "licencas" not in {a["chave"] for a in alertas.ativos(db, ids["grupo-certy"])}  # nem na tela

        _relogio(monkeypatch, inicio + timedelta(minutes=10))
        alertas.verificar()  # continua fora: nada de repetir a cada 5 minutos
        assert len(_da_api(caixa)) == len(avisos)
        _relogio(monkeypatch, inicio + timedelta(hours=12, minutes=6))
        alertas.verificar()
        lembretes = _da_api(caixa)[len(avisos):]
        assert lembretes and all("⚠️ Continua: Assinador MS" in a for _, a, _ in lembretes)

        api_licencas.situacao = "no_ar"  # voltou
        _relogio(monkeypatch, inicio + timedelta(hours=12, minutes=11))
        antes = len(_da_api(caixa))
        assert alertas.verificar()["resolvidos"] >= 1
        resolvidos = _da_api(caixa)[antes:]
        assert resolvidos and all("✅ Resolvido: Assinador MS" in a for _, a, _ in resolvidos)
        assert "durou 12 h 11 min" in resolvidos[0][2]
        assert "licencas.admin@grupocerty.com.br" not in {destino for destino, _, _ in resolvidos}
        with sessao() as db:
            assert not ler_config_json(db, alertas.LICENCAS, {})
            assert "licencas" not in {a["chave"] for a in alertas.ativos(db)}
        total = len(_da_api(caixa))
        alertas.verificar()  # no ar de novo: nada
        assert len(_da_api(caixa)) == total
        assert set(api_licencas.pedidos) == {api_licencas.URL}  # só o endereço configurado
    finally:
        with sessao() as db:  # tira as pessoas do teste (e os avisos do sino delas)
            db.execute(delete(Notificacao).where(Notificacao.usuario_id.in_([id_certy, id_ms])))
            db.execute(delete(Usuario).where(Usuario.id.in_([id_certy, id_ms])))


def test_api_de_licencas_uma_falha_so_nao_avisa(cliente, caixa, api_licencas):
    """Uma conferência sem resposta e a seguinte no ar (ex.: a API reiniciando na publicação): nenhum e-mail."""
    for situacao, erro in (("pagina", "respondeu algo inesperado"), ("lenta", "não respondeu em 10 segundos")):
        api_licencas.situacao = situacao
        alertas.verificar()
        with sessao() as db:
            contagem = ler_config_json(db, alertas.LICENCAS, {})
            assert contagem["seguidas"] == 1 and contagem["erro"] == erro
        api_licencas.situacao = "no_ar"
        alertas.verificar()
        with sessao() as db:
            assert not ler_config_json(db, alertas.LICENCAS, {})  # a contagem recomeça
    assert not _da_api(caixa)  # nem aviso nem "resolvido"


def test_api_de_licencas_fora_do_servidor_nao_confere(cliente, caixa, api_licencas, monkeypatch):
    """Sem o endereço (computador local, testes): não pergunta nada a ninguém."""
    monkeypatch.setattr(alertas.config, "LICENCAS_READY_URL", "")
    api_licencas.situacao = "parada"
    with sessao() as db:
        assert alertas.conferir_licencas(db) is None
    alertas.verificar()
    alertas.verificar()
    assert api_licencas.pedidos == [] and not _da_api(caixa)
