"""Duas ARs podem chamar a mesma empresa (decisão de 14/11/2026). Então cada resposta é da AR que recebeu: a resposta no
WhatsApp vai para o lead da AR do número que recebeu, a resposta por e-mail para o lead do e-mail respondido ou da AR
da caixa que recebeu. O SAIR no WhatsApp vale para todas as ARs (o WhatsApp Leads é um só e bloqueia para todos)."""
from types import SimpleNamespace

from sqlalchemy import select

from app import sdr
from app.banco import sessao
from app.leads_servico import limpar_campos
from app.modelos import ConexaoWhatsApp, Lead, Mensagem, Tenant
from app.rotinas import lead_da_resposta

TELEFONE = "81934561239"  # só deste teste (o 97777-1111 é do test_sistema)
EMAIL = "contato@empresa-das-duas.com.br"


def _duas_ars():
    with sessao() as db:
        ids = dict(db.execute(select(Tenant.slug, Tenant.id)).all())
        leads = {}
        for slug in ("ms", "grupo-certy"):
            lead = Lead(empresa=f"Empresa das duas ({slug})", tenant_id=ids[slug], whatsapp=TELEFONE, email=EMAIL)
            limpar_campos(lead)  # as chaves de busca (telefone e e-mail), como no cadastro
            db.add(lead)
            if db.get(ConexaoWhatsApp, f"teste_{slug}") is None:
                db.add(ConexaoWhatsApp(id=f"teste_{slug}", nome=f"Número de teste {slug}", tenant_id=ids[slug]))
            db.flush()
            leads[slug] = lead.id
        return ids, leads


def test_resposta_no_whatsapp_vai_para_o_lead_da_ar_que_recebeu(cliente):
    ids, leads = _duas_ars()
    with sessao() as db:
        sdr.aplicar_novidades_whatsapp(db, {"recebidas": [{"telefone": "55" + TELEFONE, "conexao": "teste_grupo-certy",
                                                           "texto": "Pode me explicar melhor como funciona?"}]})
    with sessao() as db:
        donos = {m.lead_id for m in db.execute(select(Mensagem).where(
            Mensagem.direcao == "entrada", Mensagem.corpo == "Pode me explicar melhor como funciona?")).scalars()}
        assert donos == {leads["grupo-certy"]}


def test_sair_no_whatsapp_vale_para_todas_as_ars(cliente):
    ids, leads = _duas_ars()
    with sessao() as db:
        sdr.aplicar_novidades_whatsapp(db, {"bloqueados": ["55" + TELEFONE]})
    with sessao() as db:
        assert all(db.get(Lead, i).opt_out for i in leads.values())


def test_resposta_por_email_vai_para_o_lead_certo(cliente):
    ids, leads = _duas_ars()
    item = {"de": EMAIL, "responde_a": []}
    with sessao() as db:
        caixa_certy = SimpleNamespace(tenant_id=ids["grupo-certy"])
        caixa_ms = SimpleNamespace(tenant_id=ids["ms"])
        assert lead_da_resposta(db, caixa_certy, item, {}).tenant_id == ids["grupo-certy"]
        assert lead_da_resposta(db, caixa_ms, item, {}).tenant_id == ids["ms"]
        # respondeu um e-mail nosso: vale o lead daquele e-mail, mesmo que a caixa seja de outra AR
        assert lead_da_resposta(db, caixa_ms, {"de": "colega@outro.com.br", "responde_a": ["<msg-1@teste>"]},
                                {"<msg-1@teste>": leads["grupo-certy"]}).id == leads["grupo-certy"]
