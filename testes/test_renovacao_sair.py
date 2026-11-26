"""SAIR só daquela renovação (pedido da Maria em 26/11/2026, "SAIR só do certificado": "você para de mandar os avisos
referente àquela determinada empresa, mas não deixe de avisar das novas que vem para frente"). O SAIR em resposta a um
aviso de renovação para os avisos dos certificados daquele aviso; os certificados que vencem depois continuam recebendo
aviso. Qualquer resposta para só os avisos do certificado de que o cliente já foi avisado."""

import json
from datetime import date, timedelta

from sqlalchemy import select

from app import renovacao, sdr
from app.banco import agora, gravar_config, sessao
from app.leads_servico import cancelar_tarefas_de_prospeccao, limpar_campos
from app.modelos import Campanha, Certificado, ComandoWhatsApp, Historico, Lead, Mensagem, Tarefa, Usuario


def _cliente(db, empresa: str, telefone: str):
    """Um cliente com duas renovações: a do certificado que vence em 10 dias (o 1º aviso já saiu e o lembrete está
    marcado) e a de um certificado que vence em 70 dias (outra campanha, nenhum aviso saiu ainda)."""
    admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
    lead = Lead(empresa=empresa, whatsapp=telefone, status="Aguardando resposta", vendedor_id=admin.id,
                origem=renovacao.ORIGEM_LEAD)
    limpar_campos(lead)
    db.add(lead)
    db.flush()

    def renovacao_de(dias: int, nome: str, enviado: bool):
        camp = Campanha(nome=f"Renovação {nome}", tipo="renovacao", status="ativa", usuario_id=admin.id,
                        canais="whatsapp", aprovado_em=agora())
        db.add(camp)
        db.flush()
        cert = Certificado(origem="planilha", protocolo=f"SAIR{lead.id}{dias}", cliente_nome=nome,
                           tipo="e-CNPJ A1 12 meses", data_vencimento=date.today() + timedelta(days=dias),
                           status="Ativo", campanha_id=camp.id, lead_id=lead.id, whatsapp=telefone)
        db.add(cert)
        db.flush()
        tarefas = [Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, certificado_id=cert.id,
                          canal="whatsapp", data=date.today() + timedelta(days=d), hora="10:17", status=status,
                          angulo=angulo, mensagem="Olá! Aviso de vencimento.")
                   for angulo, d, status in (("renov_aviso", 0, "feita" if enviado else "pendente"),
                                             ("renov_lembrete", 4, "pendente"))]
        db.add_all(tarefas)
        db.flush()
        if enviado:
            db.add(Mensagem(lead_id=lead.id, tarefa_id=tarefas[0].id, campanha_id=camp.id, canal="whatsapp",
                            direcao="saida", angulo="renov_aviso", corpo="Olá! Aviso de vencimento.",
                            status="enviada", modo="whatsapp-leads"))
            db.flush()
        return cert, tarefas

    return lead, renovacao_de(10, "EMPRESA AVISADA LTDA", True), renovacao_de(70, "EMPRESA NOVA LTDA", False)


def _encerrar(db, lead_id: int):
    """Nada deste teste sai nos outros testes."""
    for t in db.execute(select(Tarefa).where(Tarefa.lead_id == lead_id, Tarefa.status == "pendente")).scalars():
        t.status = "cancelada"
    for camp in db.execute(select(Campanha).where(Campanha.id.in_(select(Tarefa.campanha_id).where(
            Tarefa.lead_id == lead_id)))).scalars():
        camp.status = "cancelada"


def test_sair_no_whatsapp_de_um_aviso_para_so_aquela_renovacao(cliente):
    telefone = "5581988550101"
    with sessao() as db:
        lead, (cert_a, tarefas_a), (cert_b, tarefas_b) = _cliente(db, "CLIENTE SAIR QR", "(81) 98855-0101")
        lead_id, cert_a_id, cert_b_id = lead.id, cert_a.id, cert_b.id
        lembrete_a, ids_b = tarefas_a[1].id, [t.id for t in tarefas_b]
    # o WhatsApp Leads bloqueia o número no SAIR e manda a mensagem; ele fica na lista de bloqueados até o pedido de
    # desbloqueio ser feito: a mesma resposta chega mais de uma vez
    novidades = {"bloqueados": [telefone],
                 "recebidas": [{"telefone": telefone, "texto": "SAIR", "conexao": "principal"}]}
    for _ in range(2):
        with sessao() as db:
            sdr.aplicar_novidades_whatsapp(db, novidades)
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        assert not lead.opt_out  # não saiu de tudo
        assert db.get(Certificado, cert_a_id).status == "Avisos cancelados"
        assert db.get(Tarefa, lembrete_a).status == "cancelada"  # os avisos daquela renovação param
        assert db.get(Certificado, cert_b_id).status == "Ativo"
        assert [db.get(Tarefa, i).status for i in ids_b] == ["pendente", "pendente"]  # o certificado novo continua
        assert sdr.recebe_automatico(lead, db.get(Tarefa, ids_b[0]))  # e sai na hora dele
        pedidos = [c for c in db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.acao == "desbloquear_contato"))
                   .scalars() if json.loads(c.dados)["telefone"] == telefone]
        assert len(pedidos) == 1  # o WhatsApp Leads tira o bloqueio (um pedido só)
        anotacoes = db.execute(select(Historico.id).where(
            Historico.lead_id == lead_id, Historico.descricao.like("Pediu SAIR do aviso de renovação%"))).all()
        assert len(anotacoes) == 1
        _encerrar(db, lead_id)


def test_sair_fora_de_um_aviso_de_renovacao_vale_para_tudo(cliente):
    """O SAIR que não é resposta a um aviso de renovação (ex.: a uma mensagem de prospecção) continua parando tudo."""
    with sessao() as db:
        lead, _, _ = _cliente(db, "CLIENTE SAIR PROSPECCAO", "(81) 98855-0103")
        db.add(Mensagem(lead_id=lead.id, canal="whatsapp", direcao="saida", angulo="apresentacao",
                        corpo="Olá! Somos parceiros...", status="enviada", modo="whatsapp-leads",
                        criado_em=agora() + timedelta(minutes=1)))
        lead_id = lead.id
    with sessao() as db:
        sdr.aplicar_novidades_whatsapp(db, {"bloqueados": ["5581988550103"]})
    with sessao() as db:
        assert db.get(Lead, lead_id).opt_out
        assert not db.execute(select(Tarefa).where(Tarefa.lead_id == lead_id, Tarefa.status == "pendente")).first()
        _encerrar(db, lead_id)


def test_resposta_ao_aviso_para_so_os_avisos_daquele_certificado(cliente):
    with sessao() as db:
        lead, (_, tarefas_a), (_, tarefas_b) = _cliente(db, "CLIENTE RESPONDEU", "(81) 98855-0102")
        sdr.processar_resposta(db, lead, "Quanto fica para renovar?", "whatsapp")
        assert tarefas_a[1].status == "cancelada"  # o certificado de que ele foi avisado: os avisos param
        assert [t.status for t in tarefas_b] == ["pendente", "pendente"]  # o certificado novo: continua
        cancelar_tarefas_de_prospeccao(db, lead.id, "teste", tudo=True)  # SAIR para tudo: cancela todos
        assert {t.status for t in tarefas_b} == {"cancelada"}
        db.rollback()


def test_frase_do_sair_diz_que_vale_so_para_esta_renovacao(cliente):
    assert renovacao.FRASE_DO_SAIR in renovacao.MENSAGENS_PADRAO["renov_aviso"]["whatsapp"]
    with sessao() as db:  # o texto salvo de uma marca, com a frase antiga: vira a de agora
        gravar_config(db, "renov_mensagens", json.dumps(
            {"renov_aviso": {"whatsapp": "Olá! Texto da marca.\r\n\r\n" + renovacao.FRASE_DO_SAIR_ANTIGA}}))
        texto = renovacao.mensagens(db)["renov_aviso"]["whatsapp"]
        assert renovacao.FRASE_DO_SAIR in texto and renovacao.FRASE_DO_SAIR_ANTIGA not in texto
        assert renovacao.linha_do_sair(db) == renovacao.FRASE_DO_SAIR  # vai também no 1º contato de quem entra tarde
        db.rollback()
