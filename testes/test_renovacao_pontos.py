"""Pontos de atendimento fora dos avisos (26/11/2026, pedido da Maria: na planilha da MS, 173 dos 746 certificados eram do
ponto Gilberto Contábil, e os clientes dele não devem receber os avisos). A importação guarda as colunas Ponto e
Unidade; no quadro 4 a marca escreve os pontos sem avisos; os certificados deles ficam na lista ("Ponto fora dos
avisos"), mas não entram nas campanhas nem no "Montar com todos da planilha". Celulares e e-mails só destes testes."""

from sqlalchemy import select

from app import renovacao
from app.banco import config_da_ar, config_propria_da_ar, gravar_config_da_ar, sessao
from app.modelos import Certificado, Tenant
from test_renovacao import _admin, _limpar, _linha, _planilha

UNIDADE_GILBERTO, PONTO_GILBERTO = "MARIA JOSE EDUARDA NOGUEIRA DOS SANTOS", "GILBERTO CONTABIL"


def _do_ponto(dias, protocolo, cliente, email, celular, unidade=UNIDADE_GILBERTO, ponto=PONTO_GILBERTO):
    linha = _linha(dias, protocolo, "e-CPF A1 12 meses", "", "", cliente, "52998224725", email, celular)
    linha[12], linha[13] = unidade, ponto  # colunas Unidade e Ponto do relatório
    return linha


def _ms(db) -> int:
    return db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar()


def _linhas():
    return [_linha(10, "7740001", "e-CPF A1 12 meses", "", "", "CLIENTE MATRIZ", "52998224725",
                   "cliente.matriz@testeponto.com.br", "81987750001"),
            _do_ponto(10, "7740002", "CLIENTE GILBERTO", "cliente.gilberto@testeponto.com.br", "81987750002"),
            _do_ponto(12, "7740003", "OUTRO GILBERTO", "outro.gilberto@testeponto.com.br", "81987750003")]


def test_le_o_ponto_e_a_unidade_da_planilha():
    registros, problemas = renovacao.ler_planilha("r.xlsx", _planilha(_linhas()))
    assert not problemas and [(r["ponto"], r["unidade"]) for r in registros] == [
        ("MATRIZ", "MS CERTIFICACAO DIGITAL LTDA"), (PONTO_GILBERTO, UNIDADE_GILBERTO), (PONTO_GILBERTO, UNIDADE_GILBERTO)]
    d = renovacao.dados_do_registro(registros[1])
    assert d["ponto"] == PONTO_GILBERTO and d["unidade"] == UNIDADE_GILBERTO


def test_ponto_fora_dos_avisos_nao_entra_nas_campanhas(cliente):
    with sessao() as db:
        _limpar(db)
        renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha(_linhas()))[0], _admin(db))
        ms = _ms(db)
    try:
        with sessao() as db:
            with config_da_ar(db, ms):  # antes da regra: os três entram
                assert len(renovacao.contatos_para_campanha(db, ar=ms)[0]) == 3
            gravar_config_da_ar(db, ms, "renov_pontos_fora", "Gilberto Contábil")  # sem diferença de acento/maiúscula
        with sessao() as db:
            with config_da_ar(db, ms):
                contatos, fora = renovacao.contatos_para_campanha(db, ar=ms)
                assert [c.certificados[0].protocolo for c in contatos] == ["7740001"]
                assert fora == {"de ponto de atendimento fora dos avisos": 2}
                assert [c.protocolo for c in renovacao.a_avisar(db, ar=ms)] == ["7740001"]
                # quem vence nos próximos dias e o "todos da planilha" também deixam de fora
                todos, _ = renovacao.contatos_para_campanha(db, ate=renovacao.ATE_TODOS, ar=ms,
                                                             desde=renovacao.inicio_da_ultima_planilha(db))
                assert len(todos) == 1
        pagina = " ".join(cliente.get("/renovacao?ver=proximos").text.split())  # o Admin Master: a marca principal
        assert "Ponto fora dos avisos (GILBERTO CONTABIL)" in pagina
        assert "Montar com todos da planilha (1)" in pagina
        assert "2 certificados (de ponto de atendimento fora dos avisos)" in pagina
        assert "GILBERTO CONTABIL (2 certificados)" in pagina  # o quadro 4 mostra os pontos das planilhas
        with sessao() as db:  # importar de novo guarda o ponto também em quem já estava (planilha antiga, sem ele)
            for c in db.execute(select(Certificado).where(Certificado.protocolo.in_(["7740002", "7740003"]))).scalars():
                c.ponto = c.unidade = ""
        with sessao() as db:
            r = renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha(_linhas()))[0], _admin(db))
            assert r["atualizados"] == 2
            pontos = {c.protocolo: c.ponto for c in db.execute(select(Certificado).where(
                Certificado.protocolo.in_(["7740001", "7740002", "7740003"]))).scalars()}
            assert pontos == {"7740001": "MATRIZ", "7740002": PONTO_GILBERTO, "7740003": PONTO_GILBERTO}
    finally:
        with sessao() as db:
            _limpar(db)


def test_quadro_4_grava_os_pontos_sem_repetir(cliente, csrf):
    r = cliente.post("/renovacao/configurar", data={
        "csrf": csrf, "canal_whatsapp": "on", "dias": "30, 15, 5, 1", "hora_inicio": "10:00", "hora_fim": "18:00",
        "feriados": "", "pontos_fora": "gilberto  contabil; GILBERTO CONTÁBIL,\nOutro Ponto"})
    assert r.status_code == 200 and "Configuração salva." in r.text
    with sessao() as db:
        assert config_propria_da_ar(db, _ms(db), "renov_pontos_fora") == "gilberto contabil, Outro Ponto"
    assert 'value="gilberto contabil, Outro Ponto"' in cliente.get("/renovacao").text
