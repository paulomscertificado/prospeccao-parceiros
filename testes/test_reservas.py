"""Empresa travada com quem fez a campanha: 60 dias (renova a cada mudança de status) ou até liberar."""

from datetime import date, timedelta

from sqlalchemy import select

from app import campanhas, reservas
from app.banco import agora, sessao
from app.leads_servico import mudar_status
from app.modelos import Campanha, Lead, Tarefa, Usuario
from app.seguranca import resumir_senha


def _usuario(db, nome, email):
    u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
    if not u:
        u = Usuario(nome=nome, email=email, perfil="vendedor", senha_hash=resumir_senha("senhaTeste123"))
        db.add(u)
        db.flush()
    return u


def test_reserva_bloqueia_outro_usuario_e_renova_com_status(cliente):
    with sessao() as db:
        ana, beto = _usuario(db, "Ana Reserva", "ana.r@teste.com.br"), _usuario(db, "Beto Reserva", "beto.r@teste.com.br")
        lead = Lead(empresa="Contabil Travada")
        db.add(lead)
        db.flush()
        reservas.reservar(db, lead, ana, "teste")
        assert reservas.de_outro(lead, beto.id) and not reservas.de_outro(lead, ana.id)
        lead.reservado_ate = agora() + timedelta(days=5)
        mudar_status(db, lead, "Contatado", ana)
        assert lead.reservado_ate > agora() + timedelta(days=59)  # mudou o status: os 60 dias recomeçam
        db.commit()


def test_libera_sozinho_depois_de_60_dias_sem_mudanca(cliente):
    with sessao() as db:
        ana = _usuario(db, "Ana Reserva", "ana.r@teste.com.br")
        lead = Lead(empresa="Contabil Vencida", status="Perdido", motivo_perda="Sem resposta", vendedor_id=ana.id)
        engajado = Lead(empresa="Contabil Respondeu", status="Interessado", vendedor_id=ana.id)
        db.add_all([lead, engajado])
        db.flush()
        for l in (lead, engajado):
            reservas.reservar(db, l, ana)
            l.reservado_ate = agora() - timedelta(minutes=1)
        db.commit()
        ids = (lead.id, engajado.id)
    with sessao() as db:
        reservas.liberar_vencidas(db)
        db.commit()
    with sessao() as db:
        lead, engajado = db.get(Lead, ids[0]), db.get(Lead, ids[1])
        assert lead.reservado_por_id is None and lead.vendedor_id is None and lead.status == "Novo"
        assert engajado.reservado_por_id is None and engajado.status == "Interessado"  # quem respondeu não volta a Novo


def test_campanha_andando_segura_a_liberacao(cliente):
    with sessao() as db:
        ana = _usuario(db, "Ana Reserva", "ana.r@teste.com.br")
        camp = Campanha(nome="Campanha da Ana", categorias="contabil", cidade="Recife", estado="PE", quantidade=1,
                        canais="email", status="ativa", usuario_id=ana.id)
        lead = Lead(empresa="Contabil Em Campanha")
        db.add_all([camp, lead])
        db.flush()
        db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", data=date.today(), status="pendente"))
        reservas.reservar(db, lead, ana)
        lead.reservado_ate = agora() - timedelta(minutes=1)
        db.commit()
        lead_id = lead.id
    with sessao() as db:
        reservas.liberar_vencidas(db)
        db.commit()
    with sessao() as db:
        assert db.get(Lead, lead_id).reservado_por_id is not None


def test_liberar_pela_ficha(cliente):
    from conftest import csrf_de

    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        ana = _usuario(db, "Ana Reserva", "ana.r@teste.com.br")
        lead = Lead(empresa="Contabil Para Liberar", status="Contatado", vendedor_id=ana.id)
        db.add(lead)
        db.flush()
        reservas.reservar(db, lead, ana)
        db.add(Tarefa(lead_id=lead.id, canal="email", data=date.today(), status="pendente", tipo="prospeccao"))
        db.commit()
        lead_id = lead.id
        assert reservas.pode_liberar(admin, lead)
    pagina = cliente.get(f"/leads/{lead_id}").text
    assert "Reservada para Ana Reserva" in pagina and "Liberar para a base" in pagina
    cliente.post(f"/leads/{lead_id}/liberar", data={"csrf": csrf_de(pagina)})
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        assert lead.reservado_por_id is None and lead.status == "Novo"
        assert db.execute(select(Tarefa.status).where(Tarefa.lead_id == lead_id)).scalar() == "cancelada"


def test_preencher_reservas_das_campanhas_existentes(cliente):
    from app.banco import gravar_config

    with sessao() as db:
        ana = _usuario(db, "Ana Reserva", "ana.r@teste.com.br")
        camp = Campanha(nome="Campanha antiga", categorias="contabil", cidade="Recife", estado="PE", quantidade=1,
                        canais="email", status="concluida", usuario_id=ana.id)
        lead = Lead(empresa="Contabil Antiga")
        db.add_all([camp, lead])
        db.flush()
        db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", data=date.today(), status="feita"))
        gravar_config(db, "reservas_preenchidas", "")
        db.commit()
        lead_id = lead.id
    with sessao() as db:
        assert reservas.preencher_reservas_antigas(db) >= 1
        assert reservas.preencher_reservas_antigas(db) == 0  # só uma vez
        db.commit()
    with sessao() as db:
        assert db.get(Lead, lead_id).reservado_por_id is not None


def test_campanha_pula_empresa_de_outro(cliente):
    with sessao() as db:
        ana, beto = _usuario(db, "Ana Reserva", "ana.r@teste.com.br"), _usuario(db, "Beto Reserva", "beto.r@teste.com.br")
        lead = Lead(empresa="Contabil Disputada")
        db.add(lead)
        db.flush()
        reservas.reservar(db, lead, ana)
        camp_beto = Campanha(nome="Campanha do Beto", status="gerando", usuario_id=beto.id)
        db.add(camp_beto)
        db.flush()
        assert reservas.de_outro(lead, camp_beto.usuario_id)
        assert lead.id not in campanhas._leads_em_outras_campanhas(db, camp_beto.id)  # quem barra é a reserva
