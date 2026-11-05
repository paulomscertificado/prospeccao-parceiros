"""Cada usuário fala em nome da própria empresa (Minha conta > Empresa que eu represento)."""

from types import SimpleNamespace

from app import marca

TEXTO_MS = ("Olá, Daniele, tudo bem?\n\nSou Thamires, da MS Certificação Digital, Autoridade de Registro ICP-Brasil.\n\n"
            "Isso fica com a MS: atendimento, validação presencial em Recife ou por videoconferência e aviso.\n\n"
            "Nossa equipe faz a validação (presencial em Recife ou por videoconferência) e avisa.\n\n"
            "Thamires\nMS Certificação Digital · mscertificados.com.br")


def _usuario(**campos):
    base = {f"empresa_{c}": "" for c in marca.PADRAO}
    base.update({f"empresa_{k}": v for k, v in campos.items()})
    return SimpleNamespace(nome="Thamires Souza", perfil="vendedor", **base)


def test_sem_configuracao_fica_como_esta():
    assert marca.aplicar(TEXTO_MS, _usuario()) == TEXTO_MS
    assert marca.aplicar(TEXTO_MS, None) == TEXTO_MS


def test_troca_pela_empresa_do_usuario_e_tira_a_validacao():
    u = _usuario(nome="Grupo Certy Certificados", site="grupocerty.com.br", descricao="Autoridade de Registro credenciada")
    t = marca.aplicar(TEXTO_MS, u)
    assert "MS" not in t and "mscertificados" not in t and "Recife" not in t and "videoconferência" not in t
    assert "Sou Thamires, do Grupo Certy Certificados, Autoridade de Registro credenciada." in t
    assert "atendimento, validação e aviso" in t and "faz a validação e avisa" in t
    assert "Grupo Certy Certificados · grupocerty.com.br" in t


def test_empresas_novas_sem_preco_e_com_nome_do_dono():
    from app import empresas_novas

    u = _usuario(nome="Certifica Já", site="certificaja.com.br")
    lead = SimpleNamespace(empresa="Nova Loja Ltda", cidade="Recife")
    original = empresas_novas.mensagens
    empresas_novas.mensagens = lambda db: empresas_novas.MENSAGENS_PADRAO
    try:
        textos = empresas_novas.textos_do_lead(None, lead, u)
    finally:
        empresas_novas.mensagens = original
    for angulo in textos.values():
        for campo in ("whatsapp", "email", "assunto"):
            assert "R$" not in angulo[campo] and "validação" not in angulo[campo].lower() and "MS" not in angulo[campo]
    assert "da Certifica Já" in textos["venda_boas_vindas"]["whatsapp"]
    assert textos["venda_boas_vindas"]["email"].endswith("Thamires\nCertifica Já · certificaja.com.br")


def test_minha_conta_salva_empresa(cliente):
    from conftest import csrf_de
    from sqlalchemy import select

    from app.banco import sessao
    from app.modelos import Usuario

    pagina = cliente.get("/minha-conta")
    trecho = pagina.text.split("Empresa que eu represento")[1].split("</form>")[0]
    assert "Preço" not in trecho and "validação" not in trecho
    cliente.post("/minha-conta/empresa", data={"csrf": csrf_de(pagina.text), "nome": "Grupo Certy Certificados",
                                               "site": "https://www.grupocerty.com.br/", "descricao": ""})
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        assert admin.empresa_nome == "Grupo Certy Certificados" and admin.empresa_site == "grupocerty.com.br"
        admin.empresa_nome = admin.empresa_site = ""  # os outros testes esperam a empresa padrão
        db.commit()


def test_email_da_campanha_grupo_certy_teste_02():
    """Caso real: 'A MS faz todo o atendimento' (com maiúscula) escapava, e o nome do MEI vinha com o CPF."""
    u = _usuario(nome="Grupo Certy", site="grupocerty.com.br",
                 descricao="credenciado à ICP-Brasil para emitir certificados digitais.")
    t = marca.aplicar("Sou Thamires, da MS Certificação Digital, Autoridade de Registro ICP-Brasil.\n\n"
                      "1. A Alberto Vitor de Carvalho 52309851604 indica o cliente;\n"
                      "2. A MS faz todo o atendimento, emissão e validação;\n"
                      "3. A Alberto Vitor de Carvalho 52309851604 é remunerada por certificado emitido;\n"
                      "Vocês indicam e a MS cuida de tudo. Parceria MS Certificação Digital + MS Engenharia", u)
    assert "Sou Thamires, do Grupo Certy, credenciado à ICP-Brasil para emitir certificados digitais." in t
    assert "2. O Grupo Certy faz todo o atendimento" in t and "1. Vocês indicam o cliente;" in t
    assert "o Grupo Certy cuida de tudo" in t and "Parceria Grupo Certy + MS Engenharia" in t
    assert "A MS" not in t and "a MS " not in t and "52309851604" not in t


def test_nome_do_mei_sem_numeros():
    from app import util

    assert util.nome_para_mensagem("69.562.640 RAQUEL TAVARES DA SILVA") == "RAQUEL TAVARES DA SILVA"
    assert util.nome_para_mensagem("Alberto Vitor de Carvalho 52309851604") == "Alberto Vitor de Carvalho"
    assert util.nome_para_mensagem("Contabilidade 2000 Ltda") == "Contabilidade 2000 Ltda"
