"""Dono e número da Renovação de cada AR (23/11/2026). O Admin Master salvou o quadro 4 dentro do Grupo Certy e a
Renovação da MS perdeu o dono (Paulo Lucas) e o número dos disparos: dentro de uma AR, a tela só lista as pessoas e os
números dela, e esses dois valores eram da plataforma. Agora são de cada AR; o Admin Master fora das ARs mexe nos da
AR MS (os que a campanha automática do dia usa). E o teste do quadro 1 sai com a marca da AR da tela."""
import pytest
from sqlalchemy import delete, select

from app import config, renovacao
from app.banco import config_propria_da_ar, gravar_config, gravar_config_da_ar, ler_config, sessao, usar_config_da_ar
from app.integracoes import whatsapp_leads
from app.modelos import ConfiguracaoAR, Tenant
from test_master import _zerar_limite
from test_renovacao import _NUMEROS, _admin

BASE = {"canal_whatsapp": "on", "canal_email": "on", "arte": "on", "maximo_dia": "40", "hora": "07:45",
        "hora_fim": "18:00"}


@pytest.fixture
def ars(cliente):  # o cliente prepara o banco de teste
    with sessao() as db:
        ids = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}
        plataforma = {c: ler_config(db, c) for c in renovacao.PADRAO}  # a tela grava o quadro 4 todo: tudo volta
        proprias = db.execute(select(ConfiguracaoAR.tenant_id, ConfiguracaoAR.chave, ConfiguracaoAR.valor)
                              .where(ConfiguracaoAR.chave.in_(list(renovacao.PADRAO)))).all()
    yield ids
    with sessao() as db:
        for chave, valor in plataforma.items():
            gravar_config(db, chave, valor or "")
        db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.chave.in_(list(renovacao.PADRAO))))
        db.add_all([ConfiguracaoAR(tenant_id=ar, chave=chave, valor=valor) for ar, chave, valor in proprias])


def test_salvar_dentro_de_outra_ar_nao_apaga_o_dono_nem_o_numero_da_ms(cliente, csrf, ars):
    ms, certy = ars["ms"], ars["grupo-certy"]
    _zerar_limite()
    with sessao() as db:
        dono_ms = str(_admin(db).id)
        gravar_config(db, "renov_dono_id", dono_ms)  # como estava a MS: os valores da plataforma
        gravar_config(db, "renov_conexao", "principal")
        gravar_config_da_ar(db, ms, "renov_dono_id", dono_ms)  # e como fica depois de devolver: os da AR MS
        gravar_config_da_ar(db, ms, "renov_conexao", "principal")
    try:
        cliente.post(f"/master/entrar/{certy}", data={"csrf": csrf, "motivo": "configurar a renovação do Grupo Certy"})
        pagina = " ".join(cliente.get("/renovacao").text.split())
        assert "vale para todas as marcas" in pagina  # o aviso do que é de cada marca
        # dentro do Grupo Certy, as listas não têm o dono nem o número da MS: o formulário vai com os dois vazios
        r = cliente.post("/renovacao/configurar", data={"csrf": csrf, **BASE, "dono_id": "", "conexao": ""})
        assert r.status_code == 200 and "Configuração salva" in r.text
        with sessao() as db:
            assert ler_config(db, "renov_dono_id") == dono_ms and ler_config(db, "renov_conexao") == "principal"
            assert config_propria_da_ar(db, certy, "renov_dono_id") == ""  # ficou só no Grupo Certy
            usar_config_da_ar(db, ms)
            assert renovacao.dono(db).id == int(dono_ms) and renovacao.cfg(db, "renov_conexao") == "principal"
        cliente.post("/master/sair", data={"csrf": csrf})
        # fora das ARs, o Admin Master mexe na Renovação da AR MS (a que a campanha automática do dia usa)
        cliente.post("/renovacao/configurar", data={"csrf": csrf, **BASE, "dono_id": dono_ms, "conexao": ""})
        with sessao() as db:
            assert config_propria_da_ar(db, ms, "renov_dono_id") == dono_ms
            assert config_propria_da_ar(db, ms, "renov_conexao") == ""  # "Automático", gravado só na MS
            assert ler_config(db, "renov_conexao") == "principal"  # o da plataforma não mudou
        assert "vale para todas as marcas" not in " ".join(cliente.get("/renovacao").text.split())
    finally:
        cliente.post("/master/sair", data={"csrf": csrf})
        _zerar_limite()


def test_teste_do_admin_master_dentro_de_outra_ar_sai_com_a_marca_dela(cliente, ars, monkeypatch):
    filas = []
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(whatsapp_leads, "enviar", lambda *a, **k: filas.append(a[2]) or "p1")
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: _NUMEROS)
    with sessao() as db:
        gravar_config(db, "renov_dono_id", "")  # sem dono: assina quem testa (o Admin Master, que não tem AR)
        master = _admin(db)
        assert master.master and master.tenant_id is None
        renovacao.enviar_teste(db, master, 0, "whatsapp", "5581999990000", "renov_aviso", ar=ars["grupo-certy"])
        renovacao.enviar_teste(db, master, 0, "whatsapp", "5581999990000", "renov_aviso", ar=ars["ms"])
        db.rollback()
    assert len(filas) == 2
    assert "Grupo Certy" in filas[0] and "MS Certificação" not in filas[0]  # dentro do Grupo Certy: a marca dele
    assert "MS Certificação" in filas[1]  # na MS, como sempre
