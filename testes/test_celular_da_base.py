"""Celular da base com o 9 da frente e empresa repetida completada pela lista (pedido da Maria em 16/11/2026: nenhuma
campanha da lista da CNPJá saía com WhatsApp, e as empresas já cadastradas apareciam com a origem "base da Receita")."""

import io
from datetime import datetime

from sqlalchemy import select

from app import bases_importadas, campanhas, pesquisa, util
from app.banco import sessao
from app.leads_servico import criar_lead
from app.modelos import Campanha, Historico, Lead, Tarefa, Usuario
from test_bases_importadas import CAB_ESTAB, CAB_SOCIOS, _estab


def test_celular_ganha_o_9_e_fixo_nao_conta():
    assert util.celular("8198887777") == "81998887777"  # formato antigo da Receita
    assert util.celular("8133334444", "8188887777") == "81988887777"  # o fixo vem antes, o celular é o segundo
    assert util.celular("81998887777") == "81998887777"
    assert util.celular("8133334444") == ""  # só fixo
    assert util.celular("", None) == ""


def _com_tel2(linha, tel2):
    linha[CAB_ESTAB.index("Telefone Secundário")] = tel2
    return linha


def _planilha() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    est = wb.active
    est.title = "Estabelecimentos"
    est.append([None, "Estabelecimentos"])
    est.append(CAB_ESTAB)
    contabil = 6920601
    est.append(_estab("82000001000101", "CEL ANTIGO LTDA", "Contabil Celular Antigo", "Ativa", "Recife", "PE", contabil,
                      "a@cel-antigo-teste.com.br", tel="8196771001"))
    est.append(_com_tel2(_estab("82000002000102", "FIXO E CEL LTDA", "Contabil Fixo e Celular", "Ativa", "Recife", "PE",
                                contabil, "b@fixo-cel-teste.com.br", tel="8134771002"), "8196771002"))
    est.append(_com_tel2(_estab("82000003000103", "JA CADASTRADA LTDA", "Contabil Ja Cadastrada", "Ativa", "Recife", "PE",
                                contabil, "c@ja-cadastrada-teste.com.br", tel="8134771003"), "8196771003"))
    est.append(_estab("82000004000104", "MANUAL LTDA", "Contabil Cadastro Manual", "Ativa", "Recife", "PE", contabil,
                      "d@manual-teste.com.br", tel="8134771004"))
    est.append(_estab("82000005000105", "MESMO CONTADOR LTDA", "Contabil Mesmo Contador", "Ativa", "Recife", "PE",
                      contabil, "e@mesmo-contador-teste.com.br", tel="8134771005"))
    soc = wb.create_sheet("Sócios")
    soc.append([None, "Sócios e Administradores"])
    soc.append(CAB_SOCIOS)
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def test_campanha_da_lista_leva_o_celular_e_completa_a_empresa_repetida(cliente, monkeypatch):
    with sessao() as db:
        resumo = bases_importadas.importar(db, "Lista celulares", _planilha(), "celulares.xlsx")
        # já cadastradas antes, como as da busca antiga na base da Receita
        ja, _ = criar_lead(db, {"empresa": "Contabil Ja Cadastrada", "cnpj": "82000003000103",
                                "telefone": "8134771003", "observacoes": "Cliente indicou o contador."}, None,
                           origem="Prospecção: base da Receita Federal")
        manual, _ = criar_lead(db, {"empresa": "Contabil Cadastro Manual", "cnpj": "82000004000104"}, None,
                               origem="Cadastro manual")
        # outra empresa com o telefone do contador da "Mesmo Contador": não pode ganhar os dados dela
        outra, _ = criar_lead(db, {"empresa": "Outra Empresa do Contador", "cnpj": "82000099000199",
                                   "telefone": "8134771005"}, None, origem="Prospecção: base da Receita Federal")
        db.commit()
        ids = {"ja": ja.id, "manual": manual.id, "outra": outra.id}
    base = f"lista:{resumo['base_id']}"

    def pesquisar(db, lead, usar_ia=True):
        from app import score

        lead.pesquisado_em = lead.criado_em
        score.atualizar(db, lead)

    monkeypatch.setattr(pesquisa, "pesquisar_lead", pesquisar)
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        camp = Campanha(nome="Celulares da lista", categorias="contabil", cidade="", estado="PE", quantidade=10,
                        canais="whatsapp,email", status="gerando", usuario_id=admin.id, base=base)
        db.add(camp)
        db.flush()
        cid = camp.id
    campanhas.gerar(cid)
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.status == "aguardando_aprovacao", camp.erro
        leads = {t.lead.empresa: t.lead for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars()}
        origem_lista = "Prospecção: lista Lista celulares (CNPJá)"

        novo = leads["Contabil Celular Antigo"]  # celular sem o 9 no telefone principal
        assert novo.telefone == "(81) 99677-1001" and novo.whatsapp == "(81) 99677-1001"
        assert novo.chave_whatsapp == "81996771001" and novo.origem == origem_lista

        fixo = leads["Contabil Fixo e Celular"]  # fixo no principal, celular no secundário
        assert fixo.telefone == "(81) 3477-1002" and fixo.whatsapp == "(81) 99677-1002"
        assert "(81) 99677-1002" in fixo.observacoes

        ja = db.get(Lead, ids["ja"])  # a mesma empresa (o mesmo cadastro), completada pela lista
        assert leads["Contabil Ja Cadastrada"].id == ja.id
        assert ja.origem == origem_lista
        assert ja.email == "c@ja-cadastrada-teste.com.br" and ja.whatsapp == "(81) 99677-1003"
        assert ja.telefone == "(81) 3477-1003"  # o que já existia não muda
        assert ja.observacoes.startswith("Cliente indicou o contador.")
        nota = db.execute(select(Historico.descricao).where(Historico.lead_id == ja.id,
                                                            Historico.descricao.like("Empresa achada de novo%"))).scalar_one()
        assert 'origem trocada de "Prospecção: base da Receita Federal"' in nota
        assert "e-mail" in nota and "WhatsApp" in nota and "Celulares da lista" in nota

        manual = db.get(Lead, ids["manual"])  # origem que não veio de uma base fica
        assert manual.origem == "Cadastro manual" and manual.email == "d@manual-teste.com.br"

        outra = db.get(Lead, ids["outra"])  # achada pelo telefone (outra empresa): nada da lista entra nela
        assert not outra.email and outra.origem == "Prospecção: base da Receita Federal"
        camp.status = "cancelada"  # não deixa as tarefas na fila dos outros testes
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars():
            t.status = "cancelada"
