"""Empresas novas: as de maior capital social primeiro (pedido da Maria em 23/11/2026: "sempre dar preferência às
empresas que tenham o maior capital social"). A CNPJá não ordena a pesquisa: a busca pede faixa por faixa de capital
(company.equity.gte/lte), da mais alta para a mais baixa, e a campanha começa pelas de maior capital."""

import json
from datetime import date, timedelta

from sqlalchemy import select

from app import campanhas, config, empresas_novas, trabalhos
from app.banco import gravar_config, sessao
from app.modelos import BuscaCnpja, EmpresaCnpja, Lead, Tarefa, Trabalho, Usuario


def _empresa(cnpj, nome, capital, celular="91363335", email="contato@capital-teste.com.br", fundada=None):
    return {"taxId": cnpj, "founded": (fundada or date.today()).isoformat(), "alias": None,
            "company": {"name": nome, "equity": capital,
                        "nature": {"id": 2062, "text": "Sociedade Empresária Limitada"}, "size": {"text": "Demais"}},
            "address": {"city": "Recife", "state": "PE", "street": "Rua B", "number": "1", "district": "Centro",
                        "zip": "50000000"},
            "phones": [{"type": "MOBILE", "area": "81", "number": celular}] if celular else [],
            "emails": [{"address": email}] if email else [],
            "status": {"id": 2, "text": "Ativa"},
            "mainActivity": {"id": 4120400, "text": "Construção de edifícios"}}


class _Resposta:
    def __init__(self, dados, status=200, texto=""):
        self.dados, self.status_code, self.text = dados, status, texto
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self.dados


def _cnpja(empresas, pedidos, recusar_capital=False):
    """CNPJá simulada: respeita o filtro de capital e o limit, como a de verdade (que não ordena nada)."""
    def get(url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        pedidos.append(params)
        gte, lte = params.get("company.equity.gte"), params.get("company.equity.lte")
        if recusar_capital and (gte is not None or lte is not None):
            return _Resposta({"message": "company.equity.gte must be a number"}, 400,
                             '{"message":"company.equity.gte must be a number"}')
        achadas = [e for e in empresas if (gte is None or e["company"]["equity"] >= float(gte))
                   and (lte is None or e["company"]["equity"] <= float(lte))]
        return _Resposta({"records": achadas[:int(params.get("limit", 10))], "next": None})
    return get


class _SemLinhaParalela:  # a montagem roda aqui embaixo, não numa linha de execução paralela
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _montar(cid) -> list[str]:
    """Monta a campanha como o agendador faria e devolve a ordem das empresas que ela recebeu da busca."""
    with sessao() as db:
        t = db.execute(select(Trabalho).where(Trabalho.ref_id == cid, Trabalho.tipo == "campanha")).scalars().first()
        estado = json.loads(t.estado)
    ordem = [r["empresa"] for r in estado["registros"]]
    while not campanhas.etapa_gerar(cid, None, estado, float("inf")):
        pass
    return ordem


def _preparar(monkeypatch, empresas, pedidos, **k):
    monkeypatch.setattr(empresas_novas.httpx, "get", _cnpja(empresas, pedidos, **k))
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinhaParalela)


def test_faixas_de_capital_da_maior_para_a_menor_sem_sobreposicao():
    faixas = empresas_novas.faixas_de_capital()
    assert faixas[0] == {"company.equity.gte": 1_000_000}
    assert faixas[1] == {"company.equity.gte": 500_000, "company.equity.lte": 999_999.99}
    assert faixas[-1] == {"company.equity.lte": 999.99}  # a última pega também as de capital zero
    pisos = [f.get("company.equity.gte", 0) for f in faixas]
    assert pisos == sorted(pisos, reverse=True) and len(set(pisos)) == len(pisos)
    for de_cima, de_baixo in zip(faixas, faixas[1:]):
        assert de_baixo["company.equity.lte"] == round(de_cima["company.equity.gte"] - 0.01, 2)


def test_buscar_agora_traz_primeiro_as_de_maior_capital(cliente, monkeypatch):
    pedidos = []
    _preparar(monkeypatch, [_empresa("73000001000101", "PEQUENA LTDA", 5_000),
                            _empresa("73000002000102", "GRANDE LTDA", 2_500_000),
                            _empresa("73000003000103", "MEDIA LTDA", 150_000),
                            _empresa("73000004000104", "MEDIA DOIS LTDA", 60_000),
                            _empresa("73000005000105", "MEDIA TRES LTDA", 60_000),
                            _empresa("73000006000106", "CAPITAL ZERO LTDA", 0)], pedidos)
    dia = date.today() - timedelta(days=50)  # longe dos dias dos outros testes (nada reaproveitado)
    with sessao() as db:
        r = empresas_novas.buscar_e_criar(db, _admin(db), dia, dia, quantidade=3)
        busca = db.get(BuscaCnpja, r["busca_id"])
        # da faixa mais alta para a mais baixa, parando quando completou as 3: as de menos de R$ 50 mil nem foram
        # pedidas (nem pagas)
        assert [p.get("company.equity.gte") for p in pedidos] == [1_000_000, 500_000, 200_000, 100_000, 50_000]
        assert [p["limit"] for p in pedidos] == [3, 2, 2, 2, 1]
        assert r["pagas"] == 3 and busca.encontradas == 3 and busca.creditos == 3  # 1 crédito por pedido com empresa
        lista = db.execute(select(EmpresaCnpja).where(EmpresaCnpja.busca_id == busca.id)
                           .order_by(EmpresaCnpja.id)).scalars().all()
        assert [(e.razao_social, e.capital) for e in lista] == [
            ("GRANDE LTDA", 2_500_000), ("MEDIA LTDA", 150_000), ("MEDIA DOIS LTDA", 60_000)]
        cid = r["campanha_id"]
    assert _montar(cid) == ["GRANDE LTDA", "MEDIA LTDA", "MEDIA DOIS LTDA"]
    tela = cliente.get(f"/empresas-novas/busca/{r['busca_id']}").text
    assert "Capital social" in tela and "do maior capital social para o menor" in tela
    assert tela.index("R$ 2.500.000,00") < tela.index("R$ 150.000,00") < tela.index("R$ 60.000,00")
    with sessao() as db:
        lead = db.execute(select(Lead).where(Lead.chave_cnpj == "73000002000102")).scalars().one()
        assert "Capital social: R$ 2.500.000,00." in lead.observacoes


def test_campanha_automatica_leva_as_de_maior_capital_entre_quem_tem_contato(cliente, monkeypatch):
    """A busca automática pede o dobro do máximo por dia e a campanha leva o máximo: as de maior capital que a
    campanha consegue alcançar (celular ou e-mail). Só telefone fixo fica por último, mesmo com capital maior."""
    pedidos = []
    _preparar(monkeypatch, [_empresa("73100001000101", "SO TELEFONE FIXO LTDA", 900_000, celular="", email=""),
                            _empresa("73100002000102", "ALTA COM ZAP LTDA", 300_000),
                            _empresa("73100003000103", "SO EMAIL LTDA", 80_000, celular=""),
                            _empresa("73100004000104", "MENOR COM ZAP LTDA", 40_000),
                            _empresa("73100005000105", "PEQUENA COM ZAP LTDA", 10_000)], pedidos)
    dia = date.today() - timedelta(days=52)
    with sessao() as db:
        maximo_antes = empresas_novas.cfg(db, "novas_maximo_dia")
        gravar_config(db, "novas_maximo_dia", "2")  # a automática pede o dobro (4) e a campanha leva 2
        try:
            r = empresas_novas.buscar_e_criar(db, _admin(db), dia, dia, automatica=True)
        finally:
            gravar_config(db, "novas_maximo_dia", maximo_antes)
        assert pedidos[0]["limit"] == 4
        nomes = {e.razao_social for e in db.execute(
            select(EmpresaCnpja).where(EmpresaCnpja.busca_id == r["busca_id"])).scalars()}
        assert "PEQUENA COM ZAP LTDA" not in nomes and len(nomes) == 4  # a de R$ 10 mil nem veio
        cid = r["campanha_id"]
    ordem = _montar(cid)
    assert ordem[:2] == ["ALTA COM ZAP LTDA", "SO EMAIL LTDA"] and ordem[-1] == "SO TELEFONE FIXO LTDA"
    with sessao() as db:
        na_campanha = {t.lead.empresa.upper() for t in db.execute(
            select(Tarefa).where(Tarefa.campanha_id == cid)).scalars()}
    assert na_campanha == {"ALTA COM ZAP LTDA", "SO EMAIL LTDA"}


def test_filtro_de_capital_recusado_busca_sem_as_faixas(cliente, monkeypatch):
    """Se a CNPJá recusar o filtro de capital (erro 400), a busca não para: vai do jeito de antes, sem as faixas."""
    pedidos = []
    _preparar(monkeypatch, [_empresa("73200001000101", "QUALQUER UM LTDA", 1_000),
                            _empresa("73200002000102", "QUALQUER DOIS LTDA", 9_000_000)], pedidos,
              recusar_capital=True)
    custo = {}
    hoje = date.today()
    registros = empresas_novas.buscar_abertas(hoje, hoje, ["PE"], limite=5, por_capital=True, custo=custo)
    assert len(registros) == 2 and len(pedidos) == 2
    assert pedidos[0]["company.equity.gte"] == 1_000_000
    assert not any(k.startswith("company.equity") for k in pedidos[1]) and pedidos[1]["limit"] == 5
    assert custo == {"pedidos": 1, "creditos": 1}


def test_falha_no_meio_das_faixas_fica_com_as_ja_pagas(cliente, monkeypatch):
    pedidos = []
    grande = _empresa("73300001000101", "JA PAGA LTDA", 3_000_000)

    def get(url, params=None, headers=None, timeout=None):
        pedidos.append(dict(params or {}))
        if len(pedidos) == 1:
            return _Resposta({"records": [grande], "next": None})
        return _Resposta({"message": "erro"}, 500, "erro interno")

    monkeypatch.setattr(empresas_novas.httpx, "get", get)
    monkeypatch.setattr(config, "CNPJA_API_KEY", "chave-de-teste")
    hoje = date.today()
    registros = empresas_novas.buscar_abertas(hoje, hoje, ["PE"], limite=10, por_capital=True)
    assert [r["taxId"] for r in registros] == ["73300001000101"] and len(pedidos) == 2


def test_teste_da_api_continua_um_pedido_so(cliente, monkeypatch):
    """O botão Testar (10 empresas, 1 crédito) não pergunta por faixas; a lista dele sai do maior capital para o
    menor."""
    pedidos = []
    longe = date(2020, 1, 2)  # a lista do teste fica sem campanha: longe das datas das buscas dos outros testes
    _preparar(monkeypatch, [_empresa("73400001000101", "TESTE MENOR LTDA", 20_000, fundada=longe),
                            _empresa("73400002000102", "TESTE MAIOR LTDA", 700_000, fundada=longe)], pedidos)
    with sessao() as db:
        r = empresas_novas.testar(db, _admin(db))
        lista = [e.razao_social for e in db.execute(select(EmpresaCnpja).where(EmpresaCnpja.busca_id == r["busca_id"])
                                                    .order_by(EmpresaCnpja.id)).scalars()]
    assert len(pedidos) == 1 and not any(k.startswith("company.equity") for k in pedidos[0])
    assert lista == ["TESTE MAIOR LTDA", "TESTE MENOR LTDA"]
