"""Pedido da Maria (10/11/2026): campanha com WhatsApp cria a mensagem de WhatsApp para TODAS as empresas; se o campo
WhatsApp da empresa estiver em branco, a mensagem fica pronta e não sai (nem pelo telefone fixo)."""

from datetime import date

import pytest
from sqlalchemy import select

from app import cadencias, campanhas, sdr
from app.banco import sessao
from app.modelos import Cadencia, Campanha, Lead, PassoCadencia, Tarefa, Usuario


def _montar(db, whatsapp: str):
    admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
    cad = Cadencia(nome="Teste WhatsApp em branco")
    cad.passos = [PassoCadencia(dia=1, canal="auto", angulo="apresentacao")]
    lead = Lead(empresa="Contab Branco Ltda", email="contato@contabbranco-x.com.br", telefone="(81) 3333-4444",
                whatsapp=whatsapp, status="Novo")
    camp = Campanha(nome="Campanha branco", status="ativa", usuario_id=admin.id, canais="whatsapp,email")
    db.add_all([cad, lead, camp])
    db.flush()
    msgs = {lead.id: {"apresentacao": {"assunto": "Oi", "email": "Texto do e-mail", "whatsapp": "Texto do zap"}}}
    cadencias.aplicar(db, cad, [lead], admin, inicio=date.today(), campanha_id=camp.id, mensagens_sdr=msgs,
                      canais=["whatsapp", "email"])
    db.flush()
    return admin, lead, camp, db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id)).scalars().all()


def test_sem_whatsapp_cria_os_dois_e_o_zap_nao_sai(cliente):
    with sessao() as db:
        admin, lead, camp, tarefas = _montar(db, "")
        canais = sorted(t.canal for t in tarefas)
        assert canais == ["email", "whatsapp"]
        zap = next(t for t in tarefas if t.canal == "whatsapp")
        email = next(t for t in tarefas if t.canal == "email")
        assert zap.mensagem == "Texto do zap" and not zap.mensagem_email  # sem reserva: não vira e-mail repetido
        assert not email.mensagem_whatsapp  # o e-mail não vira um segundo WhatsApp
        # campo em branco: não entra no disparo, não sai pelo clique e nem pelo fixo
        assert campanhas.para_disparar(db, camp)["whatsapp"] == []
        assert campanhas.enviar_toque_agora(db, zap, admin) == sdr.SEM_WHATSAPP
        with pytest.raises(sdr.EnvioRecusado):
            sdr.enviar_whatsapp_conectado(db, zap.mensagem, admin, lead=lead, tarefa=zap)
        db.rollback()


def test_com_whatsapp_cria_so_o_zap(cliente):
    with sessao() as db:
        _admin, _lead, _camp, tarefas = _montar(db, "(81) 98888-7777")
        assert [t.canal for t in tarefas] == ["whatsapp"]
        db.rollback()
