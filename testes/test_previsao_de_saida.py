"""Horário previsto de saída ao lado do "Programado" (pedido da Maria em 17/11/2026: "do lado de programado, coloque o
horário exato que vai sair o disparo"). A previsão segue as regras da fila automática: o horário marcado, as 20 h desde
o último envio do canal para a empresa, o horário de envio em dia útil e, na Renovação, o horário dela e os feriados."""

import re
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app.banco import agora, gravar_config, sessao
from app.campanhas import JanelaDeEnvio
from app.modelos import Campanha, Lead, Mensagem, Tarefa, Usuario
from app.rotas import fila

TERCA = datetime(2026, 11, 17, 14, 0)  # terça-feira
HOJE = TERCA.date()
JANELA = JanelaDeEnvio(inicio="08:30", fim="18:00", renov_inicio="10:00", renov_fim="18:00",
                       feriados_renovacao=frozenset({date(2026, 11, 20)}))  # sexta, 20/11: feriado


def test_janela_de_envio():
    assert JANELA.proxima(TERCA) == TERCA  # dentro do horário: pode sair já
    assert JANELA.proxima(datetime(2026, 11, 17, 7, 0)) == datetime(2026, 11, 17, 8, 30)  # antes de abrir
    assert JANELA.proxima(datetime(2026, 11, 17, 18, 0)) == datetime(2026, 11, 18, 8, 30)  # fechou: dia seguinte
    assert JANELA.proxima(datetime(2026, 11, 21, 9, 0)) == datetime(2026, 11, 23, 8, 30)  # sábado: segunda
    # Renovação: só das 10:00, sem feriado, e o WhatsApp para 10 minutos antes do fim
    assert JANELA.proxima(datetime(2026, 11, 17, 9, 0), renovacao=True) == datetime(2026, 11, 17, 10, 0)
    assert JANELA.proxima(datetime(2026, 11, 19, 17, 55), renovacao=True) == datetime(2026, 11, 23, 10, 0)
    quinta = datetime(2026, 11, 19, 17, 55)
    assert JANELA.proxima(quinta, renovacao=True, canal="email") == quinta  # o e-mail vai até as 18:00
    assert JanelaDeEnvio(inicio="18:00", fim="08:00").proxima(TERCA) is None  # horário vazio: sem previsão


def _toque(canal="whatsapp", data=HOJE, hora="10:23", campanha=7, lead_id=900001, tarefa_id=900101):
    lead = Lead(empresa="Previsao Teste Ltda", whatsapp="(81) 98888-0001", email="contato@previsao-teste.com.br",
                status="Contatado")
    lead.id = lead_id
    t = Tarefa(tipo="prospeccao", canal=canal, data=data, hora=hora, campanha_id=campanha, status="pendente")
    t.id, t.lead_id, t.lead = tarefa_id, lead_id, lead
    return t


def _situacao(t, **k):
    padrao = dict(hoje=HOJE, no_horario=True, conversaram=set(), email_auto=True, whats_auto=True,
                  automaticas={7: "empresas_novas"}, janela=JANELA)
    padrao.update(k)
    return fila.situacao_e_previsao(t, **padrao)


def test_whatsapp_que_espera_as_20_horas_mostra_quando_sai(monkeypatch):
    monkeypatch.setattr(fila, "agora", lambda: TERCA)
    t = _toque()
    chave, motivo, previsto = _situacao(t, recentes={900001: datetime(2026, 11, 17, 12, 41)})
    assert chave == "programado" and "há menos de 20 h" in motivo
    assert fila.quando_sai(previsto, HOJE) == "amanhã às 08:41"  # 12:41 + 20 h
    _, _, previsto = _situacao(t, recentes={900001: datetime(2026, 11, 17, 9, 0)})
    assert fila.quando_sai(previsto, HOJE) == "amanhã às 08:30"  # 05:00 é antes de abrir: começo do horário
    futuro = _toque(data=date(2026, 11, 18), hora="08:00")
    chave, motivo, previsto = _situacao(futuro, recentes={900001: datetime(2026, 11, 17, 13, 0)})
    assert chave == "programado" and fila.quando_sai(previsto, HOJE) == "amanhã às 09:00"
    assert "Programado para 18/11 às 08:00 (sai sozinho); sai quando completar 20 h do último WhatsApp" in motivo
    _, _, previsto = _situacao(_toque(hora="16:00"))
    assert fila.quando_sai(previsto, HOJE) == "hoje às 16:00"  # marcado para mais tarde: o horário marcado


def test_quem_espera_o_clique_nao_ganha_horario(monkeypatch):
    monkeypatch.setattr(fila, "agora", lambda: TERCA)
    chave, _, previsto = _situacao(_toque(campanha=8))  # campanha sem WhatsApp automático e contato frio
    assert chave == "clique" and previsto is None


def test_renovacao_antes_das_10_fica_aguardando_o_horario(monkeypatch):
    monkeypatch.setattr(fila, "agora", lambda: datetime(2026, 11, 17, 9, 30))
    chave, motivo, previsto = _situacao(_toque(hora="09:00"), automaticas={7: "renovacao"})
    assert chave == "horario" and previsto == datetime(2026, 11, 17, 10, 0)
    assert motivo == "Aguardando o horário de envio (fica para o próximo horário de envio da Renovação)"


def test_email_com_envio_recente_e_email_que_espera_o_whatsapp(monkeypatch):
    monkeypatch.setattr(fila, "agora", lambda: TERCA)
    mail = _toque(canal="email", hora="11:00", tarefa_id=900102)
    chave, _, previsto = _situacao(mail, recentes_email={900001: datetime(2026, 11, 17, 13, 30)})
    assert chave == "programado" and fila.quando_sai(previsto, HOJE) == "amanhã às 09:30"
    # Empresas novas: o e-mail do toque sai depois do WhatsApp da empresa (que espera as 20 h)
    zap = _toque(hora="10:00")
    mail = _toque(canal="email", hora="12:00", tarefa_id=900103)
    itens = fila.itens_da_fila([mail, zap], HOJE, True, set(), True, True, {7: "empresas_novas"}, set(),
                               {900001: datetime(2026, 11, 17, 12, 0)}, {mail.id}, {}, JANELA)
    assert [i["t"].id for i in itens] == [mail.id, zap.id]  # a ordem da tela não muda
    assert itens[1]["previsto"] == "amanhã às 08:30" and itens[0]["previsto"] == "amanhã às 08:30"


def test_minha_fila_mostra_o_horario_ao_lado_do_programado(cliente, monkeypatch):
    from app.integracoes import whatsapp_leads

    monkeypatch.setattr(whatsapp_leads, "status", lambda *a, **k: {"disponivel": True})
    with sessao() as db:
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        camp = Campanha(nome="Previsao de saida", status="ativa", usuario_id=admin.id, canais="whatsapp",
                        tipo="empresas_novas", aprovado_em=agora())
        lead = Lead(empresa="Previsao Na Tela Ltda", whatsapp="(81) 98888-0002", status="Contatado",
                    vendedor_id=admin.id)
        db.add_all([camp, lead])
        db.flush()
        db.add_all([Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="whatsapp",
                           data=date.today(), hora="00:01", status="pendente", mensagem="Olá!"),
                    Mensagem(lead_id=lead.id, canal="whatsapp", direcao="saida", status="enviada",
                             angulo="apresentacao", corpo="previsao 1º toque", criado_em=agora() - timedelta(minutes=10))])
        db.commit()
        lead_id, camp_id = lead.id, camp.id
    try:
        pagina = cliente.get("/fila").text
        linha = pagina.split("Previsao Na Tela Ltda", 1)[1].split('class="linha-fila')[0]
        assert re.search(r'class="previsto-envio"[^>]*>sai (amanhã|\d\d/\d\d) às \d\d:\d\d<', linha), linha[-900:]
    finally:
        with sessao() as db:
            for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp_id)).scalars():
                t.status = "cancelada"
            db.get(Campanha, camp_id).status = "cancelada"
            db.execute(delete(Mensagem).where(Mensagem.lead_id == lead_id, Mensagem.corpo == "previsao 1º toque"))
