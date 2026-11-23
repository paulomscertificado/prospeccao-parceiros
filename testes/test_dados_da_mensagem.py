"""Os "Dados da mensagem" como no WhatsApp (pedido da Maria em 23/11/2026: "você consegue incluir essas informações no
sistema", com o print do "Lida" e do "Entregue" do WhatsApp). Nas Conversas, o WhatsApp Leads manda a hora em que o
contato recebeu e leu (as confirmações do WhatsApp); na API Oficial, a Meta manda a hora junto com a situação. A tela
mostra ✓ (saiu), ✓✓ (entregue), ✓✓ azul (lida) e, clicando na mensagem, os dados. Nada sai de verdade."""

import json
import re
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app import conexoes, util, whatsapp_oficial
from app.banco import sessao
from app.modelos import MensagemOficial, MensagemWhatsApp, Usuario
from test_contador_conversas import CAB, _entrar, _mensagem, _retorno, _usuario, nuvem  # noqa: F401 (fixture)
from test_tela_api_oficial import _conta, _evento
from test_whatsapp_oficial import _assinado, _conta_da_ms


def test_quando_extenso_como_no_whatsapp():
    hoje = date(2026, 11, 23)
    assert util.quando_extenso(datetime(2026, 11, 23, 13, 50), hoje) == "Hoje às 13:50"
    assert util.quando_extenso(datetime(2026, 11, 22, 9, 5), hoje) == "Ontem às 09:05"
    assert util.quando_extenso(datetime(2026, 11, 2, 18, 0), hoje) == "02/11 às 18:00"
    assert util.quando_extenso(datetime(2025, 12, 31, 8, 0), hoje) == "31/12/2025 às 08:00"
    assert util.quando_extenso(None) == ""
    momento = datetime(2026, 11, 23, 13, 50, 7)
    assert util.de_timestamp(int(momento.timestamp())) == momento
    assert util.de_timestamp(str(int(momento.timestamp()) * 1000)) == momento  # milissegundos também
    assert util.de_timestamp("") is None and util.de_timestamp("abc") is None


def test_conversas_mostram_entregue_e_lida(cliente, nuvem):
    fid = _usuario("func.dados.msg@teste.com.br", "Flávia Dados", "funcionario")
    with sessao() as db:
        conexoes.minha(db, db.get(Usuario, fid), criar=True)
    numero = f"u{fid}"
    inicio = cliente.post("/api/ponte/troca", headers=CAB, json={"status": {}}).json()["desde_conversas"]
    hoje = date.today().isoformat()
    a = _mensagem(inicio + 1, numero, "+5581955560001", "saida", "Olá! Tudo bem?", "celular", 0)
    b = _mensagem(inicio + 2, numero, "+5581955560001", "saida", "Segue a proposta", "celular", 1)
    a["criado_em"], b["criado_em"] = f"{hoje} 10:00:00", f"{hoje} 10:01:00"
    a["entregue_em"] = f"{hoje} 10:00:05"  # a primeira já chegou ao contato
    _retorno(cliente, [a, b])
    f = _entrar("func.dados.msg@teste.com.br")
    conversa = f.get(f"/conversas/api/conversa/81955560001?numero={numero}").json()
    primeira, segunda = conversa["mensagens"][-2:]
    assert primeira["entregue"] == "Hoje às 10:00" and primeira["lida"] == "" and segunda["entregue"] == ""
    marca = conversa["marca"]
    # depois o contato leu as duas (a confirmação vem no status do WhatsApp Leads): a conversa aberta se redesenha
    cliente.post("/api/ponte/retorno", headers=CAB, json={"confirmados": [], "novidades": {}, "conversas": {
        "mensagens": [], "ultimo_id": inicio + 2, "status": [
            {"id": inicio + 1, "status": "enviada", "erro": "", "entregue_em": f"{hoje} 10:00:05",
             "visualizada_em": f"{hoje} 10:07:00"},
            {"id": inicio + 2, "status": "enviada", "erro": "", "entregue_em": f"{hoje} 10:02:00",
             "visualizada_em": f"{hoje} 10:07:00"}]}})
    depois = f.get(f"/conversas/api/conversa/81955560001?numero={numero}&marca={marca}").json()
    assert not depois.get("igual"), "a conversa aberta precisa saber que o contato leu"
    primeira, segunda = depois["mensagens"][-2:]
    assert primeira["lida"] == "Hoje às 10:07" and segunda["entregue"] == "Hoje às 10:02" and segunda["lida"] == "Hoje às 10:07"
    # o WhatsApp Leads antigo (sem as horas) não apaga o que já chegou
    cliente.post("/api/ponte/retorno", headers=CAB, json={"confirmados": [], "novidades": {}, "conversas": {
        "mensagens": [], "ultimo_id": inicio + 2, "status": [{"id": inicio + 1, "status": "enviada", "erro": ""}]}})
    with sessao() as db:
        m = db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.id_wl == inicio + 1)).scalars().one()
        assert m.entregue_em == datetime.fromisoformat(f"{hoje} 10:00:05") and m.visualizada_em is not None
    tela = f.get("/conversas").text
    assert 'id="dados-mensagem"' in tela and "Dados da mensagem" in tela and "abrirDadosMensagem" in tela


def test_api_oficial_guarda_a_hora_da_meta_e_mostra_os_dados(cliente):
    _conta_da_ms()
    with sessao() as db:
        whatsapp_oficial.guardar_conversa(db, _conta(db), "(81) 99556-0002", "saida", "Aviso de teste dos dados",
                                          "modelo", "wamid.DADOS-1")
        db.commit()
    entregue = datetime.now().replace(microsecond=0) - timedelta(minutes=9)
    lida = entregue + timedelta(minutes=4)
    # a Meta avisou fora de ordem: a leitura antes da entrega
    eventos = [{"id": "wamid.DADOS-1", "status": "read", "timestamp": str(int(lida.timestamp()))},
               {"id": "wamid.DADOS-1", "status": "delivered", "timestamp": str(int(entregue.timestamp()))}]
    assert _assinado(cliente, _evento(statuses=eventos)).status_code == 200
    with sessao() as db:
        m = db.execute(select(MensagemOficial).where(MensagemOficial.wamid == "wamid.DADOS-1")).scalars().one()
        assert m.status == "lida" and m.visualizada_em == lida
        assert m.entregue_em == lida  # a entrega ficou com a hora da leitura (que chegou antes) e não volta
    tela = cliente.get("/oficial?telefone=81995560002").text
    dados = [json.loads(d) for d in re.findall(r"data-dados='([^']*)'", tela)]
    assert dados and dados[-1]["lida"] == util.quando_extenso(lida) and dados[-1]["entregue"] == util.quando_extenso(lida)
    assert dados[-1]["texto"] == "Aviso de teste dos dados" and dados[-1]["erro"] == ""
    assert 'id="dados-mensagem"' in tela and "abrirDadosMensagem" in tela


def test_api_oficial_mensagem_de_antes_sem_a_hora(cliente):
    """As que já estavam como lidas antes desta mudança: o painel diz que a hora não foi registrada."""
    _conta_da_ms()
    with sessao() as db:
        m = whatsapp_oficial.guardar_conversa(db, _conta(db), "(81) 99556-0003", "saida", "Aviso antigo", "modelo",
                                              "wamid.DADOS-2")
        m.status = "lida"
        db.commit()
    tela = cliente.get("/oficial?telefone=81995560003").text
    dados = [json.loads(d) for d in re.findall(r"data-dados='([^']*)'", tela)]
    assert dados[-1]["lida"] == "sim (a hora não foi registrada)" and dados[-1]["entregue"] == "sim (a hora não foi registrada)"
