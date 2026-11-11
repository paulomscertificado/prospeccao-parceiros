"""Empresas novas (pedido da Maria em 11/11/2026): depois da aprovação, o WhatsApp sai sozinho, sem o clique, pela
mesma fila automática (um por vez, com pausas e limites). Nas campanhas de parceiros o contato frio continua
esperando o clique de uma pessoa."""

from datetime import date, timedelta

from sqlalchemy import select

from app import campanhas, sdr
from app.banco import agora, gravar_config, sessao
from app.modelos import Campanha, Lead, Tarefa, Usuario


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _campanha(db, nome, tipo, status="ativa"):
    camp = Campanha(nome=nome, status=status, usuario_id=_admin(db).id, canais="whatsapp", tipo=tipo,
                    aprovado_em=agora() if status == "ativa" else None)
    db.add(camp)
    db.flush()
    return camp


def _toque(db, camp, nome, numero, dias):
    lead = Lead(empresa=nome, whatsapp=numero, status="Abordagem criada", vendedor_id=_admin(db).id)
    db.add(lead)
    db.flush()
    t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="whatsapp",
               data=date.today() + timedelta(days=dias), hora="00:01", status="pendente",
               mensagem="Olá! Tudo bem? Vi que a empresa abriu agora.")
    db.add(t)
    db.flush()
    return t


def _preparar(monkeypatch, enviados):
    from app.integracoes import whatsapp_leads

    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True})
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado",
                        lambda db, texto, u, lead=None, tarefa=None: enviados.append(lead.empresa))


def test_empresas_novas_aprovada_sai_sozinha_e_parceiros_espera_o_clique(cliente, monkeypatch):
    enviados = []
    _preparar(monkeypatch, enviados)
    with sessao() as db:
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        novas = _campanha(db, "Empresas novas automatico", "empresas_novas")
        parceiros = _campanha(db, "Parceiros frio automatico", "parceiros")
        aguardando = _campanha(db, "Empresas novas sem aprovar", "empresas_novas", status="aguardando_aprovacao")
        hoje = _toque(db, novas, "Nova Hoje Automatica", "(81) 98111-0001", 0)
        ontem = _toque(db, novas, "Nova Ontem Automatica", "(81) 98111-0002", -1)
        velha = _toque(db, novas, "Nova Atrasada Demais", "(81) 98111-0003", -3)
        _toque(db, parceiros, "Parceiro Frio Espera", "(81) 98111-0004", 0)
        _toque(db, aguardando, "Nova Sem Aprovacao", "(81) 98111-0005", 0)
        db.flush()
        campanhas.processar_fila_whatsapp(db, maximo=1000)
        assert {"Nova Hoje Automatica", "Nova Ontem Automatica"} <= set(enviados)
        assert "Parceiro Frio Espera" not in enviados  # parceiros: contato frio continua com o clique
        assert "Nova Atrasada Demais" not in enviados  # atraso grande não sai sozinho (evita rajada)
        assert "Nova Sem Aprovacao" not in enviados    # sem aprovação nada sai
        assert hoje.resultado == "Enviada sozinha (campanha de Empresas novas aprovada)"
        assert ontem.resultado == hoje.resultado and not velha.resultado
        db.rollback()


def test_fila_mostra_que_empresas_novas_sai_sozinha(cliente, monkeypatch):
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db, momento=None: True)
    with sessao() as db:
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        novas = _campanha(db, "Empresas novas na fila", "empresas_novas")
        parceiros = _campanha(db, "Parceiros na fila", "parceiros")
        _toque(db, novas, "Nova Fila Sai Sozinha", "(81) 98222-0001", 0)
        _toque(db, novas, "Nova Fila Amanha", "(81) 98222-0002", 1)
        _toque(db, novas, "Nova Fila Velha", "(81) 98222-0003", -4)
        _toque(db, parceiros, "Parceiro Fila Amanha", "(81) 98222-0004", 1)
        db.commit()
    pagina = cliente.get("/fila").text

    def linha(nome):
        return pagina.split(nome, 1)[1].split('class="linha-fila linha-prox"')[0]

    assert "Sai sozinho: campanha de Empresas novas aprovada" in linha("Nova Fila Sai Sozinha")
    assert "(sai sozinho)" in linha("Nova Fila Amanha")
    assert "não sai sozinho" in linha("Nova Fila Velha")
    assert "(vai esperar o seu clique)" in linha("Parceiro Fila Amanha")
    envios = cliente.get("/envios?aba=proximos").text
    assert "Sai sozinho: campanha de Empresas novas aprovada" in envios
    with sessao() as db:  # não deixa os toques na fila dos outros testes
        for t in db.execute(select(Tarefa).join(Campanha).where(Campanha.nome.in_(
                ["Empresas novas na fila", "Parceiros na fila"]))).scalars():
            t.status = "cancelada"
