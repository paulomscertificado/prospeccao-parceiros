"""Estado (UF) e cidade da marca (Configurações > Marca; pedido da Maria em 19/11/2026, "é para puxar os feriados"):
quem não informou a própria cidade segue os feriados da cidade e do estado da marca."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import feriados, marca
from app.banco import sessao
from app.main import app
from app.modelos import MarcaAR, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

ADMIN = "admin.local@grupocerty-marca.com.br"
VENDEDOR = "vendedor.semcidade@grupocerty-marca.com.br"
COM_CIDADE = "vendedor.comcidade@grupocerty-marca.com.br"


def _certy() -> int:
    with sessao() as db:
        return db.execute(select(Tenant.id).where(Tenant.slug == "grupo-certy")).scalar_one()


def _pessoa(email: str, perfil: str, uf: str = "", cidade: str = "") -> int:
    ar = _certy()
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if u is None:
            u = Usuario(nome=email.split("@")[0], email=email, perfil=perfil, senha_hash=resumir_senha(SENHA),
                        empresa_nome="Grupo Certy", tenant_id=ar)
            db.add(u)
        u.uf, u.cidade = uf, cidade
        db.flush()
        return u.id


def _entrar(email: str) -> TestClient:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _local_da_marca(uf: str, cidade: str) -> None:
    ar = _certy()
    with sessao() as db:
        linha = db.get(MarcaAR, ar) or MarcaAR(tenant_id=ar)
        linha.uf, linha.cidade = uf, cidade
        db.merge(linha)
    marca.esquecer(ar)


def test_marca_guarda_estado_e_cidade_e_quem_nao_informou_segue_a_marca(cliente):
    _pessoa(ADMIN, "admin")
    vendedor = _pessoa(VENDEDOR, "vendedor")
    com_cidade = _pessoa(COM_CIDADE, "vendedor", "PE", "Recife")
    c = _entrar(ADMIN)
    try:
        tela = c.get("/configuracoes?aba=marca").text
        assert "Estado (UF) da marca" in tela and "Cidade da marca" in tela
        # cidade sem o estado: recusa
        r = c.post("/configuracoes/marca", data={"csrf": csrf_de(tela), "uf": "", "cidade": "Belo Horizonte"})
        assert "Escolha também o estado" in r.text
        # o nome da cidade fica como o IBGE escreve
        r = c.post("/configuracoes/marca", data={"csrf": csrf_de(tela), "uf": "mg", "cidade": "belo horizonte"})
        assert "Marca salva" in r.text, r.text[:400]
        with sessao() as db:
            linha = db.get(MarcaAR, _certy())
            assert (linha.uf, linha.cidade) == ("MG", "Belo Horizonte")
            # sem cidade no cadastro: os feriados de Belo Horizonte (15/08 e 08/12); com cidade: a dela
            sem = db.get(Usuario, vendedor)
            assert feriados.local_da_pessoa(db, sem) == ("MG", "Belo Horizonte")
            dias = feriados.da_pessoa(db, sem, (2026,))
            assert date(2026, 8, 15) in dias and date(2026, 12, 8) in dias
            dela = db.get(Usuario, com_cidade)
            assert feriados.local_da_pessoa(db, dela) == ("PE", "Recife")
            assert date(2026, 7, 16) in feriados.da_pessoa(db, dela, (2026,))  # Nossa Senhora do Carmo (Recife)
        # a tela de feriados mostra o local da marca
        tela = c.get("/configuracoes?aba=feriados").text
        assert "padrão da marca" in tela and "Belo Horizonte" in tela
    finally:
        _local_da_marca("", "")


def test_marca_sem_local_continua_como_antes(cliente):
    _local_da_marca("", "")
    vendedor = _pessoa(VENDEDOR, "vendedor")
    with sessao() as db:
        sem = db.get(Usuario, vendedor)
        assert feriados.local_da_pessoa(db, sem) == ("", "")
        assert set(feriados.da_pessoa(db, sem, (2026,))) == set(feriados.dias_de(db, None, "", "", (2026,)))
