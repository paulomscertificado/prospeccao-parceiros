"""Base da Receita: responsável (sócio-administrador) e regime (Simples/MEI), guardando só o necessário (LGPD)."""

import zipfile

from sqlalchemy import select

from app import base_receita
from app.banco import sessao
from app.base_receita import EmpresaReceita


def _zipar(pasta, nome, linhas):
    with zipfile.ZipFile(pasta / nome, "w") as z:
        z.writestr(nome.replace(".zip", ".CSV"),
                   "\n".join(";".join(f'"{c}"' for c in l) for l in linhas).encode("latin-1"))


def _estab(basico, nome, email):
    l = [""] * 30
    l[0], l[1], l[2], l[3], l[4], l[5], l[10], l[11] = basico, "0001", "00", "1", nome, "02", "20150101", "6920601"
    l[19], l[20], l[21], l[22], l[27] = "PE", "2531", "81", basico[-8:], email
    return l


def _socio(basico, tipo, nome, qualificacao, entrada):
    return [basico, tipo, nome, "***123456**", qualificacao, entrada, "", "***000000**", "", "00", "5"]


def test_responsavel_e_regime_da_receita(cliente, tmp_path):
    _zipar(tmp_path, "Municipios.zip", [["2531", "RECIFE"]])
    _zipar(tmp_path, "Estabelecimentos0.zip", [
        _estab("73000001", "CONTABIL SOCIOS UM", "um@socios-teste.com.br"),
        _estab("73000002", "CONTABIL SOCIOS DOIS", "dois@socios-teste.com.br"),
        _estab("73000003", "CONTABIL SOCIOS TRES", "tres@socios-teste.com.br"),
    ])
    _zipar(tmp_path, "Socios0.zip", [
        _socio("73000001", "2", "MARIA SOCIA SIMPLES", "22", "20100101"),          # sócia comum
        _socio("73000001", "2", "JOAO DA SILVA ADMIN", "49", "20150101"),          # sócio-administrador: este
        _socio("73000001", "2", "ANA ANTIGA ADMIN", "49", "20200101"),             # admin mais recente: não
        _socio("73000001", "1", "HOLDING EXEMPLO LTDA", "49", "20000101"),         # pessoa jurídica: não
        _socio("73000002", "2", "CARLOS SOZINHO", "65", "20180101"),               # titular
        _socio("99999999", "2", "FORA DA BASE", "49", "20180101"),                 # empresa que não interessa
    ])
    _zipar(tmp_path, "Simples.zip", [
        ["73000001", "S", "20100101", "00000000", "N", "00000000", "00000000"],
        ["73000002", "S", "20100101", "00000000", "S", "20100101", "00000000"],
        ["73000003", "N", "20100101", "20120101", "N", "00000000", "00000000"],
    ])
    assert base_receita.importar_pasta(str(tmp_path)) == 3
    with sessao() as db:
        e = {x.cnpj_basico: x for x in db.execute(select(EmpresaReceita)).scalars()}
        assert (e["73000001"].socio_admin, e["73000001"].socio_cargo) == ("Joao da Silva Admin", "Sócio-administrador")
        assert e["73000001"].socios_qtd == 4 and e["73000001"].regime == "Simples Nacional"
        assert (e["73000002"].socio_admin, e["73000002"].socio_cargo, e["73000002"].regime) == ("Carlos Sozinho", "Titular", "MEI")
        assert e["73000003"].socio_admin == "" and e["73000003"].regime == "Fora do Simples"
        # LGPD: nada de CPF nem dos outros sócios na base
        colunas = " ".join(c.name for c in EmpresaReceita.__table__.columns)
        assert "cpf" not in colunas and "Maria Socia" not in str([vars(x) for x in e.values()])

        achados = {d["cnpj"][:8]: d for d in base_receita.buscar(db, "Recife", "PE", 10, ["contabil"])}
        um = achados["73000001"]
        assert um["responsavel"] == "Joao da Silva Admin" and um["cargo"] == "Sócio-administrador"
        assert um["regime"] == "Simples Nacional" and um["multiplos_socios"]
        assert achados["73000002"]["regime"] == "MEI" and not achados["73000002"]["multiplos_socios"]


def test_regime_simples():
    assert base_receita.regime_simples("S", "S") == "MEI"
    assert base_receita.regime_simples("S", "N") == "Simples Nacional"
    assert base_receita.regime_simples("N", "N") == "Fora do Simples"


def test_leads_existentes_recebem_responsavel_e_regime(cliente, tmp_path):
    from app.leads_servico import criar_lead
    from app.modelos import Lead, Usuario

    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        lead, _ = criar_lead(db, {"empresa": "Contábil Já Cadastrada", "cnpj": "73.000.001/0001-00"}, admin)
        lead_id = lead.id
    test_responsavel_e_regime_da_receita(cliente, tmp_path)  # importa a base de novo
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        assert lead.responsavel == "Joao da Silva Admin" and lead.cargo == "Sócio-administrador"
        assert lead.regime == "Simples Nacional" and lead.multiplos_socios
