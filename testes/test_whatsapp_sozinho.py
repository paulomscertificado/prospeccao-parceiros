"""WhatsApp automático por campanha (pedido da Maria em 12/11/2026, Campanha 3): o admin liga numa campanha de
parceiros e, depois da aprovação, o WhatsApp sai sozinho também para contato frio, pela mesma fila automática
(um por vez, com pausas e limites). Sem a opção, o contato frio continua esperando o clique."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import campanhas, sdr
from app.banco import agora, gravar_config, sessao
from app.main import app
from app.modelos import Campanha, Lead, Tarefa, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _campanha(db, nome, sozinho, status="ativa", tipo="parceiros", dono=None):
    camp = Campanha(nome=nome, status=status, usuario_id=(dono or _admin(db)).id, canais="whatsapp", tipo=tipo,
                    whatsapp_sozinho=sozinho, aprovado_em=agora() if status == "ativa" else None)
    db.add(camp)
    db.flush()
    return camp


def _toque(db, camp, nome, numero, dias):
    lead = Lead(empresa=nome, whatsapp=numero, status="Abordagem criada", vendedor_id=_admin(db).id)
    db.add(lead)
    db.flush()
    t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="whatsapp",
               data=date.today() + timedelta(days=dias), hora="00:01", status="pendente",
               mensagem="Olá! Tudo bem? Sou da MS Certificados.")
    db.add(t)
    db.flush()
    return t


def test_parceiros_com_whatsapp_sozinho_sai_sem_clique(cliente, monkeypatch):
    from app.integracoes import whatsapp_leads

    enviados = []
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True})
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado",
                        lambda db, texto, u, lead=None, tarefa=None: enviados.append(lead.empresa))
    with sessao() as db:
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        ligada = _campanha(db, "Parceiros com automatico", True)
        desligada = _campanha(db, "Parceiros sem automatico", False)
        sem_aprovar = _campanha(db, "Parceiros automatico sem aprovar", True, status="aguardando_aprovacao")
        frio = _toque(db, ligada, "Parceiro Frio Automatico", "(81) 98333-0001", 0)
        atrasado = _toque(db, ligada, "Parceiro Atrasado 2 Dias", "(81) 98333-0002", -2)
        velho = _toque(db, ligada, "Parceiro Atrasado Demais", "(81) 98333-0003", -3)
        _toque(db, desligada, "Parceiro Frio Clique", "(81) 98333-0004", 0)
        _toque(db, sem_aprovar, "Parceiro Sem Aprovacao", "(81) 98333-0005", 0)
        db.flush()
        assert campanhas.campanhas_que_saem_sozinhas(db).get(ligada.id) == "parceiros"
        campanhas.processar_fila_whatsapp(db, maximo=1000)
        assert {"Parceiro Frio Automatico", "Parceiro Atrasado 2 Dias"} <= set(enviados)
        assert "Parceiro Frio Clique" not in enviados     # sem a opção: contato frio espera o clique
        assert "Parceiro Atrasado Demais" not in enviados  # atraso grande não sai sozinho (evita rajada)
        assert "Parceiro Sem Aprovacao" not in enviados    # sem aprovação nada sai
        assert frio.resultado == "Enviada sozinha (campanha aprovada com WhatsApp automático)"
        assert atrasado.resultado == frio.resultado and not velho.resultado
        db.rollback()


def test_fila_mostra_que_a_campanha_sai_sozinha(cliente, monkeypatch):
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db, momento=None: True)
    with sessao() as db:
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        ligada = _campanha(db, "Parceiros automatico na fila", True)
        _toque(db, ligada, "Parceiro Fila Sai Sozinho", "(81) 98444-0001", 0)
        _toque(db, ligada, "Parceiro Fila Amanha Sozinho", "(81) 98444-0002", 1)
        db.commit()
    pagina = cliente.get("/fila").text

    def linha(nome):
        return pagina.split(nome, 1)[1].split('class="linha-fila linha-prox"')[0]

    assert "Sai sozinho: campanha aprovada com WhatsApp automático" in linha("Parceiro Fila Sai Sozinho")
    assert "(sai sozinho)" in linha("Parceiro Fila Amanha Sozinho")
    with sessao() as db:  # não deixa os toques na fila dos outros testes
        for t in db.execute(select(Tarefa).join(Campanha).where(Campanha.nome == "Parceiros automatico na fila")).scalars():
            t.status = "cancelada"


def test_so_o_admin_liga_e_desliga(cliente):
    with sessao() as db:
        vendedor = db.execute(select(Usuario).where(Usuario.email == "vend.sozinho@teste.com.br")).scalars().first()
        if not vendedor:
            vendedor = Usuario(nome="Vend Sozinho", email="vend.sozinho@teste.com.br", perfil="vendedor",
                               senha_hash=resumir_senha(SENHA))
            db.add(vendedor)
            db.flush()
        da_admin = _campanha(db, "Parceiros chave admin", False).id
        do_vendedor = _campanha(db, "Parceiros chave vendedor", False, dono=vendedor).id
        novas = _campanha(db, "Empresas novas chave", False, tipo="empresas_novas").id
        db.commit()

    pagina = cliente.get(f"/campanhas/{da_admin}").text
    assert 'id="whatsapp-sozinho"' in pagina and "WhatsApp sai sozinho depois da aprovação" in pagina
    r = cliente.post(f"/campanhas/{da_admin}/whatsapp-sozinho", data={"csrf": csrf_de(pagina), "ligar": "1"})
    assert "WhatsApp automático ligado: as mensagens desta campanha saem sozinhas" in r.text
    with sessao() as db:
        assert db.get(Campanha, da_admin).whatsapp_sozinho is True
    pagina = cliente.get(f"/campanhas/{da_admin}").text
    assert '<span class="selo selo-ok">ligado</span>' in pagina and ">Desligar</button>" in pagina
    cliente.post(f"/campanhas/{da_admin}/whatsapp-sozinho", data={"csrf": csrf_de(pagina), "ligar": "0"})
    cliente.post(f"/campanhas/{novas}/whatsapp-sozinho", data={"csrf": csrf_de(pagina), "ligar": "1"})
    with sessao() as db:
        assert db.get(Campanha, da_admin).whatsapp_sozinho is False
        assert db.get(Campanha, novas).whatsapp_sozinho is False  # Empresas novas já sai sozinha: não muda

    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": "vend.sozinho@teste.com.br", "senha": SENHA})
    pagina = c.get(f"/campanhas/{do_vendedor}").text
    assert 'id="whatsapp-sozinho"' not in pagina  # vendedor não vê a opção
    c.post(f"/campanhas/{do_vendedor}/whatsapp-sozinho", data={"csrf": csrf_de(pagina), "ligar": "1"})
    with sessao() as db:
        assert db.get(Campanha, do_vendedor).whatsapp_sozinho is False
        for cid in (da_admin, do_vendedor, novas):
            db.get(Campanha, cid).status = "cancelada"
