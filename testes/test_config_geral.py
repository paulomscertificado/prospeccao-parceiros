"""Configurações > Geral em grupos (pedido da Maria em 19/11/2026: "está muito confuso e feio"): nenhum campo antigo
sumiu, as chaves liga/desliga gravam 1 ou 0, o horário é um relógio, e quem é de uma AR vê só o que pode mudar."""

from app.banco import gravar_config, ler_config, sessao
from app.rotas import admin
from conftest import csrf_de

CAMPOS_ANTIGOS = (
    "mostrar_vendas", "mostrar_agenda", "link_parceria", "texto_comissao", "programa_parceria", "limite_diario_whatsapp",
    "limite_diario_email", "horas_entre_contatos_whatsapp", "horas_entre_contatos_email", "pular_fim_de_semana",
    "alertas_vencimento", "dias_parceiro_parado", "dias_lead_parado", "dias_retencao_perdidos", "custo_mensal_prospeccao",
    "prioridade_canais", "limite_hora_email", "limite_hora_whatsapp", "intervalo_whatsapp_min", "intervalo_whatsapp_max",
    "limite_frios_whatsapp", "pausa_frios_sair", "limite_diario_campanha", "limite_diario_dominio",
    "horario_envio_inicio", "horario_envio_fim", "enviar_email_automatico", "sdr_resposta_automatica",
    "dias_sem_resposta", "enviar_whatsapp_automatico", "whatsapp_sozinho_padrao", "aprovacao_obrigatoria",
    "whatsapp_convite", "notificar_por_email", "alertas_emails", "limite_banco_mb", "guarda_conversas_meses")


def test_nenhum_campo_antigo_sumiu():
    chaves = [c for c, _, _ in admin.CAMPOS_GERAIS]
    assert set(CAMPOS_ANTIGOS) <= set(chaves) and len(chaves) == len(set(chaves))


def test_tela_em_grupos_com_chaves_e_relogio(cliente):
    tela = cliente.get("/configuracoes").text
    for titulo in ("Horário de envio", "WhatsApp", "E-mail", "Campanhas e IA SDR", "Parceria", "Acompanhamento",
                   "Menu", "Avisos e LGPD"):
        assert f"<h2>{titulo}</h2>" in tela, titulo
    assert "1 = sim, 0 = não" not in tela and "IA SDR ·" not in tela  # os rótulos técnicos de antes
    assert 'type="time" name="horario_envio_inicio"' in tela
    assert 'class="interruptor"><input type="checkbox" name="aprovacao_obrigatoria"' in tela
    assert "Salvar alterações" in tela


def test_chave_liga_desliga_e_intervalo_em_branco(cliente):
    chaves = ("aprovacao_obrigatoria", "horas_entre_contatos_whatsapp")
    with sessao() as db:
        antes = {c: ler_config(db, c) for c in chaves}
    try:
        tela = cliente.get("/configuracoes").text
        # marcada: vêm o "0" escondido e o "1" da chave; vale o último
        cliente.post("/configuracoes/geral", data={"csrf": csrf_de(tela), "aprovacao_obrigatoria": ["0", "1"],
                                                   "horas_entre_contatos_whatsapp": ""})
        with sessao() as db:
            assert ler_config(db, "aprovacao_obrigatoria") == "1"
            assert ler_config(db, "horas_entre_contatos_whatsapp") == ""  # em branco = 20 h (não vira 0)
        # desmarcada: só o "0" escondido
        cliente.post("/configuracoes/geral", data={"csrf": csrf_de(tela), "aprovacao_obrigatoria": "0"})
        with sessao() as db:
            assert ler_config(db, "aprovacao_obrigatoria") == "0"
    finally:
        with sessao() as db:
            for chave, valor in antes.items():
                gravar_config(db, chave, valor)
