"""API oficial do WhatsApp por AR (app/whatsapp_oficial.py; pedido da Maria em 16/11/2026): as chaves ficam guardadas
protegidas e nunca voltam para a tela; o teste de conexão e a mensagem de teste falam com a Meta (aqui, imitada); o
webhook confere a assinatura com a chave secreta da conta do número que recebeu e manda a resposta para o lead da AR
desse número (SAIR vale para todas as ARs)."""

import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config, whatsapp_oficial
from app.banco import sessao
from app.integracoes import whatsapp_cloud
from app.leads_servico import limpar_campos
from app.main import app
from app.modelos import ContaWhatsAppOficial, Lead, LogAuditoria, Mensagem, Tenant, Usuario
from app.seguranca import criptografar, descriptografar, limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

TOKEN = "EAAGteste" + "x" * 60
SEGREDO = "segredo-do-app-teste"
NUMERO_ID = "1425129957352130"
EMAIL_MS = "admin.oficial@ms-oficial-teste.com.br"


def _zerar_limite():
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)


def _admin(email: str, empresa: str) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if u is None:
            u = Usuario(nome=f"Admin {empresa}", email=email, perfil="admin", senha_hash=resumir_senha(SENHA),
                        empresa_nome=empresa)
            db.add(u)
            db.flush()
        return u.tenant_id


def _entrar(email: str) -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


class _Resposta:  # imita a resposta do httpx
    def __init__(self, dados: dict, status: int = 200):
        self._dados, self.status_code, self.text = dados, status, json.dumps(dados)

    def json(self):
        return self._dados


def _meta_falsa(monkeypatch) -> list:
    chamadas = []

    def pedir(metodo, url, **kw):
        chamadas.append((metodo, url, kw))
        if url.endswith("/debug_token"):  # o token alcança uma conta do WhatsApp Business
            return _Resposta({"data": {"granular_scopes": [
                {"scope": "whatsapp_business_management", "target_ids": ["998877"]},
                {"scope": "whatsapp_business_messaging", "target_ids": ["998877"]}]}})
        if url.endswith("/subscribed_apps"):
            return _Resposta({"success": True})
        if metodo == "GET":
            return _Resposta({"display_phone_number": "+55 81 8343-0717", "verified_name": "Empresa Oficial Teste",
                              "quality_rating": "GREEN", "whatsapp_business_manager_messaging_limit": "TIER_2K",
                              "id": NUMERO_ID})
        return _Resposta({"messages": [{"id": "wamid.TESTE123"}]})

    monkeypatch.setattr(whatsapp_cloud.httpx, "request", pedir)
    return chamadas


def _ars() -> tuple[int, int]:
    with sessao() as db:
        ids = dict(db.execute(select(Tenant.slug, Tenant.id)).all())
    return ids["ms"], ids["grupo-certy"]


def test_tela_guarda_as_chaves_protegidas_testa_e_manda_o_teste(cliente, monkeypatch):
    _zerar_limite()
    ar = _admin(EMAIL_MS, "MS Certificação Digital")
    chamadas = _meta_falsa(monkeypatch)
    c = _entrar(EMAIL_MS)
    tela = c.get("/whatsapp").text
    assert "API oficial da Meta" in tela and "Salvar e testar" in tela
    # o ID da conta do WhatsApp Business em branco: o sistema descobre pelo token e liga o app à conta
    r = c.post("/whatsapp/oficial", data={"csrf": csrf_de(tela), "nome": "Empresa Oficial", "waba_id": "",
                                          "phone_number_id": NUMERO_ID, "token": TOKEN, "segredo": SEGREDO})
    assert r.status_code == 200 and "Salvo e conectado" in r.text and "O app foi ligado" in r.text, r.text[:500]
    with sessao() as db:
        conta = db.execute(select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.phone_number_id == NUMERO_ID)).scalar_one()
        assert TOKEN not in conta.token_cripto and descriptografar(conta.token_cripto) == TOKEN
        assert descriptografar(conta.segredo_cripto) == SEGREDO and len(conta.verificacao) >= 20
        assert conta.numero == "+55 81 8343-0717" and conta.tenant_id == ar and conta.waba_id == "998877"
        verificacao = conta.verificacao
    versao = config.WHATSAPP_API_VERSAO  # padrão v27.0; o .env pode trocar (o da pasta principal tinha v21.0)
    inscricao = [(m, u) for m, u, _ in chamadas if u.endswith("/subscribed_apps")]
    assert inscricao == [("POST", f"https://graph.facebook.com/{versao}/998877/subscribed_apps")]
    metodo, url, kw = chamadas[0]  # o teste de conexão pergunta pelo número, com o token da conta
    assert metodo == "GET" and url.endswith(f"/{versao}/{NUMERO_ID}") and "quality_rating" in kw["params"]["fields"]
    assert kw["headers"]["Authorization"] == f"Bearer {TOKEN}"
    tela = c.get("/whatsapp").text
    assert TOKEN not in tela and SEGREDO not in tela  # as chaves nunca voltam para a tela
    assert verificacao in tela and "/api/webhooks/whatsapp" in tela and "Guardado ✓" in tela
    assert "qualidade: Alta" in tela and "limite: 2K" in tela and "App ligado à conta do WhatsApp" in tela
    # salvar de novo com o token em branco mantém o token guardado
    c.post("/whatsapp/oficial", data={"csrf": csrf_de(tela), "nome": "Empresa Oficial 2", "waba_id": "998877",
                                      "phone_number_id": NUMERO_ID, "token": "", "segredo": ""})
    with sessao() as db:
        conta = db.execute(select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.phone_number_id == NUMERO_ID)).scalar_one()
        assert conta.nome == "Empresa Oficial 2" and descriptografar(conta.token_cripto) == TOKEN
    # mensagem de teste: o modelo de exemplo da Meta, para o celular com o 9 da frente
    r = c.post("/whatsapp/oficial/teste", data={"csrf": csrf_de(tela), "telefone": "(81) 9888-7777"})
    assert "Mensagem de teste enviada" in r.text
    metodo, url, kw = chamadas[-1]
    assert metodo == "POST" and url.endswith(f"/{NUMERO_ID}/messages")
    assert kw["json"]["to"] == "5581998887777" and kw["json"]["type"] == "template"
    assert kw["json"]["template"] == {"name": "hello_world", "language": {"code": "en_US"}}
    # o token da Meta recusado aparece explicado na tela
    monkeypatch.setattr(whatsapp_cloud.httpx, "request", lambda *a, **k: _Resposta(
        {"error": {"message": "Invalid OAuth access token.", "code": 190}}, 401))
    r = c.post("/whatsapp/oficial/testar", data={"csrf": csrf_de(tela)})
    assert "O teste de conexão falhou" in r.text and "Invalid OAuth access token" in r.text


def test_outra_ar_nao_ve_a_conta_e_o_vendedor_nao_mexe(cliente, monkeypatch):
    _zerar_limite()
    _meta_falsa(monkeypatch)
    _admin("admin.oficial@grupocerty-oficial.com.br", "Grupo Certy")
    certy = _entrar("admin.oficial@grupocerty-oficial.com.br")
    tela = certy.get("/whatsapp").text
    assert "API oficial da Meta" in tela and NUMERO_ID not in tela  # a conta da outra AR não aparece
    r = certy.post("/whatsapp/oficial", data={"csrf": csrf_de(tela), "nome": "Copia", "waba_id": "1",
                                              "phone_number_id": NUMERO_ID, "token": TOKEN})
    assert "já está cadastrado em outra conta" in r.text  # o mesmo número não entra em duas ARs
    # o Admin Master fora de uma AR não configura (a conta é de cada AR)
    tela = cliente.get("/whatsapp").text
    assert "Entre numa AR" in tela


def _conta_da_ms() -> str:
    """Garante a conta oficial na AR MS (com a chave secreta conhecida) e devolve o token de verificação."""
    ms, _ = _ars()
    with sessao() as db:
        conta = db.execute(select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.phone_number_id == NUMERO_ID)
                           .execution_options(sem_filtro_de_ar=True)).scalars().first()
        if conta is None:
            conta = ContaWhatsAppOficial(phone_number_id=NUMERO_ID, waba_id="998877", tenant_id=ms,
                                         token_cripto=criptografar(TOKEN), verificacao="verificacao-teste-123456789")
            db.add(conta)
        conta.segredo_cripto = criptografar(SEGREDO)
        db.flush()
        return conta.verificacao


def _assinado(cliente, dados: dict, segredo: str = SEGREDO):
    corpo = json.dumps(dados).encode()
    assinatura = "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return cliente.post("/api/webhooks/whatsapp", content=corpo,
                        headers={"x-hub-signature-256": assinatura, "content-type": "application/json"})


def _evento(telefone: str, texto: str, statuses: list | None = None) -> dict:
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": NUMERO_ID},
        "contacts": [{"wa_id": telefone, "profile": {"name": "Contato Teste"}}],
        "messages": [{"from": telefone, "id": f"wamid.{texto[:8]}", "type": "text", "text": {"body": texto}}],
        "statuses": statuses or []}}]}]}


def test_webhook_verifica_com_o_token_da_conta(cliente):
    verificacao = _conta_da_ms()
    r = cliente.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": verificacao,
                                                      "hub.challenge": "4321"})
    assert r.status_code == 200 and r.text == "4321"
    r = cliente.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "errado",
                                                      "hub.challenge": "4321"})
    assert r.status_code == 403


def test_webhook_resposta_vai_para_o_lead_da_ar_do_numero_e_sair_para_todas(cliente):
    _conta_da_ms()
    ms, certy = _ars()
    with sessao() as db:
        do_ms = Lead(empresa="Contabil Oficial MS", whatsapp="(81) 99555-1234", tenant_id=ms)
        da_certy = Lead(empresa="Contabil Oficial Certy", whatsapp="(81) 99555-1234", tenant_id=certy)
        for lead in (do_ms, da_certy):
            limpar_campos(lead)
        db.add_all([do_ms, da_certy])
        db.flush()
        enviada = Mensagem(lead_id=do_ms.id, canal="whatsapp", corpo="Oi", status="enviada", id_externo="wamid.SAIU1",
                           tenant_id=ms)
        db.add(enviada)
        db.flush()
        ids = (do_ms.id, da_certy.id, enviada.id)
    evento = _evento("5581995551234", "Quero marcar uma reunião", [{"id": "wamid.SAIU1", "status": "delivered"}])
    assert _assinado(cliente, evento, "segredo-errado").status_code == 403  # assinatura de outro app: recusado
    assert _assinado(cliente, evento).status_code == 200
    with sessao() as db:
        assert db.get(Lead, ids[0]).classificacao_resposta == "QUER REUNIÃO"  # a resposta é da AR do número
        assert not db.get(Lead, ids[1]).classificacao_resposta
        assert db.get(Mensagem, ids[2]).status == "entregue"
    assert _assinado(cliente, _evento("5581995551234", "SAIR")).status_code == 200
    with sessao() as db:
        assert db.get(Lead, ids[0]).opt_out and db.get(Lead, ids[1]).opt_out  # SAIR vale para todas as ARs


# ---------------------------------------------------------------- ativar o número novo (18/11/2026)

SEM_ATIVAR = {"platform_type": "NOT_APPLICABLE", "status": "PENDING", "code_verification_status": "VERIFIED"}


def _meta_do_registro(monkeypatch, registro: dict, erro_no_registro: dict | None = None) -> list:
    """Meta imitada para a ativação: o número com a situação `registro` (platform_type, status,
    code_verification_status) e o POST /register com sucesso (o número passa a CLOUD_API/CONNECTED) ou com o erro."""
    chamadas, situacao_do_numero = [], dict(registro)

    def pedir(metodo, url, **kw):
        chamadas.append((metodo, url, kw))
        if url.endswith("/register"):
            if erro_no_registro:
                return _Resposta({"error": erro_no_registro}, 400)
            situacao_do_numero.update(platform_type="CLOUD_API", status="CONNECTED")
            return _Resposta({"success": True})
        if url.endswith("/subscribed_apps"):
            return _Resposta({"success": True})
        if metodo == "GET" and "platform_type" in (kw.get("params") or {}).get("fields", ""):
            return _Resposta(dict(situacao_do_numero))
        if metodo == "GET":
            return _Resposta({"display_phone_number": "+55 81 3333-0000", "verified_name": "Empresa Oficial Teste",
                              "quality_rating": "UNKNOWN", "whatsapp_business_manager_messaging_limit": "TIER_250"})
        return _Resposta({"messages": [{"id": "wamid.TESTE456"}]})

    monkeypatch.setattr(whatsapp_cloud.httpx, "request", pedir)
    return chamadas


def test_ativar_o_numero_novo_com_a_senha_de_6_numeros(cliente, monkeypatch):
    _zerar_limite()
    _admin(EMAIL_MS, "MS Certificação Digital")
    _conta_da_ms()
    chamadas = _meta_do_registro(monkeypatch, SEM_ATIVAR)
    c = _entrar(EMAIL_MS)
    tela = c.get("/whatsapp").text
    r = c.post("/whatsapp/oficial/testar", data={"csrf": csrf_de(tela)})
    assert "ainda não está ativado na API da Meta" in r.text and "Achado na Meta" in r.text, r.text[:500]
    with sessao() as db:  # sem o número ativado, a Renovação não liga o envio pela API
        assert "Ativar o número" in whatsapp_oficial.falta_para_renovacao(db, _ars()[0])
    # senha fora do padrão ou diferente na repetição: nada vai para a Meta
    for pin, pin2, esperado in (("12345", "12345", "exatamente 6 números"), ("4829l5", "4829l5", "exatamente 6 números"),
                                ("482915", "482916", "não são iguais")):
        r = c.post("/whatsapp/oficial/ativar", data={"csrf": csrf_de(tela), "pin": pin, "pin2": pin2})
        assert "O número não foi ativado" in r.text and esperado in r.text
    assert not [u for _, u, _ in chamadas if u.endswith("/register")]
    r = c.post("/whatsapp/oficial/ativar", data={"csrf": csrf_de(tela), "pin": "482 915", "pin2": "482915"})
    assert "Número ativado na API da Meta" in r.text, r.text[:500]
    registro = [(m, u, kw) for m, u, kw in chamadas if u.endswith("/register")]
    assert len(registro) == 1 and registro[0][0] == "POST" and registro[0][1].endswith(f"/{NUMERO_ID}/register")
    assert registro[0][2]["json"] == {"messaging_product": "whatsapp", "pin": "482915"}
    tela = c.get("/whatsapp").text
    assert "ainda não está ativado" not in tela and "Ativar de novo" in tela and "482915" not in tela
    with sessao() as db:  # a senha não fica guardada em lugar nenhum
        conta = db.execute(select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.phone_number_id == NUMERO_ID)
                           .execution_options(sem_filtro_de_ar=True)).scalar_one()
        assert "482915" not in (conta.situacao or "") and whatsapp_oficial.situacao(conta)["ativado"] is True
        logs = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "ativou_numero_whatsapp_oficial")).scalars().all()
        assert logs and all("482915" not in (log.detalhes or "") for log in logs)
        assert "Ativar o número" not in whatsapp_oficial.falta_para_renovacao(db, _ars()[0])


def test_ativar_o_numero_explica_a_recusa_da_meta(cliente, monkeypatch):
    _zerar_limite()
    _admin(EMAIL_MS, "MS Certificação Digital")
    _conta_da_ms()
    c = _entrar(EMAIL_MS)
    tela = c.get("/whatsapp").text
    for codigo, esperado in ((133005, "não confere com a verificação em duas etapas"), (133016, "10 tentativas")):
        _meta_do_registro(monkeypatch, SEM_ATIVAR, {"message": f"(#{codigo}) Registro recusado", "code": codigo})
        r = c.post("/whatsapp/oficial/ativar", data={"csrf": csrf_de(tela), "pin": "731904", "pin2": "731904"})
        assert "O número não foi ativado" in r.text and esperado in r.text and "Registro recusado" in r.text
        assert "731904" not in r.text
    with sessao() as db:  # a tentativa que chegou à Meta fica no registro de atividades, sem a senha
        logs = db.execute(select(LogAuditoria).where(
            LogAuditoria.acao == "ativar_numero_whatsapp_oficial_recusado")).scalars().all()
        assert len(logs) >= 2 and all("731904" not in (log.detalhes or "") for log in logs)
