"""Renovação (pedido da Maria em 12/11/2026): planilha de renovação da certificadora → certificados → campanha com os
avisos 30, 15, 5 e 1 dia antes do vencimento, um por CONTATO (o mesmo WhatsApp recebe uma mensagem só, com a lista
dos certificados dele). Quem já venceu não recebe aviso; o contato vem só da planilha."""

import io
import json
from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select

from app import campanhas, renovacao, sdr
from app.banco import agora, gravar_config, sessao
from app.modelos import Campanha, Certificado, Lead, Tarefa, Trabalho, Usuario

# O cabeçalho exato do "Relatório de renovação" da certificadora: Email e Telefone repetidos (empresa e pessoa),
# acento estragado em "Razão Social" e a data de nascimento (que nunca é lida).
CABECALHO = ["Vencimento", "Protocolo", "Certificado", "Raz�o Social", "CNPJ", "Email", "Telefone", "Cliente",
             "CPF", "Data Nascimento", "Email", "Telefone", "Unidade", "Ponto", "Parceiro", None]


def _linha(dias, protocolo, certificado, razao, cnpj, cliente, cpf, email, telefone, parceiro="Sem parceiro"):
    venc = datetime.combine(date.today() + timedelta(days=dias), time())
    return [venc, protocolo, certificado, razao, cnpj, email if cnpj else "", telefone if cnpj else "", cliente, cpf,
            "01/01/1980", email, telefone, "MS CERTIFICACAO DIGITAL LTDA", "MATRIZ", parceiro, None]


def _planilha(linhas) -> bytes:
    from openpyxl import Workbook

    livro = Workbook()
    aba = livro.active
    aba.title = "RELATORIO"
    aba.append(CABECALHO)
    for linha in linhas:
        aba.append(linha)
    saida = io.BytesIO()
    livro.save(saida)
    return saida.getvalue()


def _admin(db):
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _limpar(db):
    """Os testes dividem o banco: começa sem certificados da planilha e sem campanhas de renovação em aberto."""
    for camp in db.execute(select(Campanha).where(Campanha.tipo == "renovacao",
                                                  Campanha.status != "cancelada")).scalars():
        campanhas.cancelar(db, camp, _admin(db))
        db.execute(delete(Trabalho).where(Trabalho.tipo == "campanha", Trabalho.ref_id == camp.id))
    db.execute(delete(Certificado).where(Certificado.origem == renovacao.ORIGEM))


def _montar(cid):
    with sessao() as db:
        t = db.execute(select(Trabalho).where(Trabalho.ref_id == cid, Trabalho.tipo == "campanha")).scalars().first()
        estado = json.loads(t.estado)
    while not campanhas.etapa_gerar(cid, None, estado, float("inf")):
        pass


class _SemLinha:  # a montagem roda aqui, não numa linha de execução paralela (evita corrida no teste)
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


def test_le_o_relatorio_da_certificadora():
    conteudo = _planilha([
        _linha(20, "1234567", "e-CNPJ A1 12 meses - videoconferencia", "PADARIA LEITURA LTDA", "11222333000181",
               "MARIA DA SILVA", "12345678901", "maria@padarialeitura.com.br", "81999990001"),
        # e-CPF: CPF como número (perde o zero da frente) e telefone fixo (sem WhatsApp: só e-mail)
        _linha(40, 2345678, "e-CPF A1 12 meses", "", "", "JOAO PEREIRA", 1234567890, "joao.leitura@gmail.com",
               "8133334444", parceiro="ESCRITORIO X CONTABILIDADE"),
        [None, "999", "e-CNPJ A1", "SEM DATA LTDA", "", "", "", "", "", "", "", "", "", "", "", None],
    ])
    registros, problemas = renovacao.ler_planilha("RELATORIO DE RENOVACAO.xlsx", conteudo)
    assert len(registros) == 2 and len(problemas) == 1 and "sem data de vencimento" in problemas[0]
    pj, pf = registros
    assert pj["razao_social"] == "PADARIA LEITURA LTDA" and pj["cnpj"] == "11222333000181"
    assert pj["email_empresa"] == "maria@padarialeitura.com.br" and pj["telefone_pessoa"] == "81999990001"
    assert pf["cpf"] == "01234567890" and pf["protocolo"] == "2345678" and not pf["cnpj"]
    assert all("nascimento" not in k and "1980" not in str(v) for r in registros for k, v in r.items())
    d = renovacao.dados_do_registro(pj)
    assert d["whatsapp"] == "(81) 99999-0001" and d["cnpj"] == "11.222.333/0001-81" and d["parceiro_nome"] == ""
    assert d["cliente_nome"] == "PADARIA LEITURA LTDA" and d["responsavel"] == "MARIA DA SILVA"
    d = renovacao.dados_do_registro(pf)
    assert d["whatsapp"] == "" and d["telefone"] == "(81) 3333-4444" and d["email"] == "joao.leitura@gmail.com"
    assert d["cnpj"] == "012.345.678-90" and d["cliente_nome"] == "JOAO PEREIRA"
    assert d["parceiro_nome"] == "ESCRITORIO X CONTABILIDADE"
    assert renovacao.tipo_curto("PJ - INAPTO A3 36 meses - videoconferencia") == "e-CNPJ A3"
    assert renovacao.tipo_curto("VALID e-CNPJ A1 12 meses - videoconferencia") == "e-CNPJ A1"


def test_importar_de_novo_nao_duplica(cliente):
    linhas = [_linha(20, "7000001", "e-CNPJ A1 12 meses", "LOJA REPETIDA LTDA", "11444777000161", "ANA SOUZA",
                     "11144477735", "ana@lojarepetida.com.br", "81988880001")]
    with sessao() as db:
        _limpar(db)
        r = renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha(linhas))[0], _admin(db))
        assert r["novos"] == 1 and r["na_janela"] == 1 and r["janela"] == renovacao.janela(db)
        r = renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha(linhas))[0], _admin(db))
        assert r["novos"] == 0 and r["iguais"] == 1
        linhas[0][11] = "81988880002"  # o relatório novo traz outro celular
        r = renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha(linhas))[0], _admin(db))
        assert r["novos"] == 0 and r["atualizados"] == 1
        cert = db.execute(select(Certificado).where(Certificado.protocolo == "7000001")).scalars().one()
        assert cert.whatsapp == "(81) 98888-0002" and cert.status == "Ativo" and cert.origem == "planilha"
        _limpar(db)


def test_datas_dos_avisos_30_15_5_e_1_dia_antes():
    hoje = date(2026, 11, 12)  # quinta-feira
    # longe: os 4 avisos; sábado/domingo vêm para a sexta antes (nunca para depois do vencimento)
    assert renovacao.datas_dos_avisos(date(2026, 12, 20), hoje) == [
        date(2026, 11, 20), date(2026, 12, 4), date(2026, 12, 15), date(2026, 12, 18)]
    # entrou tarde (vence em 8 dias): 1º aviso hoje; o de 5 dias cairia amanhã (dias seguidos): fica o de 1 dia
    assert renovacao.datas_dos_avisos(date(2026, 11, 20), hoje) == [hoje, None, None, date(2026, 11, 19)]
    # vence amanhã: só o 1º aviso
    assert renovacao.datas_dos_avisos(date(2026, 11, 13), hoje) == [hoje, None, None, None]
    # num sábado: o 1º aviso vai para a segunda; o de 5 dias cairia no dia seguinte; o de 1 dia (sábado) vem para a
    # sexta
    assert renovacao.datas_dos_avisos(date(2026, 11, 22), date(2026, 11, 14)) == [date(2026, 11, 16), None, None,
                                                                                    date(2026, 11, 20)]
    # já passou do vencimento: nenhum aviso
    assert renovacao.datas_dos_avisos(date(2026, 11, 10), hoje) == [None] * 4


def test_agenda_respeita_o_teto_de_whatsapps_por_dia():
    """Com 100 clientes vencendo no mês, os 100 primeiros avisos cairiam no mesmo dia (o número só faz 20 contatos frios
    por dia). A agenda espalha: quem vence antes escolhe antes, todo mundo recebe o 1º aviso e os lembretes ocupam as
    vagas que sobram."""
    hoje = date(2026, 11, 16)  # segunda-feira
    vencimentos = [date(2026, 11, 20)] * 3 + [date(2026, 12, 10)] * 3
    datas = renovacao.agenda(vencimentos, hoje, True, Counter(), teto=2)
    assert [d[0] for d in datas] == [date(2026, 11, 16)] * 2 + [date(2026, 11, 17)] * 2 + [date(2026, 11, 18)] * 2
    assert max(Counter(d for ds in datas for d in ds if d).values()) <= 2
    assert datas[0][3] == date(2026, 11, 19) and datas[2][3] is None  # sem vaga (e sem dias entre eles): fica sem
    assert all(d[0] is not None for d in datas)
    # carga de outras campanhas conta; sem teto, valem só as datas certas
    assert renovacao.agenda([date(2026, 11, 20)], hoje, True, Counter({date(2026, 11, 16): 2}), 2)[0][0] == date(2026, 11, 17)
    assert renovacao.agenda(vencimentos, hoje, True, Counter(), 0) == [renovacao.datas_dos_avisos(v, hoje)
                                                                       for v in vencimentos]


def test_mensagem_lista_os_certificados_do_contato():
    def cert(nome, dias, tipo="e-CNPJ A1 12 meses", doc="11.222.333/0001-81", responsavel="MARIA DA SILVA"):
        return Certificado(cliente_nome=nome, tipo=tipo, cnpj=doc, responsavel=responsavel,
                           data_vencimento=date(2026, 12, 1) + timedelta(days=dias))

    um = renovacao.bloco_vencimentos([cert("PADARIA UM LTDA", 0)])
    assert um == "O certificado digital e-CNPJ A1 em nome de PADARIA UM LTDA vence no dia 01/12/2026."
    proprio = renovacao.bloco_vencimentos([cert("MARIA DA SILVA", 0, "e-CPF A3 36 meses", "123.456.789-01")])
    assert proprio == "O seu certificado digital e-CPF A3 vence no dia 01/12/2026."
    tres = renovacao.bloco_vencimentos([cert("MERCADO DOIS LTDA", 3), cert("PADARIA UM LTDA", 0),
                                        cert("MARIA DA SILVA", 5, "e-CPF A1", "123.456.789-01")])
    assert tres.splitlines() == ["Estes certificados digitais vencem em breve:",
                                 "• PADARIA UM LTDA (e-CNPJ A1): vence em 01/12/2026",
                                 "• MERCADO DOIS LTDA (e-CNPJ A1): vence em 04/12/2026",
                                 "• Seu certificado (e-CPF A1): vence em 06/12/2026"]
    muitos = renovacao.bloco_vencimentos([cert(f"EMPRESA {i} LTDA", i) for i in range(57)])
    assert muitos.startswith("57 certificados digitais que você acompanha vencem entre 01/12 e 26/01/2027")
    assert "EMPRESA 30 LTDA" not in muitos  # mais de 5: um resumo, nunca a lista inteira


def test_campanha_agrupa_por_contato_e_marca_os_avisos(cliente, monkeypatch):
    from app import trabalhos

    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    linhas = [
        # contato A: o mesmo WhatsApp em 3 certificados (2 empresas + o e-CPF dela) → 1 mensagem por aviso
        _linha(25, "8000001", "e-CNPJ A1 12 meses - videoconferencia", "PADARIA GRUPO LTDA", "11222333000181",
               "MARIA DA SILVA", "12345678901", "maria@grupoteste.com.br", "81987650001"),
        _linha(27, "8000002", "e-CNPJ A1 12 meses", "MERCADO GRUPO LTDA", "11444777000161",
               "MARIA DA SILVA", "12345678901", "maria@grupoteste.com.br", "81987650001"),
        _linha(28, "8000003", "e-CPF A1 12 meses", "", "", "MARIA DA SILVA", "12345678901",
               "maria@grupoteste.com.br", "81987650001"),
        # contato B: um certificado, WhatsApp e e-mail
        _linha(20, "8000004", "e-CNPJ A1 12 meses", "LOJA SOZINHA LTDA", "22333444000105", "PEDRO LIMA",
               "98765432100", "pedro@lojasozinha.com.br", "81987650002"),
        # contato C: telefone fixo → só e-mail
        _linha(22, "8000005", "e-CPF A3 36 meses", "", "", "JOANA FIXO", "11122233344", "joana.fixo@gmail.com",
               "8132320000"),
        # D: sem WhatsApp e sem e-mail; E: vence daqui a 60 dias (fora da janela); F: já venceu
        _linha(10, "8000006", "e-CPF A1 12 meses", "", "", "SEM CONTATO", "55566677788", "", ""),
        _linha(60, "8000007", "e-CNPJ A1 12 meses", "LONGE LTDA", "33444555000106", "LUCAS LONGE", "44455566677",
               "lucas@longe.com.br", "81987650003"),
        _linha(-2, "8000008", "e-CNPJ A1 12 meses", "VENCIDA LTDA", "44555666000107", "VERA VENCIDA",
               "77788899900", "vera@vencida.com.br", "81987650004"),
    ]
    with sessao() as db:
        _limpar(db)
        admin = _admin(db)
        r = renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha(linhas))[0], admin)
        assert r["novos"] == 8 and r["vencidos"] == 1 and r["sem_contato"] == 1
        contatos, fora = renovacao.contatos_para_campanha(db)
        assert [len(c.certificados) for c in contatos] == [1, 1, 3]  # B (20 dias), C (22) e A (25): quem vence antes
        assert fora == {"sem WhatsApp e sem e-mail na planilha": 1}
        camp = renovacao.criar_campanha(db, admin, quantidade=10)
        cid = camp.id
    _montar(cid)
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.tipo == "renovacao" and camp.status == "aguardando_aprovacao", camp.erro
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars().all()
        leads = {t.lead_id: t.lead for t in tarefas}
        assert len(leads) == 3
        a = next(l for l in leads.values() if l.chave_whatsapp == "81987650001")
        assert a.origem == renovacao.ORIGEM_LEAD and a.empresa == "Maria da Silva (3 certificados)"
        dela = [t for t in tarefas if t.lead_id == a.id]
        zaps = sorted((t for t in dela if t.canal == "whatsapp"), key=lambda t: (t.data, t.hora))
        venc = date.today() + timedelta(days=25)
        esperado = renovacao.datas_dos_avisos(venc, renovacao.primeiro_dia(db))
        assert len(zaps) == sum(1 for d in esperado if d) and zaps[0].angulo == "renov_aviso"
        assert all(t.data <= venc for t in zaps)
        aviso = zaps[0].mensagem
        assert aviso.startswith("Olá, Maria! Tudo bem?") and "Estes certificados digitais vencem em breve" in aviso
        assert "PADARIA GRUPO LTDA (e-CNPJ A1)" in aviso and "Seu certificado (e-CPF A1)" in aviso and "SAIR" in aviso
        for zap in zaps:  # o e-mail de cada aviso fica para depois do WhatsApp do mesmo aviso
            mail = [t for t in dela if t.canal == "email" and t.angulo == zap.angulo]
            assert mail and (mail[0].data, mail[0].hora) > (zap.data, zap.hora)
        primeiro = db.execute(select(Certificado).where(Certificado.protocolo == "8000001")).scalars().one()
        assert {t.certificado_id for t in dela} == {primeiro.id}  # o primeiro a vencer define as datas
        b = next(l for l in leads.values() if l.chave_whatsapp == "81987650002")
        texto_b = next(t.mensagem for t in tarefas if t.lead_id == b.id and t.angulo == "renov_aviso" and t.canal == "whatsapp")
        assert "O certificado digital e-CNPJ A1 em nome de LOJA SOZINHA LTDA vence no dia" in texto_b
        c = next(l for l in leads.values() if l.email == "joana.fixo@gmail.com")
        assert {t.canal for t in tarefas if t.lead_id == c.id} == {"email"}  # sem celular: só e-mail
        presos = {x.protocolo for x in db.execute(select(Certificado).where(Certificado.campanha_id == cid)).scalars()}
        assert presos == {"8000001", "8000002", "8000003", "8000004", "8000005"}
        # aprovada no mesmo dia: as datas ficam como estão
        antes = {t.id: t.data for t in tarefas}
        campanhas.aprovar(db, camp, _admin(db))
        assert all(t.status == "pendente" and t.data == antes[t.id] for t in tarefas)
        # cancelada sem nenhum aviso enviado: os certificados voltam para a fila
        campanhas.cancelar(db, camp, _admin(db))
        assert not db.execute(select(Certificado).where(Certificado.campanha_id == cid)).scalars().all()
        _limpar(db)


def _cenario(db, dias_vencimento, protocolo, numero):
    """Campanha de renovação já aprovada com um contato, um certificado e um aviso de WhatsApp para hoje."""
    admin = _admin(db)
    camp = Campanha(nome=f"Renovação teste {protocolo}", tipo="renovacao", status="ativa", usuario_id=admin.id,
                    canais="whatsapp", aprovado_em=agora())
    lead = Lead(empresa=f"CLIENTE {protocolo} LTDA", whatsapp=numero, status="Abordagem criada",
                vendedor_id=admin.id, origem=renovacao.ORIGEM_LEAD)
    db.add_all([camp, lead])
    db.flush()
    cert = Certificado(origem="planilha", protocolo=protocolo, cliente_nome=lead.empresa, tipo="e-CNPJ A1",
                       data_vencimento=date.today() + timedelta(days=dias_vencimento), status="Ativo",
                       campanha_id=camp.id, lead_id=lead.id, whatsapp=numero)
    db.add(cert)
    db.flush()
    t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, certificado_id=cert.id, canal="whatsapp",
               data=date.today(), hora="00:01", status="pendente", angulo="renov_aviso",
               mensagem="Olá! O certificado digital vence em breve.")
    db.add(t)
    db.flush()
    return camp, cert, t


def test_aviso_de_certificado_vencido_ou_renovado_nao_sai(cliente):
    with sessao() as db:
        _, vencido, t1 = _cenario(db, -1, "9000001", "(81) 98222-0001")
        _, renovado, t2 = _cenario(db, 10, "9000002", "(81) 98222-0002")
        camp, outro, t3 = _cenario(db, 12, "9000003", "(81) 98222-0003")
        # o mesmo contato tem outro certificado na campanha: marcar um como renovado não para os avisos
        segundo = Certificado(origem="planilha", protocolo="9000004", cliente_nome="SEGUNDA LTDA", tipo="e-CNPJ A1",
                              data_vencimento=date.today() + timedelta(days=15), status="Ativo",
                              campanha_id=camp.id, lead_id=outro.lead_id)
        db.add(segundo)
        db.flush()
        assert renovacao.mudar_situacao(db, renovado, "Renovado", _admin(db)) == 1
        assert t2.status == "cancelada" and "renovado" in t2.resultado
        assert renovacao.mudar_situacao(db, outro, "Renovado", _admin(db)) == 0
        assert t3.status == "pendente" and t3.certificado_id == segundo.id
        assert renovacao.encerrar_toques(db) >= 1
        assert t1.status == "cancelada" and "vencimento" in t1.resultado  # quem já venceu não recebe aviso
        db.rollback()


def test_aprovada_depois_conta_as_datas_do_vencimento(cliente):
    """Aprovada 5 dias depois de montada: nada vai para depois do vencimento (nas outras campanhas tudo é empurrado)."""
    with sessao() as db:
        camp, cert, aviso = _cenario(db, 4, "9100001", "(81) 98333-0001")
        camp.status, camp.aprovado_em = "aguardando_aprovacao", None
        aviso.status, aviso.data = "rascunho", date.today() - timedelta(days=5)
        extras = {}
        for angulo, dias in (("renov_lembrete", -2), ("renov_reforco", 0), ("renov_ultimo", 3)):
            extras[angulo] = Tarefa(tipo="prospeccao", lead_id=aviso.lead_id, campanha_id=camp.id,
                                    certificado_id=cert.id, canal="whatsapp", data=date.today() + timedelta(days=dias),
                                    hora="10:07", status="rascunho", angulo=angulo, mensagem="Olá! Aviso.")
            db.add(extras[angulo])
        db.flush()
        campanhas.aprovar(db, camp, _admin(db))
        esperado = renovacao.datas_dos_avisos(cert.data_vencimento, renovacao.primeiro_dia(db))
        pendentes = [t for t in [aviso, *extras.values()] if t.status == "pendente"]
        assert pendentes and all(t.data <= cert.data_vencimento for t in pendentes)
        assert aviso.status == "pendente" and aviso.data >= date.today()
        assert (extras["renov_lembrete"].status == "cancelada") == (esperado[1] is None)
        db.rollback()


def test_fila_manda_a_renovacao_sozinha_e_antes(cliente, monkeypatch):
    from app.integracoes import whatsapp_leads

    enviados = []
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True})
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    monkeypatch.setattr(renovacao, "fora_do_horario", lambda db, momento=None, margem_minutos=0: "")
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado",
                        lambda db, texto, u, lead=None, tarefa=None: enviados.append(lead.empresa))
    with sessao() as db:
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        admin = _admin(db)
        novas = Campanha(nome="Empresas novas antes da renovação", tipo="empresas_novas", status="ativa",
                         usuario_id=admin.id, canais="whatsapp", aprovado_em=agora())
        lead_nova = Lead(empresa="NOVA EMPRESA FILA LTDA", whatsapp="(81) 98444-0001", status="Abordagem criada",
                         vendedor_id=admin.id)
        db.add_all([novas, lead_nova])
        db.flush()
        db.add(Tarefa(tipo="prospeccao", lead_id=lead_nova.id, campanha_id=novas.id, canal="whatsapp",
                      data=date.today(), hora="00:00", status="pendente", mensagem="Olá! Empresa nova."))
        _, _, t = _cenario(db, 10, "9200001", "(81) 98444-0002")
        _, _, vencido = _cenario(db, -1, "9200002", "(81) 98444-0003")
        db.flush()
        campanhas.processar_fila_whatsapp(db, maximo=1000)
        # mesmo dia: a renovação (tem prazo) sai antes da Empresa nova, mesmo marcada para um minuto depois
        assert enviados.index("CLIENTE 9200001 LTDA") < enviados.index("NOVA EMPRESA FILA LTDA")
        assert "CLIENTE 9200002 LTDA" not in enviados and vencido.status == "cancelada"
        assert t.resultado == "Enviada sozinha (campanha de Renovação aprovada)"
        db.rollback()


def test_ia_nao_responde_cliente_da_renovacao():
    from app import empresas_novas

    assert empresas_novas.e_lead_de_venda(Lead(empresa="X", origem=renovacao.ORIGEM_LEAD))
    assert not empresas_novas.e_lead_de_venda(Lead(empresa="X", origem="Cadastro manual"))


def test_tela_importa_a_planilha_e_monta_a_campanha(cliente, csrf, monkeypatch):
    from app import trabalhos

    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    with sessao() as db:
        _limpar(db)
    assert cliente.get("/renovacao").status_code == 200
    conteudo = _planilha([_linha(15, "9300001", "e-CNPJ A1 12 meses", "TELA RENOVACAO LTDA", "55666777000108",
                                 "CARLA TELA", "12312312312", "carla@telarenovacao.com.br", "81987659999")])
    r = cliente.post("/renovacao/importar", data={"csrf": csrf},
                     files={"arquivo": ("RELATORIO DE RENOVACAO.xlsx", conteudo,
                                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200 and "1 certificado novo" in r.text
    pagina = cliente.get("/renovacao").text
    assert "TELA RENOVACAO LTDA" in pagina and "Pronto para avisar" in pagina
    r = cliente.post("/renovacao/montar", data={"csrf": csrf, "quantidade": "10"})
    assert r.status_code == 200 and "/campanhas/" in str(r.url)
    with sessao() as db:
        camp = db.execute(select(Campanha).where(Campanha.tipo == "renovacao")
                          .order_by(Campanha.id.desc())).scalars().first()
        assert camp.status == "gerando" and camp.quantidade == 1
        _limpar(db)
    r = cliente.post("/renovacao/importar", data={"csrf": csrf},
                     files={"arquivo": ("outra.pdf", b"%PDF", "application/pdf")})
    assert "Excel (.xlsx) ou CSV" in r.text


# ---------------------------------------------------------------- Arte do aviso (a do site), pedido de 12/11/2026

PNG_ARTE = b"\x89PNG\r\n\x1a\n" + b"arte-do-aviso" * 50


def test_arte_do_toque_so_para_quem_tem_um_certificado(cliente):
    with sessao() as db:
        camp, cert, t = _cenario(db, 8, "9400001", "(81) 98555-0001")
        cert.tipo, cert.cnpj = "e-CNPJ A1 12 meses - videoconferencia", "11.222.333/0001-81"
        arte = renovacao.arte_do_toque(db, t)
        assert arte == {"tarefa": t.id, "modelo": "cnpj", "tipo": "A1", "nome": "CLIENTE 9400001 LTDA",
                        "doc": "11.222.333/0001-81", "data": cert.data_vencimento.isoformat()}
        cert.tipo, cert.cnpj = "e-CPF A3 36 meses", "123.456.789-01"
        assert renovacao.arte_do_toque(db, t)["modelo"] == "cpf" and renovacao.arte_do_toque(db, t)["tipo"] == "A3"
        # dois certificados no mesmo contato: a lista vai no texto, sem a arte (ela é de um certificado só)
        db.add(Certificado(origem="planilha", protocolo="9400002", cliente_nome="OUTRA LTDA", tipo="e-CNPJ A1",
                           data_vencimento=date.today() + timedelta(days=12), status="Ativo", campanha_id=camp.id,
                           lead_id=t.lead_id))
        db.flush()
        assert renovacao.arte_do_toque(db, t) is None
        db.rollback()
    with sessao() as db:
        _, _, t = _cenario(db, 8, "9400003", "(81) 98555-0002")
        gravar_config(db, "renov_arte", "0")
        assert renovacao.arte_do_toque(db, t) is None  # desligada na tela
        db.rollback()


def test_whatsapp_da_renovacao_leva_a_arte_mesmo_para_contato_frio(cliente, monkeypatch):
    from app import config
    from app.integracoes import whatsapp_leads

    filas = []
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)  # a arte só vai pela ponte (sistema na nuvem)
    monkeypatch.setattr(whatsapp_leads, "enviar", lambda *a, **k: filas.append(k) or "p1")
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    with sessao() as db:
        _, cert, t = _cenario(db, 8, "9500001", "(81) 98666-0001")
        cert.tipo = "e-CNPJ A1 12 meses"
        msg = sdr.enviar_whatsapp_conectado(db, t.mensagem, _admin(db), lead=t.lead, tarefa=t, conexao="numero-teste")
        assert filas[-1]["arte"]["tarefa"] == t.id and filas[-1]["midia_id"] is None
        assert msg.assunto == "[com a arte do aviso de vencimento]"
        db.rollback()


def test_ponte_leva_a_arte_e_a_copia_volta_para_o_email(cliente, monkeypatch):
    from types import SimpleNamespace

    from app import config, contas_email
    from app.integracoes import email_smtp, whatsapp_leads
    from app.modelos import ArteAviso, Configuracao, PonteWhatsApp

    monkeypatch.setattr(config, "NA_NUVEM", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", "token-arte")
    whatsapp_leads._cache["status"] = None
    cab = {"x-token": "token-arte"}
    status = {"conectado": True, "tipo": "teste", "estado": "Conectado", "numero": "5581900000000"}
    cliente.post("/api/ponte/troca", json={"status": status}, headers=cab)
    with sessao() as db:
        camp, cert, zap = _cenario(db, 8, "9600001", "(81) 98777-0001")
        email = Tarefa(tipo="prospeccao", lead_id=zap.lead_id, campanha_id=camp.id, certificado_id=cert.id,
                       canal="email", data=date.today(), hora="10:00", status="pendente", angulo="renov_aviso",
                       assunto="Vencimento do certificado digital", mensagem="Olá! O certificado vence em breve.")
        db.add(email)
        item = PonteWhatsApp(telefone="81987770001", nome="Cliente", texto="Olá com a arte",
                             arte=json.dumps(renovacao.arte_do_toque(db, zap)))
        db.add(item)
        db.commit()
        pid, email_id, zap_id = item.id, email.id, zap.id
    envios = cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()["envios"]
    com_arte = [e for e in envios if e["id"] == pid][0]
    assert com_arte["arte"]["tarefa"] == zap_id and com_arte["arte"]["modelo"] == "cnpj" and "midia" not in com_arte
    assert cliente.post(f"/api/ponte/arte/{pid}", content=PNG_ARTE, headers={"x-token": "errado"}).status_code == 403
    assert cliente.post(f"/api/ponte/arte/{pid}", content=b"nao-e-png", headers=cab).status_code == 400
    assert cliente.post(f"/api/ponte/arte/{pid}", content=PNG_ARTE, headers=cab).status_code == 200
    with sessao() as db:
        assert db.execute(select(ArteAviso).where(ArteAviso.ponte_id == pid)).scalars().one().tarefa_id == zap_id
        html, imagens = renovacao.email_com_arte(db, db.get(Tarefa, email_id), "Olá! O certificado vence em breve.",
                                                 "https://exemplo/descadastrar/1/x")
        assert 'src="cid:arte-aviso"' in html and "vence em breve" in html and "descadastrar" in html
        assert imagens == {"arte-aviso": PNG_ARTE}
    # o e-mail sai com a arte DENTRO (aparece sem "mostrar imagens") e a versão em texto
    enviados = []

    class SMTPFalso:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            pass

        def login(self, usuario, senha):
            pass

        def send_message(self, msg):
            enviados.append(msg)

    monkeypatch.setattr(email_smtp.smtplib, "SMTP", SMTPFalso)
    monkeypatch.setattr(email_smtp, "problema_de_configuracao", lambda: "")
    monkeypatch.setattr(contas_email, "credenciais", lambda conta: SimpleNamespace(
        host="smtp.gmail.com", porta=587, tls=True, login="", senha="x", remetente="MS <aviso@mscertificados.com.br>",
        endereco="aviso@mscertificados.com.br", responder_para="", imap_host="", imap_porta=993, rotulo="principal"))
    from app import arquivo_env

    monkeypatch.setattr(arquivo_env, "carregar_do_banco", lambda forcar=False: None)
    email_smtp.enviar("cliente@exemplo.com.br", "Vencimento", "Olá! O certificado vence em breve.", html=html,
                      imagens=imagens)
    partes = {p.get_content_type(): p for p in enviados[0].walk()}
    assert "text/plain" in partes and "text/html" in partes and "multipart/related" in partes
    assert partes["image/png"]["Content-ID"] == "<arte-aviso>" and partes["image/png"].get_content() == PNG_ARTE
    with sessao() as db:
        db.execute(delete(Configuracao).where(Configuracao.chave == "wl_status"))
        assert renovacao.limpar_artes(db) == 0  # nova: fica uns dias
        arte = db.execute(select(ArteAviso).where(ArteAviso.ponte_id == pid)).scalars().one()
        arte.criado_em = agora() - timedelta(days=renovacao.DIAS_GUARDANDO_ARTE + 1)
        db.flush()
        assert renovacao.limpar_artes(db) == 1
        for t in db.execute(select(Tarefa).where(Tarefa.id.in_((email_id, zap_id)))).scalars():
            t.status = "cancelada"
    whatsapp_leads._cache["status"] = None


# ---------------------------------------------------------------- Área de teste (pedido de 12/11/2026)

# situação dos números como o WhatsApp Leads informa: o principal em MODO TESTE (só simula) e o u903 por QR code
_NUMEROS = {"disponivel": True, "conectado": True, "tipo": "teste",
            "conexoes": {"principal": {"conectado": True, "tipo": "teste", "estado": "Conectado"},
                         "u903": {"conectado": True, "tipo": "qr", "estado": "Conectado", "numero": "5581999990003"},
                         "u909": {"conectado": False, "tipo": "qr", "estado": "Desconectado"}}}


def _numeros_cadastrados(db):
    from app import conexoes
    from app.modelos import ConexaoWhatsApp

    conexoes.garantir_principal(db)
    for cid, nome in (("u903", "WhatsApp de verdade"), ("u909", "WhatsApp desconectado")):
        if db.get(ConexaoWhatsApp, cid) is None:
            db.add(ConexaoWhatsApp(id=cid, nome=nome, compartilhada_todos=True))
    db.flush()

def test_area_de_teste_manda_so_para_quem_testa_com_a_arte(cliente, csrf, monkeypatch):
    """Como o teste da IA SDR: os avisos chegam no WhatsApp de quem testa, com "[TESTE]", o texto do aviso e a arte
    do site (opção marcada). Nenhum cliente recebe nada e nenhuma campanha muda."""
    from app import config, conexoes
    from app.integracoes import whatsapp_leads

    filas = []
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(whatsapp_leads, "enviar", lambda *a, **k: filas.append((a, k)) or "p1")
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: _NUMEROS)
    with sessao() as db:
        _limpar(db)
        renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha([
            _linha(12, "9700001", "e-CNPJ A1 12 meses", "TESTE ARTE LTDA", "11222333000181", "PAULA TESTE",
                   "12345678901", "paula@testearte.com.br", "81987651111"),
            _linha(14, "9700002", "e-CNPJ A1 12 meses", "GRUPO UM LTDA", "11444777000161", "RUI GRUPO",
                   "98765432100", "rui@grupo-teste.com.br", "81987652222"),
            _linha(15, "9700003", "e-CPF A3 36 meses", "", "", "RUI GRUPO", "98765432100", "rui@grupo-teste.com.br",
                   "81987652222"),
        ]))[0], _admin(db))
        um = db.execute(select(Certificado).where(Certificado.protocolo == "9700001")).scalars().one().id
        grupo = db.execute(select(Certificado).where(Certificado.protocolo == "9700002")).scalars().one().id
    pagina = cliente.get("/renovacao").text
    assert 'id="testar"' in pagina and "TESTE ARTE LTDA" in pagina and "2 certificados no mesmo contato" in pagina
    r = cliente.post("/renovacao/testar", data={"csrf": csrf, "certificado": str(um), "canal": "whatsapp",
                                                "whatsapp_teste": "(81) 99999-0000", "avisos": "todos", "com_arte": "on"})
    assert r.status_code == 200 and "Teste enviado: 4 mensagens de WhatsApp" in r.text and "Com a arte" in r.text
    assert len(filas) == 4
    for (destino, _nome, texto), k in filas:
        assert destino == "5581999990000" and k["manual"] is True and texto.startswith("[TESTE · TESTE ARTE LTDA ·")
        assert k["arte"]["teste"] == um and k["arte"]["nome"] == "TESTE ARTE LTDA" and k["arte"]["modelo"] == "cnpj"
        assert "tarefa" not in k["arte"]  # é teste: não é de nenhum aviso de campanha
    filas.clear()
    cliente.post("/renovacao/testar", data={"csrf": csrf, "certificado": str(um), "canal": "whatsapp",
                                            "whatsapp_teste": "81999990000", "avisos": "renov_aviso"})
    assert len(filas) == 1 and filas[0][1]["arte"] is None  # opção da arte desmarcada: só o texto
    filas.clear()
    r = cliente.post("/renovacao/testar", data={"csrf": csrf, "certificado": str(grupo), "canal": "whatsapp",
                                                "whatsapp_teste": "81999990000", "avisos": "renov_aviso", "com_arte": "on"})
    assert filas[0][1]["arte"] is None and "Estes certificados digitais vencem em breve" in filas[0][0][2]
    assert "tem 2 certificados" in r.text  # explica por que foi sem a arte (no envio de verdade é igual)
    r = cliente.post("/renovacao/testar", data={"csrf": csrf, "certificado": "0", "canal": "whatsapp",
                                                "whatsapp_teste": "abc", "avisos": "renov_aviso"})
    assert "celular com DDD" in r.text
    with sessao() as db:
        assert not db.execute(select(Certificado).where(Certificado.origem == "planilha",
                                                        Certificado.campanha_id.is_not(None))).first()
        assert not db.execute(select(Campanha).where(Campanha.tipo == "renovacao",
                                                     Campanha.status != "cancelada")).first()
        _limpar(db)


def test_teste_de_email_leva_a_arte_que_voltou_do_whatsapp(cliente, monkeypatch):
    from app import contas_email
    from app.integracoes import email_smtp
    from app.modelos import ArteAviso, PonteWhatsApp

    enviados = []
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **k: enviados.append((assunto, corpo, k))
                        or "<id@teste>")
    monkeypatch.setattr(contas_email, "para_enviar", lambda db, quem: None)
    with sessao() as db:
        admin = _admin(db)
        r = renovacao.enviar_teste(db, admin, 0, "email", "eu@teste.com.br", "renov_aviso", com_arte=True)
        assert r["enviadas"] == 1 and not r["arte"] and "imagens" not in enviados[-1][2]  # a arte ainda não foi feita
        assert enviados[-1][0].startswith("[TESTE] ") and "EMPRESA EXEMPLO LTDA" in enviados[-1][1]
        # o teste de WhatsApp do cliente fictício saiu e a arte voltou do computador pela ponte
        exemplo = renovacao.contato_do_teste(db, 0, admin).certificados[0]
        item = PonteWhatsApp(telefone="5581999990000", nome="Teste", texto="[TESTE]", manual=True,
                             arte=json.dumps({"teste": 0, **renovacao._arte_do_certificado(exemplo)}))
        db.add(item)
        db.flush()
        db.add(ArteAviso(ponte_id=item.id, tarefa_id=None, imagem=PNG_ARTE))
        db.flush()
        r = renovacao.enviar_teste(db, admin, 0, "email", "eu@teste.com.br", "todos", com_arte=True)
        assert r["enviadas"] == 4 and r["arte"]
        assert all(k["imagens"] == {"arte-aviso": PNG_ARTE} and "cid:arte-aviso" in k["html"] for _, _, k in enviados[-4:])
        r = renovacao.enviar_teste(db, admin, 0, "email", "eu@teste.com.br", "renov_aviso", com_arte=False)
        assert not r["arte"] and "imagens" not in enviados[-1][2]
        db.rollback()


def test_computador_do_whatsapp_a_noite_nao_aparece_como_desligado():
    """O computador dá sinal de 1 em 1 min de dia e de 5 em 5 min à noite: a nuvem espera esse tempo (com folga) antes
    de dizer "desligado" (em 12/11/2026 a tela dizia desligado às 23:41 com o último sinal às 23:38)."""
    from datetime import datetime as _dt

    from app.integracoes import whatsapp_leads as wl

    noite, dia = _dt(2026, 11, 12, 23, 38), _dt(2026, 11, 12, 10, 0)
    assert wl.espera_do_computador({}, noite) == 300 and wl.espera_do_computador({}, dia) == 60
    assert wl.espera_do_computador({}, _dt(2026, 11, 14, 10, 0)) == 300  # sábado
    assert wl.espera_do_computador({"espera": 60}, noite) == 60  # o que o computador informa vale mais
    with sessao() as db:
        for segundos, espera, disponivel in ((250, 300, True), (400, 300, True), (500, 300, False),
                                             (150, 60, True), (200, 60, False), (250, None, None)):
            visto = agora() - timedelta(seconds=segundos)
            dados = {"conectado": True, "visto_em": visto.isoformat()}
            if espera:
                dados["espera"] = espera
            gravar_config(db, "wl_status", dados)
            s = wl._status_da_ponte(db)
            if disponivel is None:  # computador antigo, sem "espera": vale a regra do horário (5 min à noite)
                disponivel = 250 <= wl.espera_do_computador({}, visto) + wl.FOLGA_DO_SINAL
            assert s["disponivel"] is disponivel, (segundos, espera, s)
        gravar_config(db, "wl_status", "")



def test_numero_automatico_nunca_e_o_de_modo_teste_se_houver_um_de_verdade(cliente, monkeypatch):
    """Em 12/11/2026 o teste da Maria não chegou: saiu pelo "principal", em MODO TESTE (o WhatsApp Leads só simula).
    No automático a Renovação prefere um número de verdade; o escolhido vale como foi escolhido (com aviso)."""
    from app import conexoes
    from app.integracoes import whatsapp_leads

    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: _NUMEROS)
    with sessao() as db:
        _numeros_cadastrados(db)
        admin = _admin(db)
        numeros = {n["id"]: n for n in renovacao.numeros_para_escolher(db)}
        assert numeros["principal"]["teste"] and numeros["principal"]["conectado"]
        assert not numeros["u903"]["teste"] and numeros["u903"]["numero"] == "(81) 99999-0003"
        assert not numeros["u909"]["conectado"]
        assert renovacao.numero_automatico(db, admin) == "u903"  # nunca o principal em modo teste
        assert renovacao.numero_do_envio(db, admin, "principal") == "principal"  # escolhido: vale (a tela avisa)
        assert renovacao.numero_em_modo_teste("principal") and not renovacao.numero_em_modo_teste("u903")
        try:
            renovacao.numero_do_envio(db, admin, "u909")
            assert False, "número desconectado não pode ser usado"
        except conexoes.SemNumero as erro:
            assert "desconectado" in str(erro)
        db.rollback()


def test_escolher_o_numero_do_teste_e_dos_disparos(cliente, csrf, monkeypatch):
    from app import config, trabalhos
    from app.integracoes import whatsapp_leads

    filas = []
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(whatsapp_leads, "enviar", lambda *a, **k: filas.append(k) or "p1")
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: _NUMEROS)
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    with sessao() as db:
        _limpar(db)
        _numeros_cadastrados(db)
        db.commit()
    pagina = cliente.get("/renovacao").text
    assert 'name="conexao_teste"' in pagina and 'name="conexao"' in pagina and "MODO TESTE (não chega de verdade)" in pagina
    assert pagina.index('id="testar"') < pagina.index('id="importar"')  # o teste é o 1º passo da tela
    # teste pelo principal (modo teste): sai por ele, mas a tela avisa que não chega de verdade
    r = cliente.post("/renovacao/testar", data={"csrf": csrf, "certificado": "0", "canal": "whatsapp",
                                                "whatsapp_teste": "81999990000", "avisos": "renov_aviso",
                                                "conexao_teste": "principal"})
    assert filas[-1]["conexao"] == "principal" and "está em MODO TESTE" in r.text
    r = cliente.post("/renovacao/testar", data={"csrf": csrf, "certificado": "0", "canal": "whatsapp",
                                                "whatsapp_teste": "81999990000", "avisos": "renov_aviso",
                                                "conexao_teste": "u903"})
    assert filas[-1]["conexao"] == "u903" and "pelo número " in r.text and "está em MODO TESTE" not in r.text
    r = cliente.post("/renovacao/testar", data={"csrf": csrf, "certificado": "0", "canal": "whatsapp",
                                                "whatsapp_teste": "81999990000", "avisos": "renov_aviso"})
    assert filas[-1]["conexao"] == "u903"  # automático: o de verdade, nunca o de modo teste
    # número dos disparos: fica gravado e cada campanha nova já nasce com ele
    cliente.post("/renovacao/configurar", data={"csrf": csrf, "canal_whatsapp": "on", "canal_email": "on",
                                                "maximo_dia": "40", "hora": "07:45", "conexao": "u903", "arte": "on"})
    with sessao() as db:
        assert renovacao.cfg(db, "renov_conexao") == "u903"
        renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha([
            _linha(12, "9800001", "e-CNPJ A1 12 meses", "NUMERO ESCOLHIDO LTDA", "11222333000181", "ANA NUMERO",
                   "12345678901", "ana@numeroescolhido.com.br", "81987653333")]))[0], _admin(db))
        camp = renovacao.criar_campanha(db, _admin(db), 10)
        assert camp.conexao_id == "u903"
        _limpar(db)
        from app.banco import gravar_config

        gravar_config(db, "renov_conexao", "")



# ---------------------------------------------------------------- Piloto de 13/11/2026 a 01/01/2027

def _configurar_piloto(db, **extra):
    from app.banco import gravar_config

    valores = {"renov_dias": "12,6,3,1", "renov_hora_inicio": "10:00", "renov_canais": "whatsapp,email",
               "renov_arte": "1", **extra}
    antes = {k: renovacao.cfg(db, k) for k in valores}
    for k, v in valores.items():
        gravar_config(db, k, v)
    return antes


def _desfazer(db, antes):
    from app.banco import gravar_config

    for k, v in antes.items():
        gravar_config(db, k, v if v != renovacao.PADRAO.get(k) else "")


def test_dias_dos_avisos_e_horario_vem_da_tela(cliente):
    """Pedido da Maria (13/11/2026): avisar 12, 6, 3 e 1 dia antes, a partir das 10h."""
    hoje = date(2026, 11, 16)  # segunda-feira
    dias = (12, 6, 3, 1)
    # vence numa quarta, 02/12: 20/11 (sex), 26/11 (qui), 27/11 (sex, 3 dias antes de 30/11 = sábado → sexta)...
    datas = renovacao.datas_dos_avisos(date(2026, 12, 2), hoje, True, dias)
    assert datas[0] == date(2026, 11, 20) and datas[1] == date(2026, 11, 26) and datas[3] == date(2026, 12, 1)
    with sessao() as db:
        antes = _configurar_piloto(db)
        assert renovacao.dias_aviso(db) == (12, 6, 3, 1) and renovacao.janela(db) == 12
        assert renovacao.hora_inicio(db) == "10:00"
        assert renovacao.nomes_dos_avisos(renovacao.dias_aviso(db))["renov_ultimo"] == "Último aviso (1 dia antes)"
        from app import cadencias

        for _ in range(30):  # horário natural sempre a partir das 10h
            assert cadencias.hora_natural(db, date(2026, 12, 7), minimo="10:00") >= "10:00"
        from app.banco import gravar_config

        gravar_config(db, "renov_dias", "40,abc")  # inválido: volta ao padrão
        assert renovacao.dias_aviso(db) == renovacao.DIAS_AVISO
        _desfazer(db, antes)


def test_campanha_do_piloto_com_ondas_e_a_partir_das_10h(cliente, monkeypatch):
    """Campanha até uma data (piloto: até 31/12) com os avisos marcados desde já: o contato com um certificado que vence
    bem depois do primeiro ganha uma 2ª onda de avisos, com o certificado dela e a arte (um certificado na onda)."""
    from app import trabalhos

    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    linhas = [
        # contato com dois vencimentos distantes (20 e 40 dias): duas ondas
        _linha(20, "9900001", "e-CNPJ A1 12 meses", "ONDA UM LTDA", "19131243000197", "OTAVIO ONDA",
               "12345678901", "otavio@onda-teste.com.br", "81987654441"),
        _linha(40, "9900002", "e-CNPJ A3 36 meses", "ONDA DOIS LTDA", "34028316000103", "OTAVIO ONDA",
               "12345678901", "otavio@onda-teste.com.br", "81987654441"),
        # outro contato, um certificado em 35 dias (fora dos 12 dias, mas dentro do piloto)
        _linha(35, "9900003", "e-CPF A1 12 meses", "", "", "PATRICIA PILOTO", "98765432100",
               "patricia@piloto-teste.com.br", "81987654442"),
    ]
    with sessao() as db:
        _limpar(db)
        antes = _configurar_piloto(db)
        renovacao.importar(db, renovacao.ler_planilha("r.xlsx", _planilha(linhas))[0], _admin(db))
        assert renovacao.contatos_para_campanha(db)[0] == []  # ninguém nos próximos 12 dias
        camp = renovacao.criar_campanha(db, _admin(db), ate=date.today() + timedelta(days=50),
                                        nome="Renovação – piloto de teste")
        cid = camp.id
    _montar(cid)
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.status == "aguardando_aprovacao" and camp.nome == "Renovação – piloto de teste", camp.erro
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars().all()
        assert all((t.hora or "") >= "10:00" for t in tarefas)  # a partir das 10h, WhatsApp e e-mail
        um = db.execute(select(Certificado).where(Certificado.protocolo == "9900001")).scalars().one()
        dois = db.execute(select(Certificado).where(Certificado.protocolo == "9900002")).scalars().one()
        do_otavio = [t for t in tarefas if t.lead_id == um.lead_id]
        assert {t.certificado_id for t in do_otavio} == {um.id, dois.id}  # duas ondas, cada uma com o seu
        onda1 = [t for t in do_otavio if t.certificado_id == um.id and t.canal == "whatsapp"]
        onda2 = [t for t in do_otavio if t.certificado_id == dois.id and t.canal == "whatsapp"]
        assert onda1 and onda2 and max(t.data for t in onda1) < min(t.data for t in onda2)
        assert all(t.data <= um.data_vencimento for t in onda1) and all(t.data <= dois.data_vencimento for t in onda2)
        assert "ONDA UM LTDA" in onda1[0].mensagem and "ONDA DOIS LTDA" not in onda1[0].mensagem
        assert "ONDA DOIS LTDA" in onda2[0].mensagem and "desconsiderar" in onda2[0].mensagem
        primeira2 = min(onda2, key=lambda t: (t.data, t.hora))
        assert (dois.data_vencimento - primeira2.data).days <= 12  # a 2ª onda começa 12 dias antes do vencimento dela
        assert renovacao.arte_do_toque(db, onda2[0])["nome"] == "ONDA DOIS LTDA"  # um certificado na onda: com arte
        # renovou o da 1ª onda: só os avisos dela param
        renovacao.mudar_situacao(db, um, "Renovado", _admin(db))
        assert all(t.status == "cancelada" for t in onda1) and all(t.status == "rascunho" for t in onda2)
        _desfazer(db, antes)
        _limpar(db)


def test_campanha_automatica_so_comeca_na_data_escolhida(cliente, monkeypatch):
    from app import trabalhos
    from app.banco import gravar_config

    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    with sessao() as db:
        antes = _configurar_piloto(db, renov_ativo="1", renov_hora="00:00", renov_dono_id=str(_admin(db).id),
                                   renov_ativo_desde=(date.today() + timedelta(days=1)).isoformat(),
                                   renov_ultima_rodada="")
        assert renovacao.rodada_diaria() == ""  # antes da data: nada
        gravar_config(db, "renov_ativo_desde", date.today().isoformat())
        db.commit()
    texto = renovacao.rodada_diaria()
    assert texto  # na data: roda (monta a campanha do dia ou avisa que não há ninguém)
    with sessao() as db:
        gravar_config(db, "renov_ultima_rodada", "")
        _desfazer(db, antes)
        _limpar(db)


def test_tela_salva_dias_horario_e_inicio(cliente, csrf):
    r = cliente.post("/renovacao/configurar", data={
        "csrf": csrf, "canal_whatsapp": "on", "canal_email": "on", "maximo_dia": "40", "hora": "07:45", "arte": "on",
        "dias": "1, 12, 3, 6", "hora_inicio": "10:00", "ativo_desde": "2027-01-01"})
    assert r.status_code == 200
    with sessao() as db:
        assert renovacao.dias_aviso(db) == (12, 6, 3, 1) and renovacao.hora_inicio(db) == "10:00"
        assert renovacao.cfg(db, "renov_ativo_desde") == "2027-01-01"
    pagina = cliente.get("/renovacao").text
    assert "Vencem em 12 dias" in pagina and "1º aviso (12 dias antes)" in pagina and 'value="12, 6, 3, 1"' in pagina
    r = cliente.post("/renovacao/configurar", data={"csrf": csrf, "canal_whatsapp": "on", "maximo_dia": "40",
                                                    "hora": "07:45", "dias": "12, 6"})
    assert "Escreva os 4 dias" in r.text
    with sessao() as db:
        from app.banco import gravar_config

        for chave in ("renov_dias", "renov_hora_inicio", "renov_ativo_desde"):
            gravar_config(db, chave, "")



def test_campanha_de_renovacao_aparece_como_renovacao(cliente):
    """Pedido da Maria (13/11/2026): "você criou essa campanha como IA SDR, preciso dela como renovação". A página da
    campanha de renovação marca o menu Renovação e volta para lá; a lista da IA SDR não mostra campanhas de renovação."""
    with sessao() as db:
        admin = _admin(db)
        camp = Campanha(nome="Renovação que é renovação", tipo="renovacao", status="aguardando_aprovacao",
                        usuario_id=admin.id, canais="whatsapp,email", objetivo="Renovar o certificado digital dos clientes")
        sdr_camp = Campanha(nome="Campanha da IA SDR comum", tipo="parceiros", status="aguardando_aprovacao",
                            usuario_id=admin.id, canais="whatsapp")
        db.add_all([camp, sdr_camp])
        db.commit()
        cid, sid = camp.id, sdr_camp.id
    pagina = cliente.get(f"/campanhas/{cid}").text
    assert "Campanha de Renovação" in pagina and 'href="/renovacao">Voltar para Renovação' in pagina
    assert 'class="item ativo" href="/renovacao"' in pagina and 'class="item ativo" href="/campanhas"' not in pagina
    assert "tom " not in pagina.split("<h1>")[1].split("</div></div>")[0]  # nada de cidade/tom da IA SDR no topo
    lista = cliente.get("/campanhas?de=todas").text
    assert "Renovação que é renovação" not in lista and "Campanha da IA SDR comum" in lista
    pagina_sdr = cliente.get(f"/campanhas/{sid}").text
    assert 'class="item ativo" href="/campanhas"' in pagina_sdr
    with sessao() as db:
        for i in (cid, sid):
            db.get(Campanha, i).status = "cancelada"



# ---------------------------------------------------------------- Só nos dias comerciais (pedido de 13/11/2026)

def test_renovacao_so_envia_de_segunda_a_sexta_das_10_as_18(cliente):
    """Pedido da Maria (13/11/2026): "os disparos das campanhas de renovação só enviem nos dias comerciais. Segunda a
    sexta das 10:00 - 18:00". O WhatsApp para 10 minutos antes do fim (ainda passa pelo computador do WhatsApp Leads)."""
    from app import cadencias

    margem = renovacao.MARGEM_WHATSAPP_MINUTOS
    sexta = datetime(2026, 11, 13)
    with sessao() as db:
        antes = _configurar_piloto(db)  # a partir das 10:00
        assert renovacao.hora_fim(db) == "18:00"  # o padrão já é até as 18:00
        assert renovacao.fora_do_horario(db, sexta.replace(hour=10)) == ""
        assert renovacao.fora_do_horario(db, sexta.replace(hour=9, minute=59))
        assert renovacao.fora_do_horario(db, sexta.replace(hour=17, minute=49), margem) == ""
        assert renovacao.fora_do_horario(db, sexta.replace(hour=17, minute=50), margem)  # WhatsApp: até 17:50
        assert renovacao.fora_do_horario(db, sexta.replace(hour=17, minute=55)) == ""  # e-mail: até as 18:00
        assert renovacao.fora_do_horario(db, sexta.replace(hour=18))
        for dia in (14, 15):  # sábado e domingo, em qualquer horário
            motivo = renovacao.fora_do_horario(db, datetime(2026, 11, dia, 11, 0))
            assert motivo == "A Renovação só envia de segunda a sexta, das 10:00 às 18:00"
        # os horários marcados nas campanhas também ficam dentro (com folga de 20 minutos no fim)
        for _ in range(40):
            hora = cadencias.hora_natural(db, date(2026, 12, 7), minimo="10:00", maximo="16:00")
            assert "10:00" <= hora <= "15:44"
        assert cadencias.dia_e_hora_futuros(db, date(2026, 12, 5), True, "10:00", "18:00")[0] == date(2026, 12, 7)
        _desfazer(db, antes)


def test_fila_segura_a_renovacao_fora_do_horario(cliente, monkeypatch):
    """Sábado ou fora das 10:00–18:00: a fila não manda os avisos da Renovação (as outras campanhas seguem) e o clique
    em "Disparar" ou em "Enviar" na Minha fila para e explica. No horário, sai."""
    from app.integracoes import whatsapp_leads

    enviados = []
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True})
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db: True)
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado",
                        lambda db, texto, u, lead=None, tarefa=None: enviados.append(lead.empresa))
    real = renovacao.fora_do_horario
    relogio = {"agora": datetime(2026, 11, 14, 11, 0)}  # sábado
    monkeypatch.setattr(renovacao, "fora_do_horario",
                        lambda db, momento=None, margem_minutos=0: real(db, relogio["agora"], margem_minutos))
    with sessao() as db:
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        antes = _configurar_piloto(db)
        admin = _admin(db)
        novas = Campanha(nome="Empresas novas no sábado", tipo="empresas_novas", status="ativa", usuario_id=admin.id,
                         canais="whatsapp", aprovado_em=agora())
        lead_nova = Lead(empresa="NOVA EMPRESA SABADO LTDA", whatsapp="(81) 98555-0001", status="Abordagem criada",
                         vendedor_id=admin.id)
        db.add_all([novas, lead_nova])
        db.flush()
        db.add(Tarefa(tipo="prospeccao", lead_id=lead_nova.id, campanha_id=novas.id, canal="whatsapp",
                      data=date.today(), hora="00:00", status="pendente", mensagem="Olá! Empresa nova."))
        camp, _, aviso = _cenario(db, 10, "9300001", "(81) 98555-0002")
        db.flush()
        campanhas.processar_fila_whatsapp(db, maximo=1000)
        assert "NOVA EMPRESA SABADO LTDA" in enviados and "CLIENTE 9300001 LTDA" not in enviados
        assert aviso.status == "pendente"  # espera o horário, não se perde
        r = campanhas.disparar(db, camp, admin, "whatsapp")
        assert r["enviados"] == 0 and "segunda a sexta" in r["parou"]
        assert "segunda a sexta" in campanhas.enviar_toque_agora(db, aviso, admin, "whatsapp")
        relogio["agora"] = datetime(2026, 11, 16, 9, 59)  # segunda, antes das 10h
        campanhas.processar_fila_whatsapp(db, maximo=1000)
        assert "CLIENTE 9300001 LTDA" not in enviados
        relogio["agora"] = datetime(2026, 11, 16, 10, 0)
        campanhas.processar_fila_whatsapp(db, maximo=1000)
        assert "CLIENTE 9300001 LTDA" in enviados
        db.rollback()
    with sessao() as db:
        _desfazer(db, antes)
        db.commit()


def test_vence_no_fim_de_semana_ultimo_aviso_na_sexta():
    """Pedido da Maria (13/11/2026): "os de sábados e domingos avisar na sexta". Vence no domingo com os avisos 12, 6,
    3 e 1 dia antes: o de 3 dias (quinta) vai para a quarta, para o último aviso caber na sexta (antes ficava sem ele).
    Nada sai no fim de semana nem depois do vencimento."""
    hoje = date(2026, 11, 2)  # segunda-feira
    dias = (12, 6, 3, 1)
    sabado, domingo = date(2026, 11, 28), date(2026, 11, 29)
    assert renovacao.datas_dos_avisos(domingo, hoje, True, dias) == [
        date(2026, 11, 17), date(2026, 11, 23), date(2026, 11, 25), date(2026, 11, 27)]
    assert renovacao.datas_dos_avisos(sabado, hoje, True, dias) == [
        date(2026, 11, 16), date(2026, 11, 20), date(2026, 11, 25), date(2026, 11, 27)]
    # com o teto de WhatsApps por dia, igual (e a sexta cheia não empurra ninguém para o fim de semana)
    assert renovacao.agenda([domingo], hoje, True, Counter(), 20, dias) == [
        renovacao.datas_dos_avisos(domingo, hoje, True, dias)]
    cheia = renovacao.agenda([domingo], hoje, True, Counter({date(2026, 11, 27): 20}), 20, dias)[0]
    assert cheia[3] is None and all(d is None or d.weekday() < 5 for d in cheia)
    for venc in (sabado, domingo, date(2026, 12, 20)):
        for padrao in (dias, renovacao.DIAS_AVISO):
            datas = renovacao.datas_dos_avisos(venc, hoje, True, padrao)
            assert datas[-1] == venc - timedelta(days=venc.weekday() - 4)  # a sexta antes
            assert all(d is None or (d.weekday() < 5 and d < venc) for d in datas)
    # vence amanhã (sábado) e hoje é sexta: o aviso é hoje
    assert renovacao.datas_dos_avisos(date(2026, 11, 14), date(2026, 11, 13), True, dias) == [
        date(2026, 11, 13), None, None, None]


def test_tela_salva_ate_que_horas_os_avisos_saem(cliente, csrf):
    base = {"csrf": csrf, "canal_whatsapp": "on", "canal_email": "on", "maximo_dia": "40", "hora": "07:45",
            "arte": "on", "hora_inicio": "10:00"}
    r = cliente.post("/renovacao/configurar", data={**base, "hora_fim": "17:30"})
    assert r.status_code == 200
    with sessao() as db:
        assert renovacao.hora_fim(db) == "17:30"
        assert "das 10:00 às 17:30" in renovacao.fora_do_horario(db, datetime(2026, 11, 14, 11, 0))
    pagina = cliente.get("/renovacao").text
    assert 'name="hora_fim" value="17:30"' in pagina and "de segunda a sexta" in pagina
    r = cliente.post("/renovacao/configurar", data={**base, "hora_fim": "09:00"})
    assert "precisa ser depois do inicial" in r.text
    with sessao() as db:
        assert renovacao.hora_fim(db) == "17:30"  # nada mudou
        for chave in ("renov_hora_inicio", "renov_hora_fim"):
            gravar_config(db, chave, "")
        db.commit()
        assert renovacao.hora_fim(db) == "18:00"



def test_tela_renovacao_tem_o_botao_de_aprovar(cliente, csrf):
    """Pedido da Maria (13/11/2026): "preciso de um botão na área de renovação de aprovação da campanha". A tela
    Renovação mostra a campanha que espera aprovação no topo, com o botão, e volta para a tela depois de aprovar."""
    with sessao() as db:
        admin = _admin(db)
        camp = Campanha(nome="Renovação para aprovar na tela", tipo="renovacao", status="aguardando_aprovacao",
                        usuario_id=admin.id, canais="whatsapp,email", objetivo="Renovar o certificado digital")
        db.add(camp)
        db.commit()
        cid = camp.id
    pagina = cliente.get("/renovacao").text
    assert "Campanha esperando aprovação:" in pagina and "Renovação para aprovar na tela" in pagina
    assert pagina.count(f'action="/campanhas/{cid}/aprovar"') == 2  # no topo e na lista de campanhas
    assert 'name="voltar" value="/renovacao"' in pagina
    assert f'action="/campanhas/{cid}/aprovar"' in cliente.get(f"/campanhas/{cid}").text  # e na página dela
    r = cliente.post(f"/campanhas/{cid}/aprovar", data={"csrf": csrf, "voltar": "/renovacao"})
    assert r.status_code == 200 and str(r.url).endswith("/renovacao") and "Campanha aprovada" in r.text
    assert f'action="/campanhas/{cid}/aprovar"' not in r.text  # aprovada: o botão some
    # endereço de volta que não é de uma área: vai para a página da campanha (nunca para fora do sistema)
    r = cliente.post(f"/campanhas/{cid}/pausar", data={"csrf": csrf, "voltar": "https://exemplo.com"})
    assert str(r.url).endswith(f"/campanhas/{cid}")
    with sessao() as db:
        assert db.get(Campanha, cid).status == "pausada"
        db.get(Campanha, cid).status = "cancelada"
        db.commit()
