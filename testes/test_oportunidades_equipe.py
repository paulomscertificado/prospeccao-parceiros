"""Oportunidades da equipe toda (pedido da Maria em 16/11/2026): ninguém "assume" a resposta. Todos veem as respostas
da AR, quem atendeu o cliente clica em "Marcar como atendido" (sem virar dono do lead), o aviso de resposta nova vai
para a equipe toda da AR e o descarte com o motivo "Já renovou" marca o certificado da Renovação como Renovado."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import renovacao, sdr
from app.banco import agora, sessao
from app.main import app
from app.modelos import Campanha, Certificado, Lead, Notificacao, Oportunidade, Tarefa, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de

SENHA = "senhaEquipe123"
BIA = "bia.equipe@teste.com.br"


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _bia(db) -> Usuario:
    bia = db.execute(select(Usuario).where(Usuario.email == BIA)).scalars().first()
    if not bia:
        bia = Usuario(nome="Bia Equipe", email=BIA, perfil="vendedor", senha_hash=resumir_senha(SENHA))
        db.add(bia)
        db.flush()
    return bia


def _usuario(db, email, nome, perfil, **extra) -> Usuario:
    u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
    if not u:
        u = Usuario(nome=nome, email=email, perfil=perfil, senha_hash=resumir_senha(SENHA), **extra)
        db.add(u)
        db.flush()
    return u


def _entrar(email) -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _op(db, empresa, vendedor_id, temperatura="quente", **extra) -> Oportunidade:
    lead = Lead(empresa=empresa, cidade="Recife", estado="PE", vendedor_id=vendedor_id, status="Interessado",
                automacao_pausada=True, **extra)
    db.add(lead)
    db.flush()
    op = Oportunidade(lead_id=lead.id, temperatura=temperatura, canal="whatsapp", status="nova",
                      classificacao="QUER SABER MAIS", resposta=f"Resposta de {empresa}")
    db.add(op)
    db.flush()
    return op


def _limpar(prefixo: str):
    """Não deixa cartões na aba Novas dos outros testes."""
    with sessao() as db:
        for op in db.execute(select(Oportunidade).join(Lead).where(Lead.empresa.like(f"{prefixo}%"),
                                                                   Oportunidade.status == "nova")).scalars():
            op.status = "descartada"


def test_a_equipe_toda_ve_e_atende_sem_virar_dona_do_lead(cliente):
    with sessao() as db:
        bia, admin = _bia(db), _admin(db)
        dela = _op(db, "Equipe Dela Ltda", bia.id, temperatura="morna", whatsapp="81347720001")
        alheia = _op(db, "Equipe Alheia Ltda", admin.id, whatsapp="81347720002", responsavel="Guilherme Souza")
        outra = _op(db, "Equipe Outra Ltda", admin.id, temperatura="morna")
        db.add(Tarefa(tipo="prospeccao", lead_id=alheia.lead_id, canal="whatsapp", status="pendente",
                      data=date.today() + timedelta(days=1), mensagem="toque que ainda não saiu"))
        ids = {"alheia": alheia.id, "outra": outra.id, "lead_alheia": alheia.lead_id, "lead_dela": dela.lead_id,
               "bia": bia.id, "admin": admin.id}
    try:
        c = _entrar(BIA)
        pagina = c.get("/oportunidades?busca=equipe").text
        # a vendedora vê as respostas dos leads de outras pessoas (antes via só as dos leads dela)
        assert "Equipe Dela Ltda" in pagina and "Equipe Alheia Ltda" in pagina and "Equipe Outra Ltda" in pagina
        assert "ASSUMIR LEAD" not in pagina and "MARCAR COMO ATENDIDO" in pagina
        assert "Esperando atendimento" in pagina and "responder até" in pagina
        assert "Responsável pelo lead" not in pagina and "Contato do cliente" in pagina and "Guilherme Souza" in pagina
        # a ficha do lead segue o alcance de leads.ver: o nome só vira link para quem pode abrir a ficha
        assert f'href="/leads/{ids["lead_dela"]}"' in pagina and f'href="/leads/{ids["lead_alheia"]}"' not in pagina
        assert "Todas as respostas" not in pagina  # continua só para administrador e gestor
        # o Painel também mostra a resposta quente de outra pessoa, com o mesmo botão
        painel = c.get("/").text
        trecho = painel[painel.index("Quem precisa de mim hoje"):]
        assert "Equipe Alheia Ltda" in trecho and "Marcar como atendido" in trecho and "esperando atendimento" in trecho

        token = csrf_de(pagina)
        r = c.post(f"/oportunidades/{ids['alheia']}/atendida",
                   data={"csrf": token, "voltar_para": "/oportunidades?busca=equipe"})
        assert "marcada como atendida por você" in r.text
        with sessao() as db:
            op, lead = db.get(Oportunidade, ids["alheia"]), db.get(Lead, ids["lead_alheia"])
            assert (op.status, op.responsavel_id) == ("assumida", ids["bia"]) and op.assumida_em
            assert lead.vendedor_id == ids["admin"] and lead.humano_id is None  # ninguém virou dono do lead
            assert lead.status == "Humano assumiu" and lead.automacao_pausada  # a IA não mexe mais na conversa
            assert db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id, Tarefa.status == "pendente")).first() is None
        assert "Equipe Alheia Ltda" not in c.get("/oportunidades?busca=equipe").text  # saiu das Novas
        atendidas = c.get("/oportunidades?ver=atendidas&busca=equipe").text
        assert "✅ Atendidas" in atendidas and "Equipe Alheia Ltda" in atendidas and "Atendida por Bia Equipe" in atendidas
        assert "Equipe Alheia Ltda" in c.get("/oportunidades?ver=assumidas&busca=equipe").text  # endereço antigo
        # clicou de novo (ou outra pessoa clicou ao mesmo tempo): avisa quem atendeu, sem mexer
        assert "Bia Equipe já tinha atendido" in c.post(f"/oportunidades/{ids['alheia']}/atendida",
                                                         data={"csrf": token}).text
        # descartar a resposta de outra pessoa da equipe também pode
        c.post(f"/oportunidades/{ids['outra']}/descartar", data={"csrf": token, "motivo": "Fora do perfil"})
        with sessao() as db:
            assert db.get(Oportunidade, ids["outra"]).status == "descartada"
        assert c.post("/oportunidades/999999/atendida", data={"csrf": token}).status_code == 404
    finally:
        _limpar("Equipe ")


def test_descartar_com_ja_renovou_marca_o_certificado_como_renovado(cliente):
    with sessao() as db:
        admin = _admin(db)
        camp = Campanha(nome="Renovação teste já renovou", tipo="renovacao", status="ativa", usuario_id=admin.id,
                        canais="whatsapp", aprovado_em=agora())
        db.add(camp)
        db.flush()
        um = _op(db, "RENOVOU UM LTDA", admin.id, whatsapp="81347720011", origem=renovacao.ORIGEM_LEAD)
        dois = _op(db, "RENOVOU DOIS LTDA", admin.id, whatsapp="81347720012", origem=renovacao.ORIGEM_LEAD)
        certs = []
        for op, protocolo, dias in ((um, "9700001", 12), (dois, "9700002", 12), (dois, "9700003", 40)):
            cert = Certificado(origem="planilha", protocolo=protocolo, cliente_nome=f"CLIENTE {protocolo} LTDA",
                               tipo="e-CNPJ A1", data_vencimento=date.today() + timedelta(days=dias), status="Ativo",
                               campanha_id=camp.id, lead_id=op.lead_id)
            db.add(cert)
            db.flush()
            certs.append(cert.id)
        aviso = Tarefa(tipo="prospeccao", lead_id=um.lead_id, campanha_id=camp.id, certificado_id=certs[0],
                       canal="whatsapp", data=date.today() + timedelta(days=5), hora="10:00", status="pendente",
                       angulo="renov_reforco", mensagem="Faltam poucos dias para o vencimento.")
        db.add(aviso)
        db.flush()
        ids = {"um": um.id, "dois": dois.id, "aviso": aviso.id}
    try:
        pagina = cliente.get("/oportunidades?busca=renovou").text
        assert "<option>Já renovou</option>" in pagina
        r = cliente.post(f"/oportunidades/{ids['um']}/descartar", data={"csrf": csrf_de(pagina), "motivo": "Já renovou"})
        assert "CLIENTE 9700001 LTDA ficou como Renovado na tela Renovação" in r.text and "1 aviso(s)" in r.text
        with sessao() as db:
            assert db.get(Oportunidade, ids["um"]).motivo == "Já renovou"
            assert db.get(Certificado, certs[0]).status == "Renovado"
            assert db.get(Tarefa, ids["aviso"]).status == "cancelada"  # o aviso que faltava não sai mais
        # contato com 2 certificados ativos: a pessoa escolhe na tela Renovação qual foi renovado
        r = cliente.post(f"/oportunidades/{ids['dois']}/descartar", data={"csrf": csrf_de(pagina), "motivo": "Já renovou"})
        assert "tem 2 certificados ativos na tela Renovação" in r.text
        with sessao() as db:
            assert {db.get(Certificado, i).status for i in certs[1:]} == {"Ativo"}
        # voltar para Novas avisa que o certificado continua como Renovado
        r = cliente.post(f"/oportunidades/{ids['um']}/reabrir", data={"csrf": csrf_de(pagina)})
        assert "voltou para Novas" in r.text and "continua assim" in r.text
    finally:
        _limpar("RENOVOU ")


def test_resposta_nova_avisa_a_equipe_toda_da_ar(cliente, monkeypatch):
    from app.integracoes import email_smtp

    emails = []
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, *args, **kwargs: emails.append(para))
    with sessao() as db:
        ids_ar = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}
        bia = _bia(db)
        dono = _usuario(db, "dono.aviso@teste.com.br", "Dono Aviso", "vendedor")
        chefe_ms = _usuario(db, "chefe.aviso@teste.com.br", "Chefe MS Aviso", "admin")
        certy = _usuario(db, "certy.aviso@grupocerty.com.br", "Certy Aviso", "admin", empresa_nome="Grupo Certy")
        portal = _usuario(db, "portal.aviso@teste.com.br", "Parceiro Aviso", "parceiro")
        master = db.execute(select(Usuario).where(Usuario.master.is_(True))).scalars().first()
        assert certy.tenant_id == ids_ar["grupo-certy"] and bia.tenant_id == dono.tenant_id == ids_ar["ms"]
        lead = Lead(empresa="Aviso Equipe Ltda", vendedor_id=dono.id, whatsapp="81347720021")
        db.add(lead)
        db.flush()
        analise = sdr.processar_resposta(db, lead, "Tenho interesse, pode me ligar amanhã?", "whatsapp")
        link = f"/oportunidades#op-{analise['oportunidade_id']}"
        avisados = set(db.execute(select(Notificacao.usuario_id).where(Notificacao.link == link)).scalars())
        # a equipe toda da AR recebe no sininho (antes só o dono do lead)
        assert {dono.id, bia.id, chefe_ms.id, master.id} <= avisados
        assert certy.id not in avisados and portal.id not in avisados  # outra AR e parceiro (portal), não
        assert emails == [dono.email]  # o e-mail continua só para quem cuida do lead
        # alguém da equipe atendeu: o aviso sai do sininho de todos
        sdr.marcar_atendida(db, lead, bia)
        db.flush()
        assert not db.execute(select(Notificacao).where(Notificacao.link == link, Notificacao.lida.is_(False))).first()
        # lead sem dono de outra AR: avisa só os administradores de lá (antes iam os de todas as ARs)
        sem_dono = Lead(empresa="Aviso Certy Sem Dono Ltda", tenant_id=ids_ar["grupo-certy"])
        db.add(sem_dono)
        db.flush()
        chefes = {u.id for u in sdr.destinatarios(db, sem_dono)}
        assert certy.id in chefes and chefe_ms.id not in chefes and master.id not in chefes
        # e um lead sem dono da MS avisa os administradores da MS (com o Admin Master)
        assert {chefe_ms.id, master.id} <= {u.id for u in sdr.destinatarios(db, Lead(empresa="x", tenant_id=ids_ar["ms"]))}
        db.rollback()
