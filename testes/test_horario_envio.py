"""Horário de envio com ou sem o zero (caso real de 19/11/2026: o Grupo Certy salvou "8:12" e, comparando como texto,
"15:48" vinha antes de "8:12": a fila pulou todos os envios automáticos dele). O horário vale do mesmo jeito e é gravado
sempre como HH:MM."""

from datetime import datetime

from app import util
from app.banco import gravar_config, ler_config, sessao
from app.mensagens import dentro_do_horario as dentro_do_horario_de_verdade  # antes de algum teste trocar por um falso
from conftest import csrf_de


def test_hora_hhmm_entende_com_e_sem_o_zero():
    for escrito, esperado in (("8:12", "08:12"), ("08:12", "08:12"), ("8h12", "08:12"), ("8h", "08:00"), ("8", "08:00"),
                              (" 17:30 ", "17:30"), ("7.45", "07:45"), ("23:59", "23:59")):
        assert util.hora_hhmm(escrito) == esperado, escrito
    for errado in ("", "25:00", "8:61", "oito", "8:1:2", None):
        assert util.hora_hhmm(errado, "padrao") == "padrao", errado


def test_horario_sem_o_zero_vale_igual_na_fila(cliente):
    with sessao() as db:
        antes = (ler_config(db, "horario_envio_inicio"), ler_config(db, "horario_envio_fim"))
        try:
            gravar_config(db, "horario_envio_inicio", "8:12")
            gravar_config(db, "horario_envio_fim", "17:30")
            quarta = datetime(2026, 11, 18)
            assert dentro_do_horario_de_verdade(db, quarta.replace(hour=15, minute=48))  # o toque da campanha 110
            assert dentro_do_horario_de_verdade(db, quarta.replace(hour=8, minute=12))
            assert not dentro_do_horario_de_verdade(db, quarta.replace(hour=8, minute=11))
            assert not dentro_do_horario_de_verdade(db, quarta.replace(hour=17, minute=30))
            assert not dentro_do_horario_de_verdade(db, datetime(2026, 11, 21, 15, 48))  # sábado
        finally:
            gravar_config(db, "horario_envio_inicio", antes[0])
            gravar_config(db, "horario_envio_fim", antes[1])


def test_configuracoes_gravam_o_horario_com_o_zero(cliente):
    with sessao() as db:
        antes = (ler_config(db, "horario_envio_inicio"), ler_config(db, "horario_envio_fim"))
    try:
        tela = cliente.get("/configuracoes").text
        r = cliente.post("/configuracoes/geral", data={"csrf": csrf_de(tela), "horario_envio_inicio": "8:12",
                                                        "horario_envio_fim": "17:30"})
        assert "Configurações salvas" in r.text
        with sessao() as db:
            assert ler_config(db, "horario_envio_inicio") == "08:12"
        r = cliente.post("/configuracoes/geral", data={"csrf": csrf_de(tela), "horario_envio_inicio": "25:00"})
        assert "Horário inválido" in r.text
        r = cliente.post("/configuracoes/geral", data={"csrf": csrf_de(tela), "horario_envio_inicio": "18:00",
                                                        "horario_envio_fim": "08:00"})
        assert "precisa terminar depois de começar" in r.text
        with sessao() as db:  # nada do que deu erro ficou gravado
            assert (ler_config(db, "horario_envio_inicio"), ler_config(db, "horario_envio_fim")) == ("08:12", "17:30")
    finally:
        with sessao() as db:
            gravar_config(db, "horario_envio_inicio", antes[0])
            gravar_config(db, "horario_envio_fim", antes[1])
