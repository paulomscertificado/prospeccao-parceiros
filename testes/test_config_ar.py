"""White label, Fase 2 parte 2: configurações próprias de cada AR (banco.CHAVES_DA_AR, tabela configuracoes_ar).

Quem é de uma AR muda só as configurações da AR, e o valor fica só nela; as da plataforma, só o Admin Master. Sem valor
próprio, a AR usa o da plataforma. As filas e as respostas leem as configurações da AR do registro que estão tratando.
"""
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app import mensagens
from app.banco import algum_valor, gravar_config, ler_config, sessao, usar_config_da_ar
from app.main import app
from app.modelos import ConfiguracaoAR, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de


def _zerar_limite():
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)


def _admin(email: str, empresa: str) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if u is None:
            u = Usuario(nome=f"Admin {empresa}", email=email, perfil="admin", senha_hash=resumir_senha(SENHA),
                        empresa_nome=empresa)
            db.add(u)
            db.flush()
        return u.tenant_id


def _entrar(email: str) -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def test_cada_ar_muda_so_as_proprias_configuracoes(cliente, csrf):
    _zerar_limite()
    ar_certy = _admin("admin.config@grupocerty.com.br", "Grupo Certy")
    _admin("admin.config@ms.com.br", "MS Certificação Digital")
    try:
        with sessao() as db:
            padrao_inicio, padrao_banco = ler_config(db, "horario_envio_inicio"), ler_config(db, "limite_banco_mb")
        certy = _entrar("admin.config@grupocerty.com.br")
        tela = certy.get("/configuracoes").text
        assert "sua AR" in tela and "da plataforma" in tela
        certy.post("/configuracoes/geral", data={"csrf": csrf_de(tela), "horario_envio_inicio": "09:15",
                                                 "limite_banco_mb": "1"})
        with sessao() as db:
            assert db.get(ConfiguracaoAR, (ar_certy, "horario_envio_inicio")).valor == "09:15"
            assert ler_config(db, "horario_envio_inicio") == padrao_inicio  # a plataforma não mudou
            assert ler_config(db, "limite_banco_mb") == padrao_banco  # da plataforma: a AR não muda
            usar_config_da_ar(db, ar_certy)
            assert ler_config(db, "horario_envio_inicio") == "09:15"
            assert ler_config(db, "limite_banco_mb") == padrao_banco
        assert 'value="09:15"' in certy.get("/configuracoes").text
        assert 'value="09:15"' not in _entrar("admin.config@ms.com.br").get("/configuracoes").text  # AR MS: padrão
        assert 'value="09:15"' not in cliente.get("/configuracoes").text  # Admin Master: o padrão da plataforma
    finally:
        _zerar_limite()
        with sessao() as db:
            db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.tenant_id == ar_certy))


def test_filas_veem_as_configuracoes_da_ar_da_tarefa():
    with sessao() as db:
        ars = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}
        usar_config_da_ar(db, ars["grupo-certy"])
        gravar_config(db, "enviar_whatsapp_automatico", "0")  # só o Grupo Certy desliga
        gravar_config(db, "horario_envio_inicio", "00:00")
        gravar_config(db, "horario_envio_fim", "23:59")
        usar_config_da_ar(db, None)
    try:
        with sessao() as db:
            assert ler_config(db, "enviar_whatsapp_automatico") == "1"  # a plataforma (e a AR MS) seguem ligadas
            assert algum_valor(db, "enviar_whatsapp_automatico", "1") and algum_valor(db, "enviar_whatsapp_automatico", "0")
            usar_config_da_ar(db, ars["grupo-certy"])
            assert ler_config(db, "enviar_whatsapp_automatico") == "0"
            usar_config_da_ar(db, ars["ms"])
            assert ler_config(db, "enviar_whatsapp_automatico") == "1"
            usar_config_da_ar(db, None)
            domingo = datetime(2026, 11, 15, 12, 0)
            assert not mensagens.dentro_do_horario(db, domingo)
            gravar_config(db, "horario_envio_fim", "00:01")  # a plataforma quase sem horário
            agora_ = datetime(2026, 11, 16, 23, 0)  # segunda, 23h: fora do horário da plataforma
            assert not mensagens.dentro_do_horario(db, agora_)
            usar_config_da_ar(db, ars["grupo-certy"])
            assert mensagens.dentro_do_horario(db, agora_)  # o Grupo Certy ainda está no horário dele
    finally:
        with sessao() as db:
            db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.tenant_id == ars["grupo-certy"]))
            gravar_config(db, "horario_envio_fim", "18:00")
