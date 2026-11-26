"""Tela Renovação, área de montar as campanhas (26/11/2026, pedido da Maria: "ajuste melhor essa área de criar as
campanhas de renovação"). O Grupo Certy ligou "Montar a campanha do dia sozinho" às 08:45, mas a campanha automática
do dia só roda na marca principal: nas outras o quadro 4 não mostra mais o liga/desliga (nem horário, início e máximo)
e salvar deixa desligada. O quadro 3 separa as duas formas de montar (A. todos da última planilha; B. só quem vence nos
próximos dias), diz quantos estão prontos em cada uma e, sem ninguém nos próximos dias, quando entra o próximo.
Celulares e e-mails só destes testes.
"""

from datetime import date, timedelta

from sqlalchemy import delete, select

from app.banco import config_propria_da_ar, gravar_config_da_ar, sessao
from app.modelos import ConfiguracaoAR, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de
from test_isolamento import _entrar
from test_renovacao import _limpar, _linha, _planilha

EMAIL_CERTY = "admin.tela.montar@grupocerty.com.br"


def _certy() -> int:
    """A administradora do Grupo Certy destes testes; devolve a AR dele."""
    with sessao() as db:
        ar = db.execute(select(Tenant.id).where(Tenant.slug == "grupo-certy")).scalar()
        if db.execute(select(Usuario).where(Usuario.email == EMAIL_CERTY)).scalars().first() is None:
            db.add(Usuario(nome="Admin Tela Certy", email=EMAIL_CERTY, perfil="admin", senha_hash=resumir_senha(SENHA),
                           empresa_nome="Grupo Certy", tenant_id=ar))
        return ar


def _formulario(csrf: str, **extra) -> dict:
    return {"csrf": csrf, "canal_whatsapp": "on", "canal_email": "on", "dias": "25, 15, 5, 1", "hora_inicio": "10:00",
            "hora_fim": "17:30", "feriados": "08/12", **extra}


def test_marca_sem_automatica_nao_mostra_o_liga_desliga_e_salvar_desliga(cliente):
    ar = _certy()
    with sessao() as db:  # como o Grupo Certy deixou em 26/11/2026: ligada às 08:45, achando que ia rodar
        for chave, valor in (("renov_ativo", "1"), ("renov_hora", "08:45"), ("renov_maximo_dia", "40")):
            gravar_config_da_ar(db, ar, chave, valor)
    c = _entrar(EMAIL_CERTY)
    pagina = c.get("/renovacao").text
    assert 'name="ativo"' not in pagina and 'name="hora"' not in pagina and 'name="ativo_desde"' not in pagina
    assert 'name="maximo_dia"' not in pagina
    assert "A campanha automática do dia ainda não" in pagina and "Quem envia, por qual número e quando" in pagina
    assert "A. Todos da última planilha" in pagina and "B. Só quem vence nos próximos" in pagina
    r = c.post("/renovacao/configurar", data=_formulario(csrf_de(pagina)))
    assert r.status_code == 200 and "Configuração salva." in r.text and "campanha automática roda" not in r.text
    with sessao() as db:
        assert config_propria_da_ar(db, ar, "renov_ativo") == "0"  # desligada: ela não roda para a marca
        assert config_propria_da_ar(db, ar, "renov_hora") == "08:45"  # o resto da automática fica como estava
        assert config_propria_da_ar(db, ar, "renov_dias") == "25,15,5,1"


def test_marca_principal_continua_com_a_campanha_automatica(cliente, csrf):
    pagina = cliente.get("/renovacao").text  # o Admin Master fora das marcas: a Renovação da marca principal
    assert 'name="ativo"' in pagina and 'name="hora"' in pagina and "Campanha automática, quem envia" in pagina
    assert "A campanha automática do dia ainda não" not in pagina
    r = cliente.post("/renovacao/configurar", data=_formulario(csrf, ativo="on", hora="07:30", maximo_dia="35"))
    assert "A campanha automática roda todo dia às 07:30" in r.text or "escolha quem é o dono" in r.text
    with sessao() as db:
        ms = db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar()
        assert config_propria_da_ar(db, ms, "renov_ativo") == "1"
        assert config_propria_da_ar(db, ms, "renov_hora") == "07:30"
        assert config_propria_da_ar(db, ms, "renov_maximo_dia") == "35"


def test_quadro_3_diz_quando_entra_o_proximo_e_conta_so_a_marca(cliente):
    ar = _certy()
    with sessao() as db:
        _limpar(db)
        gravar_config_da_ar(db, ar, "renov_dias", "12,6,3,1")
    try:
        c = _entrar(EMAIL_CERTY)
        pagina = c.get("/renovacao").text
        conteudo = _planilha([_linha(26, "7730001", "e-CPF A1 12 meses", "", "", "CLIENTE TELA CERTY", "52998224725",
                                     "cliente.tela@testetela-certy.com.br", "81987740001"),
                              _linha(5, "7730002", "e-CPF A1 12 meses", "", "", "OUTRO TELA CERTY", "52998224725",
                                     "outro.tela@testetela-certy.com.br", "81987740002")])
        r = c.post("/renovacao/importar", data={"csrf": csrf_de(pagina)},
                   files={"arquivo": ("planilha.xlsx", conteudo, "application/octet-stream")})
        assert r.status_code == 200 and "2 certificados novos" in r.text.replace("<b>", "").replace("</b>", "")
        pagina = " ".join(c.get("/renovacao").text.split())
        assert "1 contato pronto agora" in pagina  # B: o que vence em 5 dias
        assert "Montar com todos da planilha (2)" in pagina  # A: os dois da planilha
        # o Admin Master fora das marcas monta na marca principal: os clientes do Grupo Certy não contam lá
        master = " ".join(cliente.get("/renovacao").text.split())
        assert "Ninguém fora de campanha vence nos próximos" in master and "Montar com todos da planilha (0)" in master
        with sessao() as db:  # o que vence em 5 dias já entrou numa campanha: B fica sem ninguém
            from app.modelos import Certificado

            db.execute(delete(Certificado).where(Certificado.protocolo == "7730002"))
        pagina = " ".join(c.get("/renovacao").text.split())  # sem as quebras de linha do HTML
        entra, vence = date.today() + timedelta(days=14), date.today() + timedelta(days=26)
        assert "Ninguém fora de campanha vence nos próximos 12 dias." in pagina
        assert f"O próximo entra em <b>{entra:%d/%m/%Y}</b> (vence em {vence:%d/%m/%Y})" in pagina
    finally:
        with sessao() as db:
            _limpar(db)
            db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.tenant_id == ar,
                                                    ConfiguracaoAR.chave == "renov_ultima_importacao_em"))
