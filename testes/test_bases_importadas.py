"""Listas de empresas da CNPJá: base separada da Receita, escolhida na campanha e na busca."""

import io
from datetime import datetime

from sqlalchemy import select

from app import bases_importadas, campanhas, pesquisa, util
from app.banco import sessao
from app.modelos import Campanha, Tarefa, Usuario
from conftest import csrf_de

CAB_ESTAB = ["CNPJ", "Razão Social", "Porte Código", "Porte", "Capital Social", "Natureza Jurídica Código",
             "Natureza Jurídica", "Ente Federativo Responsável", "Tipo", "Data de Abertura", "Nome Fantasia",
             "Situação Cadastral Código", "Situação Cadastral", "Situação Cadastral Data", "Situação Motivo Código",
             "Situação Motivo", "Situação Especial Código", "Situação Especial", "Situação Especial Data",
             "Telefone Principal", "Telefone Secundário", "E-mail", "Município IBGE", "Logradouro", "Número",
             "Complemento", "Bairro", "Cidade", "Estado", "CEP", "País Código", "País", "Atividade Principal Código",
             "Atividade Principal", "Última Atualização"]
CAB_SOCIOS = ["CNPJ", "Razão Social", "Data de Entrada", "Tipo", "Nome", "CPF / CNPJ", "Faixa Etária", "País Código",
              "País", "Qualificação Código", "Qualificação", "Representante Nome", "Representante CPF",
              "Representante Qualificação Código", "Representante Qualificação", "Última Atualização"]


def _estab(cnpj, razao, fantasia, situacao, cidade, uf, cnae, email, tel="8130340040"):
    linha = dict.fromkeys(CAB_ESTAB, "-")
    linha.update({"CNPJ": cnpj, "Razão Social": razao, "Nome Fantasia": fantasia, "Situação Cadastral": situacao,
                  "Tipo": "Matriz", "Data de Abertura": datetime(2010, 5, 1), "Telefone Principal": tel,
                  "E-mail": email, "Logradouro": "Rua do Sol", "Número": "10", "Bairro": "Centro", "Cidade": cidade,
                  "Estado": uf, "CEP": "52010000", "Atividade Principal Código": cnae, "Porte": "Micro Empresa"})
    return [linha[c] for c in CAB_ESTAB]


def _socio(cnpj, nome, codigo, tipo="Pessoa Física"):
    linha = dict.fromkeys(CAB_SOCIOS, "-")
    linha.update({"CNPJ": cnpj, "Tipo": tipo, "Nome": nome, "CPF / CNPJ": "***123456**", "Qualificação Código": codigo})
    return [linha[c] for c in CAB_SOCIOS]


def planilha_cnpja() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    est = wb.active
    est.title = "Estabelecimentos"
    est.append([None, "Estabelecimentos"])
    est.append(CAB_ESTAB)
    est.append(_estab("81000001000101", "LISTA CONTABIL UM LTDA", "Lista Contábil Um", "Ativa", "Recife", "PE",
                      6920601, "um@listaum-teste.com.br"))
    est.append(_estab("81000002000102", "LISTA CONDOMINIOS LTDA", "Lista Adm Condomínios", "Ativa", "Recife", "PE",
                      6822600, "dois@listadois-teste.com.br", tel="8132220000"))
    est.append(_estab("81000003000103", "LISTA FECHADA LTDA", "-", "Inapta", "Recife", "PE", 6920601, "tres@x-teste.com.br"))
    est.append(_estab("81000004000104", "LISTA CORRETORA LTDA", "Corretora da Lista", "Ativa", "Belo Horizonte", "MG",
                      6821801, "quatro@listaquatro-teste.com.br", tel="3132220000"))
    soc = wb.create_sheet("Sócios")
    soc.append([None, "Sócios e Administradores"])
    soc.append(CAB_SOCIOS)
    soc.append(_socio("81000001000101", "JOAO DA SILVA", 22))
    soc.append(_socio("81000001000101", "ANA MARIA DE SOUZA", 49))
    soc.append(_socio("81000001000101", "EMPRESA SOCIA SA", 49, tipo="Pessoa Jurídica"))
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def test_le_a_planilha_da_cnpja_so_ativas_e_responsavel():
    empresas, resumo = bases_importadas.ler_planilha_cnpja(planilha_cnpja())
    assert resumo["lidas"] == 4 and resumo["inativas"] == 1 and len(empresas) == 3
    um = next(e for e in empresas if e["cnpj"] == "81000001000101")
    assert um["socio_admin"] == "Ana Maria de Souza" and um["socio_cargo"] == "Sócio-administrador"
    assert um["socios_qtd"] == 3 and um["cnae"] == "6920601" and um["municipio_chave"] == "recife"
    assert um["telefone"] == "8130340040" and um["inicio_atividade"].year == 2010


def test_importa_lista_separada_e_campanha_usa_so_ela(cliente, monkeypatch):
    with sessao() as db:
        resumo = bases_importadas.importar(db, "Lista teste PE & MG", planilha_cnpja(), "lista.xlsx")
        db.commit()
    base = f"lista:{resumo['base_id']}"
    with sessao() as db:
        assert bases_importadas.contar(db, base, "PE", "Recife") == {"contabil": 1, "condominio": 1}
        assert bases_importadas.contar(db, base, "MG") == {"outros": 1}  # corretora: sem segmento → "outros"
        # importar de novo com o mesmo nome troca as empresas (não duplica a lista)
        bases_importadas.importar(db, "Lista teste PE & MG", planilha_cnpja(), "lista.xlsx")
        db.commit()
        assert [b.total for b in bases_importadas.listas(db) if b.nome == "Lista teste PE & MG"] == [3]

    def pesquisar(db, lead, usar_ia=True):
        from app import score

        lead.pesquisado_em = lead.criado_em
        score.atualizar(db, lead)

    monkeypatch.setattr(pesquisa, "pesquisar_lead", pesquisar)
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        camp = Campanha(nome="Da lista", categorias="contabil,condominio", cidade="", estado="PE", quantidade=5,
                        canais="email", status="gerando", usuario_id=admin.id, base=base)
        db.add(camp)
        db.flush()
        cid = camp.id
    campanhas.gerar(cid)
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.status == "aguardando_aprovacao", camp.erro
        assert "2 empresas" in camp.etapa, camp.etapa
        leads = {util.normalizar_cnpj(t.lead.cnpj): t.lead for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars()}
        assert set(leads) == {"81000001000101", "81000002000102"}  # sem a inapta e sem a de MG
        assert leads["81000001000101"].responsavel == "Ana Maria de Souza"
        assert "CNPJá" in leads["81000001000101"].origem
        hora = db.execute(select(Tarefa.hora).where(Tarefa.campanha_id == cid)).scalars().first()
    # a tela da campanha mostra o horário agendado de cada mensagem, além do dia
    import re

    assert re.match(r"\d\d:\d\d$", hora)
    assert f"às {hora}" in cliente.get(f"/campanhas/{cid}").text


def test_telas_escolhem_a_base_e_escondem_a_receita(cliente):
    with sessao() as db:
        lista = next(b for b in bases_importadas.listas(db) if b.nome == "Lista teste PE & MG")
    base = f"lista:{lista.id}"
    pagina = cliente.get(f"/campanhas/nova?base={base}")
    assert 'name="base"' in pagina.text and "Lista teste PE &amp; MG" in pagina.text
    assert cliente.get("/api/contagem", params={"cidade": "", "uf": "PE", "base": base}).json() == \
        {"contabil": 1, "condominio": 1}
    assert f'value="{base}"' in cliente.get("/prospeccao").text

    config = cliente.get("/configuracoes?aba=integracoes")
    assert "Lista teste PE &amp; MG" in config.text
    cliente.post("/configuracoes/listas/receita", data={"csrf": csrf_de(config.text), "ocultar": "1"})
    with sessao() as db:
        assert bases_importadas.receita_oculta(db)
        assert "receita" not in [o["id"] for o in bases_importadas.opcoes(db)]
        assert bases_importadas.escolher(db, "receita") != "receita"
    assert 'value="receita"' not in cliente.get("/prospeccao").text
    cliente.post("/configuracoes/listas/receita", data={"csrf": csrf_de(config.text), "ocultar": "0"})
    with sessao() as db:
        assert not bases_importadas.receita_oculta(db)


def test_importa_pela_tela(cliente):
    pagina = cliente.get("/configuracoes?aba=integracoes")
    r = cliente.post("/configuracoes/listas/importar", data={"csrf": csrf_de(pagina.text), "nome": "Lista pela tela"},
                     files={"arquivo": ("cnpja.xlsx", planilha_cnpja(),
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200 and "importada: 3 empresas ativas" in r.text
    with sessao() as db:
        lista = next(b for b in bases_importadas.listas(db) if b.nome == "Lista pela tela")
        assert lista.estados.startswith("PE 2")
    pagina = cliente.get("/configuracoes?aba=integracoes")
    cliente.post(f"/configuracoes/listas/{lista.id}/apagar", data={"csrf": csrf_de(pagina.text)})
    with sessao() as db:
        assert "Lista pela tela" not in [b.nome for b in bases_importadas.listas(db)]
    with sessao() as db:  # os outros testes esperam o sistema sem listas
        for b in bases_importadas.listas(db):
            bases_importadas.apagar(db, b.id)
        db.commit()
