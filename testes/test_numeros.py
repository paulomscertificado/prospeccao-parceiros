"""Usuários com dados separados, perfil Funcionário MS e um número de WhatsApp por pessoa (com compartilhamento)."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import campanhas, config, conexoes, mensagens, sdr
from app.banco import agora, gravar_config, sessao
from app.integracoes import whatsapp_leads
from app.leads_servico import criar_lead
from app.main import app
from app.modelos import (Campanha, ConexaoWhatsApp, Lead, MensagemWhatsApp, Notificacao, PonteWhatsApp, Tarefa,
                         Usuario)
from app.seguranca import resumir_senha
from conftest import csrf_de

SENHA = "senhaFunc123"
TOKEN = "token-ponte-numeros"


def _usuario(email, perfil, nome):
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if not u:
            u = Usuario(nome=nome, email=email, perfil=perfil, senha_hash=resumir_senha(SENHA))
            db.add(u)
            db.flush()
        return u.id


def _entrar(email) -> TestClient:
    c = TestClient(app)
    pagina = c.get("/login")
    c.post("/login", data={"csrf": csrf_de(pagina.text), "email": email, "senha": SENHA})
    return c


@pytest.fixture()
def nuvem(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN)
    whatsapp_leads._cache["status"] = None
    yield
    whatsapp_leads._cache["status"] = None
    from sqlalchemy import delete, update

    from app.modelos import ComandoWhatsApp, Configuracao

    with sessao() as db:  # não deixa pedidos pendentes para os outros testes
        db.execute(update(PonteWhatsApp).where(PonteWhatsApp.status == "aguardando").values(status="erro"))
        db.execute(update(ComandoWhatsApp).where(ComandoWhatsApp.status == "aguardando").values(status="feito"))
        db.execute(delete(Configuracao).where(Configuracao.chave == "wl_status"))


def _status_ponte(cliente, conexoes_status: dict):
    """O computador da MS avisa a situação de cada número."""
    cliente.post("/api/ponte/troca", headers={"x-token": TOKEN},
                 json={"status": {"conectado": True, "tipo": "qr", "estado": "Conectado", "conexoes": conexoes_status}})
    whatsapp_leads._cache["status"] = None


def test_funcionario_ve_so_os_proprios_dados_e_usa_ferramentas(cliente):
    fid = _usuario("func1@teste.com.br", "funcionario", "Fernanda Funcionária")
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        dela, _ = criar_lead(db, {"empresa": "Contábil Da Fernanda", "vendedor_id": fid}, admin)
        de_outro, _ = criar_lead(db, {"empresa": "Contábil Do Admin", "vendedor_id": admin.id}, admin)
        dela_id, outro_id = dela.id, de_outro.id
    c = _entrar("func1@teste.com.br")
    assert "Funcionário MS" in c.get("/").text
    lista = c.get("/leads").text
    assert "Contábil Da Fernanda" in lista and "Contábil Do Admin" not in lista
    assert c.get(f"/leads/{outro_id}").status_code in (403, 404) and c.get(f"/leads/{dela_id}").status_code == 200
    assert c.get("/cadencias").status_code == 200 and c.get("/categorias").status_code == 200  # ferramentas
    assert c.get("/configuracoes").status_code == 403  # configurações: só administrador
    assert "Funcionário MS" in config.PERFIS.values()


def test_cada_um_conecta_o_seu_numero_e_pode_compartilhar(cliente, nuvem):
    fid = _usuario("func2@teste.com.br", "funcionario", "Felipe Funcionário")
    vid = _usuario("vend2@teste.com.br", "vendedor", "Vera Vendedora")
    c = _entrar("func2@teste.com.br")
    pagina = c.get("/whatsapp")
    assert "Você ainda não conectou o seu número" in pagina.text
    c.post("/whatsapp/comando", data={"csrf": csrf_de(pagina.text), "acao": "conectar", "numero": "meu", "tipo": "qr"})
    comandos = cliente.post("/api/ponte/troca", headers={"x-token": TOKEN}, json={"status": {}}).json()["comandos"]
    assert {"acao": "conectar", "dados": {"conexao": f"u{fid}", "tipo": "qr"}} in [
        {"acao": x["acao"], "dados": x["dados"]} for x in comandos]
    _status_ponte(cliente, {f"u{fid}": {"conectado": True, "estado": "Conectado", "estado_codigo": "conectado",
                                        "numero": "(81) 98888-0002"}})
    estado = c.get("/whatsapp/estado").json()
    meu = next(n for n in estado["numeros"] if n["id"] == f"u{fid}")
    assert meu["minha"] and meu["situacao"]["conectado"] and meu["gerenciar"]
    assert not any(n["id"] == "principal" for n in estado["numeros"])  # o número da MS não foi compartilhado com ele
    # o dono não pode mexer no número dos outros
    r = c.post("/whatsapp/comando", data={"csrf": csrf_de(pagina.text), "acao": "desligar", "numero": "principal"})
    assert r.status_code == 200 and "Só o dono" in r.text
    # compartilha com a vendedora
    c.post("/whatsapp/compartilhar", data={"csrf": csrf_de(pagina.text), "numero": f"u{fid}", "usuarios": [str(vid)]})
    v = _entrar("vend2@teste.com.br")
    assert any(n["id"] == f"u{fid}" and not n["gerenciar"] for n in v.get("/whatsapp/estado").json()["numeros"])


def test_ia_sdr_envia_pelo_numero_do_responsavel(cliente, nuvem, monkeypatch):
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    fid = _usuario("func3@teste.com.br", "funcionario", "Flávia Funcionária")
    _status_ponte(cliente, {"principal": {"conectado": True, "estado_codigo": "conectado"}})
    with sessao() as db:
        gravar_config(db, "horas_entre_contatos", "0")
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        lead, _ = criar_lead(db, {"empresa": "Contábil Da Flávia", "whatsapp": "(81) 97777-3003",
                                  "vendedor_id": fid, "consentimento": True}, admin)
        lead_id = lead.id
        # sem número conectado: recusa com a orientação para conectar
        with pytest.raises(sdr.EnvioRecusado, match="ainda não conectou o WhatsApp"):
            sdr.enviar_whatsapp_conectado(db, "Olá!", None, lead=db.get(Lead, lead_id))
        # fila da IA SDR: espera e avisa a pessoa para conectar
        camp = Campanha(nome="Campanha Flávia", status="ativa", aprovado_em=agora(), usuario_id=fid)
        db.add(camp)
        db.flush()
        db.add(Tarefa(tipo="prospeccao", lead_id=lead_id, canal="whatsapp", data=date.today(), hora="00:00",
                      campanha_id=camp.id, mensagem="Olá, Flávia!"))
        db.flush()
        assert campanhas.processar_fila_whatsapp(db)["enviados"] == 0
        assert db.execute(select(Notificacao).where(Notificacao.usuario_id == fid, Notificacao.link == "/whatsapp")).first()
    # conectou o próprio número: sai por ele
    _status_ponte(cliente, {"principal": {"conectado": True, "estado_codigo": "conectado"},
                            f"u{fid}": {"conectado": True, "estado_codigo": "conectado"}})
    with sessao() as db:
        conexoes.minha(db, db.get(Usuario, fid), criar=True)
        assert campanhas.processar_fila_whatsapp(db)["enviados"] == 1
        item = db.execute(select(PonteWhatsApp).order_by(PonteWhatsApp.id.desc())).scalars().first()
        assert item.conexao == f"u{fid}" and item.texto == "Olá, Flávia!"


def test_numero_compartilhado_serve_para_quem_nao_tem_numero(cliente, nuvem):
    vid = _usuario("vend4@teste.com.br", "vendedor", "Valter Vendedor")
    _status_ponte(cliente, {"principal": {"conectado": True, "estado_codigo": "conectado"}})
    with sessao() as db:
        valter = db.get(Usuario, vid)
        with pytest.raises(conexoes.SemNumero):
            conexoes.para_enviar(db, valter)
        principal = conexoes.garantir_principal(db)
        principal.compartilhada_todos = True
        db.flush()
        assert conexoes.para_enviar(db, valter) == "principal"
        principal.compartilhada_todos = False


def test_conversas_separadas_por_numero(cliente, nuvem):
    fid = _usuario("func5@teste.com.br", "funcionario", "Fábio Funcionário")
    cab = {"x-token": TOKEN}
    inicio = cliente.post("/api/ponte/troca", headers=cab, json={"status": {}}).json()["desde_conversas"]
    msgs = [{"id": inicio + 1, "direcao": "entrada", "texto": "Mensagem no número do Fábio", "status": "recebida",
             "erro": "", "origem": "", "criado_em": "2026-10-23 12:00:00", "telefone": "+5581966665005",
             "nome": "Cliente do Fábio", "conexao": f"u{fid}"},
            {"id": inicio + 2, "direcao": "entrada", "texto": "Mensagem no número da MS", "status": "recebida",
             "erro": "", "origem": "", "criado_em": "2026-10-23 12:01:00", "telefone": "+5581966665006",
             "nome": "Cliente da MS", "conexao": "principal"}]
    cliente.post("/api/ponte/retorno", headers=cab, json={"confirmados": [], "novidades": {},
                                                          "conversas": {"mensagens": msgs, "status": [], "ultimo_id": inicio + 2}})
    _status_ponte(cliente, {f"u{fid}": {"conectado": True, "estado_codigo": "conectado"}})
    with sessao() as db:
        conexoes.minha(db, db.get(Usuario, fid), criar=True)
    f = _entrar("func5@teste.com.br")
    textos = [x["ultima"] for x in f.get("/conversas/api/lista").json()["conversas"]]
    assert "Mensagem no número do Fábio" in textos and "Mensagem no número da MS" not in textos
    assert "Mensagem no número da MS" in [x["ultima"] for x in cliente.get("/conversas/api/lista").json()["conversas"]]
    assert f.get("/conversas/api/conversa/81966665006?numero=principal").json().get("numero") != "principal"
    pagina = f.get("/conversas")
    r = f.post("/conversas/api/enviar", headers={"x-csrf-token": csrf_de(pagina.text)},
               json={"telefone": "81966665005", "texto": "Respondendo pelo meu número"})
    assert r.status_code == 200 and r.json()["numero"] == f"u{fid}"
    with sessao() as db:
        item = db.execute(select(PonteWhatsApp).order_by(PonteWhatsApp.id.desc())).scalars().first()
        assert item.conexao == f"u{fid}" and item.manual
