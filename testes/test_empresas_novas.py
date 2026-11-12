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
    from app import trabalhos

    class _SemLinha:  # a montagem roda aqui embaixo, não numa linha de execução paralela (evita corrida no teste)
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
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
        primeira = [t for t in tarefas if t.lead_id == lead.id and t.angulo == "venda_boas_vindas"
                    and t.canal == "whatsapp"][0]
        assert "R$" not in primeira.mensagem_whatsapp and "acabou de abrir" in primeira.mensagem_whatsapp
        dela = [t for t in tarefas if t.lead_id == lead.id]
        # a empresa tem celular e e-mail: os 3 toques (dia 1, 3 e 7) saem pelo WhatsApp E pelo e-mail (pedido da Maria
        # em 12/11/2026), com o WhatsApp primeiro: o e-mail de cada toque fica para depois do WhatsApp do mesmo toque
        assert sorted(t.canal for t in dela) == ['email'] * 3 + ['whatsapp'] * 3
        for angulo in ("venda_boas_vindas", "venda_lembrete", "venda_ultimo"):
            zap = [t for t in dela if t.angulo == angulo and t.canal == "whatsapp"][0]
            mail = [t for t in dela if t.angulo == angulo and t.canal == "email"][0]
            assert (mail.data, mail.hora) > (zap.data, zap.hora), angulo
            assert mail.assunto and mail.mensagem and "R$" not in mail.mensagem
            assert zap.mensagem_email == "" and not mail.mensagem_whatsapp  # cada mensagem num canal só
        zap = [t for t in dela if t.angulo == 'venda_boas_vindas' and t.canal == 'whatsapp'][0]
        assert 'acabou de abrir' in zap.mensagem and zap.assunto == ''
        sem_zap = [t for t in tarefas if 'Sem Contato' in t.lead.empresa or 'SEM CONTATO' in t.lead.empresa]
        assert {t.canal for t in sem_zap} == {'whatsapp'}  # sem e-mail nem celular: só o toque a pesquisar
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
    hoje = date.today()
    with sessao() as db:
        for c, v in [("novas_ativo", "1"), ("novas_hora", "00:00"), ("novas_dono_id", str(admin_id(db))),
                     ("novas_ultima_busca", ""), ("novas_ultima_data", (hoje - timedelta(days=5)).isoformat())]:
            gravar_config(db, c, v)
    empresas_novas.rodada_diaria()
    empresas_novas.rodada_diaria()  # mesma data: não busca de novo
    # continua do dia seguinte ao último buscado e vai até 2 dias atrás (atraso da Receita)
    assert chamadas == [(hoje - timedelta(days=4), hoje - timedelta(days=2))]
    with sessao() as db:
        assert empresas_novas.cfg(db, "novas_ultima_data") == (hoje - timedelta(days=2)).isoformat()
        gravar_config(db, "novas_ultima_busca", "")
    empresas_novas.rodada_diaria()  # de novo no mesmo dia (ex.: busca apagada): esses dias já foram, não repete
    assert len(chamadas) == 1
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



def test_teste_olha_um_dia_diferente_e_busca_nao_repete_empresa(cliente, monkeypatch):
    """Antes o teste pedia sempre "os últimos 7 dias" e vinha a mesma lista. E empresa que já entrou em campanha não
    pode entrar de novo noutra busca."""
    from app.modelos import BuscaCnpja, EmpresaCnpja

    pedidos = []

    def falso(url, params=None, headers=None, timeout=None):
        pedidos.append(dict(params or {}))
        return _Resposta({"records": [_registro("77777777000177", "REPETIDA LTDA"),
                                      _registro("88888888000188", "NOVA DE VERDADE LTDA")], "next": None})

    monkeypatch.setattr(empresas_novas.httpx, "get", falso)
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    hoje = date.today()
    with sessao() as db:
        admin = db.get(Usuario, admin_id(db))
        primeiro = empresas_novas.testar(db, admin)
        segundo = empresas_novas.testar(db, admin)
        assert primeiro["dia"] != segundo["dia"] and hoje - timedelta(days=10) <= segundo["dia"] < hoje
        assert pedidos[0]["founded.gte"] == pedidos[0]["founded.lte"] == primeiro["dia"].isoformat()  # um dia só
        assert pedidos[1]["founded.gte"] == pedidos[1]["founded.lte"] == segundo["dia"].isoformat()
        # teste que não virou campanha não bloqueia a busca diária
        assert db.get(BuscaCnpja, segundo["busca_id"]).fora == 0
        # a 1ª busca vira campanha: as mesmas empresas numa busca seguinte ficam de fora
        empresas_novas.criar_campanha_da_busca(db, db.get(BuscaCnpja, primeiro["busca_id"]), admin)
        gravar_config(db, "novas_maximo_dia", "60")
        r = empresas_novas.buscar_e_criar(db, admin, hoje - timedelta(days=3), hoje - timedelta(days=2))
        assert pedidos[-1]["limit"] == 120  # pede à CNPJá só o dobro do máximo da campanha (economiza crédito)
        assert r["fora"] == 2 and r["campanha_id"] is None
        motivos = {e.motivo_fora for e in db.execute(select(EmpresaCnpja).where(EmpresaCnpja.busca_id == r["busca_id"])).scalars()}
        assert all(m.startswith("já veio na busca de") for m in motivos)


def test_empresa_baixada_fica_de_fora_mesmo_vindo_da_api(cliente, monkeypatch):
    """Caso real (10/11): a busca pede só ativas, mas a CNPJá devolveu uma empresa "Baixada"."""
    from app.modelos import EmpresaCnpja

    baixada = _registro("66666666000166", "BAIXADA NO MESMO DIA LTDA")
    baixada["status"] = {"id": 8, "text": "Baixada"}
    ativa = _registro("67676767000167", "ATIVA DE VERDADE LTDA")
    ativa["status"] = {"id": 2, "text": "Ativa"}
    monkeypatch.setattr(empresas_novas.httpx, "get",
                        lambda *a, **k: _Resposta({"records": [baixada, ativa], "next": None}))
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    with sessao() as db:
        admin = db.get(Usuario, admin_id(db))
        r = empresas_novas.testar(db, admin)
        linhas = {e.cnpj: e.motivo_fora for e in db.execute(
            select(EmpresaCnpja).where(EmpresaCnpja.busca_id == r["busca_id"])).scalars()}
    assert "Baixada" in linhas["66666666000166"] and linhas["67676767000167"] == ""


def test_buscar_de_novo_nao_paga_quem_ja_veio(cliente, monkeypatch):
    """Pedido da Maria: buscar mais de uma vez no dia não pode gastar crédito com as mesmas empresas. Depois de cada
    busca, todos os CNPJs vão para uma lista na CNPJá, e a pesquisa seguinte manda essa lista em taxId.nin."""
    from app.modelos import BuscaCnpja

    monkeypatch.setattr(config, "LISTA_EXCLUSAO_CNPJA", True)
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    pesquisas, listas = [], []
    ja_veio = {"90000001000101", "90000002000102"}

    def get(url, params=None, headers=None, timeout=None):
        pesquisas.append(dict(params or {}))
        excluir = bool((params or {}).get("taxId.nin"))
        registros = [_registro(c, f"EMPRESA {c[-4:]} LTDA") for c in sorted(ja_veio) if not excluir]
        registros.append(_registro(f"9000000{len(pesquisas)}000199", f"NOVA {len(pesquisas)} LTDA"))
        for r in registros:
            r["founded"] = params["founded.gte"]  # abertas no dia pesquisado (como a CNPJá devolve)
        return _Resposta({"records": registros, "next": None})

    def request(metodo, url, params=None, json=None, headers=None, timeout=None):
        listas.append((metodo, url.rsplit("/", 2)[-2:], len((json or {}).get("items", []))))
        return _Resposta({"id": "11111111-2222-3333-4444-555555555555"})

    monkeypatch.setattr(empresas_novas.httpx, "get", get)
    monkeypatch.setattr(empresas_novas.httpx, "request", request)
    with sessao() as db:
        gravar_config(db, "novas_lista_exclusao", "")
        admin = db.get(Usuario, admin_id(db))
        primeiro = empresas_novas.testar(db, admin)  # 3 empresas (teste, sem campanha)
        assert "taxId.nin" not in pesquisas[0]  # 1ª vez: ainda não existe lista
        assert listas[0][0] == "POST"  # criou a lista na CNPJá com os CNPJs que vieram
        assert empresas_novas.cfg(db, "novas_lista_exclusao") == "11111111-2222-3333-4444-555555555555"
        dia = primeiro["dia"]
        r = empresas_novas.buscar_e_criar(db, admin, dia, dia)  # buscar de novo o mesmo dia
        assert pesquisas[1]["taxId.nin"] == "11111111-2222-3333-4444-555555555555"
        assert r["pagas"] == 1  # a CNPJá só devolveu (e cobrou) a empresa nova
        assert r["encontradas"] == 4  # + as 3 do teste, reaproveitadas sem gastar crédito
        assert listas[-1][0] == "PATCH"  # a lista na CNPJá ganhou os CNPJs novos
        assert db.get(BuscaCnpja, r["busca_id"]).creditos == 1
        gravar_config(db, "novas_lista_exclusao", "")


class _SemLinhaParalela:  # a montagem roda aqui embaixo, não numa linha de execução paralela (evita corrida no teste)
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


def test_buscar_agora_com_a_quantidade_escolhida(cliente, monkeypatch):
    """Pedido da Maria (12/11/2026): no "Buscar agora" o usuário escolhe quantas empresas buscar (10, 20, 30, 40, 50 ou
    100). A CNPJá recebe exatamente esse número e a campanha leva todas as que vierem. Antes pedia o dobro do máximo por
    dia e a campanha só levava o máximo (em 11/11 cada busca pagou 20 empresas e usou 10)."""
    import json

    from conftest import csrf_de

    from app import trabalhos
    from app.modelos import BuscaCnpja

    pedidos = []

    def falso(url, params=None, headers=None, timeout=None):
        pedidos.append(dict(params or {}))
        return _Resposta({"records": [_registro(f"5{i:07d}000199", f"EMPRESA ESCOLHIDA {i} LTDA")
                                      for i in range(int(params["limit"]))], "next": None})

    monkeypatch.setattr(empresas_novas.httpx, "get", falso)
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinhaParalela)
    with sessao() as db:
        maximo_antes = empresas_novas.cfg(db, "novas_maximo_dia")
        gravar_config(db, "novas_maximo_dia", "10")  # o máximo por dia agora é só da busca automática
        gravar_config(db, "novas_sem_individual", "0")
    pagina = cliente.get("/empresas-novas")
    for q in (10, 20, 30, 40, 50, 100):
        assert f'name="quantidade" value="{q}"' in pagina.text
    assert 'name="quantidade" value="10" checked' in pagina.text  # já vem marcado o que gasta menos
    dia = date.today() - timedelta(days=40)  # longe dos dias dos outros testes (nada reaproveitado)
    r = cliente.post("/empresas-novas/buscar", data={"csrf": csrf_de(pagina.text), "desde": dia.isoformat(),
                                                      "ate": dia.isoformat(), "quantidade": "30"})
    assert r.status_code == 200 and "Você pediu 30 empresas: 30 encontradas" in r.text
    assert len(pedidos) == 1 and pedidos[0]["limit"] == 30  # exatamente 30 (3 créditos), não o dobro do máximo
    with sessao() as db:
        busca = db.execute(select(BuscaCnpja).order_by(BuscaCnpja.id.desc())).scalars().first()
        assert busca.encontradas == 30 and busca.creditos == 3 and busca.fora == 0 and busca.campanha_id
        cid = busca.campanha_id
        assert db.get(Campanha, cid).quantidade == 30
        t = db.execute(select(Trabalho).where(Trabalho.ref_id == cid, Trabalho.tipo == "campanha")).scalars().first()
        estado = json.loads(t.estado)
    while not campanhas.etapa_gerar(cid, None, estado, float("inf")):
        pass
    with sessao() as db:
        leads = set(db.execute(select(Tarefa.lead_id).where(Tarefa.campanha_id == cid)).scalars())
        assert len(leads) == 30  # todas as que vieram (e foram pagas) entraram na campanha
    # valor fora da lista (página antiga ou mexida) vira 10, o que gasta menos
    cliente.post("/empresas-novas/buscar", data={"csrf": csrf_de(pagina.text), "desde": dia.isoformat(),
                                                 "ate": dia.isoformat(), "quantidade": "1000"})
    assert pedidos[-1]["limit"] == 10
    with sessao() as db:
        gravar_config(db, "novas_maximo_dia", maximo_antes)


def test_campanha_da_lista_leva_todas_as_empresas_da_lista(cliente, monkeypatch):
    """O botão "Montar a campanha com estas empresas" (lista de um teste) leva todas as que podem entrar, mesmo com o
    máximo por dia menor: elas já foram pagas."""
    from app import trabalhos
    from app.modelos import BuscaCnpja

    monkeypatch.setattr(empresas_novas.httpx, "get", lambda *a, **k: _Resposta({"records": [
        _registro(f"6{i:07d}000199", f"EMPRESA DA LISTA {i} LTDA") for i in range(10)], "next": None}))
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinhaParalela)
    with sessao() as db:
        maximo_antes = empresas_novas.cfg(db, "novas_maximo_dia")
        gravar_config(db, "novas_maximo_dia", "4")
        admin = db.get(Usuario, admin_id(db))
        r = empresas_novas.testar(db, admin)
        camp = empresas_novas.criar_campanha_da_busca(db, db.get(BuscaCnpja, r["busca_id"]), admin)
        assert r["encontradas"] == 10 and camp.quantidade == 10
        gravar_config(db, "novas_maximo_dia", maximo_antes)


def _lead_teste(db, nome, email, whatsapp):
    from app.leads_servico import criar_lead

    admin = db.get(Usuario, admin_id(db))
    lead, _ = criar_lead(db, {"empresa": nome, "cidade": "Recife", "estado": "PE", "email": email,
                              "whatsapp": whatsapp}, admin, checar_duplicado=False)
    db.flush()
    return lead


def test_fila_de_email_espera_o_whatsapp_das_empresas_novas(cliente, monkeypatch):
    """Pedido da Maria (12/11/2026): nas Empresas novas o e-mail também sai, mas o WhatsApp tem prioridade. A fila de
    e-mail só solta o e-mail do toque depois que o WhatsApp da empresa saiu. WhatsApp travado (atrasado mais de 2
    dias, esperando clique) ou com o campo em branco não segura o e-mail."""
    from app import mensagens
    from app.banco import agora, ler_config
    from app.integracoes import email_smtp
    from app.rotas import fila

    enviados = []
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **k: enviados.append(para) or "id-teste")
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    hoje = date.today()
    chaves = ("limite_hora_email", "limite_diario_email", "horas_entre_contatos", "horas_entre_contatos_email")
    with sessao() as db:
        antes = {c: ler_config(db, c) for c in chaves}
        gravar_config(db, "limite_hora_email", str(mensagens.enviadas_na_hora(db, "email") + 100))
        gravar_config(db, "limite_diario_email", "100000")
        gravar_config(db, "horas_entre_contatos", "0")
        gravar_config(db, "horas_entre_contatos_email", "0")
        admin = db.get(Usuario, admin_id(db))
        camp = Campanha(nome="Empresas novas prioridade do WhatsApp", tipo="empresas_novas", canais="whatsapp,email",
                        status="ativa", usuario_id=admin.id, aprovado_em=agora())
        db.add(camp)
        db.flush()
        com_zap = _lead_teste(db, "Prioridade Zap Ltda", "contato@prioridade-zap-teste.com.br", "81991112222")
        em_branco = _lead_teste(db, "Zap Em Branco Ltda", "contato@zap-em-branco-teste.com.br", "")
        travado = _lead_teste(db, "Zap Travado Ltda", "contato@zap-travado-teste.com.br", "81993334444")

        def toque(lead, canal, data, hora):
            t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, usuario_id=admin.id, canal=canal,
                       data=data, hora=hora, status="pendente", angulo="venda_boas_vindas",
                       assunto="Certificado digital" if canal == "email" else "", mensagem="Olá! Teste de prioridade.",
                       mensagem_email="Olá! Teste de prioridade." if canal == "email" else "",
                       assunto_email="Certificado digital" if canal == "email" else "",
                       mensagem_whatsapp="Olá! Teste de prioridade." if canal == "whatsapp" else "")
            db.add(t)
            db.flush()
            return t.id

        zap = toque(com_zap, "whatsapp", hoje, "00:01")
        mail = toque(com_zap, "email", hoje, "00:02")
        toque(em_branco, "whatsapp", hoje, "00:01")  # campo WhatsApp em branco: não segura o e-mail
        mail_em_branco = toque(em_branco, "email", hoje, "00:02")
        toque(travado, "whatsapp", hoje - timedelta(days=3), "09:07")  # travado esperando clique: não segura
        mail_travado = toque(travado, "email", hoje - timedelta(days=3), "11:11")
        cid = camp.id
    with sessao() as db:
        tarefas = [db.get(Tarefa, i) for i in (zap, mail, mail_em_branco, mail_travado)]
        assert campanhas.emails_que_esperam_whatsapp(db, tarefas) == {mail}
        _, motivo = fila._situacao(db.get(Tarefa, mail), hoje, True, set(), True, True, espera_whatsapp={mail})
        assert "depois do WhatsApp" in motivo
        campanhas.processar_fila(db, maximo=500)
    with sessao() as db:
        assert db.get(Tarefa, mail).status == "pendente"  # o WhatsApp da empresa ainda não saiu: o e-mail espera
        assert db.get(Tarefa, mail_em_branco).status == "feita" and db.get(Tarefa, mail_travado).status == "feita"
        db.get(Tarefa, zap).status = "feita"  # o WhatsApp saiu
    with sessao() as db:
        campanhas.processar_fila(db, maximo=500)
    with sessao() as db:
        assert db.get(Tarefa, mail).status == "feita"  # agora o e-mail sai
        assert "contato@prioridade-zap-teste.com.br" in enviados
        camp = db.get(Campanha, cid)
        camp.status = "cancelada"  # nada desta campanha fica para os outros testes
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid, Tarefa.status == "pendente")).scalars():
            t.status = "cancelada"
        for c, v in antes.items():
            gravar_config(db, c, v)


def test_incluir_emails_em_campanha_montada_antes(cliente):
    """Campanha de Empresas novas montada antes de 12/11/2026 (só WhatsApp para quem tem celular): incluir_emails cria
    o e-mail de cada toque que ainda não saiu, depois do WhatsApp e com o texto de e-mail guardado no toque. Rodar de
    novo não duplica; empresa sem e-mail e toque que já saiu ficam como estão."""
    with sessao() as db:
        admin = db.get(Usuario, admin_id(db))
        camp = Campanha(nome="Empresas novas montada antes", tipo="empresas_novas", canais="whatsapp,email",
                        status="aguardando_aprovacao", usuario_id=admin.id)
        db.add(camp)
        db.flush()
        com_email = _lead_teste(db, "Antiga Com Email Ltda", "contato@antiga-com-email-teste.com.br", "81995556666")
        sem_email = _lead_teste(db, "Antiga Sem Email Ltda", "", "81997778888")
        amanha = date.today() + timedelta(days=1)

        def toque(lead, status, angulo):
            t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, usuario_id=admin.id, canal="whatsapp",
                       data=amanha, hora="10:07", status=status, angulo=angulo, mensagem="Olá pelo WhatsApp",
                       mensagem_whatsapp="Olá pelo WhatsApp", mensagem_email="Olá pelo e-mail",
                       assunto_email="Certificado digital")
            db.add(t)
            db.flush()
            return t

        zap = toque(com_email, "rascunho", "venda_boas_vindas")
        ja_saiu = toque(com_email, "feita", "venda_lembrete")
        toque(sem_email, "rascunho", "venda_boas_vindas")
        assert empresas_novas.incluir_emails(db, camp) == 1
        mail = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.canal == "email")).scalars().one()
        assert mail.lead_id == com_email.id and mail.status == "rascunho" and mail.angulo == "venda_boas_vindas"
        assert (mail.data, mail.hora) > (zap.data, zap.hora)  # depois do WhatsApp do mesmo toque
        assert mail.mensagem == "Olá pelo e-mail" and mail.assunto == "Certificado digital"
        assert zap.mensagem_email == "" and ja_saiu.mensagem_email == "Olá pelo e-mail"
        assert empresas_novas.incluir_emails(db, camp) == 0  # rodar de novo não duplica
        camp.status = "cancelada"
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id,
                                                 Tarefa.status.in_(("rascunho", "pendente")))).scalars():
            t.status = "cancelada"
