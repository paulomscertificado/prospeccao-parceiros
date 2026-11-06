"""Empresas novas: busca diária na API da CNPJá (simulada) → leads → campanha de venda aguardando aprovação."""

from datetime import date, timedelta

from sqlalchemy import select

from app import campanhas, config, empresas_novas, sdr
from app.banco import gravar_config, sessao
from app.modelos import Campanha, Lead, Tarefa, Trabalho, Usuario


def _registro(cnpj, nome, area="81", numero="91363335", email="contato@novaempresa.com.br", natureza=2062):
    return {"taxId": cnpj, "founded": date.today().isoformat(), "alias": None,
            "company": {"name": nome, "nature": {"id": natureza, "text": "Sociedade Empresária Limitada"},
                        "size": {"text": "Microempresa"}},
            "address": {"city": "Recife", "state": "PE", "street": "Rua A", "number": "10", "district": "Boa Viagem",
                        "zip": "51000000"},
            "phones": [{"type": "MOBILE", "area": area, "number": numero}] if numero else [],
            "emails": [{"address": email}] if email else [],
            "mainActivity": {"id": 4120400, "text": "Construção de edifícios"}}


class _Resposta:
    def __init__(self, dados, status=200):
        self.dados, self.status_code, self.headers, self.text = dados, status, {"content-type": "application/json"}, ""

    def json(self):
        return self.dados


def test_celular_ganha_o_nono_digito():
    assert empresas_novas.celular("81", "91363335") == "81991363335"
    assert empresas_novas.celular("81", "991363335") == "81991363335"
    assert empresas_novas.celular("81", "33231234") == ""  # fixo


def test_busca_monta_campanha_de_venda(cliente, monkeypatch):
    pedidos = []

    def falso(url, params=None, headers=None, timeout=None):
        pedidos.append((url, dict(params or {})))
        if url.endswith("/credit"):
            return _Resposta({"perpetual": 100, "transient": 2400})
        if (params or {}).get("token"):
            return _Resposta({"records": [_registro("44444444000144", "QUARTA EMPRESA LTDA")], "next": None})
        return _Resposta({"records": [
            _registro("11111111000111", "NOVA CONSTRUTORA LTDA"),
            _registro("22222222000122", "JOAO DA SILVA", natureza=2135, email=""),
            _registro("33333333000133", "SEM CONTATO LTDA", numero="", email=""),
            _registro("11111111000111", "NOVA CONSTRUTORA LTDA"),  # repetida
        ], "next": "abc"})

    monkeypatch.setattr(empresas_novas.httpx, "get", falso)
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        gravar_config(db, "novas_sem_individual", "1")
        gravar_config(db, "novas_maximo_dia", "60")
        r = empresas_novas.buscar_e_criar(db, admin, date.today() - timedelta(days=1), date.today())
        cid = r["campanha_id"]
    assert r["encontradas"] == 5 and cid
    assert pedidos[0][1]["founded.gte"] == (date.today() - timedelta(days=1)).isoformat()
    assert pedidos[0][1]["address.state.in"] == "PE" and pedidos[0][1]["status.id.in"] == "2"
    assert "mainActivity.id.in" not in pedidos[0][1]  # qualquer atividade: toda empresa nova precisa de e-CNPJ

    with sessao() as db:  # montagem em etapas (aqui roda direto, como o agendador faria)
        t = db.execute(select(Trabalho).where(Trabalho.ref_id == cid, Trabalho.tipo == "campanha")).scalars().first()
        import json

        estado = json.loads(t.estado)
    while not campanhas.etapa_gerar(cid, None, estado, float("inf")):
        pass
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.tipo == "empresas_novas" and camp.status == "aguardando_aprovacao", camp.erro
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars().all()
        empresas = {t.lead.empresa for t in tarefas}
        assert empresas == {"Nova Construtora Ltda", "Quarta Empresa Ltda", "Sem Contato Ltda"} or \
            {e.upper() for e in empresas} == {"NOVA CONSTRUTORA LTDA", "QUARTA EMPRESA LTDA", "SEM CONTATO LTDA"}
        lead = db.execute(select(Lead).where(Lead.cnpj.like("11.111.111%"))).scalars().first()
        assert lead.origem == empresas_novas.ORIGEM and lead.whatsapp == "(81) 99136-3335"
        primeira = [t for t in tarefas if t.lead_id == lead.id and t.angulo == "venda_boas_vindas"][0]
        assert "R$" not in primeira.mensagem_whatsapp and "acabou de abrir" in primeira.mensagem_whatsapp
        assert len([t for t in tarefas if t.lead_id == lead.id]) == 3  # dia 1, 3 e 7
        assert lead.reservado_por_id == admin_id(db)


def admin_id(db):
    return db.execute(select(Usuario.id).where(Usuario.perfil == "admin")).scalar()


def test_preco_pode_na_venda_mas_nao_na_parceria():
    assert sdr.texto_sem_spam("e-CNPJ A1: R$ 200")
    assert not sdr.texto_seguro("e-CNPJ A1: R$ 200")
    assert not sdr.texto_sem_spam("Promoção imperdível")


def test_rodada_diaria_respeita_horario_e_roda_uma_vez(cliente, monkeypatch):
    chamadas = []
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    monkeypatch.setattr(empresas_novas, "buscar_e_criar",
                        lambda db, u, desde, ate, automatica=False: chamadas.append((desde, ate))
                        or {"encontradas": 0, "campanha_id": None})
    with sessao() as db:
        for c, v in [("novas_ativo", "1"), ("novas_hora", "00:00"), ("novas_dono_id", str(admin_id(db))),
                     ("novas_ultima_busca", ""), ("novas_ultima_data", (date.today() - timedelta(days=2)).isoformat())]:
            gravar_config(db, c, v)
    empresas_novas.rodada_diaria()
    empresas_novas.rodada_diaria()  # mesma data: não busca de novo
    assert chamadas == [(date.today() - timedelta(days=1), date.today())]
    with sessao() as db:
        gravar_config(db, "novas_ativo", "0")


def test_erro_da_api_vira_aviso(cliente, monkeypatch):
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-errada")
    monkeypatch.setattr(empresas_novas.httpx, "get", lambda *a, **k: _Resposta({"message": "invalid"}, 401))
    try:
        empresas_novas.saldo()
        assert False
    except empresas_novas.ErroCnpja as erro:
        assert "chave" in str(erro)


def test_tela_abre_e_salva_configuracao(cliente, monkeypatch):
    from conftest import csrf_de

    pagina = cliente.get("/empresas-novas")
    assert pagina.status_code == 200 and "Empresas novas" in pagina.text and "Mensagens de venda" in pagina.text
    monkeypatch.setattr(empresas_novas.arquivo_env if hasattr(empresas_novas, "arquivo_env") else empresas_novas,
                        "__doc__", empresas_novas.__doc__)
    with sessao() as db:
        uid = admin_id(db)
    r = cliente.post("/empresas-novas/configurar", data={"csrf": csrf_de(pagina.text), "ufs": "pe, pb", "maximo_dia": "40",
                                                         "hora": "08:00", "dono_id": str(uid), "canal_email": "on"})
    assert r.status_code in (200, 303)
    with sessao() as db:
        assert empresas_novas.cfg(db, "novas_ufs") == "PE,PB" and empresas_novas.cfg(db, "novas_canais") == "email"
        gravar_config(db, "novas_ufs", "PE")
        gravar_config(db, "novas_canais", "whatsapp,email")


def test_teste_da_api_com_10_empresas_e_lista_de_exclusao(cliente, monkeypatch):
    """Teste: 10 empresas (1 crédito), lista guardada para conferir; quem está numa lista importada fica de fora."""
    from conftest import csrf_de

    from app import bases_importadas
    from app.modelos import BuscaCnpja, EmpresaCnpja

    pedidos = []

    def falso(url, params=None, headers=None, timeout=None):
        pedidos.append(dict(params or {}))
        registros = [_registro(f"5555555500{i:02d}{i:02d}", f"CONTABIL NOVA {i} LTDA") for i in range(10)]
        registros[0]["phones"] = [{"type": "LANDLINE", "area": "81", "number": "33231234"},
                                  {"type": "MOBILE", "area": "81", "number": "991112222"}]
        registros[0]["emails"] = [{"address": "a@contabilnova-teste.com.br"}, {"address": "b@contabilnova-teste.com.br"}]
        return _Resposta({"records": registros, "next": "mais"})

    monkeypatch.setattr(empresas_novas.httpx, "get", falso)
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    with sessao() as db:
        lista = bases_importadas.BaseDados(nome="Lista antiga", total=1)
        db.add(lista)
        db.flush()
        db.add(bases_importadas.EmpresaBase(base_id=lista.id, cnpj="55555555000101", uf="PE"))
        gravar_config(db, "novas_excluir_listas", "1")
        db.commit()
    pagina = cliente.get("/empresas-novas")
    assert "Testar (10 empresas" in pagina.text
    r = cliente.post("/empresas-novas/testar", data={"csrf": csrf_de(pagina.text)})
    assert r.status_code == 200 and "Teste feito: 10 empresas" in r.text
    assert len(pedidos) == 1 and pedidos[0]["limit"] == 10  # uma página só: 1 crédito
    with sessao() as db:
        busca = db.execute(select(BuscaCnpja).order_by(BuscaCnpja.id.desc())).scalars().first()
        assert busca.teste and busca.encontradas == 10 and busca.creditos == 1 and busca.fora == 1
        assert busca.campanha_id is None  # o teste não cria campanha sozinho
        primeira = db.execute(select(EmpresaCnpja).where(EmpresaCnpja.busca_id == busca.id,
                                                         EmpresaCnpja.cnpj == "55555555000000")).scalars().one()
        assert primeira.telefones_fixos == "8133231234" and primeira.celulares == "81991112222"
        assert primeira.emails == "a@contabilnova-teste.com.br,b@contabilnova-teste.com.br"
        excluida = db.execute(select(EmpresaCnpja).where(EmpresaCnpja.cnpj == "55555555000101")).scalars().one()
        assert "Lista antiga" in excluida.motivo_fora
        bid = busca.id
    tela = cliente.get(f"/empresas-novas/busca/{bid}")
    assert "CONTABIL NOVA 0 LTDA" in tela.text and "(81) 3323-1234" in tela.text and "Lista antiga" in tela.text
    try:
        with sessao() as db:  # dados que vão para o lead: telefone fixo, celular (WhatsApp) e o 1º e-mail
            dados = empresas_novas.para_lead(primeira_linha(db, bid))
            assert dados["telefone"] == "8133231234" and dados["whatsapp"] == "81991112222"
            assert dados["email"] == "a@contabilnova-teste.com.br" and "b@contabilnova-teste.com.br" in dados["observacoes"]
        cliente.post(f"/empresas-novas/busca/{bid}/campanha", data={"csrf": csrf_de(tela.text)})
        with sessao() as db:
            busca = db.get(BuscaCnpja, bid)
            camp = db.get(Campanha, busca.campanha_id)
            assert camp.tipo == "empresas_novas"
            # a montagem roda em segundo plano: confere pela lista (9 entram; a da lista antiga fica de fora)
            assert db.execute(select(EmpresaCnpja).where(EmpresaCnpja.busca_id == bid,
                                                         EmpresaCnpja.motivo_fora == "")).scalars().all().__len__() == 9
    finally:
        with sessao() as db:  # os outros testes esperam o sistema sem listas
            db.execute(bases_importadas.EmpresaBase.__table__.delete())
            db.execute(bases_importadas.BaseDados.__table__.delete())
            db.commit()


def primeira_linha(db, bid):
    from app.modelos import EmpresaCnpja

    return db.execute(select(EmpresaCnpja).where(EmpresaCnpja.busca_id == bid,
                                                 EmpresaCnpja.cnpj == "55555555000000")).scalars().one()


def test_chave_da_cnpja_em_configuracoes_e_painel_novo(cliente, monkeypatch):
    """A chave saiu de Empresas novas e foi para Configurações > Integrações; o painel tem estados por caixinha."""
    from conftest import csrf_de

    from app import arquivo_env

    gravadas = []
    monkeypatch.setattr(arquivo_env, "gravar", lambda valores: gravadas.append(valores))  # não mexe no .env real
    pagina = cliente.get("/configuracoes?aba=integracoes")
    assert 'id="cnpja"' in pagina.text and "Salvar chave" in pagina.text
    cliente.post("/configuracoes/cnpja", data={"csrf": csrf_de(pagina.text), "chave": "curta"})
    assert gravadas == []  # chave incompleta não é salva
    cliente.post("/configuracoes/cnpja", data={"csrf": csrf_de(pagina.text), "chave": "a" * 40 + "-" + "b" * 30})
    assert gravadas == [{"CNPJA_API_KEY": "a" * 40 + "-" + "b" * 30}]
    with sessao() as db:
        from app.modelos import LogAuditoria

        log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "salvou_chave_cnpja")).scalars().first()
        assert log and "aaaa" not in (log.detalhes or "")  # a chave nunca vai para o log

    tela = cliente.get("/empresas-novas")
    assert 'name="chave"' not in tela.text and 'class="interruptor"' in tela.text and 'name="ufs" value="MG"' in tela.text
    with sessao() as db:
        uid = admin_id(db)
    cliente.post("/empresas-novas/configurar", data={"csrf": csrf_de(tela.text), "ufs": ["PE", "MG", "XX"],
                                                     "maximo_dia": "30", "hora": "07:00", "dono_id": str(uid),
                                                     "canal_email": "on"})
    with sessao() as db:
        assert empresas_novas.cfg(db, "novas_ufs") == "PE,MG"
        gravar_config(db, "novas_ufs", "PE")
        gravar_config(db, "novas_canais", "whatsapp,email")
