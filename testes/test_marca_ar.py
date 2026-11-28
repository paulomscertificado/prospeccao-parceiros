"""White label, Fase 5: a marca de cada AR (app/marca.py).

O portão da Fase 5: nenhuma tela ou mensagem mostra a MS em outra AR. Uma administradora do Grupo Certy percorre TODAS
as telas (GET sem parâmetro, as abas das Configurações e a ficha de um lead dela) e nenhuma pode trazer o nome, o site
ou o logo da MS; as mensagens montadas para alguém do Grupo Certy também não. Antes de entrar, a tela é neutra.
"""
import base64
import io
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import marca
from app.banco import ler_config, sessao, usar_config_da_ar
from app.main import app
from app.modelos import ConfiguracaoAR, Lead, LogAuditoria, MarcaAR, Template, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

# o que denuncia a MS numa tela de outra AR ("MS" sozinho não: é a sigla de Mato Grosso do Sul nas listas de UF)
DA_MS = re.compile(r"mscertificados|MS Certifica|logo-ms|Funcion[aá]rio MS|Prospec\w* MS|MS Parceiros|MS Prospeccao|"
                   r"\b(?:da|na|pela|com a|para a|à|a|A)\s+MS\b|\(MS\)|tabela MS|Parceiro MS|equipe MS|Parceria MS")
FORA = ("/api/", "/descadastrar", "/sair", "/logout", "/static", "/marca/logo")
ABAS = ("geral", "marca", "score", "usuarios", "email", "integracoes", "lgpd", "logs")
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
MANUAL_CERTY = {"nome": "Grupo Certy", "curto": "Grupo Certy", "artigo": "o", "site": "grupocerty.com.br",
                "descricao": "credenciado à ICP-Brasil", "dominio_email": "grupocerty.com.br", "cor": "#E86A1F",
                "cor_detalhe": "#F7931E", "cor_fundo": "#F5F5F5", "fonte": "Montserrat"}


def _zerar_limite():
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)


def _entrar(email: str) -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _rotas_get():
    from fastapi.routing import APIRoute

    for item in app.routes:
        rotas = [item] if isinstance(item, APIRoute) else (
            [r for r in item.original_router.routes if isinstance(r, APIRoute)]
            if type(item).__name__ == "_IncludedRouter" else [])
        prefixo = getattr(getattr(item, "include_context", None), "prefix", "") or ""
        for rota in rotas:
            caminho = (prefixo if not isinstance(item, APIRoute) else "") + rota.path
            if "GET" in rota.methods and "{" not in caminho and not caminho.startswith(FORA):
                yield caminho


@pytest.fixture(scope="module")
def certy(cliente):
    """Uma administradora do Grupo Certy, um lead dela e a marca do manual do Grupo Certy (sem o logo)."""
    with sessao() as db:
        ar = db.execute(select(Tenant.id).where(Tenant.slug == "grupo-certy")).scalar()
        pessoa = Usuario(nome="Thais Marca", email="admin.marca@grupocerty.com.br", perfil="admin",
                         senha_hash=resumir_senha(SENHA), empresa_nome="Grupo Certy")
        db.add(pessoa)
        db.flush()
        assert pessoa.tenant_id == ar
        lead = Lead(empresa="Contábil Laranja Ltda", vendedor_id=pessoa.id, cidade="Belo Horizonte", estado="MG")
        db.add(lead)
        db.flush()
        assert marca.salvar(db, ar, MANUAL_CERTY) == []
        dados = {"ar": ar, "email": pessoa.email, "pessoa_id": pessoa.id, "lead_id": lead.id}
    pessoa.empresa_nome = ""  # a marca vem da AR, não da "empresa que eu represento"
    with sessao() as db:
        db.get(Usuario, dados["pessoa_id"]).empresa_nome = ""
    marca.esquecer()
    return dados


def test_nenhuma_tela_do_grupo_certy_mostra_a_ms(certy):
    _zerar_limite()
    c = _entrar(certy["email"])
    from app.modelos import Cadencia

    with sessao() as db:  # os modelos e as cadências da plataforma (todas as ARs veem)
        da_plataforma = [f"/templates/{i}" for i in db.execute(select(Template.id).where(Template.tenant_id.is_(None))).scalars()]
        da_plataforma += [f"/cadencias/{i}" for i in db.execute(select(Cadencia.id).where(Cadencia.tenant_id.is_(None))).scalars()]
    assert da_plataforma
    caminhos = list(_rotas_get()) + [f"/configuracoes?aba={a}" for a in ABAS] + [f"/leads/{certy['lead_id']}",
                                                                                 "/minha-conta"] + da_plataforma
    vazou, vistas = [], 0
    for caminho in caminhos:
        r = c.get(caminho, follow_redirects=False)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        vistas += 1
        achado = DA_MS.search(r.text)
        if achado:
            vazou.append(f"{caminho}: ...{r.text[max(0, achado.start() - 60):achado.end() + 40]!r}...")
    assert vistas > 40
    assert not vazou, " | ".join(vazou)


def test_a_tela_do_grupo_certy_tem_a_marca_dele_e_a_da_ms_continua_igual(certy, cliente):
    c = _entrar(certy["email"])
    pagina = c.get("/").text
    assert "Grupo Certy Parceiros" in pagina and "--fonte:" in pagina and "Montserrat" in pagina
    assert "--verde-marca:#f7931e" in pagina and "--fundo:#f5f5f5" in pagina
    azul = re.search(r"--azul:(#[0-9a-f]{6})", pagina).group(1)
    assert marca.contraste_com_branco(azul) >= 4.5  # botões legíveis com letra branca
    # o Admin Master dentro da AR MS vê a MS como sempre foi (logo de sempre, cores do sistema)
    with sessao() as db:
        ms = db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar()
        m = marca.da_ar(db, ms)
    assert m["nome"] == "MS Certificação Digital" and m["curto"] == "MS" and m["css"] == "" and m["logo_url"]
    assert m["titulo"] == "MS Parceiros"


def test_antes_de_entrar_a_tela_e_neutra():
    c = TestClient(app)
    pagina = c.get("/login").text
    assert DA_MS.search(pagina) is None and "Grupo Certy" not in pagina and "Prospecção de Parceiros" in pagina


def test_mensagens_do_grupo_certy_saem_com_a_marca_dele(certy):
    from app import config, sdr

    with sessao() as db:
        pessoa = db.get(Usuario, certy["pessoa_id"])
        lead = db.get(Lead, certy["lead_id"])
        usar_config_da_ar(db, certy["ar"])
        textos = []
        for tom in config.TONS:
            for m in sdr.mensagens_por_regras(db, lead, pessoa, tom=tom).values():
                textos += [m["whatsapp"], m["email"], m["assunto"]]
        for t in db.execute(select(Template)).scalars():
            textos += [t.assunto or "", t.corpo or ""]
        finais = [marca.aplicar(t, pessoa) for t in textos]
        assert finais and all(DA_MS.search(t) is None and "Recife" not in t for t in finais)
        assert any("Grupo Certy" in t for t in finais) and any("grupocerty.com.br" in t for t in finais)
        # o que fala da empresa vem da marca da AR, nunca da plataforma (que eram os textos da MS)
        assert ler_config(db, "empresa_nome") == "Grupo Certy"
        assert ler_config(db, "link_parceria") == "https://grupocerty.com.br"
        assert "Grupo Certy" in ler_config(db, "programa_parceria") and "MS" not in ler_config(db, "programa_parceria")
        assert ler_config(db, "whatsapp_convite") == ""
        # a AR MS ficou com os textos de antes (marca.garantir)
        ms = db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar()
        usar_config_da_ar(db, ms)
        assert ler_config(db, "link_parceria") == "https://mscertificados.com.br"
        assert "Recife" in ler_config(db, "programa_parceria")
        assert db.get(ConfiguracaoAR, (ms, "empresa_nome")) is None  # o nome sai da marca (aba Marca)
        usar_config_da_ar(db, None)


def test_a_administradora_muda_a_marca_e_o_logo(certy):
    c = _entrar(certy["email"])
    pagina = c.get("/configuracoes?aba=marca").text
    assert "Marca do Grupo Certy" in pagina
    r = c.post("/configuracoes/marca", data={"csrf": csrf_de(pagina), **MANUAL_CERTY, "cor": "#E86A1Z"},
               files={"logo": ("logo.png", PNG, "image/png")})
    assert "precisa ser no formato #RRGGBB" in r.text
    pagina = c.get("/").text
    endereco = re.search(r'src="(/marca/logo/\d+/[0-9a-f]{16}\?v=\d+)"', pagina).group(1)
    logo = c.get(endereco)
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png" and logo.content == PNG
    assert TestClient(app).get(endereco).status_code == 200  # aberto (descadastro, e-mail)
    assert c.get(re.sub(r"/[0-9a-f]{16}\?", "/0123456789abcdef?", endereco)).status_code == 404
    with sessao() as db:
        assert db.execute(select(Usuario).where(Usuario.id == certy["pessoa_id"])).scalar_one()  # nada mais mudou
        assert marca.salvar(db, certy["ar"], {}, tirar_logo=True) == []
    marca.esquecer()


def _imagem(largura, altura, fundo, desenho, caixa, formato="PNG") -> bytes:
    from PIL import Image

    imagem = Image.new("RGB", (largura, altura), fundo)
    imagem.paste(desenho, caixa)
    arquivo = io.BytesIO()
    imagem.save(arquivo, formato)
    return arquivo.getvalue()


def _endereco_do_logo(pagina: str) -> str:
    return re.search(r'src="(/marca/logo/\d+/[0-9a-f]{16}\?v=\d+)"', pagina).group(1)


def test_tirar_o_fundo_liso_do_logo():
    """Como o JPG do Grupo Certy: logo branco num fundo cinza-claro, que no menu aparecia como um retângulo."""
    from PIL import Image

    png = marca.tirar_fundo_do_logo(_imagem(300, 60, (247, 247, 247), (255, 255, 255), (20, 10, 280, 50)))
    imagem = Image.open(io.BytesIO(png))
    assert imagem.format == "PNG" and imagem.mode == "RGBA"
    assert imagem.size == (262, 42)  # as sobras em volta foram cortadas (1 px de folga)
    assert imagem.getpixel((0, 0))[3] == 0  # o que era fundo ficou transparente
    assert imagem.getpixel((131, 21)) == (255, 255, 255, 255)  # o desenho continua branco e inteiro
    assert marca.tirar_fundo_do_logo(png) == png  # de novo: nada muda
    assert marca.proporcao_do_logo(png) == pytest.approx(262 / 42, abs=0.01)
    # o JPG de verdade tem manchinhas perto do fundo: também somem
    jpg = Image.open(io.BytesIO(marca.tirar_fundo_do_logo(
        _imagem(300, 60, (247, 247, 247), (255, 255, 255), (20, 10, 280, 50), "JPEG"))))
    assert jpg.getpixel((0, 0))[3] == 0 and jpg.size[0] < 270 and jpg.getpixel((131, 21))[3] > 200
    # logo escuro em fundo branco: o desenho fica, sem contorno branco
    escuro = Image.open(io.BytesIO(marca.tirar_fundo_do_logo(_imagem(100, 40, (255, 255, 255), (0, 0, 0), (10, 10, 90, 30)))))
    assert escuro.getpixel((40, 10)) == (0, 0, 0, 255) and escuro.getpixel((0, 0))[3] == 0
    # sem fundo liso (bordas de várias cores, como uma foto) ou arquivo que não abre: fica como veio
    degrade = io.BytesIO()
    Image.linear_gradient("L").convert("RGB").save(degrade, "PNG")
    assert marca.tirar_fundo_do_logo(degrade.getvalue()) is None
    assert marca.tirar_fundo_do_logo(b"\x89PNG\r\n\x1a\nnao e imagem") is None
    assert marca.proporcao_do_logo(b"nao e imagem") is None


def test_logo_largo_fica_mais_baixo_no_menu_de_cima_e_o_fundo_sai_pela_tela(certy):
    c = _entrar(certy["email"])
    csrf = csrf_de(c.get("/configuracoes?aba=marca").text)
    jpg = _imagem(300, 61, (247, 247, 247), (255, 255, 255), (10, 8, 290, 52), "JPEG")
    try:
        c.post("/configuracoes/marca", data={"csrf": csrf}, files={"logo": ("logo.jpg", jpg, "image/jpeg")})
        pagina = c.get("/").text
        # no menu de cima (27/11/2026) o logo largo fica ao lado do traço e do rótulo, como os outros, só mais baixo
        assert 'class="menu menu-cima logo-largo' in pagina and 'class="marca marca-larga"' in pagina
        assert 'class="divisor"' in pagina and "Parceiros<br>Prospecção B2B" in pagina
        assert 'rel="icon"' not in pagina  # largo vira um risquinho na aba do navegador
        assert c.get(_endereco_do_logo(pagina)).headers["content-type"] == "image/jpeg"  # sem marcar: como veio
        # sem arquivo novo, "Tirar o fundo liso do logo" trata o logo de agora
        r = c.post("/configuracoes/marca", data={"csrf": csrf, "tirar_fundo": "1"})
        assert "Marca salva" in r.text and 'class="marca marca-larga"' in r.text  # a prévia "Como fica" também
        logo = c.get(_endereco_do_logo(c.get("/").text))
        from PIL import Image

        assert logo.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(logo.content)).getpixel((0, 0))[3] == 0
        with sessao() as db:
            registro = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "salvou_marca")
                                  .order_by(LogAuditoria.id.desc())).scalars().first()
            assert "tirou o fundo do logo" in registro.detalhes
        # logo quase quadrado (como o da MS): lado a lado com o traço e o rótulo, e vira o ícone da aba
        quadrado = _imagem(40, 34, (255, 255, 255), (0, 0, 0), (5, 5, 35, 29))
        c.post("/configuracoes/marca", data={"csrf": csrf}, files={"logo": ("logo.png", quadrado, "image/png")})
        pagina = c.get("/").text
        assert '<div class="marca">' in pagina and 'class="divisor"' in pagina and 'rel="icon"' in pagina
    finally:
        with sessao() as db:
            assert marca.salvar(db, certy["ar"], {}, tirar_logo=True) == []
            assert marca.salvar(db, certy["ar"], {}, tirar_fundo=True) == [
                "Não há logo para tirar o fundo: escolha o arquivo do logo."]
        marca.esquecer()


def test_logos_de_antes_ganham_a_medida_na_publicacao():
    with sessao() as db:
        ms = db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar()
        db.get(MarcaAR, ms).logo_proporcao = None
        db.flush()
        marca.garantir(db)
        assert db.get(MarcaAR, ms).logo_proporcao == pytest.approx(351 / 306, abs=0.01)  # o da MS: quase quadrado
    marca.esquecer()

def test_o_que_e_da_plataforma_so_o_admin_master_muda(certy, cliente):
    c = _entrar(certy["email"])
    csrf = csrf_de(c.get("/configuracoes?aba=integracoes").text)
    for caminho, dados in (("/configuracoes/cnpja", {"chave": "chave-de-outra-ar"}),
                           ("/configuracoes/email", {"endereco": "parcerias@grupocerty.com.br"}),
                           ("/configuracoes/receita", {"pasta": "C:/qualquer"})):
        r = c.post(caminho, data={"csrf": csrf, **dados})
        assert "só o Admin Master muda" in r.text, caminho
    # fora das ARs, o Admin Master muda o nome neutro da plataforma (tela de entrada)
    pagina = cliente.get("/configuracoes?aba=marca").text
    assert "Nome e suporte da plataforma" in pagina
    cliente.post("/configuracoes/marca", data={"csrf": csrf_de(pagina), "plataforma_nome": "Plataforma Teste"})
    try:
        assert "Plataforma Teste" in TestClient(app).get("/login").text
    finally:
        cliente.post("/configuracoes/marca", data={"csrf": csrf_de(pagina), "plataforma_nome": ""})
        marca.esquecer()


def test_descadastro_mostra_a_empresa_que_mandou(certy):
    from app.integracoes import email_smtp

    link = f"/descadastrar/{certy['lead_id']}/{email_smtp.assinatura_descadastro(certy['lead_id'])}"
    pagina = TestClient(app).get(link).text
    assert "do Grupo Certy" in pagina and DA_MS.search(pagina) is None


def test_tema_so_aceita_cor_e_fonte_validas():
    assert marca.tema("red", "#12", "x", "Comic Sans") == ""
    assert marca.tema("#000000") .startswith("--azul:#000000")
    assert marca.frase({"artigo": "o", "curto": "Grupo Certy", "nome": "Grupo Certy"}, "com") == "com o Grupo Certy"
    assert marca.frase({"artigo": "a", "curto": "MS", "nome": "MS"}, "de", maiuscula=True) == "Da MS"
