"""Minha fila (nov/2026): próximos envios por dia, filtros por período, situação, campanha e busca, e abas."""

from datetime import date, timedelta

from sqlalchemy import select

from app.banco import agora, sessao
from app.leads_servico import criar_lead
from app.modelos import Campanha, Tarefa, Usuario


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _lead(db, nome, **campos):
    lead, _ = criar_lead(db, {"empresa": nome, "cidade": "Recife", "estado": "PE", **campos}, _admin(db),
                         checar_duplicado=False)
    db.flush()
    return lead


def _toque(db, camp, lead, canal, dias, hora):
    db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal=canal, status="pendente", tipo="prospeccao",
                  data=date.today() + timedelta(days=dias), hora=hora, acao=canal, mensagem="Oi"))


def _secao_proximos(html: str) -> str:
    """Só a aba Próximos envios (as outras abas também vêm na página, escondidas)."""
    return html.split('aria-label="Campanha"')[1].split("<section")[0]


def test_fila_agrupa_por_dia_e_filtra(cliente):
    with sessao() as db:
        admin = _admin(db)
        camp = Campanha(nome="Fila Filtros Alfa", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        aprovado_em=agora(), usuario_id=admin.id)
        outra = Campanha(nome="Fila Filtros Beta", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                         aprovado_em=agora(), usuario_id=admin.id)
        db.add_all([camp, outra])
        db.flush()
        _toque(db, camp, _lead(db, "Atrasada Sem Zap Filtro"), "whatsapp", -2, "10:15")
        _toque(db, camp, _lead(db, "Hoje Email Filtro", email="hoje@hojeemailfiltro.com.br"), "email", 0, "23:58")
        _toque(db, camp, _lead(db, "Amanha Email Filtro", email="a@amanhaemailfiltro.com.br"), "email", 1, "09:12")
        _toque(db, outra, _lead(db, "Futura Com Zap Filtro", whatsapp="81977660123"), "whatsapp", 3, "14:40")
        db.commit()
        camp_id, outra_id = camp.id, outra.id

    pagina = cliente.get("/fila").text
    proximos = _secao_proximos(pagina)
    for nome in ("Atrasada Sem Zap Filtro", "Hoje Email Filtro", "Amanha Email Filtro", "Futura Com Zap Filtro"):
        assert nome in proximos, nome
    # um grupo por dia, na ordem em que vão sair
    assert proximos.index("Atrasados") < proximos.index("Hoje Email Filtro") < proximos.index("Amanha Email Filtro")
    assert "atrasado há 2 dias" in proximos
    # WhatsApp em branco: em vez de um botão que não funciona, o atalho para cadastrar o número
    assert "Cadastrar WhatsApp" in proximos and "WhatsApp em branco" in proximos

    amanha = _secao_proximos(cliente.get("/fila?periodo=amanha").text)
    assert "Amanha Email Filtro" in amanha and "Hoje Email Filtro" not in amanha and "Atrasada Sem Zap Filtro" not in amanha

    atrasados = _secao_proximos(cliente.get("/fila?periodo=atrasados").text)
    assert "Atrasada Sem Zap Filtro" in atrasados and "Amanha Email Filtro" not in atrasados

    sem_zap = _secao_proximos(cliente.get("/fila?situacao=sem_whatsapp").text)
    assert "Atrasada Sem Zap Filtro" in sem_zap and "Futura Com Zap Filtro" not in sem_zap

    busca = _secao_proximos(cliente.get("/fila?busca=futura com zap").text)
    assert "Futura Com Zap Filtro" in busca and "Hoje Email Filtro" not in busca

    por_campanha = _secao_proximos(cliente.get(f"/fila?campanha={outra_id}").text)
    assert "Futura Com Zap Filtro" in por_campanha and "Amanha Email Filtro" not in por_campanha
    assert f'<option value="{camp_id}" ' in por_campanha  # a outra campanha continua na lista para trocar

    nada = cliente.get("/fila?busca=empresa que nao existe xyz").text
    assert "Nenhum envio com esses filtros" in nada and "Limpar filtros" in nada


def test_fila_abas_e_atalhos_dos_numeros(cliente):
    pagina = cliente.get("/fila").text
    # os números do topo levam ao filtro certo
    assert 'href="/fila?periodo=atrasados"' in pagina and 'href="/fila?periodo=ate_hoje"' in pagina
    assert 'href="/fila?aba=historico"' in pagina
    # a aba escolhida aparece; as outras ficam escondidas
    historico = cliente.get("/fila?aba=historico").text
    assert "<section hidden>" in historico and "Histórico dos envios" in historico
    assert cliente.get("/fila?aba=nao-existe&periodo=errado&situacao=x").status_code == 200
