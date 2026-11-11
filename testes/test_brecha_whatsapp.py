"""Auditoria de 11/11/2026, P0.3: resposta de robô não libera WhatsApp sozinho; teto de contatos frios por número por
dia (vale para o clique, o Disparar e a fila automática) e pausa dos frios do número quando 3 pessoas pedem para sair."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import campanhas, mensagens, sdr
from app.banco import agora, gravar_config, sessao
from app.modelos import Lead, Mensagem, Usuario


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _lead(db, nome, numero, **extra):
    lead = Lead(empresa=nome, whatsapp=numero, status="Contatado", vendedor_id=_admin(db).id, **extra)
    db.add(lead)
    db.flush()
    return lead


def _recebida(db, lead, texto, **extra):
    m = Mensagem(lead_id=lead.id, canal="whatsapp", corpo=texto, status="recebida", direcao="entrada", **extra)
    db.add(m)
    db.flush()
    return m


def _enviada(db, lead, conexao, quando=None):
    db.add(Mensagem(lead_id=lead.id, canal="whatsapp", corpo="Olá!", status="enviada", direcao="saida",
                    conexao=conexao, criado_em=quando or agora()))
    db.flush()


class _Falso:
    def __init__(self):
        self.enviados = []

    def enviar(self, telefone, nome, texto, resposta=False, db=None, conexao="principal", **_):
        self.enviados.append(telefone)
        return len(self.enviados)


@pytest.fixture()
def whatsapp_falso(monkeypatch):
    from app.integracoes import whatsapp_leads

    falso = _Falso()
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "enviar", falso.enviar)
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": True, "conectado": True})
    return falso


def test_resposta_de_robo_nao_libera_whatsapp_sozinho(cliente):
    with sessao() as db:
        robo_antigo = _lead(db, "Robo Antigo Brecha Ltda", "81970000001")
        _recebida(db, robo_antigo, "Olá! Recebemos sua mensagem. Em breve retornaremos.")  # antes desta mudança
        robo_marcado = _lead(db, "Robo Marcado Brecha Ltda", "81970000002")
        _recebida(db, robo_marcado, "Bom dia", modo="robo")
        gente = _lead(db, "Gente Responde Brecha Ltda", "81970000003")
        _recebida(db, gente, "Olá! Recebemos sua mensagem. Em breve retornaremos.")
        _recebida(db, gente, "Oi, pode me explicar como funciona a parceria?")
        assert not campanhas.whatsapp_liberado(db, robo_antigo)
        assert not campanhas.whatsapp_liberado(db, robo_marcado)
        assert campanhas.whatsapp_liberado(db, gente)
        assert campanhas.leads_que_conversaram(db, [robo_antigo.id, robo_marcado.id, gente.id]) == {gente.id}
        # a resposta de robô que chega agora fica marcada
        novo = _lead(db, "Robo Novo Brecha Ltda", "81970000004")
        sdr.processar_resposta(db, novo, "Recebemos sua mensagem. Aguarde um momento, por favor", "whatsapp")
        assert db.execute(select(Mensagem.modo).where(Mensagem.lead_id == novo.id,
                                                      Mensagem.status == "recebida")).scalar_one() == "robo"
        assert not campanhas.whatsapp_liberado(db, novo) and sdr.contato_frio(db, novo)
        db.rollback()


def test_teto_de_contatos_frios_por_numero(cliente, whatsapp_falso):
    with sessao() as db:
        gravar_config(db, "limite_frios_whatsapp", "2")
        conexao = "teto-frios"
        ja_foram = [_lead(db, f"Frio Enviado {i} Ltda", f"8197100000{i}") for i in range(2)]
        for lead in ja_foram:
            _enviada(db, lead, conexao)
        conversou = _lead(db, "Conversou Antes Ltda", "81971000009")
        _recebida(db, conversou, "Pode mandar mais detalhes", criado_em=agora() - timedelta(days=1))
        _enviada(db, conversou, conexao)  # quem já conversou não conta no teto
        assert mensagens.frios_hoje(db, conexao) == 2
        assert "contatos frios" in mensagens.limite_de_frios(db, conexao)

        frio = _lead(db, "Frio Barrado Ltda", "81971000005")
        with pytest.raises(sdr.EnvioRecusado) as erro:
            sdr.enviar_whatsapp_conectado(db, "Olá!", _admin(db), lead=frio, conexao=conexao)
        assert "contatos frios" in str(erro.value)
        assert campanhas.motivo_curto(str(erro.value)) == "número chegou ao teto de contatos frios do dia"
        # quem autorizou passa (o teto é só para frios); outro número também
        autorizou = _lead(db, "Autorizou Receber Ltda", "81971000008", consentimento=True)
        sdr.enviar_whatsapp_conectado(db, "Olá de novo!", _admin(db), lead=autorizou, conexao=conexao)
        sdr.enviar_whatsapp_conectado(db, "Olá!", _admin(db), lead=frio, conexao="outro-numero")
        assert len(whatsapp_falso.enviados) == 2
        gravar_config(db, "limite_frios_whatsapp", "0")  # 0 = sem teto
        assert mensagens.limite_de_frios(db, conexao) == ""
        db.rollback()


def test_tres_pedidos_para_sair_pausam_os_frios_do_numero(cliente):
    with sessao() as db:
        gravar_config(db, "limite_frios_whatsapp", "0")
        conexao = "pausa-sair"
        for i in range(3):
            lead = _lead(db, f"Pediu Sair {i} Ltda", f"8197200000{i}")
            _enviada(db, lead, conexao, agora() - timedelta(days=1))
            if i < 2:
                lead.opt_out, lead.opt_out_em = True, agora()
        db.flush()
        assert mensagens.pedidos_para_sair_hoje(db, conexao) == 2 and mensagens.limite_de_frios(db, conexao) == ""
        ultimo = db.execute(select(Lead).where(Lead.empresa == "Pediu Sair 2 Ltda")).scalar_one()
        ultimo.opt_out, ultimo.opt_out_em = True, agora()
        db.flush()
        motivo = mensagens.limite_de_frios(db, conexao)
        assert "pausados até amanhã" in motivo
        assert campanhas.motivo_curto(motivo) == "número pausado hoje: pedidos para sair"
        db.rollback()
