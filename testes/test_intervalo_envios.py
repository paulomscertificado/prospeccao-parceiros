"""Regra da Maria: envios automáticos das campanhas saem um de cada vez, com 3 a 4 minutos sorteados entre eles."""

from datetime import timedelta

from app import campanhas, config
from app.banco import agora, gravar_config, ler_config, sessao


def test_um_envio_por_vez_com_intervalo_sorteado(cliente, monkeypatch):
    monkeypatch.setattr(config, "ESPACAR_ENVIOS", True)
    proximos = []
    with sessao() as db:
        for canal in ("email", "whatsapp"):
            gravar_config(db, f"proximo_envio_automatico:{canal}", "")
            assert campanhas._vez_do_canal(db, canal)  # nunca enviou: pode
        for _ in range(20):
            campanhas._anotar_envio(db, "email")
            proximo = ler_config(db, "proximo_envio_automatico:email")
            proximos.append(proximo)
            espera = (agora().fromisoformat(proximo) - agora()).total_seconds()
            assert 140 <= espera <= 211  # liberado entre 2,5 e 3,5 min: com o relógio de 1 min, sai em 3 ou 4 min
        assert not campanhas._vez_do_canal(db, "email")  # acabou de enviar: espera
        assert campanhas._vez_do_canal(db, "whatsapp")   # cada canal tem o seu intervalo
        assert len(set(proximos)) > 1                     # sorteado: não é sempre o mesmo tempo
        gravar_config(db, "proximo_envio_automatico:email",
                      (agora() - timedelta(seconds=1)).isoformat(timespec="seconds"))
        assert campanhas._vez_do_canal(db, "email")       # passou o intervalo: libera o próximo
        gravar_config(db, "proximo_envio_automatico:email", "")


def test_fila_para_quando_ainda_nao_deu_o_intervalo(cliente, monkeypatch):
    from app.integracoes import email_smtp

    monkeypatch.setattr(config, "ESPACAR_ENVIOS", True)
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    with sessao() as db:
        gravar_config(db, "enviar_email_automatico", "1")
        campanhas._anotar_envio(db, "email")
        def nao_pode_procurar(*a, **k):
            raise AssertionError("procurou e-mails antes de passar o intervalo")

        monkeypatch.setattr(campanhas, "select", nao_pode_procurar)
        assert campanhas.processar_fila(db)["enviados"] == 0  # nem procurou: o intervalo ainda não passou
        monkeypatch.undo()
    with sessao() as db:
        gravar_config(db, "proximo_envio_automatico:email", "")


def test_whatsapp_automatico_espera_8_a_12_minutos_e_segue_as_configuracoes(cliente, monkeypatch):
    """17/11/2026: o WhatsApp restringiu o número do Paulo Lucas por "envio de spam" (66 mensagens no dia, uma a cada 3
    a 4 minutos). O WhatsApp automático passa a esperar 8 a 12 minutos, ajustável em Configurações > Geral; o e-mail
    continua com 3 a 4 minutos."""
    from datetime import datetime

    monkeypatch.setattr(config, "ESPACAR_ENVIOS", True)
    chaves = ("intervalo_whatsapp_min", "intervalo_whatsapp_max")
    with sessao() as db:
        antes = {c: ler_config(db, c) for c in chaves}
        try:
            for c in chaves:
                gravar_config(db, c, "")  # sem valor: o padrão
            assert campanhas.intervalo_automatico(db, "whatsapp") == (480.0, 720.0)
            assert campanhas.texto_do_intervalo(db) == "8 a 12 minutos"
            assert campanhas.intervalo_automatico(db, "email") == campanhas.INTERVALO_AUTOMATICO_SEG
            for _ in range(10):
                campanhas._anotar_envio(db, "whatsapp")
                proximo = datetime.fromisoformat(ler_config(db, "proximo_envio_automatico:whatsapp"))
                assert 470 <= (proximo - agora()).total_seconds() <= 721
            gravar_config(db, "intervalo_whatsapp_min", "15")
            gravar_config(db, "intervalo_whatsapp_max", "10")  # máximo menor que o mínimo: vale o mínimo
            assert campanhas.intervalo_automatico(db, "whatsapp") == (900.0, 900.0)
            assert campanhas.texto_do_intervalo(db) == "15 minutos"
            db.commit()
            assert "com 15 minutos entre um e outro" in cliente.get("/envios?aba=regras").text
        finally:
            for c, v in antes.items():
                gravar_config(db, c, v)
            gravar_config(db, "proximo_envio_automatico:whatsapp", "")
            db.commit()
