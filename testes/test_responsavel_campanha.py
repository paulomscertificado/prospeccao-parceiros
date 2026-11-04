"""Campanha de uma pessoa com empresas que estavam com outro vendedor: quem criou a campanha assina e envia."""

from datetime import date

from sqlalchemy import select

from app import campanhas
from app.banco import agora, sessao
from app.modelos import Campanha, Lead, Tarefa, Usuario
from app.seguranca import resumir_senha


def _usuario(db, nome, email):
    u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
    if not u:
        u = Usuario(nome=nome, email=email, perfil="vendedor", senha_hash=resumir_senha("senhaTeste123"))
        db.add(u)
        db.flush()
    return u


def test_aviso_e_troca_de_assinatura(cliente):
    from conftest import csrf_de

    with sessao() as db:
        paulo = _usuario(db, "Paulo Marinho", "paulo@teste.com.br")
        jefferson = _usuario(db, "Jefferson Lima", "jefferson@teste.com.br")
        camp = Campanha(nome="Campanha Paulo 1", categorias="contabil", cidade="Recife", estado="PE", quantidade=2,
                        canais="whatsapp,email", status="aguardando_aprovacao", usuario_id=paulo.id)
        livre = Lead(empresa="Rhc Servicos", vendedor_id=jefferson.id)
        conversou = Lead(empresa="Genesis Assessoria", vendedor_id=jefferson.id, contatado_em=agora())
        db.add_all([camp, livre, conversou])
        db.flush()
        email = ("Na prática, é uma receita extra.\n\nJefferson\nMS Certificação Digital · mscertificados.com.br")
        zap = "Olá! Sou Jefferson, da MS Certificação Digital, e estamos ampliando a rede."
        for lead in (livre, conversou):
            db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="whatsapp", data=date.today(), status="rascunho",
                          mensagem=zap, mensagem_whatsapp=zap, mensagem_email=email, usuario_id=jefferson.id))
        db.commit()
        cid, livre_id, conversou_id, paulo_id = camp.id, livre.id, conversou.id, paulo.id

    pagina = cliente.get(f"/campanhas/{cid}").text
    assert "2 empresas desta campanha" in pagina and "Jefferson Lima" in pagina

    cliente.post(f"/campanhas/{cid}/assumir-empresas", data={"csrf": csrf_de(pagina)})
    with sessao() as db:
        assert db.get(Lead, livre_id).vendedor_id == paulo_id
        assert db.get(Lead, conversou_id).vendedor_id != paulo_id  # já conversou com o Jefferson: fica com ele
        t = db.execute(select(Tarefa).where(Tarefa.lead_id == livre_id)).scalars().first()
        assert "\n\nPaulo\nMS Certificação Digital" in t.mensagem_email and "Jefferson" not in t.mensagem_email
        assert t.mensagem.startswith("Olá! Sou Paulo, da MS") and t.usuario_id == paulo_id
        t2 = db.execute(select(Tarefa).where(Tarefa.lead_id == conversou_id)).scalars().first()
        assert "Jefferson" in t2.mensagem_email


def test_trocar_assinatura_nao_mexe_no_resto_do_texto():
    texto = "Falei com o Jefferson ontem.\n\nJefferson\nMS Certificação Digital · mscertificados.com.br"
    novo = campanhas._trocar_assinatura(texto, "Jefferson", "Paulo")
    assert novo.startswith("Falei com o Jefferson ontem.") and novo.endswith("Paulo\nMS Certificação Digital · mscertificados.com.br")
