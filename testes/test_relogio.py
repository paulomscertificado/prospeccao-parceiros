"""Relógio das filas (Fase 0 do white label, 13/11/2026): com o plano Pro, o cron da Vercel chama o /api/cron a cada
minuto e o computador da MS vira reserva (?reserva=1). A reserva só faz a rodada se a nuvem não chamou nos últimos 3
minutos, e cada vez que ela precisa rodar conta para o portão da Fase 0 (7 dias seguidos sem o computador)."""
from datetime import timedelta

import pytest
from sqlalchemy import delete

from app import alertas, config, relogio
from app.banco import agora, gravar_config, sessao
from app.modelos import Configuracao

SENHA = "senha-do-relogio-teste"
NUVEM = {"Authorization": f"Bearer {SENHA}", "User-Agent": "vercel-cron/1.0"}
COMPUTADOR = {"Authorization": f"Bearer {SENHA}"}


def _apagar():
    with sessao() as db:
        db.execute(delete(Configuracao).where(Configuracao.chave == relogio.CHAVE))


def _gravar(**valores):
    with sessao() as db:
        gravar_config(db, relogio.CHAVE, {k: v.isoformat(timespec="seconds") if hasattr(v, "isoformat") else v
                                          for k, v in valores.items()})


def _resumo() -> dict:
    with sessao() as db:
        return relogio.resumo(db)


@pytest.fixture()
def rodadas(monkeypatch):
    """Senha do agendador ligada e rodada de mentira (só anota quem chamou)."""
    monkeypatch.setattr(config, "CRON_SECRET", SENHA)
    feitas = []
    monkeypatch.setattr("app.rotas.api.rodada", lambda numero: feitas.append(numero))
    monkeypatch.setattr("app.trabalhos.rodar_pendentes", lambda prazo: 0)
    _apagar()
    yield feitas
    _apagar()


def test_sem_o_plano_pro_o_computador_continua_fazendo_a_rodada(cliente, rodadas):
    r = cliente.get("/api/cron?reserva=1", headers=COMPUTADOR)
    assert r.status_code == 200 and r.json()["rodada"] and rodadas == [None]
    # o cron diário da Vercel (plano gratuito) é registrado, mas não conta como "a cada minuto"
    _gravar(nuvem_em=agora() - timedelta(days=1), nuvem_seguidas=2)
    assert cliente.get("/api/cron", headers=NUVEM).json()["rodada"]
    resumo = _resumo()
    assert resumo["nuvem_em"] is not None and resumo["nuvem_desde"] is None and "portao_ok" not in resumo
    # o mesmo aviso entregue de novo segundos depois também não conta
    assert cliente.get("/api/cron", headers=NUVEM).status_code == 200
    with sessao() as db:
        assert relogio.estado(db)["nuvem_seguidas"] == 0 and _resumo()["nuvem_desde"] is None
    assert "Agendador do Windows, a cada minuto" in cliente.get("/configuracoes?aba=integracoes").text


def test_com_a_nuvem_a_cada_minuto_a_reserva_e_dispensada(cliente, rodadas):
    _gravar(nuvem_em=agora() - timedelta(seconds=60), nuvem_seguidas=1)
    assert cliente.get("/api/cron", headers=NUVEM).json()["rodada"]
    assert _resumo()["nuvem_desde"] is None  # 2 intervalos de 1 minuto ainda não bastam
    _gravar(nuvem_em=agora() - timedelta(seconds=60), nuvem_seguidas=2)
    assert cliente.get("/api/cron", headers=NUVEM).json()["rodada"]
    assert _resumo()["nuvem_desde"] is not None  # 3 intervalos seguidos de 1 minuto: plano Pro ligado
    r = cliente.get("/api/cron?reserva=1", headers=COMPUTADOR)
    assert r.json() == {"rodada": False, "etapas": 0, "reserva": "dispensada"}
    assert rodadas == [None, None]  # só as duas rodadas da nuvem; a da reserva foi dispensada
    resumo = _resumo()
    assert resumo["reserva_vezes"] == 0 and resumo["dias_sem_reserva"] == 0 and not resumo["portao_ok"]
    html = cliente.get("/configuracoes?aba=integracoes").text
    assert "nuvem (Vercel), a cada minuto" in html and "0 de 7 dias seguidos sem o computador" in html


def test_nuvem_parada_o_computador_cobre_avisa_e_o_portao_recomeca(cliente, rodadas):
    _gravar(nuvem_desde=agora() - timedelta(days=8), nuvem_em=agora() - timedelta(minutes=12))
    assert _resumo()["portao_ok"]  # 8 dias sem precisar do computador
    with sessao() as db:
        assert "relogio" in alertas.problemas_agora(db)  # a nuvem parou há 12 minutos: vira aviso
    r = cliente.get("/api/cron?reserva=1", headers=COMPUTADOR)
    assert r.json()["rodada"] and rodadas == [None]  # o computador cobriu
    resumo = _resumo()
    assert resumo["reserva_vezes"] == 1 and resumo["dias_sem_reserva"] == 0 and not resumo["portao_ok"]
    assert cliente.get("/api/cron", headers=NUVEM).status_code == 200  # a nuvem voltou
    with sessao() as db:
        assert "relogio" not in alertas.problemas_agora(db)
    assert "precisou 1 vez" in cliente.get("/configuracoes?aba=integracoes").text
