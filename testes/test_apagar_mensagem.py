"""Conversas: "Apagar para todos", como no WhatsApp (24/11/2026, pedido da Maria: "suba a opção de apagar mensagem no
whatsapp lead"). A mensagem que saiu some do WhatsApp do contato pelo WhatsApp Leads (comando "apagar_mensagem" da
ponte) e a conversa mostra "Você apagou esta mensagem", com quem apagou. Só a que saiu e chegou ao WhatsApp, só até 2
dias depois do envio e só nos números de quem pede (os mesmos do envio pela tela).
Para nós ela não some (24/11/2026, "apague para o cliente mas não para nós"): o aviso fica em cima do texto, também na
que o contato apagou ("Essa mensagem foi apagada pelo contato")."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import conexoes
from app.banco import agora, sessao
from app.main import app
from app.modelos import MensagemWhatsApp, Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de

TOKEN = "token-ponte-apagar"
SENHA = "senhaApagar123"
TELEFONE = "81955508001"
PONTE = {"x-token": TOKEN}


def _usuario(email: str, nome: str) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if not u:
            u = Usuario(nome=nome, email=email, perfil="funcionario", senha_hash=resumir_senha(SENHA))
            db.add(u)
            db.flush()
        conexoes.minha(db, u, criar=True)
        return u.id


def _entrar(email: str) -> tuple[TestClient, dict]:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c, {"x-csrf-token": csrf_de(c.get("/conversas").text)}


def _hora(**antes) -> str:
    return (agora() - timedelta(**antes)).strftime("%Y-%m-%d %H:%M:%S")


def _pela_ponte(cliente, numero: str, mensagens: list[dict]) -> None:
    """O computador do WhatsApp Leads manda a cópia das conversas (como em /api/ponte/retorno)."""
    inicio = cliente.post("/api/ponte/troca", headers=PONTE, json={"status": {}}).json()["desde_conversas"]
    for i, m in enumerate(mensagens, start=1):
        m.update({"id": inicio + i, "erro": m.get("erro", ""), "telefone": "+55" + TELEFONE, "nome": "Contato Apagar",
                  "conexao": numero, "origem": m.get("origem", "manual")})
    cliente.post("/api/ponte/retorno", headers=PONTE, json={
        "confirmados": [], "novidades": {},
        "conversas": {"mensagens": mensagens, "status": [], "ultimo_id": inicio + len(mensagens)}})


def _retorno(cliente, comandos: list | None = None, status: list | None = None) -> None:
    """O retorno do WhatsApp Leads: o resultado dos pedidos e o status das mensagens."""
    cliente.post("/api/ponte/retorno", headers=PONTE, json={
        "confirmados": [], "novidades": {}, "comandos": comandos or [],
        "conversas": {"mensagens": [], "status": status} if status else None})


def _da_conversa(c, numero: str) -> dict:
    d = c.get(f"/conversas/api/conversa/{TELEFONE}?numero={numero}").json()
    return {m["texto"]: m for m in d["mensagens"]}


def test_apagar_para_todos(cliente, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    pid = _usuario("paula.apagar@teste.com.br", "Paula Apagar")
    _usuario("rui.apagar@teste.com.br", "Rui Apagar")
    numero = f"u{pid}"
    _pela_ponte(cliente, numero, [
        {"direcao": "saida", "texto": "Mensagem antiga", "status": "enviada", "criado_em": _hora(days=3)},
        {"direcao": "entrada", "texto": "Resposta do contato", "status": "recebida", "origem": "",
         "criado_em": _hora(hours=3)},
        {"direcao": "saida", "texto": "Não saiu", "status": "erro", "erro": "sem WhatsApp",
         "criado_em": _hora(hours=2, minutes=30)},
        {"direcao": "saida", "texto": "Outra mensagem", "status": "enviada", "criado_em": _hora(hours=2)},
        {"direcao": "saida", "texto": "Apagada pelo celular", "status": "enviada", "origem": "celular",
         "criado_em": _hora(hours=1, minutes=30)},
        {"direcao": "saida", "texto": "Mensagem errada", "status": "enviada", "criado_em": _hora(hours=1)}])
    paula, cab = _entrar("paula.apagar@teste.com.br")
    msgs = _da_conversa(paula, numero)
    assert msgs["Mensagem errada"]["pode_apagar"] and msgs["Outra mensagem"]["pode_apagar"]
    assert not msgs["Mensagem antiga"]["pode_apagar"]  # mais de 2 dias: o WhatsApp não deixa mais
    assert not msgs["Resposta do contato"]["pode_apagar"] and not msgs["Não saiu"]["pode_apagar"]
    pagina = paula.get(f"/conversas?telefone={TELEFONE}&numero={numero}").text
    assert 'id="dm-apagar"' in pagina and "Apagar para todos" in pagina

    # o que não pode ser apagado volta com o motivo
    for texto, motivo in [("Mensagem antiga", "2 dias"), ("Resposta do contato", "Só dá para apagar"),
                          ("Não saiu", "não chegou a sair")]:
        r = paula.post(f"/conversas/api/mensagem/{msgs[texto]['id']}/apagar", headers=cab, json={})
        assert r.status_code == 409 and motivo in r.json()["erro"], texto
    # quem não vê o número (o Rui) não apaga
    rui, cab_rui = _entrar("rui.apagar@teste.com.br")
    alvo = msgs["Mensagem errada"]["id"]
    assert rui.post(f"/conversas/api/mensagem/{alvo}/apagar", headers=cab_rui, json={}).status_code == 404

    # a Paula pede: o pedido vai para o WhatsApp Leads pela ponte
    r = paula.post(f"/conversas/api/mensagem/{alvo}/apagar", headers=cab, json={})
    assert r.status_code == 200, r.text
    pedido = r.json()["pedido"]
    assert paula.get(f"/conversas/api/apagar/{pedido}").json()["situacao"] == "esperando"
    assert rui.get(f"/conversas/api/apagar/{pedido}").status_code == 404  # o pedido é de quem pediu
    troca = cliente.post("/api/ponte/troca", headers=PONTE, json={"status": {}}).json()
    levado = [c for c in troca["comandos"] if c["id"] == pedido]
    with sessao() as db:
        id_wl = db.get(MensagemWhatsApp, alvo).id_wl
    assert levado and levado[0]["acao"] == "apagar_mensagem"
    assert levado[0]["dados"] == {"conexao": numero, "id_wl": id_wl}
    # o WhatsApp Leads apagou: a conversa mostra "Você apagou esta mensagem", com quem apagou
    _retorno(cliente, comandos=[{"id": pedido, "erro": ""}])
    assert paula.get(f"/conversas/api/apagar/{pedido}").json()["situacao"] == "apagada"
    msgs = _da_conversa(paula, numero)
    apagada = msgs["Mensagem errada"]
    assert apagada["apagada"].startswith("Hoje às") and apagada["apagada_por"] == "Paula Apagar"
    assert not apagada["pode_apagar"]
    r = paula.post(f"/conversas/api/mensagem/{alvo}/apagar", headers=cab, json={})
    assert r.status_code == 409 and "já foi apagada" in r.json()["erro"]
    lista = paula.get(f"/conversas/api/lista?numero={numero}").json()["conversas"]
    ultima = [c for c in lista if c["telefone"] == TELEFONE][0]
    assert ultima["ultima"] == "🚫 Você apagou esta mensagem" and ultima["ultima_apagada"]
    with sessao() as db:  # o texto continua guardado, como registro
        assert db.get(MensagemWhatsApp, alvo).texto == "Mensagem errada"

    # o WhatsApp Leads não conseguiu: a tela mostra o motivo e a mensagem continua
    pedido2 = paula.post(f"/conversas/api/mensagem/{msgs['Outra mensagem']['id']}/apagar", headers=cab,
                         json={}).json()["pedido"]
    _retorno(cliente, comandos=[{"id": pedido2, "erro": "o WhatsApp deste número está desconectado"}])
    s = paula.get(f"/conversas/api/apagar/{pedido2}").json()
    assert s["situacao"] == "erro" and "desconectado" in s["erro"]
    assert _da_conversa(paula, numero)["Outra mensagem"]["apagada"] == ""

    # apagada por outro caminho (a hora vem com o status da mensagem): fica apagada, sem o nome de quem apagou
    with sessao() as db:
        id_celular = db.execute(select(MensagemWhatsApp.id_wl)
                                .where(MensagemWhatsApp.texto == "Apagada pelo celular")).scalar()
    _retorno(cliente, status=[{"id": id_celular, "status": "enviada", "erro": "", "apagada_em": _hora(minutes=5)}])
    pelo_celular = _da_conversa(paula, numero)["Apagada pelo celular"]
    assert pelo_celular["apagada"] and pelo_celular["apagada_por"] == "" and not pelo_celular["pode_apagar"]


def test_apagada_pelo_contato_fica_com_o_texto(cliente, monkeypatch):
    """O contato apagou para todos uma mensagem que mandou: a hora vem do WhatsApp Leads com o status da mensagem e a
    conversa mostra o aviso com o texto embaixo (para nós ela não some); a lista mostra o aviso."""
    from app import config
    from app.banco import ler_config
    from app.rotas.conversas import VERSAO

    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    pid = _usuario("lia.apagar@teste.com.br", "Lia Apagar")
    numero = f"u{pid}"
    _pela_ponte(cliente, numero, [
        {"direcao": "saida", "texto": "Bom dia! Tudo bem?", "status": "enviada", "criado_em": _hora(minutes=20)},
        {"direcao": "entrada", "texto": "Mandei errado", "status": "recebida", "origem": "",
         "criado_em": _hora(minutes=10)}])
    lia, _ = _entrar("lia.apagar@teste.com.br")
    assert not _da_conversa(lia, numero)["Mandei errado"]["apagada"]
    with sessao() as db:
        id_wl = db.execute(select(MensagemWhatsApp.id_wl).where(MensagemWhatsApp.texto == "Mandei errado")).scalar()
        versao = ler_config(db, VERSAO)
    _retorno(cliente, status=[{"id": id_wl, "status": "recebida", "erro": "", "apagada_em": _hora(minutes=1)}])
    m = _da_conversa(lia, numero)["Mandei errado"]
    assert m["apagada"] and m["direcao"] == "entrada" and m["texto"] == "Mandei errado" and not m["pode_apagar"]
    lista = lia.get(f"/conversas/api/lista?numero={numero}").json()["conversas"]
    ultima = [c for c in lista if c["telefone"] == TELEFONE][0]
    assert ultima["ultima"] == "🚫 Essa mensagem foi apagada pelo contato" and ultima["ultima_apagada"]
    with sessao() as db:
        assert ler_config(db, VERSAO) != versao  # as listas abertas se atualizam
        assert db.execute(select(MensagemWhatsApp.texto).where(MensagemWhatsApp.id_wl == id_wl)).scalar() \
            == "Mandei errado"

    # o contato apagou antes de a cópia vir para cá: entra já apagada, com o texto
    _pela_ponte(cliente, numero, [{"direcao": "entrada", "texto": "Apaguei rapidinho", "status": "recebida",
                                   "origem": "", "criado_em": _hora(minutes=1), "apagada_em": _hora(seconds=30)}])
    m2 = _da_conversa(lia, numero)["Apaguei rapidinho"]
    assert m2["apagada"] and m2["texto"] == "Apaguei rapidinho"
    pagina = lia.get(f"/conversas?telefone={TELEFONE}&numero={numero}").text
    assert "Essa mensagem foi apagada pelo contato" in pagina and "aviso-apagada" in pagina
