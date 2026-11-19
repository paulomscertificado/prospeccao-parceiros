"""Módulos de cada AR (white label, Fase 3): o Admin Master liga e desliga no Painel master só para a AR escolhida.

Até 19/11/2026 a Assertiva ficava fora de banco.CHAVES_DA_AR e de CHAVES_SO_MASTER: desligar no Grupo Certy gravava
na configuração da plataforma e desligava em todas as ARs, e o painel mostrava o mesmo estado em todas."""
import re

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import autorizacao, isolamento
from app.banco import CHAVES_DA_AR, CHAVES_SO_MASTER, ler_config, sessao, usar_config_da_ar
from app.main import app
from app.modelos import Configuracao, ConfiguracaoAR, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

CHAVES = sorted(chave for _, chave in autorizacao.MODULOS.values())


def test_todo_modulo_e_de_cada_ar_e_so_o_master_muda():
    """Módulo fora das listas repete o defeito da Assertiva: o Painel master gravaria na plataforma (todas as ARs)."""
    assert [c for c in CHAVES if c not in CHAVES_DA_AR] == []
    assert [c for c in CHAVES if c not in CHAVES_SO_MASTER] == []  # o administrador da AR não muda os módulos


def _entrar(email: str) -> TestClient:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _admins() -> dict:
    """Um administrador da AR MS e um do Grupo Certy (a AR vem da empresa representada)."""
    pessoas = {}
    with sessao() as db:
        ars = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}
        for slug, empresa in (("ms", "MS Certificação Digital"), ("grupo-certy", "Grupo Certy")):
            email = f"admin.{slug}.modulos@teste.com.br"
            u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
            if u is None:
                u = Usuario(nome=f"Admin {slug} (módulos)", email=email, perfil="admin",
                            senha_hash=resumir_senha(SENHA), empresa_nome=empresa)
                db.add(u)
                db.flush()
            assert u.tenant_id == ars[slug]
            pessoas[slug] = {"id": u.id, "email": email, "ar": u.tenant_id}
    return pessoas


def _modulos_da_ar(ar: int) -> dict[str, bool]:
    with sessao() as db:
        usar_config_da_ar(db, ar)
        return autorizacao.modulos_ligados(db)


def _foto() -> tuple[dict, list]:
    """Os valores gravados dos módulos (da plataforma e de cada AR): no fim o teste devolve tudo como estava."""
    with sessao() as db:
        plataforma = dict(db.execute(select(Configuracao.chave, Configuracao.valor)
                                     .where(Configuracao.chave.in_(CHAVES))).all())
        das_ars = sorted(tuple(linha) for linha in db.execute(
            select(ConfiguracaoAR.tenant_id, ConfiguracaoAR.chave, ConfiguracaoAR.valor)
            .where(ConfiguracaoAR.chave.in_(CHAVES))).all())
    return plataforma, das_ars


def _devolver(foto: tuple[dict, list]) -> None:
    plataforma, das_ars = foto
    with sessao() as db:
        db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.chave.in_(CHAVES)))
        db.add_all(ConfiguracaoAR(tenant_id=ar, chave=chave, valor=valor) for ar, chave, valor in das_ars)
        for item in db.execute(select(Configuracao).where(Configuracao.chave.in_(CHAVES))).scalars():
            if item.chave in plataforma:
                item.valor = plataforma[item.chave]
            else:
                db.delete(item)


def _assertiva_marcada(pagina: str, ar: int) -> bool:
    """A caixinha da Assertiva no formulário de módulos da AR, no Painel master."""
    formulario = re.search(rf'action="/master/ar/{ar}/modulos".*?</form>', pagina, re.S).group(0)
    return "checked" in re.search(r'<input[^>]*name="m__assertiva"[^>]*>', formulario).group(0)


def _tem_a_permissao(pessoa: dict) -> bool:
    """A permissão que vale para a pessoa, lida como numa tela dela (configurações da AR dela)."""
    with sessao() as db:
        usuario = db.get(Usuario, pessoa["id"])
        isolamento.ligar(db, usuario)
        return "assertiva.consultar" in autorizacao.efetivas(usuario, db)


def test_assertiva_liga_e_desliga_so_na_ar_escolhida(cliente):
    p = _admins()
    ms, certy = p["ms"]["ar"], p["grupo-certy"]["ar"]
    foto = _foto()
    with sessao() as db:
        plataforma = ler_config(db, "modulo_assertiva")  # sem AR: o valor da plataforma
    antes = _modulos_da_ar(certy)
    assert antes["assertiva"] and _modulos_da_ar(ms)["assertiva"]  # padrão: ligada nas duas
    adm_ms, adm_certy = _entrar(p["ms"]["email"]), _entrar(p["grupo-certy"]["email"])
    assert "Consulta Assertiva" in adm_certy.get("/").text and _tem_a_permissao(p["grupo-certy"])

    pagina = cliente.get("/master").text  # o Admin Master desliga a Assertiva só do Grupo Certy
    form = {"csrf": csrf_de(pagina), **{f"m__{m}": "on" for m, ligado in antes.items() if ligado and m != "assertiva"}}
    try:
        assert cliente.post(f"/master/ar/{certy}/modulos", data=form).status_code == 200
        # 1. só o Grupo Certy desligou: a MS e a plataforma ficaram como estavam, e o painel mostra cada uma
        assert _modulos_da_ar(certy) == {**antes, "assertiva": False}
        assert _modulos_da_ar(ms)["assertiva"]
        with sessao() as db:
            assert ler_config(db, "modulo_assertiva") == plataforma
        pagina = cliente.get("/master").text
        assert not _assertiva_marcada(pagina, certy) and _assertiva_marcada(pagina, ms)
        # 2. o menu "Consulta Assertiva" some só no Grupo Certy
        tela_ms, tela_certy = adm_ms.get("/").text, adm_certy.get("/").text
        assert "Consulta Assertiva" in tela_ms and 'href="/assertiva"' in tela_ms
        assert "Consulta Assertiva" not in tela_certy and 'href="/assertiva"' not in tela_certy
        # 3. a permissão assertiva.consultar some só no Grupo Certy (e a tela fica fechada para ele)
        assert _tem_a_permissao(p["ms"]) and not _tem_a_permissao(p["grupo-certy"])
        assert adm_ms.get("/assertiva").status_code == 200
        r = adm_certy.get("/assertiva")
        assert r.status_code == 403 and "está desligada" in r.text

        # o Admin Master liga de novo: volta para o Grupo Certy, e a MS segue igual
        form["csrf"] = csrf_de(cliente.get("/master").text)
        form["m__assertiva"] = "on"
        assert cliente.post(f"/master/ar/{certy}/modulos", data=form).status_code == 200
        assert _modulos_da_ar(certy) == antes and _modulos_da_ar(ms)["assertiva"]
        assert "Consulta Assertiva" in adm_certy.get("/").text and _tem_a_permissao(p["grupo-certy"])
    finally:
        _devolver(foto)
    assert _foto() == foto
