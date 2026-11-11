"""Tela Oportunidades (nov/2026): abas Novas / Assumidas / Descartadas / Todas as respostas, filtros com contagem,
quentes primeiro em cada dia, tempo de espera, descartar as mostradas e "Voltar para Novas"."""

import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.banco import agora, sessao
from app.main import app
from app.modelos import Historico, Lead, Mensagem, Oportunidade, Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de

SENHA = "senhaOport123"


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _op(db, empresa, *, status="nova", temperatura="morna", criado_em=None, assumida_em=None, responsavel=None,
        canal="whatsapp", vendedor_id=None, **extra) -> Oportunidade:
    lead = Lead(empresa=empresa, cidade="Recife", estado="PE", whatsapp="81996660000", vendedor_id=vendedor_id)
    db.add(lead)
    db.flush()
    op = Oportunidade(lead_id=lead.id, temperatura=temperatura, canal=canal, status=status,
                      classificacao="QUER SABER MAIS" if temperatura == "quente" else "RESPOSTA INDEFINIDA",
                      resposta=f"Resposta de {empresa}", criado_em=criado_em or agora(), assumida_em=assumida_em,
                      responsavel_id=responsavel, **extra)
    db.add(op)
    db.flush()
    return op


def test_abas_ordem_espera_e_filtros(cliente):
    inicio_do_dia = agora().replace(hour=0, minute=0, second=1)
    with sessao() as db:
        admin = _admin(db)
        # a morna é MAIS NOVA, mas a quente vem primeiro no mesmo dia (antes as mornas vinham antes)
        _op(db, "Tela Op Quente Ltda", temperatura="quente", criado_em=inicio_do_dia)
        _op(db, "Tela Op Morna Ltda", criado_em=inicio_do_dia + timedelta(seconds=1))
        _op(db, "Tela Op Assumida Ltda", status="assumida", criado_em=agora() - timedelta(hours=3),
            assumida_em=agora() - timedelta(hours=1), responsavel=admin.id)
        _op(db, "Tela Op Descartada Ltda", status="descartada", criado_em=agora() - timedelta(days=40),
            assumida_em=agora() - timedelta(days=39), responsavel=admin.id)

    pagina = cliente.get("/oportunidades?busca=tela op").text  # busca sem acento/maiúscula
    assert "Tela Op Quente Ltda" in pagina and "Tela Op Morna Ltda" in pagina
    assert pagina.index("Tela Op Quente Ltda") < pagina.index("Tela Op Morna Ltda")
    assert "Tela Op Assumida Ltda" not in pagina and "Tela Op Descartada Ltda" not in pagina
    assert "esperando há" in pagina and "Novas para assumir" in pagina and "Hoje" in pagina
    for aba in ("🔥 Novas", "✅ Assumidas", "🗑️ Descartadas", "💬 Todas as respostas"):
        assert aba in pagina, aba

    so_quentes = cliente.get("/oportunidades?busca=tela op&temperatura=quente").text
    assert "Tela Op Quente Ltda" in so_quentes and "Tela Op Morna Ltda" not in so_quentes
    assert "Descartar as 1 mostradas" in so_quentes  # com filtro aparece o descartar de uma vez
    assert "mostradas" not in cliente.get("/oportunidades").text  # sem filtro, não (evita descartar tudo sem querer)

    assumidas = cliente.get("/oportunidades?ver=assumidas&busca=tela op").text
    assert "Tela Op Assumida Ltda" in assumidas and "Tela Op Quente Ltda" not in assumidas
    assert "Assumida por Maria Admin · 2 h depois da resposta" in assumidas
    assert "Tela Op Assumida Ltda" in cliente.get("/oportunidades?ver=tratadas&busca=tela op").text  # endereço antigo

    descartadas = cliente.get("/oportunidades?ver=descartadas&busca=tela op").text
    assert "Tela Op Descartada Ltda" in descartadas and "Voltar para Novas" in descartadas
    assert "Tela Op Descartada Ltda" not in cliente.get("/oportunidades?ver=descartadas&busca=tela op&periodo=7d").text
    assert "Tela Op Descartada Ltda" in cliente.get("/oportunidades?ver=descartadas&busca=tela op&periodo=antes").text
    with sessao() as db:  # não deixa cartões na aba Novas dos outros testes
        for op in db.execute(select(Oportunidade).join(Lead).where(Lead.empresa.like("Tela Op %"),
                                                                   Oportunidade.status == "nova")).scalars():
            op.status = "descartada"


def test_descartar_varias_e_voltar_para_novas(cliente):
    with sessao() as db:
        ids = [_op(db, f"Descarte Lote {n} Ltda").id for n in (1, 2)]
        outra = _op(db, "Descarte Fica Ltda", temperatura="quente").id
    filtrada = cliente.get("/oportunidades?busca=descarte lote&temperatura=morna").text
    assert "Descartar as 2 mostradas" in filtrada
    r = cliente.post("/oportunidades/descartar-varias",
                     data={"csrf": csrf_de(filtrada), "ids": ",".join(map(str, ids)), "motivo": "Sem interesse",
                           "voltar_para": "/oportunidades?busca=descarte+lote"})
    assert "2 oportunidade(s) descartada(s)" in r.text
    with sessao() as db:
        assert {db.get(Oportunidade, i).status for i in ids} == {"descartada"}
        assert db.get(Oportunidade, outra).status == "nova"  # só as mostradas
        lead_id = db.get(Oportunidade, ids[0]).lead_id
        assert db.execute(select(Historico).where(Historico.lead_id == lead_id,
                                                  Historico.descricao.like("%descartada por%"))).first()
    assert "Nenhuma oportunidade para descartar" in cliente.post(
        "/oportunidades/descartar-varias", data={"csrf": csrf_de(filtrada), "ids": ",".join(map(str, ids)),
                                                 "motivo": "Sem interesse"}).text

    # Desfazer: volta para Novas
    r = cliente.post(f"/oportunidades/{ids[0]}/reabrir",
                     data={"csrf": csrf_de(filtrada), "voltar_para": "/oportunidades?ver=descartadas"})
    assert "voltou para Novas" in r.text
    with sessao() as db:
        op = db.get(Oportunidade, ids[0])
        assert (op.status, op.responsavel_id, op.assumida_em) == ("nova", None, None)
    assert "Descarte Lote 1 Ltda" in cliente.get("/oportunidades?busca=descarte lote").text
    assert "Só dá para voltar" in cliente.post(f"/oportunidades/{outra}/reabrir", data={"csrf": csrf_de(filtrada)}).text
    assert cliente.post("/oportunidades/999999/reabrir", data={"csrf": csrf_de(filtrada)}).status_code == 404
    # o descarte de um cartão volta para a tela de onde veio (com os filtros)
    r = cliente.post(f"/oportunidades/{ids[0]}/descartar",
                     data={"csrf": csrf_de(filtrada), "voltar_para": "/oportunidades?busca=descarte+lote",
                           "motivo": "Fora do perfil"},
                     follow_redirects=False)
    assert r.headers["location"] == "/oportunidades?busca=descarte+lote"
    r = cliente.post(f"/oportunidades/{outra}/descartar", data={"csrf": csrf_de(filtrada), "voltar_para": "//fora.com",
                                                                 "motivo": "Outro"},
                     follow_redirects=False)
    assert r.headers["location"] == "/oportunidades"  # nunca manda para fora do sistema


def test_todas_as_respostas_filtra_por_tipo_e_canal(cliente):
    with sessao() as db:
        saiu = Lead(empresa="Resposta Saiu Ltda", whatsapp="81996661111", classificacao_resposta="OPT-OUT")
        quer = Lead(empresa="Resposta Quer Ltda", email="quer@resposta-tela.com.br", classificacao_resposta="QUER PROPOSTA")
        db.add_all([saiu, quer])
        db.flush()
        db.add_all([Mensagem(lead_id=saiu.id, canal="whatsapp", corpo="Me tira da lista", status="recebida",
                             direcao="entrada"),
                    Mensagem(lead_id=quer.id, canal="email", corpo="Manda a proposta", status="recebida",
                             direcao="entrada")])
    todas = cliente.get("/oportunidades?ver=respostas&busca=resposta").text
    assert "Todas as respostas dos contatos" in todas and "Me tira da lista" in todas and "Manda a proposta" in todas
    assert "Pediu para sair" in todas and "Com interesse" in todas  # botões de filtro com contagem
    so_saiu = cliente.get("/oportunidades?ver=respostas&busca=resposta&classe=saiu").text
    assert "Me tira da lista" in so_saiu and "Manda a proposta" not in so_saiu
    so_email = cliente.get("/oportunidades?ver=respostas&busca=resposta&canal=email").text
    assert "Manda a proposta" in so_email and "Me tira da lista" not in so_email
    assert "/conversas?telefone=81996661111" in todas  # abre a conversa do WhatsApp
    # o número "Respostas (7 dias)" do topo bate com a lista que ele abre (mesma regra de dias)
    pagina = cliente.get("/oportunidades?ver=respostas").text
    kpi = re.search(r'Respostas \(7 dias\)</div><div class="valor">(\d+)<', pagina).group(1)
    assert kpi == re.search(r'Últimos 7 dias <span class="n">(\d+)<', pagina).group(1)


def test_vendedor_ve_so_as_dele_e_nao_ve_todas_as_respostas(cliente):
    with sessao() as db:
        vend = db.execute(select(Usuario).where(Usuario.email == "vend.op@teste.com.br")).scalars().first()
        if not vend:
            vend = Usuario(nome="Vendedora Oport", email="vend.op@teste.com.br", perfil="vendedor",
                           senha_hash=resumir_senha(SENHA))
            db.add(vend)
            db.flush()
        admin = _admin(db)
        minha = _op(db, "Vend Op Minha Ltda", vendedor_id=vend.id).id
        alheia = _op(db, "Vend Op Alheia Ltda", vendedor_id=admin.id).id
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": "vend.op@teste.com.br", "senha": SENHA})
    pagina = c.get("/oportunidades?busca=vend op").text
    assert "Vend Op Minha Ltda" in pagina and "Vend Op Alheia Ltda" not in pagina
    assert "Todas as respostas" not in pagina
    assert "Todas as respostas dos contatos" not in c.get("/oportunidades?ver=respostas").text  # volta para Novas
    csrf = csrf_de(pagina)
    assert c.post(f"/oportunidades/{alheia}/descartar", data={"csrf": csrf, "motivo": "Outro"}).status_code == 404
    c.post("/oportunidades/descartar-varias", data={"csrf": csrf, "ids": f"{minha},{alheia}", "motivo": "Outro"})
    with sessao() as db:
        assert db.get(Oportunidade, minha).status == "descartada"
        assert db.get(Oportunidade, alheia).status == "nova"  # a de outra pessoa não é mexida
        db.get(Oportunidade, alheia).status = "descartada"  # não deixa cartão na tela dos outros testes
