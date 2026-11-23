"""Arte do aviso de cada marca (pedido da Maria em 23/11/2026: "preciso que tenha um campo para configurar de onde você
vai configurar a arte do site/AR. Coloque um campo editável"). Renovação, quadro 4: o endereço da página do site que
desenha a arte, um por AR, que só o Admin Master troca (quem abre a página, com os dados do cliente, é o servidor). Sem
endereço, a AR MS usa a do site da MS e as outras marcas mandam só o texto: a arte de uma marca nunca vai em outra."""
import httpx
import pytest
from sqlalchemy import delete, select

from app import config, renovacao
from app.banco import config_propria_da_ar, gravar_config, gravar_config_da_ar, ler_config, sessao
from app.integracoes import whatsapp_leads
from app.modelos import Configuracao, ConfiguracaoAR, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de
from test_master import _entrar, _zerar_limite
from test_renovacao import _NUMEROS, _admin, _cenario

URL_CERTY = "https://arte.grupo-exemplo.com.br/interno/aviso-vencimento"
SEM_DESENHO = "https://arte.grupo-exemplo.com.br/outra"
PAGINA_BOA = '<html><body><canvas id="cv"></canvas><script>function update(){}</script></body></html>'


@pytest.fixture
def ars(cliente):  # o cliente prepara o banco de teste
    with sessao() as db:
        ids = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}
        antes = {c: ler_config(db, c) for c in renovacao.PADRAO}  # a tela grava o quadro 4 todo: tudo volta no fim
    yield ids
    with sessao() as db:
        for chave, valor in antes.items():
            gravar_config(db, chave, valor or "")
        db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.tenant_id == ids["grupo-certy"],
                                                ConfiguracaoAR.chave.in_([*renovacao.PADRAO, renovacao.CHAVE_URL_DA_ARTE])))
        db.execute(delete(Configuracao).where(Configuracao.chave == renovacao.CHAVE_URL_DA_ARTE))


@pytest.fixture
def site_falso(monkeypatch):
    """Sem internet nos testes: o DNS e as páginas de cada endereço são de mentira."""
    paginas = {URL_CERTY: PAGINA_BOA, SEM_DESENHO: "<html><body>outra coisa</body></html>"}

    def _pagina(url):
        if url not in paginas:
            raise httpx.ConnectError("sem resposta")
        return paginas[url]

    monkeypatch.setattr(renovacao, "endereco_publico", lambda url: ".grupo-exemplo.com.br/" in url)
    monkeypatch.setattr(renovacao, "_pagina_da_arte", _pagina)
    return paginas


def _tela(c) -> str:
    """A tela da Renovação com os espaços e as quebras de linha do HTML juntados (o texto quebra em várias linhas)."""
    return " ".join(c.get("/renovacao").text.split())


def test_cada_marca_tem_o_seu_endereco_e_o_da_plataforma_nao_vale(ars):
    with sessao() as db:
        ms, certy = ars["ms"], ars["grupo-certy"]
        assert renovacao.url_da_arte(db, ms) == renovacao.URL_DA_ARTE  # a MS: a do site da MS, como sempre
        assert renovacao.url_da_arte(db, certy) == ""  # outra marca sem endereço: só o texto
        gravar_config(db, renovacao.CHAVE_URL_DA_ARTE, URL_CERTY)  # gravado na plataforma: não vale para nenhuma marca
        assert renovacao.url_da_arte(db, certy) == "" and renovacao.url_da_arte(db, ms) == renovacao.URL_DA_ARTE
        gravar_config_da_ar(db, certy, renovacao.CHAVE_URL_DA_ARTE, URL_CERTY)
        assert renovacao.url_da_arte(db, certy) == URL_CERTY and renovacao.url_da_arte(db, ms) == renovacao.URL_DA_ARTE
        assert config_propria_da_ar(db, ms, renovacao.CHAVE_URL_DA_ARTE) is None
        # cada aviso leva o endereço da marca da campanha (quem desenha é o WhatsApp Leads)
        _, _, aviso_ms = _cenario(db, 8, "9800001", "(81) 98666-0001")
        _, _, aviso_certy = _cenario(db, 8, "9800002", "(81) 98666-0002")
        aviso_ms.tenant_id, aviso_certy.tenant_id = ms, certy
        assert renovacao.arte_do_toque(db, aviso_ms)["url"] == renovacao.URL_DA_ARTE
        assert renovacao.arte_do_toque(db, aviso_certy)["url"] == URL_CERTY
        gravar_config_da_ar(db, certy, renovacao.CHAVE_URL_DA_ARTE, "")
        assert renovacao.arte_do_toque(db, aviso_certy) is None  # sem endereço: o aviso sai só com o texto
        db.rollback()


def test_endereco_fora_de_um_site_da_internet_e_recusado():
    for ruim in ("http://arte.exemplo.com.br/x", "https://127.0.0.1/x", "https://localhost/x", "https://intranet/x",
                 "https://servidor.local/x", "ftp://arte.exemplo.com.br/x", "https://usuario:senha@exemplo.com.br/x"):
        assert renovacao.endereco_publico(ruim) is False, ruim


def test_so_o_admin_master_troca_o_endereco_da_arte(cliente, csrf, ars, site_falso, monkeypatch):
    certy = ars["grupo-certy"]
    _zerar_limite()
    with sessao() as db:
        gravar_config(db, "renov_arte", "1")
    base = {"canal_whatsapp": "on", "canal_email": "on", "arte": "on", "maximo_dia": "40", "hora": "07:45",
            "hora_fim": "18:00"}
    try:
        cliente.post(f"/master/entrar/{certy}", data={"csrf": csrf, "motivo": "colocar a arte do Grupo Certy"})
        pagina = _tela(cliente)
        assert 'name="arte_url"' in pagina and "Grupo Certy ainda não tem a arte do aviso" in pagina
        # sem a arte, a opção "Arte do aviso junto" não aparece: o valor vai escondido (salvar não a desliga na MS)
        assert '<input type="hidden" name="arte" value="1">' in pagina
        for ruim, motivo in [("http://arte.grupo-exemplo.com.br/x", "precisa começar com https://"),
                             (renovacao.URL_DA_ARTE, "endereço da arte da MS"),
                             ("https://sumiu.exemplo.com.br/x", "não é de um site da internet"),
                             (SEM_DESENHO, "não tem o desenho da arte"),
                             ("https://arte.grupo-exemplo.com.br/fora", "o site não respondeu")]:
            r = cliente.post("/renovacao/configurar", data={"csrf": csrf, **base, "arte_url": ruim})
            assert "O endereço da arte não foi salvo" in r.text and motivo in r.text, ruim
        with sessao() as db:
            assert renovacao.url_da_arte(db, certy) == ""
        r = cliente.post("/renovacao/configurar", data={"csrf": csrf, **base, "arte_url": URL_CERTY})
        assert "Configuração salva." in r.text and f"Os avisos do Grupo Certy passam a sair com a arte de {URL_CERTY}" in r.text
        with sessao() as db:
            assert renovacao.url_da_arte(db, certy) == URL_CERTY
            assert renovacao.url_da_arte(db, ars["ms"]) == renovacao.URL_DA_ARTE  # a da MS não mudou
        pagina = _tela(cliente)
        assert f'value="{URL_CERTY}"' in pagina and f'href="{URL_CERTY}"' in pagina and 'name="com_arte"' in pagina
        # o teste do quadro 1 com o cliente fictício leva a arte da marca da tela
        pedidos, real = {}, renovacao.enviar_teste
        resultado = {"enviadas": 0, "erros": [], "arte": False, "arte_pedida": False, "certificados": 1,
                     "remetente": "x", "numero": "", "modo_teste": False}
        monkeypatch.setattr(renovacao, "enviar_teste", lambda *a, **k: pedidos.update(k) or resultado)
        cliente.post("/renovacao/testar", data={"csrf": csrf, "certificado": "0", "canal": "whatsapp",
                                                "whatsapp_teste": "(81) 99999-0000", "avisos": "renov_aviso",
                                                "com_arte": "on"})
        assert pedidos["ar"] == certy
        monkeypatch.setattr(renovacao, "enviar_teste", real)
        filas = []
        monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
        monkeypatch.setattr(whatsapp_leads, "enviar", lambda *a, **k: filas.append(k) or "p1")
        monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: _NUMEROS)
        with sessao() as db:
            r = renovacao.enviar_teste(db, _admin(db), 0, "whatsapp", "5581999990000", "renov_aviso", ar=certy)
            assert r["arte"] and filas[-1]["arte"]["url"] == URL_CERTY, r
            renovacao.enviar_teste(db, _admin(db), 0, "whatsapp", "5581999990000", "renov_aviso", ar=ars["ms"])
            assert filas[-1]["arte"]["url"] == renovacao.URL_DA_ARTE
            db.rollback()
        # em branco: o Grupo Certy volta a mandar só o texto
        r = cliente.post("/renovacao/configurar", data={"csrf": csrf, **base, "arte_url": ""})
        assert "Sem endereço da arte: os avisos do Grupo Certy saem só com o texto." in r.text
        with sessao() as db:
            assert renovacao.url_da_arte(db, certy) == ""
        cliente.post("/master/sair", data={"csrf": csrf})
        # a administradora do Grupo Certy vê o endereço, mas não troca (o campo nem aparece para ela)
        with sessao() as db:
            gravar_config_da_ar(db, certy, renovacao.CHAVE_URL_DA_ARTE, URL_CERTY)
            if db.execute(select(Usuario.id).where(Usuario.email == "arte.certy@grupocerty.com.br")).first() is None:
                db.add(Usuario(nome="Administradora Arte Certy", email="arte.certy@grupocerty.com.br", perfil="admin",
                               senha_hash=resumir_senha(SENHA), empresa_nome="Grupo Certy"))
        c = _entrar("arte.certy@grupocerty.com.br")
        pagina = _tela(c)
        assert 'name="arte_url"' not in pagina and URL_CERTY in pagina and "quem troca o endereço é o administrador" in pagina
        c.post("/renovacao/configurar", data={"csrf": csrf_de(pagina), **base, "arte_url": SEM_DESENHO})
        with sessao() as db:
            assert renovacao.url_da_arte(db, certy) == URL_CERTY  # não mudou
    finally:
        cliente.post("/master/sair", data={"csrf": csrf})
        _zerar_limite()
        with sessao() as db:
            pessoa = db.execute(select(Usuario).where(Usuario.email == "arte.certy@grupocerty.com.br")).scalars().first()
            if pessoa is not None:
                pessoa.ativo = False
