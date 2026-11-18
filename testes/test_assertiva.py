"""Assertiva (pedido da Maria em 18/11/2026): cada marca usa as próprias credenciais (Configurações > Integrações),
guardadas criptografadas; consultas só por clique, cobradas, reaproveitadas por 30 dias, registradas e apagadas
depois de 30 dias; na ficha do lead, o que veio na consulta pode entrar no lead. A Assertiva é simulada aqui."""
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import assertiva
from app.banco import agora, sessao
from app.main import app
from app.modelos import ConsultaAssertiva, ContaAssertiva, Historico, Lead, LogAuditoria, Tenant, Usuario
from app.seguranca import descriptografar, limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

CNPJ = "37.991.557/0001-41"  # só neste teste (outros testes usam o 11.222.333/0001-81)
CID_MS, SEGREDO_MS = "cid-assertiva-ms-123", "segredo-assertiva-ms-abcdef"
RESPOSTA_CNPJ = {"cabecalho": {"protocolo": "prot-assertiva-1"}, "resposta": {
    "dadosCadastrais": {"cnpj": CNPJ, "razaoSocial": "CONTABIL TESTE ASSERTIVA LTDA", "nomeFantasia": "CONTAB TESTE",
                        "situacaoCadastral": "ATIVA", "dataAbertura": "04/01/2000", "idadeEmpresa": 26},
    "telefones": {"moveis": [{"numero": "(81) 99123-7845", "relacao": "Direto", "naoPerturbe": False,
                              "aplicativos": {"whatsApp": True}}],
                  "fixos": [{"numero": "(81) 3333-4444", "relacao": "Direto", "naoPerturbe": True}]},
    "emails": [{"email": "Contato@ContabilTeste.com.br"}],
    "enderecos": [{"tipoLogradouro": "R", "logradouro": "DAS FLORES", "numero": 10, "bairro": "CENTRO",
                   "cidade": "RECIFE", "uf": "PE", "cep": "50000-000"}],
    "socios": [{"documento": "123.456.789-01", "nomeOuRazaoSocial": "JOAO DA SILVA", "dataEntrada": "04/01/2000"}]}}


class FalsaAssertiva:
    """Faz o papel da Assertiva: conta os tokens pedidos e as consultas (cobradas) feitas."""

    def __init__(self):
        self.tokens, self.consultas = 0, []
        self.status_token, self.status_consulta = 200, [200]

    def post(self, url, **kw):
        assert url == assertiva.URL_TOKEN and kw["data"] == {"grant_type": "client_credentials"}
        self.tokens += 1
        if self.status_token != 200:
            return httpx.Response(self.status_token, json={"error": "invalid_client"})
        return httpx.Response(200, json={"access_token": f"tok{self.tokens}", "token_type": "bearer",
                                         "expires_in": 60})

    def get(self, url, **kw):
        self.consultas.append((url, dict(kw["params"]), kw["headers"]["Authorization"]))
        status = self.status_consulta.pop(0) if len(self.status_consulta) > 1 else self.status_consulta[0]
        if status != 200:
            return httpx.Response(status, json={"resposta": "Erro de teste da Assertiva"})
        return httpx.Response(200, json=RESPOSTA_CNPJ)


@pytest.fixture()
def falsa(monkeypatch):
    f = FalsaAssertiva()
    monkeypatch.setattr(assertiva, "_post", f.post)
    monkeypatch.setattr(assertiva, "_get", f.get)
    assertiva._TOKENS.clear()
    return f


def _entrar(email: str) -> TestClient:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _csrf(c: TestClient) -> str:
    return csrf_de(c.get("/minha-conta").text)


_PESSOAS: dict = {}


def _pessoas() -> dict:
    """Administrador da MS, administrador do Grupo Certy e um vendedor da MS (sem a permissão por padrão)."""
    if _PESSOAS:
        return _PESSOAS
    with sessao() as db:
        ids_ar = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}
        for chave, perfil, empresa in (("adm_ms", "admin", "MS Certificação Digital"),
                                       ("adm_certy", "admin", "Grupo Certy"),
                                       ("vend_ms", "vendedor", "MS Certificação Digital")):
            u = Usuario(nome=f"Assertiva {chave}", email=f"{chave}.assertiva@teste.com.br", perfil=perfil,
                        senha_hash=resumir_senha(SENHA), empresa_nome=empresa)
            db.add(u)
            db.flush()
            _PESSOAS[chave] = {"id": u.id, "email": u.email, "ar": u.tenant_id}
        assert _PESSOAS["adm_ms"]["ar"] == ids_ar["ms"] and _PESSOAS["adm_certy"]["ar"] == ids_ar["grupo-certy"]
    return _PESSOAS


def _salvar_credenciais(c: TestClient) -> None:
    r = c.post("/configuracoes/assertiva", data={"csrf": _csrf(c), "client_id": CID_MS, "segredo": SEGREDO_MS,
                                                 "finalidade": "5"}, follow_redirects=False)
    assert r.status_code == 303


def test_credenciais_por_marca_criptografadas_e_nunca_na_tela(cliente, falsa):
    p = _pessoas()
    ms = _entrar(p["adm_ms"]["email"])
    _salvar_credenciais(ms)
    pagina = ms.get("/configuracoes?aba=integracoes").text
    assert 'id="assertiva"' in pagina and "salvas" in pagina
    assert CID_MS not in pagina and SEGREDO_MS not in pagina  # nunca voltam para a tela
    with sessao() as db:
        contas = db.execute(select(ContaAssertiva).execution_options(sem_filtro_de_ar=True)).scalars().all()
        conta = next(c for c in contas if c.tenant_id == p["adm_ms"]["ar"])
        assert conta.client_id_cripto != CID_MS and descriptografar(conta.client_id_cripto) == CID_MS
        assert descriptografar(conta.segredo_cripto) == SEGREDO_MS and conta.finalidade == 5
    # o teste das credenciais só pede o acesso (não gasta consulta)
    ms.post("/configuracoes/assertiva/testar", data={"csrf": _csrf(ms)})
    assert falsa.tokens == 1 and falsa.consultas == []
    assert "funcionando" in ms.get("/configuracoes?aba=integracoes").text
    # o Grupo Certy tem o próprio quadro, sem as credenciais da MS
    certy = _entrar(p["adm_certy"]["email"]).get("/configuracoes?aba=integracoes").text
    assert 'id="assertiva"' in certy and "faltam" in certy


def test_consulta_por_cnpj_mostra_contatos_reaproveita_e_registra(cliente, falsa):
    p = _pessoas()
    ms = _entrar(p["adm_ms"]["email"])
    _salvar_credenciais(ms)
    r = ms.post("/assertiva/consultar", data={"csrf": _csrf(ms), "tipo": "cnpj", "valor": CNPJ}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/assertiva/consulta/")
    pagina = ms.get(r.headers["location"]).text
    for texto in ("CONTABIL TESTE ASSERTIVA LTDA", "(81) 99123-7845", "tem WhatsApp", "não perturbe",
                  "contato@contabilteste.com.br", "JOAO DA SILVA", "123.***.***-01", "prot-assertiva-1"):
        assert texto in pagina, texto
    assert "123.456.789-01" not in pagina  # CPF do sócio mascarado
    url, params, autorizacao = falsa.consultas[0]
    assert url.endswith("/localize/v3/cnpj") and params == {"cnpj": "37991557000141", "idFinalidade": 5}
    assert autorizacao == "Bearer tok1"
    # a mesma consulta de novo: reaproveita, sem cobrar
    r2 = ms.post("/assertiva/consultar", data={"csrf": _csrf(ms), "tipo": "cnpj", "valor": "37991557000141"},
                 follow_redirects=False)
    assert r2.headers["location"] == r.headers["location"] and len(falsa.consultas) == 1
    # "Consultar de novo" cobra outra
    ms.post("/assertiva/consultar", data={"csrf": _csrf(ms), "tipo": "cnpj", "valor": CNPJ, "de_novo": "1"})
    assert len(falsa.consultas) == 2
    with sessao() as db:
        logs = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "consultou_assertiva")).scalars().all()
        assert len(logs) >= 2 and all(SEGREDO_MS not in (l.detalhes or "") for l in logs)
    assert "Últimas consultas desta marca" in ms.get("/assertiva").text


def test_cada_marca_so_ve_o_que_e_dela_e_vendedor_sem_permissao(cliente, falsa):
    p = _pessoas()
    ms = _entrar(p["adm_ms"]["email"])
    _salvar_credenciais(ms)
    r = ms.post("/assertiva/consultar", data={"csrf": _csrf(ms), "tipo": "cnpj", "valor": CNPJ, "de_novo": "1"},
                follow_redirects=False)
    endereco = r.headers["location"]
    certy = _entrar(p["adm_certy"]["email"])
    assert certy.get(endereco).status_code == 404  # a consulta da MS não aparece para o Grupo Certy
    antes = len(falsa.consultas)
    certy.post("/assertiva/consultar", data={"csrf": _csrf(certy), "tipo": "cnpj", "valor": CNPJ})
    assert len(falsa.consultas) == antes  # sem credenciais próprias, nada sai (nem com as da MS)
    assert "ainda não tem as credenciais" in certy.get("/assertiva").text
    vendedor = _entrar(p["vend_ms"]["email"])
    assert vendedor.get("/assertiva").status_code == 403  # a permissão vem só para administrador e gestor


def test_ficha_do_lead_usa_so_o_que_veio_na_consulta(cliente, falsa):
    p = _pessoas()
    ms = _entrar(p["adm_ms"]["email"])
    _salvar_credenciais(ms)
    with sessao() as db:
        lead = Lead(empresa="Contábil Teste Assertiva", cnpj=CNPJ, vendedor_id=p["adm_ms"]["id"])
        db.add(lead)
        db.flush()
        lead_id = lead.id
    assert "Buscar contatos na Assertiva" in ms.get(f"/leads/{lead_id}").text
    r = ms.post(f"/leads/{lead_id}/assertiva", data={"csrf": _csrf(ms), "de_novo": "1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith(f"?lead={lead_id}")
    consulta_id = int(r.headers["location"].split("/consulta/")[1].split("?")[0])
    assert "Usar como WhatsApp" in ms.get(r.headers["location"]).text
    ms.post(f"/leads/{lead_id}/assertiva/usar", data={"csrf": _csrf(ms), "consulta": consulta_id,
                                                       "campo": "whatsapp", "valor": "81991237845"})
    ms.post(f"/leads/{lead_id}/assertiva/usar", data={"csrf": _csrf(ms), "consulta": consulta_id,
                                                       "campo": "email", "valor": "outro@inventado.com.br"})
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        try:
            assert lead.chave_whatsapp == "81991237845" and lead.email == ""  # o e-mail inventado não entrou
            textos = [h.descricao for h in db.execute(select(Historico).where(Historico.lead_id == lead_id)).scalars()]
            assert any("Assertiva" in t for t in textos)
            assert db.get(ConsultaAssertiva, consulta_id).lead_id == lead_id
        finally:  # o lead do teste sai do banco (senão entra nas campanhas e na deduplicação dos outros testes)
            for h in db.execute(select(Historico).where(Historico.lead_id == lead_id)).scalars():
                db.delete(h)
            for c in db.execute(select(ConsultaAssertiva).where(ConsultaAssertiva.lead_id == lead_id)).scalars():
                c.lead_id = None
            db.delete(lead)


def test_erros_da_assertiva_viram_avisos_claros(cliente, falsa):
    p = _pessoas()
    with sessao() as db:
        conta = ContaAssertiva(client_id_cripto=assertiva.criptografar(CID_MS),
                               segredo_cripto=assertiva.criptografar(SEGREDO_MS), finalidade=5,
                               tenant_id=p["adm_ms"]["ar"])
        db.add(conta)
        db.flush()
        falsa.status_token = 401
        with pytest.raises(assertiva.ErroAssertiva, match="recusou o Client ID"):
            assertiva.testar(db, conta)
        falsa.status_token = 200
        falsa.status_consulta = [403]
        with pytest.raises(assertiva.ErroAssertiva, match="não tem permissão"):
            assertiva.consultar(db, conta, None, "cnpj", CNPJ, de_novo=True)
        falsa.status_consulta = [401, 200]  # token vencido antes da hora: pede outro e tenta de novo
        consulta, reaproveitada = assertiva.consultar(db, conta, None, "cnpj", CNPJ, de_novo=True)
        assert not reaproveitada and consulta.protocolo == "prot-assertiva-1"
        db.delete(conta)


def test_conferencia_do_que_e_consultado():
    for tipo, valor, filtros in (("cpf", "111.111.111-11", None), ("cnpj", "11.222.333/0001-00", None),
                                 ("telefone", "8199", None), ("email", "sem-arroba", None),
                                 ("nome", "", {"nome": "Jo"}), ("nome", "", {"nome": "Joao Silva", "cidade": "Recife"})):
        with pytest.raises(assertiva.ErroAssertiva):
            assertiva.preparar(tipo, valor, filtros)
    assert assertiva.preparar("cpf", "529.982.247-25", None) == ("52998224725", {"cpf": "52998224725"})
    assert assertiva.preparar("telefone", "+55 (81) 99876-5432", None)[0] == "81998765432"
    chave, params = assertiva.preparar("nome", "", {"nome": "Joao  da Silva", "uf": "pe", "cidade": "Recife",
                                                     "buscar_por": "pessoas"})
    assert params == {"buscarPor": "pessoas", "nomeOuRazaoSocial": "Joao da Silva", "uf": "PE", "cidade": "Recife"}


def test_consultas_com_mais_de_30_dias_sao_apagadas(cliente):
    with sessao() as db:
        velha = ConsultaAssertiva(tipo="cnpj", chave="37991557000141", resultado="{}",
                                  criado_em=agora() - timedelta(days=assertiva.DIAS_GUARDA + 1))
        nova = ConsultaAssertiva(tipo="cnpj", chave="37991557000141", resultado="{}")
        db.add_all([velha, nova])
        db.flush()
        ids = (velha.id, nova.id)
    with sessao() as db:
        assert assertiva.apagar_antigas(db) >= 1
    with sessao() as db:
        assert db.get(ConsultaAssertiva, ids[0]) is None and db.get(ConsultaAssertiva, ids[1]) is not None
