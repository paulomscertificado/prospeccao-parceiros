"""Tela Novas oportunidades: mostra a campanha, o dono, o canal e a conversa em ordem."""

from sqlalchemy import select

from app.banco import sessao
from app.modelos import Campanha, Lead, Mensagem, Oportunidade, Usuario
from app.seguranca import resumir_senha


def test_cartao_mostra_campanha_dono_e_canal(cliente):
    with sessao() as db:
        paulo = db.execute(select(Usuario).where(Usuario.email == "paulo.op@teste.com.br")).scalars().first()
        if not paulo:
            paulo = Usuario(nome="Paulo Origem", email="paulo.op@teste.com.br", perfil="vendedor",
                            senha_hash=resumir_senha("senhaTeste123"))
            db.add(paulo)
            db.flush()
        camp = Campanha(nome="Campanha Paulo 1", categorias="contabil", cidade="Recife", estado="PE", quantidade=1,
                        canais="whatsapp", status="ativa", usuario_id=paulo.id)
        lead = Lead(empresa="EDILEILA CONTABILIDADE", cidade="Recife", estado="PE", vendedor_id=paulo.id)
        db.add_all([camp, lead])
        db.flush()
        db.add(Mensagem(lead_id=lead.id, canal="whatsapp", campanha_id=camp.id, direcao="saida", status="enviada",
                        corpo="Olá! Sou Paulo, da MS Certificação Digital.", conexao="principal"))
        db.add(Oportunidade(lead_id=lead.id, temperatura="morna", classificacao="RESPOSTA INDEFINIDA", canal="whatsapp",
                            resposta="Edileila Contabilidade agradece seu contato. Em que podemos ajudar?",
                            resumo="Agradeceu e perguntou como pode ajudar.", interesse="baixo",
                            proximo_passo="ler a resposta e decidir o próximo passo"))
        db.commit()
    pagina = cliente.get("/oportunidades").text
    trecho = pagina[pagina.index("EDILEILA CONTABILIDADE"):]
    for esperado in ("Campanha Paulo 1", "Dono da campanha", "Paulo Origem", "WhatsApp", "1. O que enviamos",
                     "Sou Paulo, da MS", "2. O que o lead respondeu", "3. O que a IA entendeu"):
        assert esperado in trecho, esperado
