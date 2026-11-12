"""Nova campanha (nov/2026): tons que mudam as mensagens também sem IA, toques novos (pergunta rápida, dica útil,
convite por e-mail) e cadências novas da IA SDR."""

from datetime import date

from sqlalchemy import select

from app import cadencias, config, modelos_segmento, sdr
from app.banco import gravar_config, sessao
from app.modelos import CADENCIAS_SDR_EXTRAS, Cadencia, Categoria, Lead, Tarefa, Usuario


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _lead(db, nome, categoria="contabil", **extra):
    cat = db.execute(select(Categoria).where(Categoria.codigo == categoria)).scalars().first()
    lead = Lead(empresa=nome, cidade="Recife", estado="PE", responsavel="Ana Souza", categoria=cat,
                whatsapp="81974440000", email="ana@tom-teste.com.br", **extra)
    db.add(lead)
    db.flush()
    return lead


def test_cada_tom_tem_o_proprio_texto_e_segue_as_regras(cliente):
    with sessao() as db:
        lead = _lead(db, "Tom Contabilidade Ltda")
        primeiras = {}
        for tom in config.TONS:
            msgs = sdr.mensagens_por_regras(db, lead, _admin(db), tom=tom)
            assert {"apresentacao", "pergunta", "praticidade", "conteudo", "receita", "convite", "encerramento"} <= set(msgs)
            for angulo, m in msgs.items():
                juntos = m["whatsapp"] + m["email"] + m["assunto"]
                assert sdr.texto_seguro(m["whatsapp"]) and sdr.texto_seguro(m["email"]), (tom, angulo)
                assert "{" not in juntos and "viu minha mensagem" not in juntos.lower(), (tom, angulo)
            assert "não envio mais" in msgs["apresentacao"]["whatsapp"] or "não enviaremos" in msgs["apresentacao"]["whatsapp"]
            primeiras[tom] = msgs["apresentacao"]["whatsapp"]
        assert len(set(primeiras.values())) == len(config.TONS)  # cada tom começa de um jeito
        assert primeiras["pergunta"].startswith("Oi, Ana!") and "vocês indicam alguém?" in primeiras["pergunta"]
        assert primeiras["formal"].startswith("Prezado(a) Ana,")
        assert "Atenciosamente" in sdr.mensagens_por_regras(db, lead, _admin(db), tom="formal")["receita"]["email"]
        assert "escritórios contábeis" in primeiras["parceiro"]  # vocabulário do segmento
        db.rollback()


def test_tons_valem_para_todos_os_segmentos_e_para_o_generico(cliente):
    with sessao() as db:
        codigos = [c for c in modelos_segmento.SEGMENTOS if db.execute(
            select(Categoria.id).where(Categoria.codigo == c)).first()]
        for codigo in codigos + ["outros"]:
            lead = _lead(db, f"Segmento {codigo} Teste", categoria=codigo)
            for tom in config.TONS:
                for angulo, m in sdr.mensagens_por_regras(db, lead, _admin(db), tom=tom).items():
                    assert sdr.texto_seguro(m["whatsapp"]) and sdr.texto_seguro(m["email"]), (codigo, tom, angulo)
        db.rollback()


def test_convite_leva_o_link_do_whatsapp_quando_configurado(cliente):
    with sessao() as db:
        lead = _lead(db, "Convite Link Ltda")
        assert "é só responder" in sdr.mensagens_por_regras(db, lead, _admin(db))["convite"]["email"]
        gravar_config(db, "whatsapp_convite", "(81) 99999-8888")
        assert "https://wa.me/5581999998888" in sdr.mensagens_por_regras(db, lead, _admin(db))["convite"]["email"]
        gravar_config(db, "whatsapp_convite", "")
        db.rollback()


def test_cadencias_novas_e_campanha_com_pergunta_primeiro(cliente):
    with sessao() as db:
        nomes = {c.nome: c for c in db.execute(select(Cadencia)).scalars()}
        for nome, _, passos in CADENCIAS_SDR_EXTRAS:
            assert nome in nomes and [(p.dia, p.angulo) for p in nomes[nome].passos] == [(d, a) for d, _, a, _ in passos]
        cad = nomes["Pergunta primeiro – 3 toques (D1, D4, D10)"]
        lead = _lead(db, "Pergunta Primeiro Ltda")
        textos = {lead.id: sdr.mensagens_por_regras(db, lead, _admin(db), tom="direto")}
        r = cadencias.aplicar(db, cad, [lead], _admin(db), date.today(), None, textos, ["whatsapp"], "rascunho",
                              tom="direto")
        assert r["leads"] == 1
        toques = db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id).order_by(Tarefa.data, Tarefa.id)).scalars().all()
        assert [t.angulo for t in toques] == ["pergunta", "apresentacao", "encerramento"]
        assert toques[0].mensagem == textos[lead.id]["pergunta"]["whatsapp"] and "10 minutos" in toques[0].mensagem
        # toque que a IA não escreveu: sai das regras do tom (não fica vazio)
        outro = _lead(db, "Sem Pergunta Da IA Ltda")
        so_ia = {outro.id: {a: m for a, m in sdr.mensagens_por_regras(db, outro, _admin(db)).items()
                            if a in config.ANGULOS}}
        cadencias.aplicar(db, cad, [outro], _admin(db), date.today(), None, so_ia, ["whatsapp"], "rascunho")
        primeira = db.execute(select(Tarefa).where(Tarefa.lead_id == outro.id).order_by(Tarefa.data, Tarefa.id)).scalars().first()
        assert primeira.angulo == "pergunta" and primeira.mensagem.strip()
        db.rollback()


def test_tela_nova_campanha_com_tons_e_cadencias(cliente):
    pagina = cliente.get("/campanhas/nova").text
    assert pagina.index("Onde?") < pagina.index("Que tipo de empresa?")  # a cidade vem antes (as quantidades dependem dela)
    assert pagina.count('name="tom"') == len(config.TONS) and "Pergunta curta" in pagina and "Formal e institucional" in pagina
    for nome, _, _ in CADENCIAS_SDR_EXTRAS:
        assert nome.split(" (")[0] in pagina
    assert "Prospecção de escritórios (10 dias)" not in pagina  # cadência da Agenda (ligação/LinkedIn) não serve aqui
    assert "⭐ Mais indicado" in pagina and 'id="mostrar-vazias"' in pagina and 'data-so-email="1"' in pagina
