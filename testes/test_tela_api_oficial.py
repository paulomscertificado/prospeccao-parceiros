"""Tela API Oficial (pedido da Maria em 21/11/2026: "preciso ver as respostas dos clientes em algum lugar ... separado
das conversas ... como API Oficial"). O número oficial está ligado direto na API e não abre em celular nenhum: o
sistema guarda tudo o que ele manda e tudo o que chega nele (de cliente ou não), com a situação da entrega, e mostra
numa tela própria do menu, só para a AR que tem a API oficial. A Meta é imitada: nada sai de verdade."""

from datetime import timedelta

from sqlalchemy import func, select

from app import whatsapp_oficial
from app.banco import agora, gravar_config, sessao
from app.leads_servico import apagar_conversas_antigas, limpar_campos
from app.modelos import ContaWhatsAppOficial, Lead, MensagemOficial
from test_whatsapp_oficial import NUMERO_ID, _admin, _ars, _assinado, _conta_da_ms, _entrar

CERTY = "admin.tela.oficial@grupocerty.com.br"


def _evento(mensagens: list[dict] | None = None, statuses: list[dict] | None = None) -> dict:
    """Como a Meta manda: um contato (com o nome do perfil) por número, e as mensagens."""
    nomes = {}
    for m in mensagens or []:
        nome = m.pop("nome", "")
        if nome:
            nomes.setdefault(m["from"], nome)
    return {"entry": [{"id": "998877", "changes": [{"value": {
        "metadata": {"phone_number_id": NUMERO_ID},
        "contacts": [{"wa_id": numero, "profile": {"name": nome}} for numero, nome in nomes.items()],
        "messages": mensagens or [], "statuses": statuses or []}}]}]}


def _conta(db) -> ContaWhatsAppOficial:
    return db.execute(select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.phone_number_id == NUMERO_ID)
                      .execution_options(sem_filtro_de_ar=True)).scalars().one()


def test_guarda_tudo_o_que_chega_no_numero_oficial(cliente):
    """A resposta do cliente, a mensagem de quem não é cliente e o toque no botão ficam guardados (com o nome do
    perfil); a Meta mandando o mesmo evento de novo não duplica."""
    _conta_da_ms()
    ms, _ = _ars()
    with sessao() as db:
        lead = Lead(empresa="CLIENTE TELA OFICIAL LTDA", whatsapp="(81) 99555-7001", tenant_id=ms)
        limpar_campos(lead)
        db.add(lead)
        db.commit()
        lead_id = lead.id
    evento = lambda: _evento([  # noqa: E731
        {"from": "5581995557001", "id": "wamid.TELA-CLIENTE", "type": "text", "text": {"body": "Quero renovar sim"},
         "nome": "Paula Cliente"},
        {"from": "5581995557002", "id": "wamid.TELA-OUTRO", "type": "text", "text": {"body": "Quem é?"},
         "nome": "Desconhecido"},
        {"from": "5581995557001", "id": "wamid.TELA-BOTAO", "type": "button",
         "button": {"text": "Já renovei", "payload": "renov:renovei:999999999"}},
        {"from": "5581995557002", "id": "wamid.TELA-FOTO", "type": "image", "image": {"id": "1"}}])
    assert _assinado(cliente, evento()).status_code == 200
    assert _assinado(cliente, evento()).status_code == 200  # a Meta mandou de novo
    with sessao() as db:
        linhas = {m.wamid: m for m in db.execute(select(MensagemOficial).where(
            MensagemOficial.wamid.like("wamid.TELA-%"))).scalars()}
        assert set(linhas) == {"wamid.TELA-CLIENTE", "wamid.TELA-OUTRO", "wamid.TELA-BOTAO", "wamid.TELA-FOTO"}
        cliente_msg, outro = linhas["wamid.TELA-CLIENTE"], linhas["wamid.TELA-OUTRO"]
        assert cliente_msg.direcao == "entrada" and cliente_msg.lead_id == lead_id and cliente_msg.tenant_id == ms
        assert cliente_msg.telefone == "81995557001" and cliente_msg.nome == "Paula Cliente" and not cliente_msg.lida
        assert outro.lead_id is None and outro.texto == "Quem é?"  # de quem não é cliente também fica
        assert linhas["wamid.TELA-BOTAO"].tipo == "botao" and linhas["wamid.TELA-BOTAO"].texto == "Já renovei"
        assert linhas["wamid.TELA-FOTO"].tipo == "midia"


def test_situacao_da_entrega_nunca_volta_e_a_falha_mostra_o_motivo(cliente):
    _conta_da_ms()
    with sessao() as db:
        conta = _conta(db)
        whatsapp_oficial.guardar_conversa(db, conta, "(81) 99555-7003", "saida", "Aviso de teste", "modelo",
                                          "wamid.TELA-SAIU")
        whatsapp_oficial.guardar_conversa(db, conta, "(81) 99555-7004", "saida", "Outro aviso", "modelo",
                                          "wamid.TELA-FALHOU")
        db.commit()
    eventos = [{"id": "wamid.TELA-SAIU", "status": "delivered"}, {"id": "wamid.TELA-SAIU", "status": "read"},
               {"id": "wamid.TELA-SAIU", "status": "delivered"},  # chegou fora de ordem: continua "lida"
               {"id": "wamid.TELA-FALHOU", "status": "failed", "errors": [{"title": "Re-engagement message"}]}]
    assert _assinado(cliente, _evento(statuses=eventos)).status_code == 200
    with sessao() as db:
        saiu = db.execute(select(MensagemOficial).where(MensagemOficial.wamid == "wamid.TELA-SAIU")).scalars().one()
        falhou = db.execute(select(MensagemOficial).where(MensagemOficial.wamid == "wamid.TELA-FALHOU")).scalars().one()
        assert saiu.status == "lida" and saiu.telefone == "81995557003"
        assert falhou.status == "falhou" and "Re-engagement" in falhou.erro


def test_tela_mostra_as_conversas_so_para_a_ar_do_numero(cliente):
    """O item "API Oficial" aparece só na AR que tem a API oficial, com o número de mensagens novas; abrir a conversa
    marca como lidas. A outra AR não vê o item nem as conversas."""
    _conta_da_ms()
    ms, certy = _ars()
    with sessao() as db:
        conta = _conta(db)
        whatsapp_oficial.guardar_conversa(db, conta, "(81) 99555-7010", "saida", "Olá! Último aviso: vence amanhã.",
                                          "modelo", "wamid.TELA-AVISO")
        whatsapp_oficial.guardar_conversa(db, conta, "(81) 99555-7010", "entrada", "Pode me ligar amanhã?", "texto",
                                          "wamid.TELA-RESPOSTA", "Marina Tela")
        db.commit()
        novas = db.execute(select(func.count(MensagemOficial.id)).where(
            MensagemOficial.direcao == "entrada", MensagemOficial.lida.is_(False))).scalar()
    menu = cliente.get("/leads").text  # o Admin Master (fora de uma AR) vê as de todas
    assert 'href="/oficial"' in menu and f'title="Mensagens novas no número oficial">{novas}<' in menu
    conversa = cliente.get("/oficial?telefone=81995557010").text
    assert "Marina Tela" in conversa and "Pode me ligar amanhã?" in conversa and "Último aviso" in conversa
    assert "não está cadastrado como cliente" in conversa
    with sessao() as db:
        resposta = db.execute(select(MensagemOficial).where(MensagemOficial.wamid == "wamid.TELA-RESPOSTA")).scalars().one()
        assert resposta.lida  # abriu a conversa: ficou lida
    assert cliente.get("/oficial/marca").json()["marca"]

    assert _admin(CERTY, "Grupo Certy") == certy  # o Grupo Certy não tem API oficial
    certy_tela = _entrar(CERTY)
    menu = certy_tela.get("/leads").text
    assert 'href="/oficial"' not in menu
    pagina = certy_tela.get("/oficial").text
    assert "ainda não tem a <b>API oficial do WhatsApp</b>" in pagina and "Marina Tela" not in pagina


def test_conversas_antigas_saem_no_prazo_de_guarda(cliente):
    _conta_da_ms()
    with sessao() as db:
        conta = _conta(db)
        velha = whatsapp_oficial.guardar_conversa(db, conta, "(81) 99555-7020", "entrada", "Mensagem antiga", "texto",
                                                  "wamid.TELA-VELHA")
        velha.criado_em = agora() - timedelta(days=400)
        gravar_config(db, "guarda_conversas_meses", "12")
        db.commit()
        apagar_conversas_antigas(db)
        db.commit()
        assert db.execute(select(MensagemOficial).where(MensagemOficial.wamid == "wamid.TELA-VELHA")).first() is None
