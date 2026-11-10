"""Revisão geral (10/11/2026): filas que não travam, limite por campanha, horário à mão na aprovação e proteção dos
créditos da CNPJá quando a busca diária dá erro."""

from datetime import date, timedelta

from sqlalchemy import select

from app import campanhas, config, empresas_novas, sdr
from app.banco import agora, gravar_config, sessao
from app.modelos import Campanha, Lead, Mensagem, Tarefa, Usuario


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _campanha(db, nome, status="ativa"):
    camp = Campanha(nome=nome, status=status, usuario_id=_admin(db).id, canais="whatsapp,email",
                    aprovado_em=agora() if status == "ativa" else None)
    db.add(camp)
    db.flush()
    return camp


def test_campanha_no_limite_nao_trava_as_outras(cliente, monkeypatch):
    """Antes: uma campanha no limite do dia dava "break" e os e-mails de TODAS as outras paravam."""
    from app.integracoes import email_smtp

    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    enviados = []
    monkeypatch.setattr(campanhas, "conta_do_toque", lambda db, t, u=None: None)
    monkeypatch.setattr(campanhas, "_enviar_email_da_tarefa",
                        lambda db, t, u, r, conta=None, registrar_erro_da_caixa=True: enviados.append(t.lead.empresa) or "")
    monkeypatch.setattr(campanhas, "_chave_pausa", lambda conta: "fila_email_pausada_ate:teste")
    with sessao() as db:
        gravar_config(db, "enviar_email_automatico", "1")
        gravar_config(db, "limite_diario_campanha", "1")
        cheia, outra = _campanha(db, "Cheia hoje"), _campanha(db, "Outra campanha")
        ontem = date.today() - timedelta(days=1)
        for i in range(3):
            lead = Lead(empresa=f"Cheia {i}", email=f"c{i}@cheia-limite.com.br", status="Contatado")
            db.add(lead)
            db.flush()
            db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=cheia.id, canal="email", data=ontem,
                          hora="08:01", status="pendente", mensagem="Olá"))
        livre = Lead(empresa="Da outra campanha", email="x@outra-limite.com.br", status="Contatado")
        db.add(livre)
        db.flush()
        db.add(Tarefa(tipo="prospeccao", lead_id=livre.id, campanha_id=outra.id, canal="email", data=ontem,
                      hora="09:01", status="pendente", mensagem="Olá"))
        db.add(Mensagem(lead_id=None, canal="email", campanha_id=cheia.id, direcao="saida", status="enviada",
                        corpo="já saiu hoje"))
        db.flush()
        campanhas.processar_fila(db, maximo=1000)
        assert "Da outra campanha" in enviados  # a outra campanha sai...
        assert not [e for e in enviados if e.startswith("Cheia")]  # ...e a cheia espera amanhã
        db.rollback()
    with sessao() as db:
        gravar_config(db, "limite_diario_campanha", "60")


def test_whatsapp_liberado_sai_mesmo_atras_de_muitos_frios(cliente, monkeypatch):
    """Antes: os toques frios (que esperam o clique) ocupavam as 200 vagas da consulta e o liberado nunca saía."""
    from app.integracoes import whatsapp_leads

    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True})
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    enviados = []
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado",
                        lambda db, texto, u, lead=None, tarefa=None: enviados.append(lead.empresa))
    with sessao() as db:
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        camp = _campanha(db, "Muitos frios")
        ontem = date.today() - timedelta(days=1)
        for i in range(210):
            frio = Lead(empresa=f"Frio {i}", whatsapp=f"(81) 98{i:03d}-0000", status="Contatado")
            db.add(frio)
            db.flush()
            db.add(Tarefa(tipo="prospeccao", lead_id=frio.id, campanha_id=camp.id, canal="whatsapp", data=ontem,
                          hora="08:01", status="pendente", mensagem="Oi"))
        quente = Lead(empresa="Já conversou", whatsapp="(81) 97777-1111", status="Contatado", consentimento=True)
        db.add(quente)
        db.flush()
        db.add(Tarefa(tipo="prospeccao", lead_id=quente.id, campanha_id=camp.id, canal="whatsapp", data=ontem,
                      hora="17:59", status="pendente", mensagem="Oi de novo"))
        db.flush()
        campanhas.processar_fila_whatsapp(db, maximo=1000)
        assert "Já conversou" in enviados
        assert not [e for e in enviados if e.startswith("Frio ")]  # frio continua esperando o clique
        db.rollback()


def test_aprovar_mantem_horario_escolhido_a_mao(cliente):
    with sessao() as db:
        camp = _campanha(db, "Horário à mão", status="aguardando_aprovacao")
        lead = Lead(empresa="Hora Mão Ltda", email="a@horamao-x.com.br", status="Abordagem criada")
        db.add(lead)
        db.flush()
        amanha = date.today() + timedelta(days=1)
        mao = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="email", data=amanha,
                     hora="10:20", status="rascunho", mensagem="Olá")
        antiga = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal="email",
                        data=amanha + timedelta(days=2), hora="09:00", status="rascunho", mensagem="Olá 2")
        db.add_all([mao, antiga])
        db.flush()
        campanhas.aprovar(db, camp, _admin(db))
        assert mao.hora == "10:20"           # escolhido à mão: fica (antes virava outro horário)
        assert antiga.hora != "09:00"        # 09:00 do passo (campanha antiga): vira horário natural
        db.rollback()


def test_busca_diaria_com_erro_tenta_no_maximo_3_vezes(cliente, monkeypatch):
    """Cada tentativa pode gastar crédito: com erro, tenta de novo, mas só 3 vezes no dia."""
    chamadas = []

    def quebra(db, u, desde, ate, automatica=False):
        chamadas.append(1)
        raise empresas_novas.ErroCnpja("a CNPJá não respondeu")

    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    monkeypatch.setattr(empresas_novas, "buscar_e_criar", quebra)
    hoje = date.today()
    with sessao() as db:
        for c, v in [("novas_ativo", "1"), ("novas_hora", "00:00"), ("novas_dono_id", str(_admin(db).id)),
                     ("novas_ultima_busca", ""), ("novas_tentativas", ""),
                     ("novas_ultima_data", (hoje - timedelta(days=4)).isoformat())]:
            gravar_config(db, c, v)
    for _ in range(6):
        empresas_novas.rodada_diaria()
    assert len(chamadas) == 3
    with sessao() as db:
        assert "amanhã" in empresas_novas.cfg(db, "novas_ultimo_resultado")
        for c, v in [("novas_ativo", "0"), ("novas_tentativas", ""), ("novas_ultima_busca", "")]:
            gravar_config(db, c, v)


def test_erro_no_meio_da_busca_fica_com_as_paginas_pagas(cliente, monkeypatch):
    class _R:
        def __init__(self, dados, status=200):
            self.dados, self.status_code, self.headers, self.text = dados, status, {"content-type": "application/json"}, ""

        def json(self):
            return self.dados

    def falso(url, params=None, headers=None, timeout=None):
        if (params or {}).get("token"):
            return _R({"message": "erro"}, 500)  # a 2ª página falha
        return _R({"records": [{"taxId": "11111111000111"}, {"taxId": "22222222000122"}], "next": "abc"})

    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    monkeypatch.setattr(empresas_novas.httpx, "get", falso)
    registros = empresas_novas.buscar_abertas(date.today(), date.today(), ["PE"])
    assert [r["taxId"] for r in registros] == ["11111111000111", "22222222000122"]


def test_fim_de_cadencia_numa_consulta_so(cliente):
    with sessao() as db:
        parado = Lead(empresa="Sem Resposta Rev", email="a@semresp-rev.com.br", status="Contatado")
        ativo = Lead(empresa="Ainda Em Cadencia Rev", email="b@emcad-rev.com.br", status="Contatado")
        db.add_all([parado, ativo])
        db.flush()
        velho = agora() - timedelta(days=10)
        db.add_all([
            Tarefa(tipo="prospeccao", lead_id=parado.id, canal="email", data=date.today() - timedelta(days=10),
                   status="feita", concluida_em=velho),
            Tarefa(tipo="prospeccao", lead_id=ativo.id, canal="email", data=date.today() - timedelta(days=10),
                   status="feita", concluida_em=velho),
            Tarefa(tipo="prospeccao", lead_id=ativo.id, canal="email", data=date.today() + timedelta(days=2),
                   status="pendente"),
            Tarefa(tipo="prospeccao", lead_id=None, canal="ligacao", data=date.today(), status="pendente"),
        ])
        db.flush()
        campanhas.finalizar_cadencias(db)
        assert parado.status == "Perdido" and parado.motivo_perda == "Sem resposta"
        assert ativo.status == "Contatado"  # ainda tem toque pela frente
        db.rollback()
