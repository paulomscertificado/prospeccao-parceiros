"""Campanhas não podem parar por causa de UMA empresa (site quebrado) nem ficar "prontas" com 0 empresas."""

import zipfile

import httpx
import pytest
from sqlalchemy import select

from app import base_receita, campanhas, pesquisa, prospeccao
from app.banco import sessao
from app.modelos import Campanha, Historico, Lead, Tarefa, Usuario


def _zipar(pasta, nome, linhas):
    with zipfile.ZipFile(pasta / nome, "w") as z:
        z.writestr(nome.replace(".zip", ".CSV"),
                   "\n".join(";".join(f'"{c}"' for c in l) for l in linhas).encode("latin-1"))


def _estab(basico, nome, email, bairro="CENTRO"):
    l = [""] * 30
    l[0], l[1], l[2], l[3], l[4], l[5], l[10], l[11] = basico, "0001", "00", "1", nome, "02", "20150101", "6920601"
    l[17], l[19], l[20], l[21], l[22], l[27] = bairro, "PE", "2531", "81", basico[-8:], email
    return l


def test_site_que_redireciona_para_um_email_nao_quebra_a_leitura(monkeypatch):
    """O site da CT Contábil redireciona para "/contato@ctcontabil.com.br": o httpx levanta ValueError."""
    original = httpx.Client.get

    def get_com_defeito(self, url, *a, **k):
        raise ValueError("unknown url type: '/contato@ctcontabil.com.br'")

    monkeypatch.setattr(httpx.Client, "get", get_com_defeito)
    assert pesquisa.ler_site("https://www.ctcontabil.com.br") == {}
    assert prospeccao.dados_do_site("https://www.ctcontabil.com.br") == {}
    assert prospeccao.descobrir_site("CT Contabil", "claudio@ctcontabil.com.br") == ""
    monkeypatch.setattr(httpx.Client, "get", original)


def test_uma_empresa_com_problema_nao_trava_a_campanha(cliente, tmp_path, monkeypatch):
    _zipar(tmp_path, "Municipios.zip", [["2531", "RECIFE"]])
    _zipar(tmp_path, "Estabelecimentos0.zip", [
        _estab("74000001", "CONTABIL PROBLEMA SITE", "a@problema-teste.com.br", "BOA VIAGEM"),
        _estab("74000002", "CONTABIL TUDO CERTO", "b@tudocerto-teste.com.br", "BOA VIAGEM"),
    ])
    base_receita.importar_pasta(str(tmp_path))

    def pesquisar(db, lead, usar_ia=True):
        if "Problema" in lead.empresa:
            raise ValueError("unknown url type: '/contato@problema-teste.com.br'")
        from app import score

        lead.pesquisado_em = lead.criado_em
        score.atualizar(db, lead)

    monkeypatch.setattr(pesquisa, "pesquisar_lead", pesquisar)
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        # "Boa Viagem" é bairro de Recife, não cidade: a busca procura pelo bairro
        camp = Campanha(nome="Boa Viagem", categorias="contabil", cidade="boa viagem", estado="PE", quantidade=5,
                        canais="email", status="gerando", usuario_id=admin.id)
        db.add(camp)
        db.flush()
        cid = camp.id
    campanhas.gerar(cid)
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.status == "aguardando_aprovacao", camp.erro
        empresas = {t.lead.empresa for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars()}
        assert {"Contabil Problema Site", "Contabil Tudo Certo"} <= empresas  # a com problema segue com os dados da Receita
        problema = db.execute(select(Lead).where(Lead.empresa == "Contabil Problema Site")).scalars().one()
        assert db.execute(select(Historico).where(Historico.lead_id == problema.id,
                                                  Historico.descricao.like("Não foi possível pesquisar%"))).first()


def test_regiao_sem_empresas_avisa_em_vez_de_ficar_pronta_vazia(cliente):
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        camp = Campanha(nome="Lugar que não existe", categorias="contabil", cidade="Cidade Inventada", estado="PE",
                        quantidade=5, canais="email", status="gerando", usuario_id=admin.id)
        db.add(camp)
        db.flush()
        cid = camp.id
    with pytest.raises(RuntimeError, match="Não encontrei empresas novas"):
        campanhas.gerar(cid)


def test_campanhas_seguidas_pegam_empresas_diferentes(cliente, tmp_path, monkeypatch):
    from app import score

    _zipar(tmp_path, "Municipios.zip", [["2531", "RECIFE"]])
    _zipar(tmp_path, "Estabelecimentos0.zip", [
        _estab(f"7500000{i}", f"CONTABIL DIFERENTE {i}", f"c{i}@diferente{i}-teste.com.br", "GRACAS") for i in range(1, 9)])
    base_receita.importar_pasta(str(tmp_path))

    def pesquisar(db, lead, usar_ia=True):
        lead.pesquisado_em = lead.criado_em
        score.atualizar(db, lead)

    monkeypatch.setattr(pesquisa, "pesquisar_lead", pesquisar)
    empresas = []
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        ids = []
        for n in (1, 2, 3):
            camp = Campanha(nome=f"Graças {n}", categorias="contabil", cidade="gracas", estado="PE", quantidade=2,
                            canais="email", status="gerando", usuario_id=admin.id)
            db.add(camp)
            db.flush()
            ids.append(camp.id)
    for cid in ids:
        campanhas.gerar(cid)
        with sessao() as db:
            empresas.append({t.lead.empresa for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars()})
    assert all(len(e) == 2 for e in empresas), empresas
    assert not (empresas[0] & empresas[1]) and not (empresas[0] & empresas[2]) and not (empresas[1] & empresas[2])
    # campanha cancelada libera as empresas para uma campanha nova
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        campanhas.cancelar(db, db.get(Campanha, ids[0]), admin)
        camp = Campanha(nome="Graças 4", categorias="contabil", cidade="gracas", estado="PE", quantidade=2,
                        canais="email", status="gerando", usuario_id=admin.id)
        db.add(camp)
        db.flush()
        cid = camp.id
    campanhas.gerar(cid)
    with sessao() as db:
        quarta = {t.lead.empresa for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars()}
    assert quarta and not (quarta & (empresas[1] | empresas[2]))
