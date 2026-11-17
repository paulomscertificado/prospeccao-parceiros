"""Etapa 2 da API oficial (pedido da Maria em 16/11/2026): os avisos da Renovação pelo número oficial da Meta. O sistema
pede a aprovação dos modelos (com a arte e só com o texto), acompanha a situação, manda cada aviso com o modelo
aprovado (a arte desenhada pelo computador do WhatsApp Leads no cabeçalho) e os botões Quero renovar / Já renovei /
Parar avisos fazem o trabalho sozinhos. A Meta é imitada: nada sai de verdade."""

import hashlib
import hmac
import json
from datetime import date, timedelta

from sqlalchemy import select

from app import config, mensagens, renovacao, whatsapp_oficial
from app.banco import agora, gravar_config, ler_config, sessao
from app.integracoes import whatsapp_cloud
from app.leads_servico import limpar_campos
from app.main import app
from app.modelos import (ArteAviso, Campanha, Certificado, ComandoWhatsApp, ContaWhatsAppOficial, Lead, Mensagem,
                         ModeloWhatsAppOficial, Oportunidade, Tarefa, Tenant, Usuario)
from app.seguranca import criptografar, limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

TOKEN = "EAAGteste" + "x" * 60
SEGREDO = "segredo-do-app-teste"
NUMERO_ID = "1425129957352130"
TOKEN_PONTE = "token-da-ponte-teste"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 6000
ADMIN = "admin.renov.oficial@ms-oficial-teste.com.br"


class _Resposta:  # imita a resposta do httpx
    def __init__(self, dados: dict, status: int = 200):
        self._dados, self.status_code, self.text = dados, status, json.dumps(dados)

    def json(self):
        return self._dados


def _meta(monkeypatch, situacao: str = "") -> list:
    """A Meta imitada. `situacao`: o que a lista de modelos devolve (vazio = nenhum modelo na conta)."""
    chamadas = []

    def pedir(metodo, url, **kw):
        chamadas.append((metodo, url, kw))
        if url.endswith("/debug_token"):
            return _Resposta({"data": {"app_id": "1838539180819325"}})
        if url.endswith("/uploads"):
            return _Resposta({"id": "upload:MTIz"})
        if "upload:" in url:
            return _Resposta({"h": "4::exemplo"})
        if url.endswith("/message_templates"):
            if metodo == "POST":
                return _Resposta({"id": f"tpl{len(chamadas)}", "status": "PENDING", "category": "UTILITY"})
            return _Resposta({"data": [{"name": nome, "language": "pt_BR", "status": situacao, "category": "UTILITY",
                                        "id": f"tpl-{nome}", "rejected_reason": "NONE"}
                                       for nome in whatsapp_oficial.NOMES_DOS_MODELOS.values()] if situacao else []})
        if url.endswith("/media"):
            return _Resposta({"id": "midia123"})
        if url.endswith("/messages"):
            return _Resposta({"messages": [{"id": f"wamid.renov{len(chamadas)}"}]})
        return _Resposta({})

    monkeypatch.setattr(whatsapp_cloud.httpx, "request", pedir)
    return chamadas


def _ar_ms(db) -> int:
    return db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar_one()


def _conta(db, aprovados: bool = True) -> ContaWhatsAppOficial:
    """A conta oficial da AR MS, testada; com os dois modelos aprovados (ou sem modelos)."""
    ms = _ar_ms(db)
    conta = db.execute(select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.tenant_id == ms)
                       .execution_options(sem_filtro_de_ar=True)).scalars().first()
    if conta is None:
        conta = ContaWhatsAppOficial(phone_number_id=NUMERO_ID, tenant_id=ms, verificacao="verificacao-renov-123456")
        db.add(conta)
    conta.waba_id, conta.token_cripto, conta.segredo_cripto = "998877", criptografar(TOKEN), criptografar(SEGREDO)
    conta.testado_em = agora()
    db.flush()
    for m in whatsapp_oficial.modelos_da_conta(db, conta).values():
        db.delete(m)
    db.flush()
    if aprovados:
        for uso, nome in whatsapp_oficial.NOMES_DOS_MODELOS.items():
            db.add(ModeloWhatsAppOficial(conta_id=conta.id, uso=uso, nome=nome, status="APPROVED",
                                         com_imagem=uso == whatsapp_oficial.USO_ARTE, tenant_id=ms,
                                         corpo=whatsapp_oficial.corpo_renovacao("Empresa Teste"),
                                         rodape=whatsapp_oficial.RODAPE_RENOVACAO))
        db.flush()
    return conta


def _aviso(db, empresa: str, telefone: str, certificados: int = 1, oficial: bool = True) -> Tarefa:
    """Campanha de renovação aprovada (pela API oficial) com um contato, os certificados dele e o aviso de hoje."""
    ms = _ar_ms(db)
    admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
    camp = Campanha(nome=f"Renovação API {empresa}", tipo="renovacao", status="ativa", usuario_id=admin.id,
                    canais="whatsapp", aprovado_em=agora(), envio_oficial=oficial, tenant_id=ms)
    lead = Lead(empresa=empresa, whatsapp=telefone, status="Abordagem criada", vendedor_id=admin.id,
                origem=renovacao.ORIGEM_LEAD, tenant_id=ms)
    limpar_campos(lead)
    db.add_all([camp, lead])
    db.flush()
    certs = []
    for n in range(certificados):
        cert = Certificado(origem="planilha", protocolo=f"API{lead.id}{n}", cliente_nome=f"{empresa} {n or ''}".strip(),
                           tipo="e-CNPJ A1 12 meses", cnpj="12345678000195", responsavel="GUILHERME SOUZA",
                           data_vencimento=date.today() + timedelta(days=5 + n), status="Ativo",
                           campanha_id=camp.id, lead_id=lead.id, whatsapp=telefone, tenant_id=ms)
        db.add(cert)
        db.flush()
        certs.append(cert)
    t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, certificado_id=certs[0].id, canal="whatsapp",
               data=date.today(), hora="00:01", status="pendente", angulo="renov_reforco",
               mensagem="Olá! O certificado vence em breve.", tenant_id=ms)
    db.add(t)
    db.flush()
    return t


def _no_horario(monkeypatch):
    """Os avisos só saem de segunda a sexta, no horário: no teste, sempre dentro."""
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db: True)
    monkeypatch.setattr(renovacao, "fora_do_horario", lambda db, *a, **k: "")


def test_modelos_do_aviso_vao_para_a_meta_e_a_situacao_e_acompanhada(cliente, monkeypatch):
    chamadas = _meta(monkeypatch)
    with sessao() as db:
        conta = _conta(db, aprovados=False)
        ms = conta.tenant_id
        guardada, conta.segredo_cripto = conta.segredo_cripto, ""
        assert "chave secreta do app" in whatsapp_oficial.falta_para_renovacao(db, ms)  # sem ela os botões não chegam
        conta.segredo_cripto = guardada
        assert "peça a aprovação" in whatsapp_oficial.falta_para_renovacao(db, ms)
        assert whatsapp_oficial.pedir_modelos_renovacao(db, conta) == []
        modelos = whatsapp_oficial.modelos_da_conta(db, conta)
        assert {m.status for m in modelos.values()} == {"PENDING"} and len(modelos) == 2
        pedidos = [kw["json"] for metodo, url, kw in chamadas if url.endswith("/message_templates") and metodo == "POST"]
        com_arte = next(p for p in pedidos if p["name"] == "aviso_vencimento_certificado_arte")
        assert com_arte["category"] == "UTILITY" and com_arte["language"] == "pt_BR"
        tipos = [c["type"] for c in com_arte["components"]]
        assert tipos == ["HEADER", "BODY", "FOOTER", "BUTTONS"]
        assert com_arte["components"][0]["example"]["header_handle"] == ["4::exemplo"]  # a arte de exemplo subiu
        corpo = com_arte["components"][1]
        assert "{{1}}" in corpo["text"] and "{{3}}" in corpo["text"] and len(corpo["example"]["body_text"][0]) == 3
        assert [b["text"] for b in com_arte["components"][3]["buttons"]] == ["Quero renovar", "Já renovei", "Parar avisos"]
        so_texto = next(p for p in pedidos if p["name"] == "aviso_vencimento_certificado")
        assert [c["type"] for c in so_texto["components"]] == ["BODY", "FOOTER", "BUTTONS"]
        assert "em análise" in whatsapp_oficial.falta_para_renovacao(db, ms)
        # pedir de novo não manda outra vez o que já está em análise
        antes = len(chamadas)
        whatsapp_oficial.pedir_modelos_renovacao(db, conta)
        assert not [1 for metodo, url, _ in chamadas[antes:] if url.endswith("/message_templates") and metodo == "POST"]
        db.commit()
    # a Meta aprovou: a rotina de hora em hora pergunta e guarda
    _meta(monkeypatch, situacao="APPROVED")
    with sessao() as db:
        assert whatsapp_oficial.atualizar_modelos_pendentes(db) == 2
        assert whatsapp_oficial.falta_para_renovacao(db, _ar_ms(db)) == ""


def test_aviso_sai_pela_api_com_a_arte_e_os_botoes(cliente, monkeypatch):
    chamadas = _meta(monkeypatch)
    _no_horario(monkeypatch)
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN_PONTE)
    with sessao() as db:
        conta = _conta(db)
        t = _aviso(db, "PADARIA API OFICIAL LTDA", "(81) 99446-0001")
        varios = _aviso(db, "GRUPO API OFICIAL LTDA", "(81) 99446-0002", certificados=2)
        db.commit()
        tid, varios_id = t.id, varios.id
        # 1ª rodada: a arte é pedida ao computador do WhatsApp Leads e o aviso espera; o de vários certificados
        # (sem arte, a lista vai no texto) sai na hora com o modelo só de texto
        r = whatsapp_oficial.processar_fila(db)
        db.commit()
        assert r["esperando_arte"] == 1 and r["enviados"] == 1, r
        pedido = db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.tarefa_id == tid)).scalars().one()
        assert pedido.acao == "desenhar_arte" and json.loads(pedido.dados)["arte"]["nome"] == "PADARIA API OFICIAL LTDA"
        cid = pedido.id
    envio = next(kw["json"] for metodo, url, kw in chamadas if url.endswith("/messages"))
    assert envio["template"]["name"] == "aviso_vencimento_certificado"  # só texto
    parametros = envio["template"]["components"][0]["parameters"]
    assert parametros[0]["text"] == "Guilherme" and parametros[1]["text"].startswith("2 certificados:")
    assert "\n" not in parametros[1]["text"]  # a Meta recusa quebra de linha nos valores
    assert [b["parameters"][0]["payload"] for b in envio["template"]["components"][1:]] == [
        f"renov:renovar:{varios_id}", f"renov:renovei:{varios_id}", f"renov:parar:{varios_id}"]
    # o computador do WhatsApp Leads desenha e devolve a arte (senha da ponte)
    assert cliente.post(f"/api/ponte/arte-pedido/{cid}", content=PNG, headers={"x-token": "errado"}).status_code == 403
    assert cliente.post(f"/api/ponte/arte-pedido/{cid}", content=b"nada", headers={"x-token": TOKEN_PONTE}).status_code == 400
    assert cliente.post(f"/api/ponte/arte-pedido/{cid}", content=PNG, headers={"x-token": TOKEN_PONTE}).status_code == 200
    chamadas.clear()
    with sessao() as db:
        assert db.get(ComandoWhatsApp, cid).status == "feito"
        assert whatsapp_oficial.processar_fila(db)["enviados"] == 1
        db.commit()
        t = db.get(Tarefa, tid)
        assert t.status == "feita" and "API oficial" in t.resultado
        msg = db.execute(select(Mensagem).where(Mensagem.tarefa_id == tid)).scalars().one()
        assert msg.modo == "oficial" and msg.id_externo.startswith("wamid.renov") and msg.conexao == f"oficial:{NUMERO_ID}"
        assert "Guilherme" in msg.corpo and "[Quero renovar]" in msg.corpo and "arte" in msg.assunto
        # a arte fica guardada para o e-mail do mesmo aviso (umas 2 h depois)
        assert db.execute(select(ArteAviso).where(ArteAviso.tarefa_id == tid)).scalars().first() is not None
        _limpar(db, [tid, varios_id])
    assert [url.rsplit("/", 1)[-1] for _, url, _ in chamadas] == ["media", "messages"]  # a arte sobe e o aviso sai
    componentes = chamadas[1][2]["json"]["template"]["components"]
    assert chamadas[1][2]["json"]["template"]["name"] == "aviso_vencimento_certificado_arte"
    assert componentes[0] == {"type": "header", "parameters": [{"type": "image", "image": {"id": "midia123"}}]}


def test_sem_a_arte_a_tempo_o_aviso_sai_so_com_o_texto(cliente, monkeypatch):
    chamadas = _meta(monkeypatch)
    _no_horario(monkeypatch)
    with sessao() as db:
        _conta(db)
        t = _aviso(db, "OTICA API OFICIAL LTDA", "(81) 99446-0003")
        whatsapp_oficial.pedir_arte(db, t, renovacao.arte_do_toque(db, t))
        pedido = db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.tarefa_id == t.id)).scalars().one()
        pedido.status, pedido.erro = "erro", "pedido desconhecido"  # computador com a versão antiga do WhatsApp Leads
        db.commit()
        assert whatsapp_oficial.processar_fila(db)["enviados"] == 1
        db.commit()
        assert db.get(Tarefa, t.id).status == "feita"
        _limpar(db, [t.id])
    envio = next(kw["json"] for metodo, url, kw in chamadas if url.endswith("/messages"))
    assert envio["template"]["name"] == "aviso_vencimento_certificado"
    assert not [1 for _, url, _ in chamadas if url.endswith("/media")]


def test_fila_do_qr_code_nao_pega_os_avisos_da_api(cliente, monkeypatch):
    from app import campanhas, sdr
    from app.integracoes import whatsapp_leads

    _no_horario(monkeypatch)
    monkeypatch.setattr(mensagens, "dentro_do_horario_de_alguma_ar", lambda db: True)
    monkeypatch.setattr(campanhas, "_vez_do_canal", lambda db, canal: True)
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "status", lambda *a, **k: {"disponivel": True})
    pelo_qr = []
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado", lambda db, texto, usuario, **kw: pelo_qr.append(kw["tarefa"].id))
    with sessao() as db:
        _conta(db)
        oficial = _aviso(db, "MERCADO API OFICIAL LTDA", "(81) 99446-0004")
        qr = _aviso(db, "MERCADO QR CODE LTDA", "(81) 99446-0005", oficial=False)
        db.commit()
        campanhas.processar_fila_whatsapp(db, maximo=50)
        assert qr.id in pelo_qr and oficial.id not in pelo_qr
        db.rollback()
        _limpar(db, [oficial.id, qr.id])


def _limpar(db, tarefas: list[int]):
    """As tarefas que sobraram não saem nos outros testes."""
    for t in db.execute(select(Tarefa).where(Tarefa.id.in_(tarefas))).scalars():
        if t.status == "pendente":
            t.status = "cancelada"
    db.commit()


def _assinado(cliente, dados: dict):
    corpo = json.dumps(dados).encode()
    assinatura = "sha256=" + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
    return cliente.post("/api/webhooks/whatsapp", content=corpo,
                        headers={"x-hub-signature-256": assinatura, "content-type": "application/json"})


def _botao(telefone: str, payload: str, texto: str) -> dict:
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": NUMERO_ID},
        "contacts": [{"wa_id": telefone, "profile": {"name": "Cliente"}}],
        "messages": [{"from": telefone, "id": f"wamid.botao{payload[-6:]}", "type": "button",
                      "button": {"payload": payload, "text": texto}}]}}]}]}


def test_botoes_do_aviso_resolvem_sozinhos(cliente, monkeypatch):
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    with sessao() as db:
        _conta(db)
        quer = _aviso(db, "QUER RENOVAR API LTDA", "(81) 99446-0011")
        renovou = _aviso(db, "JA RENOVOU API LTDA", "(81) 99446-0012")
        dois = _aviso(db, "DOIS CERTIFICADOS API LTDA", "(81) 99446-0013", certificados=2)
        parar = _aviso(db, "PARAR AVISOS API LTDA", "(81) 99446-0014")
        db.commit()
        ids = {"quer": quer.id, "renovou": renovou.id, "dois": dois.id, "parar": parar.id}
        leads = {k: t.lead_id for k, t in (("quer", quer), ("renovou", renovou), ("dois", dois), ("parar", parar))}
    assert _assinado(cliente, _botao("5581994460011", f"renov:renovar:{ids['quer']}", "Quero renovar")).status_code == 200
    assert _assinado(cliente, _botao("5581994460012", f"renov:renovei:{ids['renovou']}", "Já renovei")).status_code == 200
    assert _assinado(cliente, _botao("5581994460013", f"renov:renovei:{ids['dois']}", "Já renovei")).status_code == 200
    assert _assinado(cliente, _botao("5581994460014", f"renov:parar:{ids['parar']}", "Parar avisos")).status_code == 200
    # botão com o aviso de OUTRO contato: não mexe em nada dele (segue como resposta comum)
    assert _assinado(cliente, _botao("5581994460099", f"renov:renovei:{ids['parar']}", "Já renovei")).status_code == 200
    with sessao() as db:
        op = db.execute(select(Oportunidade).where(Oportunidade.lead_id == leads["quer"])).scalars().one()
        assert op.temperatura == "quente" and op.classificacao == "QUER RENOVAR" and op.status == "nova"
        assert db.get(Lead, leads["quer"]).status == "Interessado"
        assert db.get(Tarefa, ids["quer"]).status == "cancelada"  # os próximos avisos param
        cert = db.execute(select(Certificado).where(Certificado.lead_id == leads["renovou"])).scalars().one()
        assert cert.status == "Renovado"  # "Já renovei" com um certificado: resolvido, sem trabalho para a equipe
        assert not db.execute(select(Oportunidade).where(Oportunidade.lead_id == leads["renovou"])).first()
        # com dois certificados, a equipe confere qual foi renovado
        op = db.execute(select(Oportunidade).where(Oportunidade.lead_id == leads["dois"])).scalars().one()
        assert op.classificacao == "JÁ RENOVOU" and op.temperatura == "morna" and "2 certificados" in op.resumo
        assert {c.status for c in db.execute(select(Certificado).where(Certificado.lead_id == leads["dois"])).scalars()} \
            == {"Ativo"}
        assert db.get(Lead, leads["parar"]).opt_out  # Parar avisos = SAIR
        assert {c.status for c in db.execute(select(Certificado).where(Certificado.lead_id == leads["parar"])).scalars()} \
            == {"Ativo"}  # o botão de outro contato não marcou o certificado dele
        for op in db.execute(select(Oportunidade).where(Oportunidade.lead_id.in_(list(leads.values())))).scalars():
            op.status = "descartada"  # não deixa cartões nas telas dos outros testes
        db.commit()


def test_renovacao_liga_a_api_oficial_so_quando_esta_pronta(cliente, monkeypatch):
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    with sessao() as db:
        if not db.execute(select(Usuario).where(Usuario.email == ADMIN)).scalars().first():
            db.add(Usuario(nome="Admin Renovação API", email=ADMIN, perfil="admin", senha_hash=resumir_senha(SENHA),
                           empresa_nome="MS Certificação Digital"))
        conta = _conta(db, aprovados=False)
        t = _aviso(db, "CAMPANHA EM ANDAMENTO API LTDA", "(81) 99446-0021", oficial=False)
        camp_id = t.campanha_id
        guardadas = {c: ler_config(db, c) for c in renovacao.PADRAO}
        db.commit()
    from fastapi.testclient import TestClient

    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": ADMIN, "senha": SENHA})
    try:
        pagina = c.get("/renovacao").text
        assert "Enviar o WhatsApp dos avisos pela API oficial da Meta" in pagina and "Ainda não dá para ligar" in pagina
        form = {"csrf": csrf_de(pagina), "canal_whatsapp": "on", "canal_email": "on", "oficial": "on",
                "hora": "07:45", "maximo_dia": "40", "hora_fim": "18:00"}
        r = c.post("/renovacao/configurar", data=form)
        assert "Ainda não dá para enviar pela API oficial da Meta" in r.text
        with sessao() as db:
            assert renovacao.cfg(db, "renov_envio_oficial") == "0"
            _conta(db)  # a Meta aprovou os modelos
            db.commit()
        r = c.post("/renovacao/configurar", data=form)
        assert "passam a sair pela API oficial da Meta" in r.text, r.text[:400]
        with sessao() as db:
            assert renovacao.cfg(db, "renov_envio_oficial") == "1"
            assert db.get(Campanha, camp_id).envio_oficial  # a campanha em andamento também
        assert "API oficial" in c.get("/renovacao").text
        r = c.post("/renovacao/configurar", data={k: v for k, v in form.items() if k != "oficial"})
        assert "voltam a sair pelo número do QR code" in r.text
        with sessao() as db:
            assert not db.get(Campanha, camp_id).envio_oficial
    finally:
        with sessao() as db:
            for chave, valor in guardadas.items():
                gravar_config(db, chave, valor)
            _limpar(db, [t.id])
