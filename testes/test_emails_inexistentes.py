"""E-mails que não existem: conferência do domínio antes de enviar e leitura das devoluções."""

import email
from datetime import date

import httpx
from sqlalchemy import select

from app import email_validacao, rotinas
from app.banco import sessao
from app.integracoes import email_imap
from app.modelos import Lead, Tarefa

DEVOLUCAO_GMAIL = b"""From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
To: maria@mscertificados.com.br
Subject: Delivery Status Notification (Failure)
Message-ID: <devolucao-1@mx.google.com>
MIME-Version: 1.0
Content-Type: multipart/report; boundary="XYZ"; report-type=delivery-status

--XYZ
Content-Type: text/plain; charset="UTF-8"
Content-Transfer-Encoding: 8bit

Endere\xc3\xa7o n\xc3\xa3o encontrado
Sua mensagem n\xc3\xa3o foi entregue a leoi@terra.com.br porque o endere\xc3\xa7o n\xc3\xa3o foi encontrado.

--XYZ
Content-Type: message/delivery-status

Reporting-MTA: dns; googlemail.com

Final-Recipient: rfc822; leoi@terra.com.br
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 <leoi@terra.com.br>: Recipient address rejected: User unknown

--XYZ
Content-Type: text/rfc822-headers

From: Maria <maria@mscertificados.com.br>
To: leoi@terra.com.br
Subject: Parceria MS Certificacao Digital + Lohn Contabilidade
Message-ID: <enviado-123@mscertificados.com.br>

--XYZ--
"""

DEVOLUCAO_SO_TEXTO = (
    "From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>\n"
    "Subject: Endereço não encontrado\nContent-Type: text/plain; charset=utf-8\n\n"
    "A mensagem não foi entregue para jaci@jacicontabilpe.com.br porque o domínio jacicontabilpe.com.br "
    "não foi encontrado.\n").encode("utf-8")

CAIXA_CHEIA = b"""From: postmaster@outlook.com
Subject: Undeliverable: Parceria
Content-Type: multipart/report; boundary="B"; report-type=delivery-status

--B
Content-Type: text/plain

The recipient's mailbox is full.

--B
Content-Type: message/delivery-status

Final-Recipient: rfc822; cheio@outlook.com
Action: delayed
Status: 4.2.2

--B--
"""


def test_le_devolucao_do_gmail():
    msg = email.message_from_bytes(DEVOLUCAO_GMAIL)
    assert email_validacao.parece_devolucao(msg["From"], msg["Subject"], msg["Content-Type"])
    d = email_validacao.analisar_devolucao(msg)
    assert d["destinatarios"] == ["leoi@terra.com.br"]
    assert d["permanente"] is True
    assert "<enviado-123@mscertificados.com.br>" in d["ids_originais"]


def test_le_devolucao_so_texto_em_portugues():
    msg = email.message_from_bytes(DEVOLUCAO_SO_TEXTO)
    assert email_validacao.parece_devolucao(msg["From"], "Endereço não encontrado")
    d = email_validacao.analisar_devolucao(msg)
    assert "jaci@jacicontabilpe.com.br" in d["destinatarios"]
    assert d["permanente"] is True and "domínio" in d["motivo"]


def test_caixa_cheia_nao_tira_o_email():
    d = email_validacao.analisar_devolucao(email.message_from_bytes(CAIXA_CHEIA))
    assert d["destinatarios"] == ["cheio@outlook.com"] and d["permanente"] is False


def test_resposta_normal_nao_e_devolucao():
    assert not email_validacao.parece_devolucao("Fulano <fulano@contabil.com.br>", "Re: Parceria MS")


class _Resposta:
    def __init__(self, dados):
        self.dados = dados

    def raise_for_status(self):
        pass

    def json(self):
        return self.dados


def test_confere_dominio(monkeypatch):
    respostas = {
        ("semdominio.com.br", "MX"): {"Status": 3},
        ("contabil.com.br", "MX"): {"Status": 0, "Answer": [{"type": 15, "data": "10 mx.contabil.com.br."}]},
        ("nulo.com.br", "MX"): {"Status": 0, "Answer": [{"type": 15, "data": "0 ."}]},
        ("soa.com.br", "MX"): {"Status": 0},
        ("soa.com.br", "A"): {"Status": 0, "Answer": [{"type": 1, "data": "1.2.3.4"}]},
    }

    def falso(url, params, timeout):
        if params["name"] == "forasite.com.br":
            raise httpx.ConnectError("sem internet")
        return _Resposta(respostas.get((params["name"], params["type"]), {"Status": 0}))

    monkeypatch.setenv("CONFERIR_DOMINIO_EMAIL", "1")
    monkeypatch.setattr(email_validacao.httpx, "get", falso)
    monkeypatch.setattr(email_validacao, "_cache_dominios", {})
    assert email_validacao.conferir("jaci@semdominio.com.br")[0] is False
    assert email_validacao.conferir("ana@contabil.com.br") == (True, "")
    assert email_validacao.conferir("x@nulo.com.br")[0] is False
    assert email_validacao.conferir("x@soA.com.br")[0] is True
    assert email_validacao.conferir("x@forasite.com.br")[0] is None  # sem internet: não barra
    assert email_validacao.conferir("fulano@@gmail")[0] is False


def _lead_com_toque(email_lead: str) -> tuple[int, int]:
    with sessao() as db:
        lead = Lead(empresa=f"Teste {email_lead}", email=email_lead, chave_email=email_lead)
        db.add(lead)
        db.flush()
        t = Tarefa(lead_id=lead.id, canal="email", data=date.today(), status="pendente", mensagem="Olá")
        db.add(t)
        db.commit()
        return lead.id, t.id


def test_dominio_inexistente_cancela_toques_e_volta_ao_corrigir(cliente, monkeypatch):
    monkeypatch.setattr(email_validacao, "conferir",
                        lambda e: (False, "o domínio x não existe") if "morto" in e else (True, ""))
    lead_id, tarefa_id = _lead_com_toque("ana@morto.com.br")
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        assert email_validacao.utilizavel(db, lead) is False
        db.commit()
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        assert lead.email_invalido and db.get(Tarefa, tarefa_id).status == "cancelada"
        lead.email = "ana@vivo.com.br"  # corrigiu na ficha
        assert email_validacao.utilizavel(db, lead) is True and not lead.email_invalido


def test_devolucao_na_caixa_marca_o_lead(cliente, monkeypatch):
    lead_id, tarefa_id = _lead_com_toque("leoi@terra.com.br")
    analise = email_validacao.analisar_devolucao(email.message_from_bytes(DEVOLUCAO_GMAIL))
    analise["message_id"] = "<devolucao-1@mx.google.com>"
    monkeypatch.setattr(email_imap, "ler_devolucoes", lambda desde, conta=None: [analise])
    assert rotinas._ler_devolucoes(None, {}) == 1
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        assert lead.email_invalido and "não existe" in lead.email_motivo
        assert db.get(Tarefa, tarefa_id).status == "cancelada"
    assert rotinas._ler_devolucoes(None, {}) == 0  # a mesma devolução de novo não conta duas vezes


def test_devolucao_temporaria_nao_marca(cliente, monkeypatch):
    lead_id, _ = _lead_com_toque("cheio@outlook.com")
    analise = email_validacao.analisar_devolucao(email.message_from_bytes(CAIXA_CHEIA))
    monkeypatch.setattr(email_imap, "ler_devolucoes", lambda desde, conta=None: [analise])
    rotinas._ler_devolucoes(None, {})
    with sessao() as db:
        assert not db.execute(select(Lead.email_invalido).where(Lead.id == lead_id)).scalar()
