"""Pedido da Maria em 17/11/2026: a fila automática nunca manda dois e-mails para a mesma empresa em menos de 20 h,
como já fazia com o WhatsApp (campanhas.HORAS_MINIMAS_FILA_AUTOMATICA). Caso real: com o intervalo mínimo em 0 nas
Configurações, 8 empresas de Empresas novas receberam 2 e-mails no mesmo dia em 16-17/11 (algumas com 3 minutos de
diferença). Cada canal tem o seu controle, e o envio manual segue a configuração."""

from datetime import date, timedelta

from sqlalchemy import delete, select

from app import campanhas
from app.banco import agora, gravar_config, ler_config, sessao
from app.modelos import Campanha, Lead, Mensagem, Tarefa, Usuario
from app.rotas import fila

NOME = "E-mails intervalo minimo"
CHAVES = ("enviar_email_automatico", "horas_entre_contatos", "horas_entre_contatos_email", "limite_hora_email",
          "limite_diario_email", "limite_diario_campanha")
AVISO = "a empresa recebeu e-mail há menos de 20 h"


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def test_fila_nunca_manda_dois_emails_para_a_mesma_empresa_em_menos_de_20h(cliente, monkeypatch):
    from app.integracoes import email_smtp

    enviados = []
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db, momento=None: True)
    monkeypatch.setattr(campanhas, "conta_do_toque", lambda db, t, u=None: None)
    monkeypatch.setattr(campanhas, "_chave_pausa", lambda conta: "fila_email_pausada_ate:teste")
    monkeypatch.setattr(campanhas, "_enviar_email_da_tarefa",
                        lambda db, t, u, r, conta=None, registrar_erro_da_caixa=True: enviados.append(t.id) or "")
    hoje = date.today()
    with sessao() as db:
        antes = {c: ler_config(db, c) for c in CHAVES}
        gravar_config(db, "enviar_email_automatico", "1")
        gravar_config(db, "horas_entre_contatos", "0")
        gravar_config(db, "horas_entre_contatos_email", "0")  # controle de frequência desligado na tela, como na nuvem
        for chave in ("limite_hora_email", "limite_diario_email", "limite_diario_campanha"):
            gravar_config(db, chave, "100000")  # os limites do canal não entram neste teste
        admin = _admin(db)
        camp = Campanha(nome=NOME, status="ativa", usuario_id=admin.id, canais="email", aprovado_em=agora())
        db.add(camp)
        db.flush()

        def toque(nome, hora, lead=None):
            if lead is None:
                lead = Lead(empresa=nome, email=f"contato@{nome.lower().replace(' ', '-')}-intervalo.com.br",
                            status="Contatado", vendedor_id=admin.id)
                db.add(lead)
                db.flush()
            t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="email", data=hoje, hora=hora,
                       status="pendente", assunto="Parceria", mensagem="Olá!")
            db.add(t)
            db.flush()
            return t

        recente = toque("Email Recebeu Agora", "00:01")
        antiga = toque("Email Recebeu Ontem", "00:01")
        dois_hoje = toque("Email Dois Hoje", "00:01")
        segundo = toque("", "00:02", lead=dois_hoje.lead)
        db.add_all([Mensagem(lead_id=recente.lead_id, canal="email", direcao="saida", status="enviada",
                             angulo="apresentacao", corpo="1º toque", criado_em=agora() - timedelta(minutes=10)),
                    Mensagem(lead_id=antiga.lead_id, canal="email", direcao="saida", status="enviada",
                             angulo="apresentacao", corpo="1º toque", criado_em=agora() - timedelta(hours=21)),
                    # um WhatsApp de agora há pouco não segura o e-mail: cada canal tem o seu controle
                    Mensagem(lead_id=antiga.lead_id, canal="whatsapp", direcao="saida", status="enviada",
                             angulo="apresentacao", corpo="1º toque", criado_em=agora() - timedelta(minutes=5))])
        db.flush()
        leads = [recente.lead_id, antiga.lead_id, dois_hoje.lead_id]
        assert campanhas.leads_com_contato_recente(db, leads, "email") == {recente.lead_id}
        assert campanhas.leads_com_whatsapp_recente(db, leads) == {antiga.lead_id}
        _, motivo = fila._situacao(recente, hoje, True, set(), True, True, recentes_email={recente.lead_id})
        assert AVISO in motivo

        campanhas.processar_fila(db, maximo=1000)
        assert antiga.id in enviados and recente.id not in enviados  # recebeu e-mail há 10 min: espera as 20 h
        assert dois_hoje.id in enviados and segundo.id not in enviados  # o 2º e-mail do dia fica para depois
        antiga.status = dois_hoje.status = "feita"
        db.commit()
    try:
        pagina = cliente.get("/fila").text
        linha = pagina.split("Email Recebeu Agora", 1)[1].split('class="linha-fila')[0]
        assert AVISO in linha  # a Minha fila explica por que o e-mail ainda não saiu
        envios = cliente.get("/envios?aba=proximos")
        assert envios.status_code == 200 and AVISO in envios.text
        regras = cliente.get("/envios?aba=regras").text  # a tela mostra o intervalo da fila, não o 0 de Configurações
        assert "1 WhatsApp a cada 20 h e 1 e-mail a cada 20 h" in regras
    finally:
        with sessao() as db:
            for t in db.execute(select(Tarefa).join(Campanha).where(Campanha.nome == NOME)).scalars():
                t.status = "cancelada"
            db.execute(delete(Mensagem).where(Mensagem.lead_id.in_(leads), Mensagem.corpo == "1º toque"))
            for chave, valor in antes.items():
                gravar_config(db, chave, valor)
