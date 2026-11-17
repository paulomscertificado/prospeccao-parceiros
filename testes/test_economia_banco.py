"""Economia do banco da nuvem (Supabase, 17/11/2026): a tela Conversas só baixa tudo de novo quando algo mudou (a
"marca"), a ponte troca a cada 10 s com a tela Conversas aberta e o status do computador não é regravado à toa."""

from datetime import datetime, timedelta

import pytest

from app import config
from app.banco import agora, gravar_config, ler_config, ler_config_json, sessao
from app.integracoes import whatsapp_leads

TOKEN_PONTE = "token-da-ponte-economia"
CAB = {"x-token": TOKEN_PONTE}
STATUS = {"conectado": True, "tipo": "qr", "estado": "Conectado", "estado_codigo": "conectado", "numero": "x"}


@pytest.fixture()
def nuvem(monkeypatch):
    monkeypatch.setattr(config, "NA_NUVEM", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN_PONTE)
    whatsapp_leads._cache["status"] = None
    yield
    whatsapp_leads._cache["status"] = None


def _mensagem(id_wl: int, direcao: str, texto: str, status: str, minuto: int) -> dict:
    return {"id": id_wl, "direcao": direcao, "texto": texto, "status": status, "erro": "", "origem": "celular",
            "criado_em": f"2026-11-17 09:{minuto:02d}:00", "telefone": "+5581944440001", "nome": "Paula Economia"}


def _retorno(cliente, mensagens: list, status: list | None = None) -> None:
    ultimo = max([m["id"] for m in mensagens] + [s["id"] for s in status or []])
    cliente.post("/api/ponte/retorno", headers=CAB, json={"confirmados": [], "novidades": {}, "conversas": {
        "mensagens": mensagens, "status": status or [], "ultimo_id": ultimo}})


def _limpar_telas() -> None:
    with sessao() as db:
        for chave in ("wl_tela_vista_em", "wl_conversas_vista_em"):
            gravar_config(db, chave, "")
        gravar_config(db, "wl_conv_pendente", "0")


def test_conversa_e_lista_so_vem_inteiras_quando_algo_muda(cliente, nuvem):
    inicio = cliente.post("/api/ponte/troca", json={"status": STATUS}, headers=CAB).json()["desde_conversas"]
    _retorno(cliente, [_mensagem(inicio + 1, "entrada", "Bom dia, quero renovar", "recebida", 0),
                       _mensagem(inicio + 2, "saida", "Bom dia, Paula!", "na_fila", 1)])
    url = "/conversas/api/conversa/81944440001"

    c = cliente.get(url).json()
    assert [m["texto"] for m in c["mensagens"]] == ["Bom dia, quero renovar", "Bom dia, Paula!"] and c["marca"]
    igual = cliente.get(f"{url}?marca={c['marca']}").json()
    assert igual["igual"] and "mensagens" not in igual and "situacao" in igual  # nada mudou: só "igual"
    assert not cliente.get(f"{url}?marca=outra").json().get("igual")  # marca velha ou de outra conversa: vem tudo

    # o status da mensagem enviada mudou (na fila -> enviada): vem tudo de novo
    _retorno(cliente, [], [{"id": inicio + 2, "status": "enviada", "erro": ""}])
    c2 = cliente.get(f"{url}?marca={c['marca']}").json()
    assert not c2.get("igual") and c2["mensagens"][-1]["status"] == "enviada" and c2["marca"] != c["marca"]

    # mensagem nova: vem tudo de novo, com ela
    _retorno(cliente, [_mensagem(inicio + 3, "entrada", "Pode ser hoje?", "recebida", 2)])
    c3 = cliente.get(f"{url}?marca={c2['marca']}").json()
    assert not c3.get("igual") and c3["mensagens"][-1]["texto"] == "Pode ser hoje?"
    assert cliente.get(f"{url}?marca={c3['marca']}").json()["igual"]

    # lista: igual enquanto nada muda; mensagem nova e conversa lida mudam a marca
    lista = cliente.get("/conversas/api/lista").json()
    assert any(x["telefone"] == "81944440001" for x in lista["conversas"]) and lista["marca"]
    assert cliente.get(f"/conversas/api/lista?marca={lista['marca']}").json()["igual"]
    assert not cliente.get(f"/conversas/api/lista?busca=paula&marca={lista['marca']}").json().get("igual")  # outra busca
    _retorno(cliente, [_mensagem(inicio + 4, "entrada", "Alô?", "recebida", 3)])
    lista2 = cliente.get(f"/conversas/api/lista?marca={lista['marca']}").json()
    paula = next(x for x in lista2["conversas"] if x["telefone"] == "81944440001")
    assert paula["ultima"] == "Alô?" and paula["nao_lidas"] == 1
    cliente.get(url)  # abrir a conversa marca como lida: a lista muda (tira o "não lida")
    lista3 = cliente.get(f"/conversas/api/lista?marca={lista2['marca']}").json()
    assert not lista3.get("igual")
    assert next(x for x in lista3["conversas"] if x["telefone"] == "81944440001")["nao_lidas"] == 0
    assert cliente.get(f"/conversas/api/lista?marca={lista3['marca']}").json()["igual"]


def test_ponte_troca_a_cada_10_s_com_a_tela_conversas(cliente, nuvem):
    cliente.post("/api/ponte/troca", json={"status": STATUS}, headers=CAB)  # leva o que outros testes deixaram
    _limpar_telas()
    assert cliente.post("/api/ponte/troca", json={"status": STATUS}, headers=CAB).json()["intervalo"] == 30
    assert cliente.get("/conversas").status_code == 200
    assert cliente.post("/api/ponte/troca", json={"status": STATUS}, headers=CAB).json()["intervalo"] == 10
    cliente.get("/whatsapp/estado")  # a tela WhatsApp (QR code, pedidos) continua rápida
    assert cliente.post("/api/ponte/troca", json={"status": STATUS}, headers=CAB).json()["intervalo"] == 3
    _limpar_telas()


def test_tela_aberta_grava_no_maximo_a_cada_10_s(nuvem):
    with sessao() as db:
        gravar_config(db, "wl_conversas_vista_em", (agora() - timedelta(seconds=4)).isoformat())
        antes = ler_config(db, "wl_conversas_vista_em")
        whatsapp_leads.marcar_tela(db, "wl_conversas_vista_em")
        assert ler_config(db, "wl_conversas_vista_em") == antes  # anotado há 4 s: não grava de novo
        gravar_config(db, "wl_conversas_vista_em", (agora() - timedelta(seconds=12)).isoformat())
        whatsapp_leads.marcar_tela(db, "wl_conversas_vista_em")
        assert (agora() - datetime.fromisoformat(ler_config(db, "wl_conversas_vista_em"))).total_seconds() < 2
        gravar_config(db, "wl_conversas_vista_em", "")


def test_status_igual_do_computador_nao_e_regravado(cliente, nuvem):
    with sessao() as db:
        gravar_config(db, "wl_status", "")
    cliente.post("/api/ponte/troca", json={"status": STATUS}, headers=CAB)
    with sessao() as db:
        primeiro = ler_config_json(db, "wl_status", {})
    assert primeiro["conectado"] and primeiro["visto_em"]
    cliente.post("/api/ponte/troca", json={"status": STATUS}, headers=CAB)
    with sessao() as db:
        assert ler_config_json(db, "wl_status", {})["visto_em"] == primeiro["visto_em"]  # igual e recente: não grava
    desligado = {**STATUS, "conectado": False, "estado": "Desconectado", "estado_codigo": "desconectado"}
    cliente.post("/api/ponte/troca", json={"status": desligado}, headers=CAB)
    with sessao() as db:
        assert ler_config_json(db, "wl_status", {})["conectado"] is False  # mudou: grava na hora
        velho = {**ler_config_json(db, "wl_status", {}), "visto_em": (agora() - timedelta(seconds=55)).isoformat()}
        gravar_config(db, "wl_status", velho)
    cliente.post("/api/ponte/troca", json={"status": desligado}, headers=CAB)
    with sessao() as db:  # igual, mas o último sinal gravado tem quase 1 min: grava (o "visto_em" não fica velho)
        visto = datetime.fromisoformat(ler_config_json(db, "wl_status", {})["visto_em"])
        assert (agora() - visto).total_seconds() < 5
        gravar_config(db, "wl_status", "")
