"""A imagem dos avisos na tela API Oficial (pedido da Maria em 23/11/2026: "eu não consigo ver a imagem das mensagens
para saber se saíram corretas"). O aviso que sai pelo número oficial com a arte guarda uma cópia dela (a de
artes_aviso sai em 10 dias) e a tela mostra a imagem dentro da mensagem, como no WhatsApp; um clique abre inteira.
Cada AR vê só as suas. A Meta é imitada: nada sai de verdade."""

from datetime import timedelta

from sqlalchemy import delete, select

from app import whatsapp_oficial
from app.banco import agora, gravar_config, ler_config, sessao
from app.leads_servico import apagar_conversas_antigas
from app.modelos import ArteAviso, ImagemOficial, MensagemOficial
from test_whatsapp_oficial import _admin, _entrar, _zerar_limite
from test_whatsapp_oficial_renovacao import PNG, _aviso, _conta, _limpar, _meta, _no_horario

CERTY = "admin.imagem.oficial@grupocerty.com.br"


def _avisar_com_arte(db, empresa: str, telefone: str):
    """Um aviso da Renovação que sai pelo número oficial com a arte (o computador do WhatsApp Leads já desenhou)."""
    t = _aviso(db, empresa, telefone)
    db.add(ArteAviso(ponte_id=0, tarefa_id=t.id, imagem=PNG, tenant_id=t.tenant_id))
    db.flush()
    whatsapp_oficial.enviar_toque(db, t)
    saiu = db.execute(select(MensagemOficial).where(MensagemOficial.lead_id == t.lead_id)).scalars().one()
    return t, saiu


def test_arte_do_aviso_aparece_dentro_da_mensagem(cliente, monkeypatch):
    _meta(monkeypatch)
    _no_horario(monkeypatch)
    with sessao() as db:
        _conta(db)
        t, saiu = _avisar_com_arte(db, "FLORICULTURA ARTE OFICIAL LTDA", "(81) 99447-0001")
        db.commit()
        assert saiu.texto.startswith(whatsapp_oficial.MARCA_DA_ARTE)
        imagem = db.execute(select(ImagemOficial).where(ImagemOficial.mensagem_id == saiu.id)).scalars().one()
        assert imagem.wamid == saiu.wamid and imagem.tipo == "image/png" and imagem.tenant_id == saiu.tenant_id
        mid = saiu.id
        _limpar(db, [t.id])
    tela = cliente.get("/oficial?telefone=81994470001").text
    assert f'<img src="/oficial/imagem/{mid}"' in tela and f'href="/oficial/imagem/{mid}" target="_blank"' in tela
    assert "não está guardada" not in tela
    r = cliente.get(f"/oficial/imagem/{mid}")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert f'filename="aviso-{mid}.png"' in r.headers["content-disposition"]

    # outra AR não vê a imagem (nem adivinhando o número da mensagem)
    _zerar_limite()
    _admin(CERTY, "Grupo Certy")
    assert _entrar(CERTY).get(f"/oficial/imagem/{mid}").status_code == 404

    # restaurou um backup (que não leva as imagens) e o número da mensagem foi reaproveitado: a imagem de outra
    # mensagem nunca aparece (o id da mensagem na Meta é conferido junto)
    with sessao() as db:
        db.execute(select(ImagemOficial).where(ImagemOficial.mensagem_id == mid)).scalars().one().wamid = "wamid.outra"
        db.commit()
    tela = cliente.get("/oficial?telefone=81994470001").text
    assert f'<img src="/oficial/imagem/{mid}"' not in tela and "A imagem deste aviso não está guardada aqui." in tela
    assert cliente.get(f"/oficial/imagem/{mid}").status_code == 404


def test_avisos_que_ja_tinham_saido_ganham_a_imagem(cliente, monkeypatch):
    """Os avisos que saíram antes desta mudança: a arte ainda guardada (10 dias) vira a imagem da mensagem; o aviso de
    exemplo do teste ganha a arte de exemplo; o aviso só com o texto continua sem imagem. Pode rodar de novo."""
    _meta(monkeypatch)
    _no_horario(monkeypatch)
    with sessao() as db:
        conta = _conta(db)
        t, saiu = _avisar_com_arte(db, "LIVRARIA ARTE OFICIAL LTDA", "(81) 99447-0002")
        db.execute(delete(ImagemOficial).where(ImagemOficial.mensagem_id == saiu.id))  # como antes de 23/11/2026
        exemplo = whatsapp_oficial.guardar_conversa(
            db, conta, "(81) 99447-0003", "saida",
            whatsapp_oficial.PREFIXO_DO_EXEMPLO + whatsapp_oficial.MARCA_DA_ARTE + "Olá, Guilherme!", "modelo",
            "wamid.IMG-EXEMPLO-1")
        so_texto = whatsapp_oficial.guardar_conversa(db, conta, "(81) 99447-0004", "saida", "Aviso só com o texto",
                                                     "modelo", "wamid.IMG-SO-TEXTO-1")
        db.commit()
        ids = [saiu.id, exemplo.id, so_texto.id]
        assert whatsapp_oficial.guardar_imagens_que_faltam(db) >= 2
        db.commit()
        assert whatsapp_oficial.guardar_imagens_que_faltam(db) == 0  # pode rodar de novo: nada em dobro
        imagens = {i.mensagem_id: i for i in db.execute(select(ImagemOficial).where(
            ImagemOficial.mensagem_id.in_(ids))).scalars()}
        assert set(imagens) == {saiu.id, exemplo.id}
        assert imagens[saiu.id].imagem == PNG and imagens[saiu.id].wamid == saiu.wamid
        assert imagens[exemplo.id].imagem == whatsapp_oficial.IMAGEM_DE_EXEMPLO.read_bytes()
        _limpar(db, [t.id])


def test_aviso_de_exemplo_do_teste_guarda_a_arte_de_exemplo(cliente, monkeypatch):
    _meta(monkeypatch)
    with sessao() as db:
        conta = _conta(db)
        assert whatsapp_oficial.enviar_teste_renovacao(db, conta, "(81) 99447-0006") == "aviso_vencimento_certificado_arte"
        db.commit()
        saiu = db.execute(select(MensagemOficial).where(MensagemOficial.telefone == "81994470006")
                          .order_by(MensagemOficial.id.desc())).scalars().first()
        assert saiu.texto.startswith(whatsapp_oficial.PREFIXO_DO_EXEMPLO + whatsapp_oficial.MARCA_DA_ARTE)
        imagem = db.execute(select(ImagemOficial).where(ImagemOficial.mensagem_id == saiu.id)).scalars().one()
        assert imagem.imagem == whatsapp_oficial.IMAGEM_DE_EXEMPLO.read_bytes()


def test_imagem_sai_junto_com_a_conversa_no_prazo_de_guarda(cliente):
    with sessao() as db:
        prazo_de_antes = ler_config(db, "guarda_conversas_meses")
        try:
            conta = _conta(db)
            velha = whatsapp_oficial.guardar_conversa(db, conta, "(81) 99447-0005", "saida",
                                                      whatsapp_oficial.MARCA_DA_ARTE + "Aviso antigo", "modelo",
                                                      "wamid.IMG-VELHA", imagem=PNG)
            imagem = db.execute(select(ImagemOficial).where(ImagemOficial.mensagem_id == velha.id)).scalars().one()
            velha.criado_em = imagem.criado_em = agora() - timedelta(days=400)
            gravar_config(db, "guarda_conversas_meses", "12")
            db.commit()
            imagem_id = imagem.id
            apagar_conversas_antigas(db)
            db.commit()
            assert db.execute(select(ImagemOficial.id).where(ImagemOficial.id == imagem_id)).first() is None
            assert db.execute(select(MensagemOficial.id).where(MensagemOficial.wamid == "wamid.IMG-VELHA")).first() is None
        finally:  # os outros testes contam com o prazo de antes (sem prazo = nada sai)
            gravar_config(db, "guarda_conversas_meses", prazo_de_antes or "0")
            db.commit()
