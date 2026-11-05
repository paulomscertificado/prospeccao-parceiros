"""Cada usuário fala em nome da própria empresa (Minha conta > Empresa que eu represento)."""

from types import SimpleNamespace

from app import marca

TEXTO_MS = ("Olá, Daniele, tudo bem?\n\nSou Thamires, da MS Certificação Digital, Autoridade de Registro ICP-Brasil.\n\n"
            "Isso fica com a MS: atendimento, validação presencial em Recife ou por videoconferência.\n\n"
            "Thamires\nMS Certificação Digital · mscertificados.com.br")


def _usuario(**campos):
    base = {f"empresa_{c}": "" for c in marca.PADRAO}
    base.update({f"empresa_{k}": v for k, v in campos.items()})
    return SimpleNamespace(nome="Thamires Souza", perfil="vendedor", **base)


def test_sem_configuracao_fica_como_esta():
    assert marca.aplicar(TEXTO_MS, _usuario()) == TEXTO_MS
    assert marca.aplicar(TEXTO_MS, None) == TEXTO_MS


def test_troca_pela_empresa_do_usuario():
    u = _usuario(nome="Grupo Certy Certificados", site="grupocerty.com.br", descricao="Autoridade de Registro credenciada",
                 validacao="por videoconferência ou presencial em Fortaleza")
    t = marca.aplicar(TEXTO_MS, u)
    assert "MS" not in t and "mscertificados" not in t and "Recife" not in t
    assert "Sou Thamires, do Grupo Certy Certificados, Autoridade de Registro credenciada." in t
    assert "Grupo Certy Certificados · grupocerty.com.br" in t
    assert "validação por videoconferência ou presencial em Fortaleza" in t


def test_empresas_novas_usa_preco_e_nome_do_dono():
    from app import empresas_novas

    u = _usuario(nome="Certifica Já", preco_a1="R$ 180", preco_a3="R$ 400", site="certificaja.com.br")
    lead = SimpleNamespace(empresa="Nova Loja Ltda", cidade="Recife")

    class Db:  # mensagens() lê só a configuração (sem textos salvos: usa os modelos)
        pass

    original = empresas_novas.mensagens
    empresas_novas.mensagens = lambda db: empresas_novas.MENSAGENS_PADRAO
    try:
        textos = empresas_novas.textos_do_lead(Db(), lead, u)
    finally:
        empresas_novas.mensagens = original
    zap = textos["venda_boas_vindas"]["whatsapp"]
    assert "da Certifica Já" in zap and "R$ 180" in zap and "R$ 400" in zap and "MS" not in zap
    assert textos["venda_boas_vindas"]["email"].endswith("Thamires\nCertifica Já · certificaja.com.br")


def test_minha_conta_salva_empresa(cliente):
    from conftest import csrf_de
    from sqlalchemy import select

    from app.banco import sessao
    from app.modelos import Usuario

    pagina = cliente.get("/minha-conta")
    assert "Empresa que eu represento" in pagina.text
    cliente.post("/minha-conta/empresa", data={"csrf": csrf_de(pagina.text), "nome": "Grupo Certy Certificados",
                                               "site": "https://www.grupocerty.com.br/", "descricao": "", "validacao": "",
                                               "preco_a1": "", "preco_a3": ""})
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        assert admin.empresa_nome == "Grupo Certy Certificados" and admin.empresa_site == "grupocerty.com.br"
        admin.empresa_nome = admin.empresa_site = ""  # os outros testes esperam a empresa padrão
        db.commit()
