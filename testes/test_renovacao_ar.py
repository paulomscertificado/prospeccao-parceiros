"""Renovação de uma AR que não é a MS (17-18/11/2026). A Thamires, administradora do Grupo Certy, subiu a planilha e
montou a campanha de renovação, mas o lead e os avisos foram parar na AR MS: o lead criado por um administrador nasce
sem vendedor e a montagem roda em segundo plano, sem a AR da tela. A campanha ficou vazia na tela do Grupo Certy, a
aprovação não achou os avisos (ficaram em rascunho) e ela foi dada como concluída. Aqui: tudo fica na AR da campanha,
a rodada diária da MS não leva os clientes do Grupo Certy, o cliente do Grupo Certy não vira o lead da MS e a campanha
não guarda o número de outra pessoa. CNPJs, celulares e e-mails só destes testes (o banco é dividido: um lead
com o CNPJ de outro teste vira "duplicado" lá).
"""

from sqlalchemy import select

from app import campanhas, renovacao, trabalhos
from app.banco import gravar_config, ler_config, sessao
from app.isolamento import ligar
from app.modelos import Campanha, Certificado, ConexaoWhatsApp, Lead, Tarefa, Tenant, Trabalho, Usuario
from app.seguranca import resumir_senha
from test_renovacao import _SemLinha, _admin, _limpar, _linha, _planilha


def _pessoa(db, nome, email, perfil, empresa) -> Usuario:
    u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
    if u is None:
        u = Usuario(nome=nome, email=email, senha_hash=resumir_senha("senhaRenovAR123"), perfil=perfil,
                    empresa_nome=empresa)
        db.add(u)
        db.flush()
    return u


def _ids_ar(db) -> dict[str, int]:
    return {slug: i for i, slug in db.execute(select(Tenant.id, Tenant.slug))}


def _montar_pelo_trabalho(cid: int) -> None:
    """Como no sistema de verdade: o trabalho em segundo plano (trabalhos.executar) monta a campanha."""
    with sessao() as db:
        tid = db.execute(select(Trabalho.id).where(Trabalho.tipo == "campanha", Trabalho.ref_id == cid)).scalar()
    for _ in range(50):
        if trabalhos.executar(tid, 600) != "continua":
            break


def _importar(db, linhas, quem) -> None:
    renovacao.importar(db, renovacao.ler_planilha("planilha.xlsx", _planilha(linhas))[0], quem)
    db.flush()


def test_campanha_da_administradora_de_outra_ar_fica_toda_nela(cliente, monkeypatch):
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    with sessao() as db:
        _limpar(db)
        certy = _pessoa(db, "Thamires AR", "thamires.ar@grupocerty.com.br", "admin", "Grupo Certy")
        certy_id, ar_certy = certy.id, _ids_ar(db)["grupo-certy"]
        assert certy.tenant_id == ar_certy
    with sessao() as db:  # na tela da Thamires (AR do Grupo Certy)
        certy = db.get(Usuario, certy_id)
        ligar(db, certy)
        _importar(db, [_linha(9, "7700001", "e-CNPJ A1 12 meses", "TESTE CERTY LTDA", "90123456000191",
                              "CLIENTE CERTY", "12345678901", "cliente@testecerty.com.br", "81987710001")], certy)
        camp = renovacao.criar_campanha(db, certy, quantidade=10)
        assert camp is not None
        cid = camp.id
    _montar_pelo_trabalho(cid)
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.tenant_id == ar_certy and camp.status == "aguardando_aprovacao", camp.erro
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars().all()
        assert tarefas and {t.tenant_id for t in tarefas} == {ar_certy}  # antes: AR MS
        lead = tarefas[0].lead
        assert lead.tenant_id == ar_certy and lead.chave_whatsapp == "81987710001"
    with sessao() as db:  # a Thamires aprova na tela dela: os avisos aparecem e passam a valer
        certy = db.get(Usuario, certy_id)
        ligar(db, certy)
        camp = db.get(Campanha, cid)
        campanhas.aprovar(db, camp, certy)
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars().all()
        assert tarefas and all(t.status == "pendente" for t in tarefas)  # antes: ficavam em rascunho
    with sessao() as db:
        _limpar(db)


def test_rodada_diaria_da_ms_nao_leva_os_clientes_de_outra_ar(cliente, monkeypatch):
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    with sessao() as db:
        _limpar(db)
        ids = _ids_ar(db)
        ms = _pessoa(db, "Dono Renovação MS", "dono.renovacao.ms@mscertificados.com.br", "admin",
                     "MS Certificação Digital")
        certy = _pessoa(db, "Admin Certy Rodada", "admin.rodada@grupocerty.com.br", "admin", "Grupo Certy")
        ms_id, certy_id = ms.id, certy.id
        # o mesmo celular já é um lead da MS: o cliente do Grupo Certy não pode virar esse lead
        lead_ms = Lead(empresa="LEAD DA MS COM O MESMO CELULAR", whatsapp="81987710002", tenant_id=ids["ms"],
                       vendedor_id=ms.id)
        db.add(lead_ms)
        db.flush()
        lead_ms_id = lead_ms.id
    with sessao() as db:  # a planilha da MS (sem tela: AR do dono) e a do Grupo Certy (na tela dela)
        _importar(db, [_linha(8, "7700002", "e-CNPJ A1 12 meses", "CLIENTE MS LTDA", "90123456000272", "CLIENTE MS",
                              "98765432100", "cliente@clientems.com.br", "81987710003")], db.get(Usuario, ms_id))
        for c in db.execute(select(Certificado).where(Certificado.protocolo == "7700002")).scalars():
            c.tenant_id = ids["ms"]
    with sessao() as db:
        certy = db.get(Usuario, certy_id)
        ligar(db, certy)
        _importar(db, [_linha(8, "7700003", "e-CNPJ A1 12 meses", "CLIENTE CERTY LTDA", "90123456000353",
                              "CLIENTE CERTY", "44455566677", "cliente@clientecerty.com.br", "81987710002")], certy)
    with sessao() as db:  # a rodada diária: sem tela, em nome do dono da Renovação (da MS)
        camp = renovacao.criar_campanha(db, db.get(Usuario, ms_id), quantidade=10)
        cid = camp.id
        assert camp.tenant_id == ids["ms"]
        da_certy = db.execute(select(Certificado).where(Certificado.protocolo == "7700003")).scalars().one()
        assert da_certy.tenant_id == ids["grupo-certy"]
    _montar_pelo_trabalho(cid)
    with sessao() as db:
        presos = {c.protocolo for c in db.execute(select(Certificado).where(Certificado.campanha_id == cid)).scalars()}
        assert presos == {"7700002"}  # antes: levava também o 7700003, do Grupo Certy
        assert {t.tenant_id for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars()} == {ids["ms"]}
    with sessao() as db:  # agora a campanha do Grupo Certy, com o celular que também é lead da MS
        certy = db.get(Usuario, certy_id)
        ligar(db, certy)
        camp = renovacao.criar_campanha(db, certy, quantidade=10)
        cid_certy = camp.id
    _montar_pelo_trabalho(cid_certy)
    with sessao() as db:
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid_certy)).scalars().all()
        assert tarefas and {t.lead_id for t in tarefas} != {lead_ms_id}
        assert all(t.lead.tenant_id == ids["grupo-certy"] for t in tarefas)  # um lead novo, do Grupo Certy
        assert not db.execute(select(Tarefa).where(Tarefa.lead_id == lead_ms_id)).first()  # o da MS ficou como estava
        _limpar(db)


def test_campanha_nao_guarda_o_numero_de_outra_pessoa(cliente, monkeypatch):
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    with sessao() as db:
        _limpar(db)
        antes = ler_config(db, "renov_conexao")
        dono_do_numero = _pessoa(db, "Paulo Número MS", "paulo.numero@mscertificados.com.br", "vendedor",
                                 "MS Certificação Digital")
        certy = _pessoa(db, "Thamires Número", "thamires.numero@grupocerty.com.br", "admin", "Grupo Certy")
        for cid_, dono in (("u-renov-ms", dono_do_numero), ("u-renov-certy", certy)):
            if db.get(ConexaoWhatsApp, cid_) is None:
                db.add(ConexaoWhatsApp(id=cid_, nome=f"WhatsApp de {dono.nome}", dono_id=dono.id))
        certy_id = certy.id
    try:
        for protocolo, celular, numero, esperado in (
                # o número da configuração da Renovação é de outra pessoa (como o do Paulo Lucas em 17/11/2026):
                # a campanha fica no automático (no envio, o número de quem monta)
                ("7700004", "81987710004", "u-renov-ms", ""),
                ("7700005", "81987710005", "u-renov-certy", "u-renov-certy")):  # o número é dela: fica gravado
            with sessao() as db:  # a planilha na tela dela
                certy = db.get(Usuario, certy_id)
                ligar(db, certy)
                _importar(db, [_linha(9, protocolo, "e-CNPJ A1 12 meses", f"CLIENTE {protocolo} LTDA",
                                      "90123456000434", f"CLIENTE {protocolo}", "77788899900",
                                      f"cliente{protocolo}@numerocerty.com.br", celular)], certy)
            with sessao() as db:  # sem a AR da tela, como a rodada diária
                gravar_config(db, "renov_conexao", numero)
                camp = renovacao.criar_campanha(db, db.get(Usuario, certy_id), quantidade=10)
                assert camp is not None and camp.conexao_id == esperado, numero
                _limpar(db)
    finally:
        with sessao() as db:
            gravar_config(db, "renov_conexao", antes)
            _limpar(db)
