"""Renovação de cada marca (24/11/2026, pedido da Maria: "só separe a parte de renovação, que cada uma tem a sua base de
dados interna"). Dias dos avisos, horário, outros feriados, canais, arte, textos e o que a tela guarda passam a ser de
cada marca: salvar o quadro 4 numa marca mudava o das outras, e as filas usavam um horário só para todas."""

from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from app import banco, campanhas, renovacao, sdr
from app.banco import agora, config_da_ar, config_propria_da_ar, gravar_config, sessao
from app.modelos import Campanha, Certificado, ConfiguracaoAR, Lead, Tarefa, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de
from test_isolamento import _entrar
from test_renovacao import _admin

CHAVES = ("renov_dias", "renov_hora_inicio", "renov_hora_fim", "renov_feriados", "renov_ativo_desde", "renov_canais",
          "renov_maximo_dia", "renov_hora", "renov_arte", "renov_mensagens", "renov_ultima_importacao")


def _ars(db) -> dict[str, int]:
    return {slug: i for i, slug in db.execute(select(Tenant.id, Tenant.slug))}


def _limpar_config():
    with sessao() as db:
        db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.chave.in_(CHAVES)))


def _aviso(db, ar: int, protocolo: str, celular: str, dia: date, vence_em: int = 10) -> Tarefa:
    """Campanha de renovação aprovada da marca `ar` com um cliente e um aviso de WhatsApp no `dia`."""
    admin = _admin(db)
    camp = Campanha(nome=f"Renovação marca {protocolo}", tipo="renovacao", status="ativa", usuario_id=admin.id,
                    canais="whatsapp", aprovado_em=agora(), tenant_id=ar)
    lead = Lead(empresa=f"CLIENTE MARCA {protocolo} LTDA", whatsapp=celular, status="Abordagem criada",
                vendedor_id=admin.id, origem=renovacao.ORIGEM_LEAD, tenant_id=ar)
    db.add_all([camp, lead])
    db.flush()
    cert = Certificado(origem="planilha", protocolo=protocolo, cliente_nome=lead.empresa, tipo="e-CNPJ A1",
                       data_vencimento=dia + timedelta(days=vence_em), status="Ativo", campanha_id=camp.id,
                       lead_id=lead.id, whatsapp=celular, tenant_id=ar)
    db.add(cert)
    db.flush()
    t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, certificado_id=cert.id, canal="whatsapp",
               data=dia, hora="00:01", status="pendente", angulo="renov_aviso", tenant_id=ar,
               mensagem="Olá! O certificado digital vence em breve.")
    db.add(t)
    db.flush()
    assert (camp.tenant_id, t.tenant_id) == (ar, ar)
    return t


def test_todas_as_configuracoes_da_renovacao_sao_de_cada_marca(cliente):
    assert set(CHAVES) <= banco.CHAVES_DA_AR
    with sessao() as db:
        ar = _ars(db)
        with config_da_ar(db, None):
            gravar_config(db, "renov_dias", "")  # a plataforma no padrão (30, 15, 5 e 1)
        with config_da_ar(db, ar["ms"]):
            gravar_config(db, "renov_dias", "12,6,3,1")
            gravar_config(db, "renov_hora_inicio", "10:00")
        with config_da_ar(db, ar["grupo-certy"]):
            gravar_config(db, "renov_hora_inicio", "08:00")
        with config_da_ar(db, ar["ms"]):
            assert renovacao.dias_aviso(db) == (12, 6, 3, 1) and renovacao.hora_inicio(db) == "10:00"
        with config_da_ar(db, ar["grupo-certy"]):  # sem valor próprio, o da plataforma
            assert renovacao.dias_aviso(db) == renovacao.DIAS_AVISO and renovacao.hora_inicio(db) == "08:00"
        # segunda 09:00: só a MS (que começa às 10:00) está fora do horário
        segunda_9h = datetime(2026, 11, 16, 9, 0)
        fora = renovacao.ars_fora_do_horario(db, segunda_9h)
        assert ar["ms"] in fora and ar["grupo-certy"] not in fora
        assert {ar["ms"], ar["grupo-certy"]} <= renovacao.ars_fora_do_horario(db, datetime(2026, 11, 14, 11, 0))  # sábado
        db.rollback()


def test_quadro_4_de_uma_marca_nao_muda_o_da_outra(cliente):
    with sessao() as db:
        ar = _ars(db)
        certy = db.execute(select(Usuario).where(Usuario.email == "admin.renov.marca@grupocerty.com.br")).scalars().first()
        if certy is None:
            certy = Usuario(nome="Admin Renovação Certy", email="admin.renov.marca@grupocerty.com.br", perfil="admin",
                            senha_hash=resumir_senha(SENHA), empresa_nome="Grupo Certy", tenant_id=ar["grupo-certy"])
            db.add(certy)
        with config_da_ar(db, ar["ms"]):
            gravar_config(db, "renov_dias", "12,6,3,1")
            gravar_config(db, "renov_hora_inicio", "10:00")
            gravar_config(db, "renov_feriados", "08/12")
    try:
        c = _entrar("admin.renov.marca@grupocerty.com.br")
        pagina = c.get("/renovacao").text
        r = c.post("/renovacao/configurar", data={
            "csrf": csrf_de(pagina), "canal_whatsapp": "on", "maximo_dia": "25", "hora": "08:15", "dias": "20, 10, 5, 2",
            "hora_inicio": "08:00", "hora_fim": "17:00", "feriados": "02/02", "ativo_desde": ""})
        assert r.status_code == 200
        with sessao() as db:
            propria = {chave: config_propria_da_ar(db, ar["grupo-certy"], chave)
                       for chave in ("renov_dias", "renov_hora_inicio", "renov_hora_fim", "renov_feriados")}
            assert propria == {"renov_dias": "20,10,5,2", "renov_hora_inicio": "08:00", "renov_hora_fim": "17:00",
                               "renov_feriados": "02/02"}
            # a MS ficou como estava
            assert config_propria_da_ar(db, ar["ms"], "renov_dias") == "12,6,3,1"
            assert config_propria_da_ar(db, ar["ms"], "renov_hora_inicio") == "10:00"
            assert config_propria_da_ar(db, ar["ms"], "renov_feriados") == "08/12"
        assert 'value="20, 10, 5, 2"' in c.get("/renovacao").text  # a tela do Grupo Certy mostra os dele
    finally:
        _limpar_config()


def test_fila_segura_so_os_avisos_da_marca_fora_do_horario(cliente, monkeypatch):
    from app.integracoes import whatsapp_leads

    enviados = []
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True})
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado",
                        lambda db, texto, u, lead=None, tarefa=None: enviados.append(lead.empresa))
    real = renovacao.fora_do_horario
    relogio = {"agora": datetime(2026, 11, 16, 9, 0)}  # segunda, 09:00
    monkeypatch.setattr(renovacao, "fora_do_horario",
                        lambda db, momento=None, margem_minutos=0: real(db, relogio["agora"], margem_minutos))
    try:
        with sessao() as db:
            ar = _ars(db)
            gravar_config(db, "enviar_whatsapp_automatico", "1")
            with config_da_ar(db, ar["ms"]):
                gravar_config(db, "renov_hora_inicio", "10:00")
            with config_da_ar(db, ar["grupo-certy"]):
                gravar_config(db, "renov_hora_inicio", "08:00")
            _aviso(db, ar["ms"], "9500001", "(81) 98556-0001", date.today())
            _aviso(db, ar["grupo-certy"], "9500002", "(81) 98556-0002", date.today())
            campanhas.processar_fila_whatsapp(db, maximo=1000)
            # o Grupo Certy já começou (08:00); a MS só às 10:00
            assert "CLIENTE MARCA 9500002 LTDA" in enviados and "CLIENTE MARCA 9500001 LTDA" not in enviados
            relogio["agora"] = datetime(2026, 11, 16, 10, 0)
            campanhas.processar_fila_whatsapp(db, maximo=1000)
            assert "CLIENTE MARCA 9500001 LTDA" in enviados
            db.rollback()
    finally:
        _limpar_config()


def test_feriado_de_uma_marca_nao_mexe_nos_avisos_da_outra(cliente):
    hoje = date.today()
    dia = hoje + timedelta(days=(2 - hoje.weekday()) % 7 + 7)  # uma quarta-feira daqui a 1 ou 2 semanas
    with sessao() as db:
        ar = _ars(db)
        with config_da_ar(db, ar["ms"]):
            gravar_config(db, "renov_feriados", dia.strftime("%d/%m/%Y"))  # feriado só da MS
        da_ms = _aviso(db, ar["ms"], "9500003", "(81) 98556-0003", dia)
        da_certy = _aviso(db, ar["grupo-certy"], "9500004", "(81) 98556-0004", dia)
        r = renovacao.remarcar_feriados(db)
        assert r["remarcados"] >= 1
        assert da_ms.data != dia and da_certy.data == dia  # só o aviso da MS saiu do feriado dela
        db.rollback()
    _limpar_config()
