"""Auditoria de 11/11/2026, P1.7: "Quem precisa de mim hoje" no Painel (prazo de 2 horas úteis, tarefas, leads
esfriando) e motivo obrigatório ao descartar uma resposta ou marcar um lead como Perdido."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app import hoje
from app.banco import agora, sessao
from app.modelos import Historico, Lead, Oportunidade, Tarefa, Usuario
from conftest import csrf_de

ABRE, FECHA = time(8, 30), time(18, 0)


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def test_prazo_de_2_horas_uteis():
    quarta = datetime(2026, 11, 11, 10, 0)  # quarta-feira
    assert hoje.somar_horas_uteis(quarta, 2, ABRE, FECHA) == datetime(2026, 11, 11, 12, 0)
    assert hoje.somar_horas_uteis(quarta.replace(hour=17, minute=30), 2, ABRE, FECHA) == datetime(2026, 11, 12, 10, 0)
    assert hoje.somar_horas_uteis(datetime(2026, 11, 13, 17, 0), 2, ABRE, FECHA) == datetime(2026, 11, 16, 9, 30)  # sexta
    assert hoje.somar_horas_uteis(datetime(2026, 11, 14, 11, 0), 2, ABRE, FECHA) == datetime(2026, 11, 16, 10, 30)  # sábado
    assert hoje.somar_horas_uteis(datetime(2026, 11, 10, 7, 0), 2, ABRE, FECHA) == datetime(2026, 11, 10, 10, 30)  # cedo


def test_painel_mostra_quem_precisa_de_mim_hoje(cliente):
    with sessao() as db:
        admin = _admin(db)
        quente = Lead(empresa="Hoje Quente Contabil Ltda", status="Interessado", vendedor_id=admin.id)
        morna = Lead(empresa="Hoje Morna Contabil Ltda", status="Respondeu", vendedor_id=admin.id)
        parado = Lead(empresa="Hoje Esfriando Contabil Ltda", status="Negociação", vendedor_id=admin.id,
                      criado_em=agora() - timedelta(days=40))
        com_tarefa = Lead(empresa="Hoje Com Tarefa Ltda", status="Reunião", vendedor_id=admin.id)
        db.add_all([quente, morna, parado, com_tarefa])
        db.flush()
        db.add_all([
            Oportunidade(lead_id=quente.id, temperatura="quente", classificacao="QUER REUNIÃO", status="nova",
                         criado_em=agora() - timedelta(days=3)),
            Oportunidade(lead_id=morna.id, temperatura="morna", classificacao="RESPOSTA INDEFINIDA", status="nova"),
            Historico(lead_id=parado.id, tipo="contato", descricao="Ligação", criado_em=agora() - timedelta(days=20)),
            Historico(lead_id=com_tarefa.id, tipo="contato", descricao="Ligação", criado_em=agora() - timedelta(days=20)),
            Tarefa(tipo="reuniao", lead_id=com_tarefa.id, usuario_id=admin.id, canal="video", status="pendente",
                   data=date.today() - timedelta(days=1), hora="15:00", acao="Reunião de apresentação"),
        ])
        db.flush()
        h = hoje.itens(db, admin)
        assert any(q["o"].lead.empresa == "Hoje Quente Contabil Ltda" and q["atrasada"] for q in h["quentes"])
        assert h["mornas"] >= 1
        esfriando = {e["lead"].empresa for e in h["esfriando"]}
        assert "Hoje Esfriando Contabil Ltda" in esfriando
        assert "Hoje Com Tarefa Ltda" not in esfriando  # tem tarefa (atrasada) e aparece em tarefas
        assert any(t["t"].lead_id == com_tarefa.id and t["atrasada"] for t in h["tarefas"])
    pagina = cliente.get("/").text
    assert "Quem precisa de mim hoje" in pagina
    trecho = pagina[pagina.index("Quem precisa de mim hoje"):pagina.index('action="/campanhas/nova"')]
    for esperado in ("Hoje Quente Contabil Ltda", "fora do prazo há", "Assumir", "Respostas para analisar",
                     "Hoje Esfriando Contabil Ltda", "sem movimento há", "Reunião de apresentação", "atrasada há 1 dia"):
        assert esperado in trecho, esperado
    with sessao() as db:  # não deixa cartões nas telas dos outros testes
        for o in db.execute(select(Oportunidade).join(Lead).where(Lead.empresa.like("Hoje %"))).scalars():
            o.status = "assumida"
        for t in db.execute(select(Tarefa).join(Lead).where(Lead.empresa.like("Hoje %"))).scalars():
            t.status = "feita"


def test_descartar_exige_motivo(cliente):
    with sessao() as db:
        lead = Lead(empresa="Motivo Descarte Ltda")
        db.add(lead)
        db.flush()
        op = Oportunidade(lead_id=lead.id, temperatura="morna", classificacao="OBJEÇÃO", status="nova")
        db.add(op)
        db.flush()
        oid = op.id
    pagina = cliente.get("/oportunidades?busca=motivo descarte").text
    assert 'name="motivo" required' in pagina and "Já tem parceiro ou fornecedor" in pagina
    r = cliente.post(f"/oportunidades/{oid}/descartar", data={"csrf": csrf_de(pagina)})
    assert "Escolha o motivo do descarte" in r.text
    with sessao() as db:
        assert db.get(Oportunidade, oid).status == "nova"  # nada foi descartado
    cliente.post(f"/oportunidades/{oid}/descartar", data={"csrf": csrf_de(pagina), "motivo": "Já tem parceiro ou fornecedor"})
    with sessao() as db:
        op = db.get(Oportunidade, oid)
        assert (op.status, op.motivo) == ("descartada", "Já tem parceiro ou fornecedor")
        assert db.execute(select(Historico).where(Historico.lead_id == op.lead_id,
                                                  Historico.descricao.like("%(Já tem parceiro ou fornecedor)%"))).first()
    assert "Motivo:</b> Já tem parceiro ou fornecedor" in cliente.get(
        "/oportunidades?ver=descartadas&busca=motivo descarte").text
    cliente.post(f"/oportunidades/{oid}/reabrir", data={"csrf": csrf_de(pagina)})
    with sessao() as db:
        assert db.get(Oportunidade, oid).motivo == ""  # voltou para Novas sem o motivo antigo
        db.get(Oportunidade, oid).status = "descartada"


def test_lead_perdido_exige_motivo(cliente):
    with sessao() as db:
        lead = Lead(empresa="Perdido Sem Motivo Ltda", cidade="Recife", estado="PE", status="Interessado",
                    vendedor_id=_admin(db).id)
        db.add(lead)
        db.flush()
        lid = lead.id
    pagina = cliente.get(f"/leads/{lid}").text
    csrf = csrf_de(pagina)
    r = cliente.post(f"/leads/{lid}", data={"csrf": csrf, "status": "Perdido"})  # botão de status, sem motivo
    assert "escolha o motivo da perda" in r.text
    r = cliente.post(f"/api/leads/{lid}/status", json={"status": "Perdido"}, headers={"x-csrf-token": csrf})
    assert r.status_code == 400 and "motivo" in r.json()["erro"]
    r = cliente.post("/leads/acoes", data={"csrf": csrf, "acao": "status", "status": "Perdido", "ids": str(lid)})
    assert "escolha o motivo da perda" in r.text
    with sessao() as db:
        assert db.get(Lead, lid).status == "Interessado"
    cliente.post(f"/leads/{lid}", data={"csrf": csrf, "status": "Perdido", "motivo_perda": "Sem fit"})
    with sessao() as db:
        lead = db.get(Lead, lid)
        assert (lead.status, lead.motivo_perda) == ("Perdido", "Sem fit")
