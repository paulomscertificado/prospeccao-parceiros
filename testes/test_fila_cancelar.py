"""Minha fila (nov/2026): botão Cancelar em cada envio e "Cancelar os N envios mostrados" (com filtro escolhido)."""

from datetime import date, timedelta

from sqlalchemy import select

from app.banco import agora, sessao
from app.modelos import Campanha, Historico, Lead, LogAuditoria, Tarefa, Usuario


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _csrf(html: str) -> str:
    return html.split('name="csrf" content="')[1].split('"')[0]


def _preparar(nome_camp, empresas):
    """Campanha ativa com 1 toque pendente por empresa (e um 2º toque para a primeira). Devolve os ids."""
    with sessao() as db:
        admin = _admin(db)
        camp = Campanha(nome=nome_camp, status="ativa", aprovado_em=agora(), usuario_id=admin.id, canais="email")
        db.add(camp)
        db.flush()
        ids = []
        for i, nome in enumerate(empresas):
            lead = Lead(empresa=nome, email=f"c{i}@{nome.split()[0].lower()}-cancelar.com.br", status="Abordagem criada",
                        vendedor_id=admin.id)
            db.add(lead)
            db.flush()
            for dias in ((0, 3) if i == 0 else (0,)):
                t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="email", status="pendente",
                           data=date.today() + timedelta(days=dias), hora="23:59", mensagem="Oi", assunto="Parceria")
                db.add(t)
                db.flush()
                ids.append((lead.id, t.id))
        return camp.id, ids


def test_cancelar_um_envio(cliente):
    camp_id, ids = _preparar("Cancelar Um Teste", ["Cancela Primeira Ltda"])
    (lead_id, t1), (_, t2) = ids
    pagina = cliente.get("/fila").text
    assert f'action="/fila/cancelar/{t1}"' in pagina and "btn-perigo" in pagina
    r = cliente.post(f"/fila/cancelar/{t1}", data={"csrf": _csrf(pagina), "voltar_para": "/fila"})
    assert "cancelado: ele não vai mais sair" in r.text
    with sessao() as db:
        assert db.get(Tarefa, t1).status == "cancelada" and "Cancelado por" in db.get(Tarefa, t1).resultado
        assert db.get(Tarefa, t2).status == "pendente"  # só o toque escolhido
        assert db.get(Lead, lead_id).status == "Abordagem criada"  # ainda tem um toque em aberto
        assert db.execute(select(LogAuditoria).where(LogAuditoria.acao == "cancelou_envio",
                                                     LogAuditoria.entidade_id == t1)).first()
        assert db.execute(select(Historico).where(Historico.lead_id == lead_id,
                                                  Historico.descricao.like("%cancelado por%"))).first()
    # cancelar de novo: avisa que já foi; e o último toque devolve a empresa para "Novo"
    r = cliente.post(f"/fila/cancelar/{t1}", data={"csrf": _csrf(pagina), "voltar_para": "/fila"})
    assert "já saiu ou já foi cancelado" in r.text
    cliente.post(f"/fila/cancelar/{t2}", data={"csrf": _csrf(pagina), "voltar_para": "/fila"})
    with sessao() as db:
        assert db.get(Lead, lead_id).status == "Novo"  # sem toque em aberto: pode entrar em outra campanha
    assert cliente.post("/fila/cancelar/999999", data={"csrf": _csrf(pagina)}).status_code == 404


def test_cancelar_os_envios_mostrados_so_com_filtro(cliente):
    camp_id, ids = _preparar("Cancelar Varios Teste", ["Varios Um Ltda", "Varios Dois Ltda", "Varios Tres Ltda"])
    sem_filtro = cliente.get("/fila").text
    assert "envios mostrados" not in sem_filtro  # sem filtro não aparece (evita cancelar tudo sem querer)
    filtrada = cliente.get(f"/fila?campanha={camp_id}&periodo=hoje").text
    assert "Cancelar os 3 envios mostrados" in filtrada
    with sessao() as db:
        hoje_ids = [t.id for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp_id,
                                                                  Tarefa.data == date.today())).scalars()]
    r = cliente.post("/fila/cancelar-varios", data={"csrf": _csrf(filtrada), "ids": ",".join(map(str, hoje_ids)),
                                                    "voltar_para": f"/fila?campanha={camp_id}"})
    assert "3 envio(s) cancelado(s)" in r.text
    with sessao() as db:
        status = {t.data: t.status for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp_id)).scalars()}
        assert status[date.today()] == "cancelada" and status[date.today() + timedelta(days=3)] == "pendente"
    assert "Nenhum envio para cancelar" in cliente.post(
        "/fila/cancelar-varios", data={"csrf": _csrf(filtrada), "ids": ",".join(map(str, hoje_ids))}).text
    with sessao() as db:  # não deixa toques na fila dos outros testes
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp_id)).scalars():
            t.status = "cancelada"
