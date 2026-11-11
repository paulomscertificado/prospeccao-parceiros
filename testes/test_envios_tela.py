"""Tela Envios (nov/2026): abas Enviados / Próximos envios, grupos por dia, testes da campanha e a situação de cada
toque que ainda vai sair. Caso real: a campanha aprovada às 10:16 mostrava "Hoje 10:28" em Próximos envios e a
equipe achou que tinha saído; o teste das 10:15 aparecia nas Conversas no contato de quem testou. (Desde então as
campanhas de Empresas novas saem sozinhas; o caso do clique continua valendo nas campanhas de parceiros.)"""

from datetime import date, timedelta

from sqlalchemy import select

from app import mensagens
from app.banco import agora, sessao
from app.leads_servico import criar_lead
from app.modelos import Campanha, LogAuditoria, Tarefa, Usuario


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _lead(db, nome, **campos):
    lead, _ = criar_lead(db, {"empresa": nome, "cidade": "Recife", "estado": "PE", **campos}, _admin(db),
                         checar_duplicado=False)
    db.flush()
    return lead


def _aba(html: str, nome: str) -> str:
    """O conteúdo de uma aba (as outras também vêm na página, escondidas)."""
    marcas = {"enviados": "O que a MS mandou, o mais novo primeiro", "proximos": "Toques das campanhas ativas que ainda"}
    return html.split(marcas[nome])[1].split("</section>")[0]


def test_envios_mostra_teste_da_campanha_e_o_que_espera_clique(cliente):
    with sessao() as db:
        admin = _admin(db)
        camp = Campanha(nome="Parceiros Teste Envios Tela", categorias="contabil", cidade="Recife", estado="PE",
                        status="ativa", aprovado_em=agora(), usuario_id=admin.id, tipo="parceiros")
        db.add(camp)
        db.flush()
        frio = _lead(db, "Leandro Frio Envios Tela", whatsapp="81977661234")
        db.add(Tarefa(lead_id=frio.id, campanha_id=camp.id, canal="whatsapp", status="pendente", tipo="prospeccao",
                      data=date.today() - timedelta(days=1), hora="10:28", acao="whatsapp", mensagem="Oi"))
        db.add(LogAuditoria(usuario_id=admin.id, usuario_nome="Paulo Teste", acao="testou_campanha", entidade="campanha",
                            entidade_id=camp.id, detalhes="1 mensagens de whatsapp de teste para 5581993230157"))
        enviado = _lead(db, "Contábil Enviada Ontem Tela", email="o@enviadaontem-tela.com.br")
        m = mensagens.registrar(db, enviado.id, "email", "Olá", None, modo="api", status="enviada", assunto="Parceria",
                                campanha_id=camp.id)
        m.criado_em = agora() - timedelta(days=1)
        db.commit()
        camp_id = camp.id

    pagina = cliente.get("/envios").text
    enviados = _aba(pagina, "enviados")
    # o teste aparece como teste, para quem testou, e deixa claro que não foi para nenhuma empresa
    assert "Teste da campanha" in enviados and "(81) 99323-0157" in enviados and "não foi para nenhuma empresa" in enviados
    assert "Ontem" in enviados and "Contábil Enviada Ontem Tela" in enviados  # agrupado por dia
    # o toque frio cuja hora já passou está em Próximos envios, como atrasado e esperando o clique
    proximos = _aba(cliente.get(f"/envios?aba=proximos&campanha={camp_id}").text, "proximos")
    assert "Leandro Frio Envios Tela" in proximos and "Aguardando seu clique" in proximos and "atrasado há 1 dia" in proximos
    assert "Enviar por WhatsApp" in proximos
    assert 'href="/envios?aba=proximos&amp;quando=ate_hoje&amp;situacao=clique"' in pagina  # atalho no topo

    so_testes = _aba(cliente.get("/envios?status=teste").text, "enviados")
    assert "Teste da campanha" in so_testes and "Contábil Enviada Ontem Tela" not in so_testes
    da_campanha = cliente.get(f"/envios?campanha={camp_id}&aba=proximos").text
    assert "Leandro Frio Envios Tela" in _aba(da_campanha, "proximos")
    # busca sem acento acha "Contábil"
    assert "Contábil Enviada Ontem Tela" in _aba(cliente.get("/envios?busca=contabil enviada ontem").text, "enviados")
    clique = _aba(cliente.get(f"/envios?aba=proximos&situacao=clique&quando=ate_hoje&campanha={camp_id}").text, "proximos")
    assert "Leandro Frio Envios Tela" in clique
    with sessao() as db:  # não deixa o toque na fila dos outros testes
        camp = db.get(Campanha, camp_id)
        camp.status = "pausada"
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp_id)).scalars():
            t.status = "cancelada"


def test_envios_filtros_invalidos_nao_quebram(cliente):
    r = cliente.get("/envios?aba=xx&periodo=zz&status=yy&quando=ww&situacao=vv&campanha=abc")
    assert r.status_code == 200 and "Como funcionam os disparos" in r.text
    assert "4 toques por empresa" in cliente.get("/envios?aba=regras").text
