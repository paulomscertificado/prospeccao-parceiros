"""Toques de campanha nunca ficam num horário que já passou (pedido da Maria)."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app import banco, cadencias, campanhas
from app.banco import gravar_config, sessao
from app.modelos import Campanha, Lead, Tarefa, Usuario


@pytest.fixture(autouse=True)
def _devolve_config():
    """Os outros testes contam com a configuração de fim de semana como estava."""
    with sessao() as db:
        antes = banco.ler_config(db, "pular_fim_de_semana")
    yield
    with sessao() as db:
        gravar_config(db, "pular_fim_de_semana", antes)


def _relogio(monkeypatch, quando: datetime):
    monkeypatch.setattr(banco, "agora", lambda: quando)
    monkeypatch.setattr(campanhas, "agora", lambda: quando)


def test_hoje_so_horario_que_ainda_nao_passou(cliente, monkeypatch):
    hoje = date.today()
    _relogio(monkeypatch, datetime.combine(hoje, datetime.min.time()).replace(hour=15, minute=40))
    with sessao() as db:
        gravar_config(db, "horario_envio_inicio", "08:30")
        gravar_config(db, "horario_envio_fim", "18:00")
        for _ in range(50):
            hora = cadencias.hora_natural(db, hoje)
            assert "15:55" <= hora <= "17:44"  # 15 min de folga depois de agora, até o fim do horário de envio
        assert cadencias.hora_natural(db, hoje - timedelta(days=1)) is None  # dia que já passou
        # outro dia: qualquer horário do expediente
        assert "08:30" <= cadencias.hora_natural(db, hoje + timedelta(days=1)) <= "17:44"


def test_depois_do_expediente_vai_para_o_proximo_dia(cliente, monkeypatch):
    hoje = date.today()
    _relogio(monkeypatch, datetime.combine(hoje, datetime.min.time()).replace(hour=17, minute=50))
    with sessao() as db:
        gravar_config(db, "pular_fim_de_semana", "0")
        assert cadencias.hora_natural(db, hoje) is None
        dia, hora = cadencias.dia_e_hora_futuros(db, hoje)
        assert dia == hoje + timedelta(days=1) and "08:30" <= hora <= "17:44"


def test_aprovar_tarde_reagenda_o_que_ja_passou(cliente, monkeypatch):
    hoje = date.today()
    _relogio(monkeypatch, datetime.combine(hoje, datetime.min.time()).replace(hour=16, minute=0))
    with sessao() as db:
        gravar_config(db, "pular_fim_de_semana", "0")
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        lead = Lead(empresa="Horario Teste Ltda", email="contato@horarioteste-x.com.br", status="Abordagem criada")
        db.add(lead)
        camp = Campanha(nome="Aprovada à tarde", status="aguardando_aprovacao", usuario_id=admin.id, canais="email")
        db.add(camp)
        db.flush()
        manha = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="email", data=hoje,
                       hora="09:47", status="rascunho", mensagem="Olá")
        depois = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="email",
                        data=hoje + timedelta(days=2), hora="10:13", status="rascunho", mensagem="Olá de novo")
        db.add_all([manha, depois])
        db.flush()
        campanhas.aprovar(db, camp, admin)
        assert (manha.data, manha.hora) > (hoje, "16:14")  # 09:47 já tinha passado: ganhou horário novo
        assert (depois.data, depois.hora) == (hoje + timedelta(days=2), "10:13")  # o que não passou fica igual
        db.rollback()
