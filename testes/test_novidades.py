"""Avisos como no WhatsApp (pedido da Maria em 23/11/2026: "replique o funcionamento de notificações do WhatsApp para o
sistema, além de que adicione esse som para quando alguém responder em alguma conversa ou algum disparo de alguma
campanha"): o navegador pergunta a /novidades e recebe os números do menu e o que chegou de novo (mensagem nas
Conversas, no número oficial e resposta de campanha), só do que a pessoa pode ver; toca o som e mostra o aviso."""

from sqlalchemy import select, update

from app import conexoes, whatsapp_oficial
from app.banco import sessao
from app.modelos import ContaWhatsAppOficial, MensagemWhatsApp, Notificacao, Usuario
from test_contador_conversas import _entrar, _usuario
from test_whatsapp_oficial import NUMERO_ID, _admin, _conta_da_ms

EMAIL_FUNC = "func.novidades@teste.com.br"
EMAIL_VEND = "vend.novidades@teste.com.br"
EMAIL_CERTY = "admin.novidades@grupocerty-novidades.com.br"


def _mensagem(db, id_wl: int, numero: str, telefone: str, texto: str, lida: bool = False) -> MensagemWhatsApp:
    m = MensagemWhatsApp(id_wl=id_wl, telefone=telefone, conexao=numero, nome="Cliente Novidades", direcao="entrada",
                         texto=texto, status="recebida", origem="", lida=lida)
    db.add(m)
    db.flush()
    return m


def test_novidades_so_do_que_a_pessoa_ve(cliente):
    _conta_da_ms()
    fid = _usuario(EMAIL_FUNC, "Fábio Novidades", "funcionario")
    vid = _usuario(EMAIL_VEND, "Vera Sem Número Novidades", "vendedor")
    _admin(EMAIL_CERTY, "Grupo Certy")
    with sessao() as db:
        conexoes.minha(db, db.get(Usuario, fid), criar=True)
    numero = f"u{fid}"
    func_, vend, certy = _entrar(EMAIL_FUNC), _entrar(EMAIL_VEND), _entrar(EMAIL_CERTY)

    # a primeira pergunta: os números do menu e o ponto de partida, sem avisar o que já estava lá
    inicio = func_.get("/novidades").json()
    assert inicio["novas"] == [] and set(inicio["ultimos"]) == {"c", "o", "n"}
    assert {"conversas", "oficial", "oportunidades", "avisos"} <= set(inicio["contadores"])
    desde = "?c={c}&o={o}&n={n}".format(**inicio["ultimos"])

    with sessao() as db:
        _mensagem(db, 970_000_001, numero, "81955556001", "Bom dia!\n\nQuero renovar o meu certificado")
        conta = db.execute(select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.phone_number_id == NUMERO_ID)
                           .execution_options(sem_filtro_de_ar=True)).scalars().one()
        whatsapp_oficial.guardar_conversa(db, conta, "(81) 95555-6002", "entrada", "Pode me ligar?", "texto",
                                          "wamid.NOVIDADES-1", "Olga Oficial")
        db.add(Notificacao(usuario_id=fid, texto="🔥 Resposta quente: EMPRESA NOVIDADES LTDA", link="/oportunidades#op-1"))
        db.add(Notificacao(usuario_id=fid, texto="Conecte o seu WhatsApp", link="/whatsapp"))  # aviso do sistema: sem som

    r = func_.get("/novidades" + desde).json()
    por_tipo = {n["tipo"]: n for n in r["novas"]}
    assert set(por_tipo) == {"conversa", "oficial", "resposta"}
    conversa = por_tipo["conversa"]
    assert conversa["titulo"] == "Cliente Novidades" and conversa["texto"] == "Bom dia! Quero renovar o meu certificado"
    assert conversa["link"] == f"/conversas?telefone=81955556001&numero={numero}" and conversa["numero"] == numero
    assert por_tipo["oficial"]["titulo"] == "Olga Oficial · número oficial" and por_tipo["oficial"]["link"].startswith("/oficial?")
    assert por_tipo["resposta"]["texto"].startswith("🔥 Resposta quente") and por_tipo["resposta"]["link"] == "/oportunidades#op-1"
    assert r["contadores"]["conversas"] >= 1 and r["contadores"]["avisos"] >= 2
    assert r["ultimos"]["c"] >= conversa["id"]

    # a vendedora não vê o número do Fábio nem os avisos dele; o Grupo Certy não vê nada da MS
    tipos_vend = {n["tipo"] for n in vend.get("/novidades" + desde).json()["novas"]}
    assert "conversa" not in tipos_vend and "resposta" not in tipos_vend and "oficial" in tipos_vend
    da_certy = certy.get("/novidades" + desde).json()
    assert da_certy["novas"] == [] and "oficial" not in da_certy["contadores"]

    # abriu a conversa: não avisa mais (só o que ainda não foi lido)
    with sessao() as db:
        db.execute(update(MensagemWhatsApp).where(MensagemWhatsApp.id_wl == 970_000_001).values(lida=True))
    assert "conversa" not in {n["tipo"] for n in func_.get("/novidades" + desde).json()["novas"]}
    assert vid  # (a vendedora existe só para conferir o que ela não vê)


def test_som_botoes_e_numeros_do_menu_nas_telas(cliente):
    som = cliente.get("/static/sons/notificacao.wav")
    assert som.status_code == 200 and som.headers["content-type"].startswith("audio/") and len(som.content) > 10_000
    assert cliente.get("/static/notificacoes.js").status_code == 200
    pagina = cliente.get("/leads").text
    assert '<script src="/static/notificacoes.js' in pagina and 'id="notif-config"' in pagina
    for ident in ("contador-conversas", "contador-oportunidades", "link-avisos"):
        assert f'id="{ident}"' in pagina  # o navegador atualiza estes números sozinho


def test_conversas_filtro_nao_lidas(cliente):
    fid = _usuario(EMAIL_FUNC, "Fábio Novidades", "funcionario")
    with sessao() as db:
        conexoes.minha(db, db.get(Usuario, fid), criar=True)
        _mensagem(db, 970_000_101, f"u{fid}", "81955556101", "Ainda não li esta", lida=False)
        _mensagem(db, 970_000_102, f"u{fid}", "81955556102", "Esta já foi lida", lida=True)
    f = _entrar(EMAIL_FUNC)
    todas = {c["telefone"] for c in f.get("/conversas/api/lista").json()["conversas"]}
    assert {"81955556101", "81955556102"} <= todas
    so_nao_lidas = f.get("/conversas/api/lista?nao_lidas=1").json()["conversas"]
    telefones = {c["telefone"] for c in so_nao_lidas}
    assert "81955556101" in telefones and "81955556102" not in telefones
    assert all(c["nao_lidas"] > 0 for c in so_nao_lidas)
