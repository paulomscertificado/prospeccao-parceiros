"""Feriados de cada pessoa (pedido da Maria em 18/11/2026: "tem municípios que têm feriados, e isso impactaria nas
campanhas"; no mesmo dia: "pesquise e cadastre logo de todo o Brasil"). Valem os nacionais + os do estado e da cidade
onde a pessoa trabalha (cadastro): os de todo o Brasil vêm da base (app/feriados_brasil.json) e cada marca acerta em
Configurações > Feriados. Nesses dias as campanhas dela não marcam nem mandam toques e a agenda dela não oferece
reunião."""

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from app import agenda_horarios, campanhas, feriados, util
from app.banco import sessao
from app.isolamento import ligar
from app.modelos import Campanha, Configuracao, ConfiguracaoAR, Lead, Tarefa, Usuario
from app.seguranca import resumir_senha

SENHA = "senhaFeriado123"


def _sem_listas():
    with sessao() as db:
        db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.chave == feriados.CHAVE))
        db.execute(delete(Configuracao).where(Configuracao.chave == feriados.CHAVE))


@pytest.fixture(autouse=True)
def listas_limpas(cliente):  # cliente: o banco de teste já existe
    """Cada teste começa e termina sem listas de feriados (os outros testes marcam toques em dias úteis)."""
    _sem_listas()
    yield
    _sem_listas()


def _dia_util(d: date) -> date:
    """O primeiro dia de semana a partir de `d` que não é feriado nacional."""
    while d.weekday() >= 5 or d in util.feriados_nacionais(d.year):
        d += timedelta(days=1)
    return d


def _pessoa(db, nome, email, empresa="MS Certificação Digital", perfil="vendedor", cidade="", uf="") -> Usuario:
    u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
    if u is None:
        u = Usuario(nome=nome, email=email, senha_hash=resumir_senha(SENHA), perfil=perfil, empresa_nome=empresa)
        db.add(u)
        db.flush()
    u.cidade, u.uf = cidade, uf
    return u


def _gravar_da_ar(pessoa_id: int, listas: dict) -> None:
    """Grava as listas na marca (AR) da pessoa, como a tela dela faz."""
    with sessao() as db:
        ligar(db, db.get(Usuario, pessoa_id))
        feriados.gravar_locais(db, listas)


def test_ler_a_lista_escrita_na_tela():
    itens, ruins = feriados.ler_lista("16/07 Nossa Senhora do Carmo\n08/12/2026 – Conceição; 31/02 errado\nabc\n-24/06\n")
    assert itens == [(16, 7, None, "Nossa Senhora do Carmo"), (8, 12, 2026, "Conceição"), (24, 6, None, feriados.TIRAR)]
    assert ruins == ["31/02 errado", "abc"]
    assert feriados.texto_da_lista(itens) == "-24/06\n16/07 Nossa Senhora do Carmo\n08/12/2026 Conceição"
    assert feriados.chave_do_local("pe", "  Recife ") == "PE/RECIFE"
    assert feriados.chave_do_local("MG", "São João del-Rei") == "MG/SAO JOAO DEL-REI"
    assert feriados.chave_do_local("XX", "Recife") == "" and feriados.chave_do_local("PE") == "PE"


def test_base_tem_todo_o_brasil_e_confere_o_nome_da_cidade():
    base = feriados.base()
    assert len(base["cidades"]) == 5570 and len(base["estados"]) >= 20  # os 5.570 municípios do IBGE
    assert ("15/08", "Assunção de Nossa Senhora") in feriados._base_na_tela("MG/BELO HORIZONTE")
    assert ("06/03", "Revolução Pernambucana") in feriados._base_na_tela("PE")
    assert feriados.conferir_cidade("pe", "  recife ") == ("Recife", "")
    assert feriados.conferir_cidade("SP", "sao paulo") == ("São Paulo", "")  # o nome como o IBGE escreve
    nome, aviso = feriados.conferir_cidade("PE", "Recifee")
    assert nome == "Recifee" and "Você quis dizer Recife?" in aviso
    assert feriados.conferir_cidade("", "Recife")[1] == "Escolha também a UF da cidade."


def test_feriados_da_pessoa_vem_da_base_com_os_acertos_da_marca_dela(cliente):
    ano = date.today().year
    with sessao() as db:
        ana = _pessoa(db, "Ana Feriado", "ana.feriado@mscertificados.com.br", cidade="Recife", uf="PE")
        bia = _pessoa(db, "Bia Feriado", "bia.feriado@grupocerty.com.br", "Grupo Certy", cidade="Recife", uf="PE")
        caio = _pessoa(db, "Caio Feriado", "caio.feriado@mscertificados.com.br")  # sem cidade no cadastro
        ids = ana.id, bia.id, caio.id
    with sessao() as db:  # só a base (nenhuma marca acertou nada ainda)
        dias = feriados.da_pessoa(db, db.get(Usuario, ids[0]))
        assert dias[date(ano, 7, 16)] == "Nossa Senhora do Carmo"  # Recife
        assert date(ano, 12, 8) in dias and date(ano, 3, 6) in dias  # Recife e o estado de Pernambuco
        assert date(ano, 8, 15) not in dias  # é de Belo Horizonte, não de Recife
    _gravar_da_ar(ids[0], {"PE/RECIFE": "02/02 Acerto da MS\n-16/07\n-25/12"})
    _gravar_da_ar(ids[1], {"PE/RECIFE": "03/03 Acerto do Grupo Certy"})
    with sessao() as db:  # sem tela (como as filas): cada pessoa com os acertos da marca dela
        ana, bia, caio = (db.get(Usuario, i) for i in ids)
        dias_ana, dias_bia, dias_caio = (feriados.da_pessoa(db, p) for p in (ana, bia, caio))
        assert date(ano, 2, 2) in dias_ana and date(ano, 3, 3) not in dias_ana  # o acerto do Grupo Certy não vale na MS
        assert date(ano, 7, 16) not in dias_ana  # a MS tirou o 16/07 da base
        assert date(ano, 12, 25) in dias_ana  # um feriado nacional nunca sai
        assert date(ano, 3, 3) in dias_bia and date(ano, 7, 16) in dias_bia  # o Grupo Certy segue a base
        assert date(ano, 12, 25) in dias_caio and date(ano, 7, 16) not in dias_caio  # sem cidade: só os nacionais
        assert feriados.feriado_do_dia(db, bia, date(ano + 1, 7, 16)) == "Nossa Senhora do Carmo"  # vale todo ano


def test_campanha_toques_e_reunioes_pulam_o_feriado_da_cidade_de_quem_envia(cliente):
    alvo = _dia_util(date.today() + timedelta(days=3))
    with sessao() as db:
        ana = _pessoa(db, "Ana Feriado", "ana.feriado@mscertificados.com.br", cidade="Recife", uf="PE")
        bruno = _pessoa(db, "Bruno Feriado", "bruno.feriado@mscertificados.com.br", cidade="Belo Horizonte", uf="MG")
        ana.expediente = "seg-dom 09:00-12:00"
        ana_id, bruno_id = ana.id, bruno.id
    _gravar_da_ar(ana_id, {"PE/RECIFE": f"{alvo:%d/%m/%Y} Feriado de teste"})
    with sessao() as db:
        ana, bruno = db.get(Usuario, ana_id), db.get(Usuario, bruno_id)
        camp = Campanha(nome="Campanha do feriado", status="ativa", usuario_id=ana.id)
        camp_bruno = Campanha(nome="Campanha do Bruno", status="ativa", usuario_id=bruno.id)
        db.add_all([camp, camp_bruno])
        db.flush()
        assert alvo in campanhas._feriados(db, camp)  # a campanha nova não marca toque no feriado dela
        assert date(alvo.year, 12, 25) in campanhas._feriados(db, camp)  # e nem nos nacionais (antes: só a Renovação)
        assert alvo not in campanhas._feriados(db, camp_bruno)
        lead = Lead(empresa="Empresa do Feriado Ltda", whatsapp="81987730001", vendedor_id=ana.id)
        lead_bruno = Lead(empresa="Empresa do Bruno Ltda", whatsapp="31987730002", vendedor_id=bruno.id)
        db.add_all([lead, lead_bruno])
        db.flush()
        seguinte = _dia_util(alvo + timedelta(days=1))
        tarefas = [Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal=canal, data=dia, hora=hora,
                          status="pendente", usuario_id=ana.id, mensagem="Olá")
                   for canal, dia, hora in (("whatsapp", alvo, "16:40"), ("email", alvo, "16:40"),
                                            ("whatsapp", seguinte, "09:05"))]
        do_bruno = Tarefa(tipo="prospeccao", lead_id=lead_bruno.id, campanha_id=camp_bruno.id, canal="whatsapp",
                          data=alvo, hora="10:00", status="pendente", usuario_id=bruno.id, mensagem="Olá")
        db.add_all([*tarefas, do_bruno])
        db.flush()
        ids = [t.id for t in tarefas], do_bruno.id, camp.id, camp_bruno.id
        # a agenda da Ana não oferece reunião no feriado
        horarios = agenda_horarios.horarios_livres(db, ana, dias=10, quantidade=500)
        assert horarios and not any(h.date() == alvo for h in horarios)
    with sessao() as db:  # a rotina de hora em hora (e a tela, ao salvar): os toques do feriado mudam de dia
        assert feriados.remarcar(db) >= 2
    with sessao() as db:
        zap, email, prox = (db.get(Tarefa, i) for i in ids[0])
        dias_ana = feriados.da_pessoa(db, db.get(Usuario, ana_id))
        for t in (zap, email):
            assert t.data > alvo and t.data not in dias_ana and t.status == "pendente"
        assert (prox.data, prox.hora) >= (zap.data, zap.hora)  # o toque seguinte nunca fica antes do que mudou
        assert db.get(Tarefa, ids[1]).data == alvo  # o Bruno (Belo Horizonte) não tem esse feriado
        # a fila, na hora de enviar, adia o toque que ainda estiver num feriado de quem envia
        zap.data = alvo
        assert feriados.adiar_se_feriado(db, zap, hoje=alvo) == "Feriado de teste" and zap.data > alvo
        assert feriados.adiar_se_feriado(db, db.get(Tarefa, ids[1]), hoje=alvo) == ""
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id.in_(ids[2:]))).scalars():
            t.status = "cancelada"  # não ficam para os outros testes
        for cid in ids[2:]:
            db.get(Campanha, cid).status = "cancelada"


def test_telas_da_cidade_e_dos_feriados(cliente, csrf):
    with sessao() as db:
        vera = _pessoa(db, "Vera Feriado", "vera.feriado@mscertificados.com.br", cidade="Olinda", uf="PE")
        vera_id = vera.id
    pagina = cliente.get("/configuracoes?aba=feriados")
    assert pagina.status_code == 200 and "Feriados nacionais" in pagina.text and "5.570" in pagina.text
    assert 'name="local__PE/OLINDA"' in pagina.text and "Vera Feriado" in pagina.text
    assert "Aniversário da Cidade de Olinda" in pagina.text  # o que vem da base aparece no quadro da cidade
    # consulta de qualquer cidade do Brasil
    pagina = cliente.get("/configuracoes?aba=feriados&uf=MG&cidade=belo+horizonte")
    assert "Belo Horizonte (MG)" in pagina.text and "Assunção de Nossa Senhora" in pagina.text
    assert "Você quis dizer Recife?" in cliente.get("/configuracoes?aba=feriados&uf=PE&cidade=Recifee").text
    # linha que não dá para entender: nada é salvo
    r = cliente.post("/configuracoes/feriados", data={"csrf": csrf, "local__PE/OLINDA": "dia de São Bento"})
    assert "Não entendi" in r.text
    with sessao() as db:
        assert feriados.locais(db, None) == {}
    r = cliente.post("/configuracoes/feriados", data={
        "csrf": csrf, "local__PE/OLINDA": "-10/11\n20/11/2026 Ponto facultativo", "nova_uf": "MG",
        "nova_cidade": "Belo Horizonte", "nova_lista": "16/11/2026 Ponto facultativo"})
    assert "Feriados salvos" in r.text
    with sessao() as db:
        salvas = feriados.locais(db, db.get(Usuario, vera_id).tenant_id)
        assert salvas["PE/OLINDA"] == "-10/11\n20/11/2026 Ponto facultativo"
        assert salvas["MG/BELO HORIZONTE"] == "16/11/2026 Ponto facultativo"
        dias = feriados.da_pessoa(db, db.get(Usuario, vera_id))
        assert date(date.today().year, 3, 12) in dias and date(date.today().year, 11, 10) not in dias
    # a cidade no cadastro da pessoa (Configurações > Usuários): fica com o nome do IBGE
    r = cliente.post(f"/configuracoes/usuarios/{vera_id}", data={
        "csrf": csrf, "nome": "Vera Feriado", "email": "vera.feriado@mscertificados.com.br", "perfil": "vendedor",
        "ativo": "on", "cidade": "  recife ", "uf": "pe"})
    assert "Usuário salvo" in r.text
    with sessao() as db:
        vera = db.get(Usuario, vera_id)
        assert (vera.cidade, vera.uf) == ("Recife", "PE")
    # e em Minha conta (a própria pessoa)
    pagina = cliente.get("/minha-conta")
    assert 'action="/minha-conta/cidade"' in pagina.text
    r = cliente.post("/minha-conta/cidade", data={"csrf": csrf, "cidade": "Recife", "uf": ""})
    assert "Escolha também a UF" in r.text
    r = cliente.post("/minha-conta/cidade", data={"csrf": csrf, "cidade": "Recifee", "uf": "PE"})
    assert "Cidade salva" in r.text and "Você quis dizer Recife?" in r.text
    r = cliente.post("/minha-conta/cidade", data={"csrf": csrf, "cidade": "recife", "uf": "PE"})
    assert "Cidade salva" in r.text and "Você quis dizer" not in r.text
    with sessao() as db:
        eu = db.execute(select(Usuario).where(Usuario.email == "admin@teste.com.br")).scalars().one()
        assert (eu.cidade, eu.uf) == ("Recife", "PE")
        eu.cidade, eu.uf = "", ""
