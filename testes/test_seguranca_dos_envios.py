"""Correções de risco do benchmark (Fase 0): e-mail que não se perde nem trava a fila, áudio, parceiro e lead com
humano fora da IA, limite de WhatsApp por número, CNPJ inativo e backup. Nada acessa a internet."""

import email.utils
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select

from app import arquivo_env, campanhas, config, mensagens, pesquisa, rotinas, sdr
from app.banco import agora, gravar_config, ler_config, sessao
from app.integracoes import email_imap, email_smtp
from app.leads_servico import criar_lead
from app.modelos import Campanha, Lead, Mensagem, Notificacao, Oportunidade, Parceiro, Tarefa, Usuario


@pytest.fixture(autouse=True)
def sem_internet(monkeypatch):
    monkeypatch.setattr(pesquisa, "descobrir_site", lambda *a, **k: "")
    monkeypatch.setattr(pesquisa, "ler_site", lambda *a, **k: {})
    monkeypatch.setattr(pesquisa, "dados_do_cnpj", lambda *a, **k: {})
    monkeypatch.setattr(pesquisa, "dados_do_site", lambda *a, **k: {})
    monkeypatch.setattr(arquivo_env, "carregar_do_banco", lambda forcar=False: None)


CHAVES_MEXIDAS = ("enviar_email_automatico", "horas_entre_contatos", "limite_hora_email", "fila_email_pausada_ate",
                  "sdr_resposta_automatica", "imap_ler_desde")


@pytest.fixture(autouse=True)
def config_restaurada():
    """Devolve as configurações mexidas aqui (mesmo se o teste falhar), para não atrapalhar os outros testes."""
    with sessao() as db:
        antes = {c: ler_config(db, c) for c in CHAVES_MEXIDAS}
    yield
    with sessao() as db:
        for chave, valor in antes.items():
            gravar_config(db, chave, valor)


def _admin(db) -> Usuario:
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _novo_lead(db, nome, **campos) -> Lead:
    lead, _ = criar_lead(db, {"empresa": nome, "cidade": "Recife", "estado": "PE", **campos}, _admin(db),
                         checar_duplicado=False)
    db.flush()
    return lead


# ---------------------------------------------------------------- E-mail: destinatário x caixa

def test_endereco_invalido_e_recusado_antes_de_conectar(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.teste")
    monkeypatch.setattr(config, "SMTP_REMETENTE", "comercial@mscertificados.com.br")
    monkeypatch.setattr(config, "EMAIL_DOMINIO", "mscertificados.com.br")

    def nao_conecta(*a, **k):
        raise AssertionError("não deveria abrir conexão com o servidor")

    monkeypatch.setattr(email_smtp.smtplib, "SMTP", nao_conecta)
    for ruim in ("fulano@", "sem arroba.com.br", "contato@gmail", ""):
        with pytest.raises(email_smtp.ErroDestinatario):
            email_smtp.enviar(ruim, "Assunto", "Texto")


def test_destinatario_recusado_nao_trava_a_fila_e_erro_da_caixa_pausa(cliente, monkeypatch):
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    enviados, caixa_quebrada = [], {"sim": False}

    def enviar(para, assunto, corpo, **k):
        if caixa_quebrada["sim"]:
            raise email_smtp.ErroEmail("O Google recusou a senha.")
        if para.startswith("recusado"):
            raise email_smtp.ErroDestinatario(f"O servidor recusou o endereço {para}.")
        enviados.append(para)
        return f"<{len(enviados)}@teste>"

    monkeypatch.setattr(email_smtp, "enviar", enviar)
    with sessao() as db:
        gravar_config(db, "enviar_email_automatico", "1")
        gravar_config(db, "horas_entre_contatos", "0")
        gravar_config(db, "limite_hora_email", "1000")
        gravar_config(db, "fila_email_pausada_ate", "")
        camp = Campanha(nome="Fila com e-mail ruim", status="ativa", aprovado_em=agora(), usuario_id=_admin(db).id)
        db.add(camp)
        db.flush()
        ruim = _novo_lead(db, "Contábil Email Ruim", email="recusado@ruim.com.br")
        bom = _novo_lead(db, "Contábil Email Bom", email="bom@contabil.com.br")
        for lead in (ruim, bom):
            db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, canal="email", data=date.today(), hora="00:00",
                          campanha_id=camp.id, angulo="apresentacao", mensagem="Olá!", assunto="Parceria"))
        db.flush()
        camp_id, ruim_id = camp.id, ruim.id
    with sessao() as db:
        r = campanhas.processar_fila(db)
    assert r["erros"] >= 1 and "bom@contabil.com.br" in enviados  # o e-mail ruim não segurou os outros
    with sessao() as db:
        t = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp_id, Tarefa.lead_id == ruim_id)).scalars().one()
        assert t.status == "cancelada" and "recusou" in t.resultado
        assert ler_config(db, "fila_email_pausada_ate") == ""  # e-mail ruim de um lead não pausa a fila

        outro = _novo_lead(db, "Contábil Email Depois", email="depois@contabil.com.br")
        db.add(Tarefa(tipo="prospeccao", lead_id=outro.id, canal="email", data=date.today(), hora="00:00",
                      campanha_id=camp_id, angulo="apresentacao", mensagem="Olá!", assunto="Parceria"))
    caixa_quebrada["sim"] = True
    with sessao() as db:
        r = campanhas.processar_fila(db)
        assert r["enviados"] == 0 and r["erros"] == 1
        assert ler_config(db, "fila_email_pausada_ate") > agora().isoformat()
    caixa_quebrada["sim"] = False
    with sessao() as db:
        assert campanhas.processar_fila(db)["enviados"] == 0  # pausada: nem tenta
        gravar_config(db, "fila_email_pausada_ate", "")
    with sessao() as db:
        campanhas.processar_fila(db)
    assert "depois@contabil.com.br" in enviados


# ---------------------------------------------------------------- E-mail: leitura das respostas

class CaixaFalsa:
    """IMAP de mentira: guarda se alguém tentou marcar como lido."""

    def __init__(self, mensagens_brutas):
        self.mensagens = mensagens_brutas
        self.somente_leitura = None
        self.pedidos = []

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        return "OK", []

    def select(self, caixa, readonly=False):
        self.somente_leitura = readonly
        return "OK", []

    def search(self, charset, *criterios):
        self.pedidos.append(criterios)
        return "OK", [" ".join(str(i + 1) for i in range(len(self.mensagens))).encode()]

    def fetch(self, num, partes):
        self.pedidos.append(partes)
        bruto = self.mensagens[int(num) - 1]
        if "HEADER.FIELDS" in partes:
            bruto = bruto.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
        return "OK", [(b"1", bruto)]


def _email_bruto(de, assunto, texto, message_id, quando, responde_a=""):
    cab = [f"From: {de}", f"Subject: {assunto}", f"Message-ID: {message_id}",
           f"Date: {email.utils.format_datetime(quando.astimezone())}"]
    if responde_a:
        cab += [f"In-Reply-To: {responde_a}", f"References: {responde_a}"]
    return ("\r\n".join(cab) + "\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n" + texto).encode("utf-8")


def test_respostas_por_email_lidas_ou_nao_uma_vez_so_e_no_mesmo_fio(cliente, monkeypatch):
    monkeypatch.setattr(config, "IMAP_HOST", "imap.teste")
    monkeypatch.setattr(config, "IMAP_USUARIO", "comercial@mscertificados.com.br")
    monkeypatch.setattr(config, "IMAP_SENHA", "x")
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    respostas = []
    monkeypatch.setattr(email_smtp, "enviar",
                        lambda para, assunto, corpo, **k: respostas.append((para, assunto, k)) or "<resp@teste>")
    agora_ = datetime.now()
    with sessao() as db:
        gravar_config(db, "sdr_resposta_automatica", "1")
        gravar_config(db, "imap_ler_desde", (agora() - timedelta(hours=6)).isoformat())
        lead = _novo_lead(db, "Contábil Responde Email", email="dono@respondeemail.com.br")
        colega = _novo_lead(db, "Contábil Colega Responde", email="geral@colegaresponde.com.br")
        enviado = mensagens.registrar(db, colega.id, "email", "Olá!", None, modo="api", status="enviada",
                                      id_externo="<enviado-pelo-sistema@mscertificados.com.br>")
        enviado.direcao = "saida"
        lead_id, colega_id = lead.id, colega.id
    caixa = CaixaFalsa([
        _email_bruto("Dono <dono@respondeemail.com.br>", "Re: Parceria", "Tenho interesse, como funciona?",
                     "<r1@cliente>", agora_),
        _email_bruto("Outra Pessoa <outra@colegaresponde.com.br>", "Re: Olá", "Quero saber mais sobre a parceria",
                     "<r2@cliente>", agora_, responde_a="<enviado-pelo-sistema@mscertificados.com.br>"),
        _email_bruto("Desconhecido <x@qualquer.com>", "Oi", "Nada a ver", "<r3@cliente>", agora_),
        _email_bruto("Dono <dono@respondeemail.com.br>", "Re: antigo", "Resposta antiga já tratada",
                     "<r0@cliente>", agora_ - timedelta(days=1)),
    ])
    monkeypatch.setattr(email_imap.imaplib, "IMAP4_SSL", caixa)
    assert rotinas.ler_respostas_por_email() == 2
    assert caixa.somente_leitura is True
    assert not any("RFC822" in str(p) for p in caixa.pedidos)  # nada é marcado como lido
    assert rotinas.ler_respostas_por_email() == 0  # a 2ª leitura não repete
    with sessao() as db:
        assert db.get(Lead, lead_id).classificacao_resposta and db.get(Lead, colega_id).classificacao_resposta
        entradas = db.execute(select(Mensagem.id_externo).where(Mensagem.direcao == "entrada",
                                                                Mensagem.lead_id.in_([lead_id, colega_id]))).scalars()
        assert set(entradas) == {"<r1@cliente>", "<r2@cliente>"}
    para_dono = [r for r in respostas if r[0] == "dono@respondeemail.com.br"]
    assert para_dono and para_dono[0][1] == "Re: Parceria" and para_dono[0][2]["em_resposta_a"] == "<r1@cliente>"


# ---------------------------------------------------------------- WhatsApp: áudio, humano e parceiro

def test_audio_nao_e_classificado_as_cegas(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Mandou Áudio", whatsapp="(81) 98000-1111")
        analise = sdr.processar_resposta(db, lead, "[áudio]", "whatsapp")
        assert analise["resposta_sugerida"] == "" and not rotinas.responder_automaticamente(db, lead, "whatsapp", analise)
        op = db.get(Oportunidade, analise["oportunidade_id"])
        assert "Ouvir o áudio" in op.proximo_passo and op.temperatura == "morna"
        assert lead.automacao_pausada and not lead.opt_out and lead.status == "Respondeu"
        # áudio com legenda tem texto: segue a classificação normal
        outro = _novo_lead(db, "Contábil Imagem Com Legenda", whatsapp="(81) 98000-2222")
        assert sdr.processar_resposta(db, outro, "[imagem] Tenho interesse", "whatsapp")["classe"] != ""


def test_lead_com_humano_a_ia_so_registra_e_avisa(cliente):
    with sessao() as db:
        admin = _admin(db)
        lead = _novo_lead(db, "Contábil Em Negociação", whatsapp="(81) 98000-3333")
        sdr.assumir_lead(db, lead, admin)
        assert lead.status == "Humano assumiu"
        for texto in ("Não temos interesse no momento", "Por favor não enviem mais nada"):
            analise = sdr.processar_resposta(db, lead, texto, "whatsapp")
            assert analise.get("com_humano") and analise["resposta_sugerida"] == ""
            assert not rotinas.responder_automaticamente(db, lead, "whatsapp", analise)
        assert lead.status == "Humano assumiu" and not lead.opt_out  # a etapa não volta e não vira Perdido
        avisos = db.execute(select(Notificacao.texto).where(Notificacao.link == f"/leads/{lead.id}")).scalars().all()
        assert len(avisos) == 2 and "parar" in avisos[-1]  # o 2º aviso sai mesmo dentro das 2 horas
        # registrado à mão por uma pessoa: continua classificado
        assert sdr.processar_resposta(db, lead, "Quero uma reunião", "whatsapp", usuario=admin)["classe"]


def test_mensagem_de_parceiro_nao_vira_opt_out(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Parceira Ativa", whatsapp="(81) 98000-4444")
        db.add(Parceiro(escritorio="Contábil Parceira Ativa", lead_id=lead.id, status="ATIVO"))
        db.flush()
        analise = sdr.processar_resposta(db, lead, "Cancelar a indicação do João", "whatsapp")
        assert analise.get("com_humano") and not lead.opt_out and not lead.classificacao_resposta
        assert db.execute(select(Oportunidade).where(Oportunidade.lead_id == lead.id)).first() is None


# ---------------------------------------------------------------- WhatsApp: limite por número

def test_limite_diario_vale_para_cada_numero(cliente):
    with sessao() as db:
        limite = mensagens.limite_diario(db, "whatsapp")
        for _ in range(limite):
            m = mensagens.registrar(db, None, "whatsapp", "oi", None, modo="whatsapp-leads", status="enviada")
            m.conexao = "u901"
        db.flush()
        assert "este número" in mensagens.limite_do_numero(db, "u901").lower()
        assert mensagens.limite_do_numero(db, "u902") == ""  # outro número ainda pode
        assert mensagens.bloqueio_de_envio(db, None, "whatsapp", conexao="u902") == ""
        assert mensagens.whatsapp_hoje_por_numero(db)["u901"] == limite


# ---------------------------------------------------------------- CNPJ inativo

def test_cnpj_inativo_vira_perdido_e_sai_da_campanha(cliente, monkeypatch):
    monkeypatch.setattr(pesquisa, "dados_do_cnpj", lambda cnpj: {"situacao": "BAIXADA", "fonte_url": ""})
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Fechada", cnpj="60701426000102")
        pesquisa.pesquisar_lead(db, lead, usar_ia=False)
        assert lead.perdido and lead.motivo_perda == "CNPJ inativo"
        conversando = _novo_lead(db, "Contábil Fechada Conversando", cnpj="73481955000181")
        conversando.status = "Interessado"
        pesquisa.pesquisar_lead(db, conversando, usar_ia=False)
        assert not conversando.perdido  # com conversa em andamento, só fica o aviso no histórico


# ---------------------------------------------------------------- Backup

def test_backup_e_restauracao_sem_a_base_da_receita(cliente, tmp_path):
    import restaurar_backup
    from enviar_para_nuvem import copiar
    from fazer_backup import FORA_DO_BACKUP

    origem = create_engine(config.DATABASE_URL)
    arquivo = tmp_path / "nuvem_teste.db"
    contagem = copiar(origem, create_engine(f"sqlite:///{arquivo.as_posix()}"), avisar=lambda _t: None,
                      pular=FORA_DO_BACKUP)
    assert contagem["leads"] > 0 and "base_receita" not in contagem
    destino = create_engine(f"sqlite:///{(tmp_path / 'restaurado.db').as_posix()}")
    assert restaurar_backup.restaurar(arquivo, destino, avisar=lambda _t: None)["leads"] == contagem["leads"]
