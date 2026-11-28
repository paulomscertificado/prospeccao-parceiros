"""Logo da plataforma (28/11/2026, pedido da Maria: "quero a logo marca da MS bem bonita aqui", no alto da tela do
Admin Master fora das ARs, onde aparecia o nome "AR MS Certificados" em texto).

O Admin Master envia o logo em Configurações > Marca (fora das ARs). Ele fica na linha marca.AR_DA_PLATAFORMA (0) de
marcas_ar e aparece só no alto das telas da plataforma: as ARs continuam com o logo delas e a tela de entrada não muda.
"""
import io

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app import marca
from app.banco import sessao
from app.main import app
from app.modelos import LogAuditoria, MarcaAR, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de

LOGO_DA_PLATAFORMA = "/marca/logo/0/"


def _png(largura: int = 48, altura: int = 34) -> bytes:
    """Um símbolo branco num fundo transparente (como o MS da plataforma)."""
    imagem = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    imagem.paste((255, 255, 255, 255), (4, 4, largura - 4, altura - 4))
    arquivo = io.BytesIO()
    imagem.save(arquivo, "PNG")
    return arquivo.getvalue()


def _barra(pagina: str) -> str:
    """A abertura do menu de cima (as classes dizem se é a plataforma e se tem logo)."""
    inicio = pagina.index('<nav class="menu menu-cima')
    return pagina[inicio:pagina.index(">", inicio)]


def _salvar(cliente, **arquivos_e_campos):
    pagina = cliente.get("/configuracoes?aba=marca").text
    arquivos = {"logo": arquivos_e_campos.pop("logo")} if "logo" in arquivos_e_campos else None
    dados = {"csrf": csrf_de(pagina), "plataforma_nome": "", **arquivos_e_campos}
    return cliente.post("/configuracoes/marca", data=dados, files=arquivos)


def _fora_das_ars(cliente):
    """O Admin Master dos testes pode ter ficado dentro de uma AR (Painel master > Entrar na AR) num teste anterior."""
    pagina = cliente.get("/").text
    if 'action="/master/sair"' in pagina:
        cliente.post("/master/sair", data={"csrf": csrf_de(pagina)})


def _tirar_o_logo():
    with sessao() as db:
        linha = db.get(MarcaAR, marca.AR_DA_PLATAFORMA)
        if linha is not None:
            db.delete(linha)
    marca.esquecer()


def test_sem_logo_a_plataforma_mostra_o_nome_em_texto(cliente):
    _fora_das_ars(cliente)
    _tirar_o_logo()
    pagina = cliente.get("/").text
    assert "plataforma sem-logo" in _barra(pagina)  # o rótulo ao lado do nome sai (estilo.css)
    assert '<span class="logo-texto">' in pagina and LOGO_DA_PLATAFORMA not in pagina
    config = cliente.get("/configuracoes?aba=marca").text
    assert "Nome, logo e suporte da plataforma" in config and 'name="logo"' in config
    assert 'enctype="multipart/form-data"' in config and "Tirar o logo" not in config  # ainda não há logo para tirar


def test_logo_da_plataforma_pela_tela_aparece_so_no_alto_da_plataforma(cliente):
    _fora_das_ars(cliente)
    logo = _png()
    try:
        r = _salvar(cliente, logo=("ms.png", logo, "image/png"))
        assert "Nome, logo e suporte da plataforma salvos." in r.text
        pagina = cliente.get("/").text
        barra = _barra(pagina)
        assert "plataforma" in barra and "sem-logo" not in barra  # com o logo, o rótulo fica, como nas marcas
        assert '<img class="logo-img" src="/marca/logo/0/' in pagina and "Parceiros<br>Prospecção B2B" in pagina
        endereco = pagina.split('<img class="logo-img" src="', 1)[1].split('"', 1)[0]
        imagem = TestClient(app).get(endereco)  # aberto, como o logo das ARs (endereço com assinatura)
        assert imagem.status_code == 200 and imagem.headers["content-type"] == "image/png" and imagem.content == logo
        assert TestClient(app).get("/marca/logo/0/0000000000000000").status_code == 404  # assinatura errada
        with sessao() as db:
            registro = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "salvou_nome_da_plataforma")
                                  .order_by(LogAuditoria.id.desc())).scalars().first()
            assert "logo novo" in registro.detalhes
            assert '"logo": ["não tem", "tem"]' in registro.mudancas
        # a tela de entrada não muda (continua o nome em texto) e quem é de uma AR vê a marca dela
        assert LOGO_DA_PLATAFORMA not in TestClient(app).get("/login").text
        with sessao() as db:
            certy = db.execute(select(Tenant.id).where(Tenant.slug == "grupo-certy")).scalar()
            if db.execute(select(Usuario).where(Usuario.email == "admin.logo@grupocerty.com.br")).scalar() is None:
                db.add(Usuario(nome="Thais Logo", email="admin.logo@grupocerty.com.br", perfil="admin",
                               senha_hash=resumir_senha(SENHA), tenant_id=certy, empresa_nome="Grupo Certy"))
        da_ar = TestClient(app)
        da_ar.post("/login", data={"csrf": csrf_de(da_ar.get("/login").text), "email": "admin.logo@grupocerty.com.br",
                                   "senha": SENHA})
        pagina_da_ar = da_ar.get("/").text
        assert '<nav class="menu menu-cima' in pagina_da_ar and LOGO_DA_PLATAFORMA not in pagina_da_ar
        assert "plataforma" not in _barra(pagina_da_ar)
        # a prévia "Como fica" da tela mostra o logo, e agora dá para tirar
        config = cliente.get("/configuracoes?aba=marca").text
        assert '<img class="logo-img" src="/marca/logo/0/' in config and "Tirar o logo" in config
        # "Tirar o fundo liso" sem arquivo novo trata o logo de agora; "Tirar o logo" volta o nome em texto
        r = _salvar(cliente, tirar_fundo="1")
        assert "Nome, logo e suporte da plataforma salvos." in r.text or "fundo liso" in r.text
        r = _salvar(cliente, tirar_logo="1")
        assert "Nome, logo e suporte da plataforma salvos." in r.text
        pagina = cliente.get("/").text
        assert "sem-logo" in _barra(pagina) and LOGO_DA_PLATAFORMA not in pagina
        r = _salvar(cliente, tirar_fundo="1")
        assert "Não há logo para tirar o fundo" in r.text
    finally:
        _tirar_o_logo()


def test_logo_grande_demais_ou_que_nao_e_imagem_nao_entra(cliente):
    _fora_das_ars(cliente)
    try:
        r = _salvar(cliente, logo=("ms.png", b"\x89PNG" + b"0" * (marca.LIMITE_LOGO + 10), "image/png"))
        assert "o limite é 300 KB" in r.text
        r = _salvar(cliente, logo=("ms.txt", b"isto nao e uma imagem", "text/plain"))
        assert "PNG, JPG ou WebP" in r.text
        assert LOGO_DA_PLATAFORMA not in cliente.get("/").text
        with sessao() as db:
            linha = db.get(MarcaAR, marca.AR_DA_PLATAFORMA)
            assert linha is None or not linha.logo_tipo
    finally:
        _tirar_o_logo()


def test_marca_da_plataforma_le_o_logo_sem_trazer_a_imagem():
    """`da_plataforma` só lê o tipo, a medida e a data (o endereço muda quando o logo muda); a imagem vem pela rota."""
    try:
        with sessao() as db:
            assert marca.salvar_logo_da_plataforma(db, _png(120, 40)) == []
        with sessao() as db:
            m = marca.da_plataforma(db)
            assert m["plataforma"] and m["logo_url"].startswith(LOGO_DA_PLATAFORMA)
            assert m["logo_proporcao"] == 3.0 and m["logo_largo"]  # 120 x 40: largo, fica mais baixo na barra
            assert marca.da_ar(db, None)["logo_url"] == m["logo_url"]
            assert marca.logo(db, marca.AR_DA_PLATAFORMA)[1] == "image/png"
            assert marca.salvar_logo_da_plataforma(db) == []  # nada para mudar: não grava
    finally:
        _tirar_o_logo()
