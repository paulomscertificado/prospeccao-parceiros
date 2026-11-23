"""Expediente com horário diferente num dia (pedido da Maria em 23/11/2026, depois de testar o calendário da Renovação:
"altere o horário para esses aqui": segunda a quinta 08:00-18:00, sexta 08:00-17:30). Os horários livres do
calendário e das reuniões da IA SDR saem do expediente de quem atende."""

from datetime import datetime, time

from sqlalchemy import select

from app import agenda_horarios
from app.banco import sessao
from app.modelos import Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA

HORARIO_MS = "seg-qui 08:00-18:00; sex 08:00-17:30"


def test_le_o_expediente_por_dia():
    por_dia = agenda_horarios.faixas_por_dia(HORARIO_MS)
    assert sorted(por_dia) == [0, 1, 2, 3, 4]
    assert por_dia[0] == [(time(8), time(18))] and por_dia[4] == [(time(8), time(17, 30))]
    antigo = agenda_horarios.faixas_por_dia("seg-sex 09:00-12:00,14:00-18:00")  # o formato de antes continua valendo
    assert sorted(antigo) == [0, 1, 2, 3, 4] and antigo[2] == [(time(9), time(12)), (time(14), time(18))]
    assert agenda_horarios.faixas_por_dia("seg-qui 08:00-18:00; sexta 8h") == {}  # um pedaço errado: inválido
    assert agenda_horarios.faixas_por_dia("") == {}


def test_horarios_livres_respeitam_a_sexta(cliente, monkeypatch):
    # domingo cedo: a semana inteira pela frente (a antecedência de 2 h não corta nada)
    monkeypatch.setattr(agenda_horarios, "agora", lambda: datetime(2026, 11, 29, 6, 0))
    with sessao() as db:
        ms = db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar_one()
        u = db.execute(select(Usuario).where(Usuario.email == "expediente.sexta@teste.com.br")).scalars().first()
        if u is None:
            u = Usuario(nome="Expediente Sexta", email="expediente.sexta@teste.com.br", perfil="funcionario",
                        senha_hash=resumir_senha(SENHA), tenant_id=ms)
            db.add(u)
        u.expediente, u.duracao_reuniao, u.uf, u.cidade = HORARIO_MS, 30, "PE", ""
        db.flush()
        livres = agenda_horarios.horarios_livres(db, u, dias=6, quantidade=500, antecedencia_horas=2)
        db.rollback()
    por_dia: dict = {}
    for h in livres:
        por_dia.setdefault(h.date().isoformat(), []).append(h.strftime("%H:%M"))
    segunda, sexta = por_dia["2026-11-30"], por_dia["2026-12-04"]
    assert segunda[0] == "08:00" and segunda[-1] == "17:30" and len(segunda) == 20  # 08:00 a 17:30, de 30 em 30
    assert sexta[0] == "08:00" and sexta[-1] == "17:00" and len(sexta) == 19        # sexta termina às 17:30
    assert "2026-12-05" not in por_dia and "2026-12-06" not in por_dia              # sábado e domingo, não
