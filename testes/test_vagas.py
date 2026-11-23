"""Vagas de WhatsApp por número (app/vagas.py; pedido da Maria em 23/11/2026: "se eu fizer muitas campanhas, essas
campanhas vão acumular a quantidade de disparos dentro de um único número ... que não fique gargalando, não fique
acumulando e que eu não fique com as mensagens atrasadas aqui na minha fila").

- cada número tem a própria vez na fila (8 a 12 min entre um WhatsApp e outro do mesmo número);
- a conversa que já começou (toque seguinte) sai antes do primeiro toque de outra empresa;
- ao aprovar, cada WhatsApp entra numa vaga do número (o que não cabe vai para o próximo dia com vaga);
- de hora em hora, o atrasado de dias anteriores e o que está numa hora lotada vão para a próxima vaga;
- as vagas aparecem na Nova campanha, no Buscar agora das Empresas novas e na aprovação."""

from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import select, update

from app import campanhas, config, feriados, sdr, vagas
from app.banco import agora, gravar_config, ler_config, sessao, usar_config_da_ar
from app.modelos import Campanha, ConexaoWhatsApp, Lead, Tarefa, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de

REGRAS = {"horario_envio_inicio": "07:30", "horario_envio_fim": "20:00", "limite_hora_whatsapp": "6",
          "pular_fim_de_semana": "1"}
_contador = Counter()


def _ar_ms(db) -> int:
    return db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar_one()


def _regras(db, ar):
    """Horário 07:30-20:00, 6 por hora, 8 a 12 min entre um WhatsApp e outro e sem fim de semana: na plataforma e na AR."""
    gravar_config(db, "intervalo_whatsapp_min", "8")
    gravar_config(db, "intervalo_whatsapp_max", "12")
    for chave, valor in REGRAS.items():
        gravar_config(db, chave, valor)
    usar_config_da_ar(db, ar)
    for chave, valor in REGRAS.items():
        gravar_config(db, chave, valor)
    usar_config_da_ar(db, None)


def _remetente(db, ar, nome):
    """Uma pessoa com o próprio número de WhatsApp (cada uma tem o seu disparo)."""
    pessoa = Usuario(nome=nome, email=f"{nome.lower().replace(' ', '.')}@vagas.teste", perfil="vendedor",
                     senha_hash=resumir_senha(SENHA), tenant_id=ar)
    db.add(pessoa)
    db.flush()
    db.add(ConexaoWhatsApp(id=f"u{pessoa.id}", nome=f"WhatsApp de {nome}", dono_id=pessoa.id, tenant_id=ar))
    db.flush()
    return pessoa


def _campanha(db, dono, ar, nome, tipo="empresas_novas", status="ativa", sozinho=True):
    camp = Campanha(nome=nome, tipo=tipo, status=status, usuario_id=dono.id, canais="whatsapp,email",
                    whatsapp_sozinho=sozinho, aprovado_em=agora() if status == "ativa" else None, tenant_id=ar)
    db.add(camp)
    db.flush()
    return camp


def _toque(db, camp, dono, dia, hora, canal="whatsapp", status="pendente", lead=None, nome=""):
    if lead is None:
        _contador["lead"] += 1
        lead = Lead(empresa=nome or f"Empresa vagas {_contador['lead']}", whatsapp=f"(81) 9{87000000 + _contador['lead']}",
                    email=f"contato{_contador['lead']}@vagas-teste.com.br", status="Abordagem criada",
                    vendedor_id=dono.id, tenant_id=camp.tenant_id)
        db.add(lead)
        db.flush()
    t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal=canal, data=dia, hora=hora, status=status,
               mensagem="Olá! Tudo bem?", usuario_id=dono.id, tenant_id=camp.tenant_id)
    db.add(t)
    db.flush()
    return t


def _dia_util(db, pessoa, depois_de: date | None = None) -> date:
    """Um dia de envio (seg a sex, sem feriado de quem envia) daqui a pelo menos 3 dias, ou o próximo depois de outro."""
    sem = feriados.dias_sem_envio(db, pessoa)
    dia = depois_de + timedelta(days=1) if depois_de else date.today() + timedelta(days=3)
    while dia.weekday() >= 5 or dia in sem:
        dia += timedelta(days=1)
    return dia


def _lotar(db, ar, dono, dia):
    """Ocupa todas as vagas do número no dia com outra campanha (64 no horário 07:30-20:00)."""
    cheia = _campanha(db, dono, ar, f"Vagas lotam o dia {dono.nome}")
    usar_config_da_ar(db, ar)
    try:
        for hora, (n, de, _ate) in vagas.vagas_por_hora(db).items():
            for i in range(n):
                minuto = de + i * 2
                _toque(db, cheia, dono, dia, f"{minuto // 60:02d}:{minuto % 60:02d}", nome=f"Lota {hora}h {i}")
    finally:
        usar_config_da_ar(db, None)
    return cheia


def test_vagas_por_hora_seguem_o_horario_e_o_ritmo(cliente):
    with sessao() as db:
        _regras(db, _ar_ms(db))
        assert vagas.por_hora(db) == 6  # 8 a 12 min entre um e outro: uns 6 por hora
        horas = vagas.vagas_por_hora(db)
        assert horas[7] == (3, 7 * 60 + 30, 7 * 60 + 59)  # começa às 07:30
        assert [horas[h][0] for h in (8, 9, 10, 11, 14, 15, 16, 17, 18)] == [6] * 9
        assert 12 not in horas and horas[13][0] == 3  # almoço: 12:00-13:30
        assert horas[19] == (4, 19 * 60, 19 * 60 + 40)  # 20 minutos de folga antes das 20:00
        assert sum(n for n, _de, _ate in horas.values()) == 64
        assert set(vagas.vagas_por_hora(db, minimo="10:00", maximo="18:00")) == {10, 11, 13, 14, 15, 16, 17}
        gravar_config(db, "limite_hora_whatsapp", "4")  # limite por hora menor que o ritmo: vale o limite
        assert vagas.por_hora(db) == 4
        db.rollback()


def test_quem_usa_numero_compartilhado_divide_as_vagas_dele(cliente, monkeypatch):
    """Caso real (23/11/2026): as campanhas de uma pessoa saem pelo número que outra compartilhou com ela; as vagas são
    as daquele número (o mesmo que a fila escolhe, conexoes.para_enviar), não as de um número próprio desconectado."""
    import json

    from app.integracoes import whatsapp_leads

    with sessao() as db:
        ar = _ar_ms(db)
        dono_do_numero = _remetente(db, ar, "Vagas Dono Numero")
        usa = _remetente(db, ar, "Vagas Usa Compartilhado")  # tem número próprio, mas desconectado
        numero = db.get(ConexaoWhatsApp, f"u{dono_do_numero.id}")
        numero.compartilhada_com = json.dumps([usa.id])
        monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {
            "disponivel": True, "conexoes": {numero.id: {"conectado": True}}})
        assert vagas.Numeros(db).da_pessoa(usa.id) == numero.id  # dispara pelo compartilhado: divide as vagas dele
        assert vagas.Numeros(db).da_pessoa(dono_do_numero.id) == numero.id
        monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": False, "erro": "desligado"})
        assert vagas.Numeros(db).da_pessoa(usa.id) == f"u{usa.id}"  # sem saber quem está conectado: o próprio
        db.rollback()


def test_campanha_que_cabe_fica_como_esta(cliente):
    with sessao() as db:
        ar = _ar_ms(db)
        _regras(db, ar)
        dono = _remetente(db, ar, "Vagas Cabe")
        camp = _campanha(db, dono, ar, "Vagas que cabem")
        dia = _dia_util(db, dono)
        horas = ["08:13", "09:22", "10:41", "14:07", "15:33", "16:48"]
        toques = [_toque(db, camp, dono, dia, h) for h in horas]
        usar_config_da_ar(db, ar)
        feito = vagas.planejar(db, toques)
        usar_config_da_ar(db, None)
        assert feito["movidos"] == 0 and feito["empresas"] == 6 and feito["de"] == feito["ate"] == dia
        assert [(t.data, t.hora) for t in toques] == [(dia, h) for h in horas]  # nada mudou
        db.rollback()


def test_hora_lotada_espalha_no_mesmo_dia(cliente):
    with sessao() as db:
        ar = _ar_ms(db)
        _regras(db, ar)
        dono = _remetente(db, ar, "Vagas Hora Cheia")
        camp = _campanha(db, dono, ar, "Vagas hora cheia")
        dia = _dia_util(db, dono)
        horas = [f"09:{2 + i * 5:02d}" for i in range(10)]  # 10 na mesma hora; cabem 6
        toques = [_toque(db, camp, dono, dia, h) for h in horas]
        usar_config_da_ar(db, ar)
        vagas.planejar(db, toques)
        usar_config_da_ar(db, None)
        por_hora = Counter(int(t.hora[:2]) for t in toques)
        assert all(t.data == dia for t in toques)  # coube no mesmo dia, em outras horas
        assert por_hora[9] == 6 and max(por_hora.values()) <= 6
        assert [t.hora for t in toques[:6]] == horas[:6]  # os primeiros ficaram onde estavam
        assert all(not t.hora.endswith(("0", "5")) or t.hora in horas for t in toques)  # nada de horário redondo
        db.rollback()


def test_dia_lotado_vai_para_o_proximo_dia_com_vaga(cliente):
    with sessao() as db:
        ar = _ar_ms(db)
        _regras(db, ar)
        dono = _remetente(db, ar, "Vagas Dia Cheio")
        dia = _dia_util(db, dono)
        seguinte = _dia_util(db, dono, dia)
        _lotar(db, ar, dono, dia)
        usar_config_da_ar(db, ar)
        resumo = vagas.resumo(db, dono, dias=10)
        do_dia = next(d for d in resumo["dias"] if d["dia"] == dia)
        assert do_dia["marcados"] == do_dia["cabem"] == 64 and do_dia["livres"] == 0
        nova = _campanha(db, dono, ar, "Vagas campanha nova")
        toques = [_toque(db, nova, dono, dia, "10:41") for _ in range(5)]
        feito = vagas.planejar(db, toques)
        usar_config_da_ar(db, None)
        assert feito["movidos"] == 5 and feito["de"] == feito["ate"] == seguinte
        assert all(t.data == seguinte for t in toques)
        db.rollback()


def test_email_e_toques_seguintes_andam_junto(cliente):
    with sessao() as db:
        ar = _ar_ms(db)
        _regras(db, ar)
        dono = _remetente(db, ar, "Vagas Junto")
        dia = _dia_util(db, dono)
        _lotar(db, ar, dono, dia)
        camp = _campanha(db, dono, ar, "Vagas junto")
        zap1 = _toque(db, camp, dono, dia, "09:47")
        lead = zap1.lead
        email_junto = _toque(db, camp, dono, dia, "09:47", canal="email", lead=lead)    # mesmo horário do WhatsApp
        email_depois = _toque(db, camp, dono, dia, "11:52", canal="email", lead=lead)   # umas 2 h depois dele
        email_meio = _toque(db, camp, dono, dia + timedelta(days=1), "10:17", canal="email", lead=lead)  # só e-mail
        zap2 = _toque(db, camp, dono, dia + timedelta(days=3), "14:23", lead=lead)
        usar_config_da_ar(db, ar)
        feito = vagas.planejar(db, [zap1, email_junto, email_depois, email_meio, zap2])
        usar_config_da_ar(db, None)
        assert zap1.data > dia and feito["movidos"] == 2
        assert (email_junto.data, email_junto.hora) == (zap1.data, zap1.hora)
        assert (email_depois.data, email_depois.hora) > (zap1.data, zap1.hora)
        assert zap1.data < email_meio.data <= zap2.data  # o e-mail do meio não passa na frente
        assert (zap2.data - zap1.data).days >= 3          # o espaço da cadência continua
        db.rollback()


def test_aprovar_encaixa_a_campanha_nas_vagas(cliente):
    with sessao() as db:
        ar = _ar_ms(db)
        _regras(db, ar)
        dono = _remetente(db, ar, "Vagas Aprovar")
        dia = _dia_util(db, dono)
        seguinte = _dia_util(db, dono, dia)
        _lotar(db, ar, dono, dia)
        camp = _campanha(db, dono, ar, "Vagas para aprovar", status="aguardando_aprovacao")
        rascunhos = [_toque(db, camp, dono, dia, "10:41", status="rascunho") for _ in range(3)]
        previa = vagas.da_campanha(db, camp)
        assert previa["empresas"] == 3 and previa["whatsapps"] == 3 and len(previa["dias"]) == 7
        assert previa["primeiros"]["de"]["dia"] == previa["primeiros"]["ate"]["dia"] == seguinte  # o dia dela está cheio
        nas_vagas: dict = {}
        assert campanhas.aprovar(db, camp, dono, nas_vagas) == 3
        assert camp.status == "ativa"
        assert all(t.status == "pendente" and t.data == seguinte for t in rascunhos)
        assert nas_vagas["movidos"] == 3 and nas_vagas["de"] == seguinte
        assert "ar_config" not in db.info  # a aprovação devolve as configurações como estavam
        renovacao = _campanha(db, dono, ar, "Vagas renovação", tipo="renovacao", status="aguardando_aprovacao")
        assert vagas.da_campanha(db, renovacao) is None  # a Renovação tem prazo: datas pelo vencimento
        db.rollback()


def test_replanejar_leva_atrasados_e_hora_lotada(cliente):
    with sessao() as db:
        ar = _ar_ms(db)
        _regras(db, ar)
        dono = _remetente(db, ar, "Vagas Replanejar")
        hoje = date.today()
        ontem = hoje - timedelta(days=1)
        dia = _dia_util(db, dono)
        auto = _campanha(db, dono, ar, "Vagas sai sozinha")
        clique = _campanha(db, dono, ar, "Vagas espera clique", tipo="parceiros", sozinho=False)
        renovacao = _campanha(db, dono, ar, "Vagas renovação ativa", tipo="renovacao")
        atrasado = _toque(db, auto, dono, ontem, "10:41")
        seguinte = _toque(db, auto, dono, ontem + timedelta(days=2), "10:13", lead=atrasado.lead)
        parado_clique = _toque(db, clique, dono, ontem, "10:41")
        parado_renovacao = _toque(db, renovacao, dono, ontem, "10:41")
        com_sair = _toque(db, auto, dono, ontem, "10:41")
        com_sair.lead.opt_out = True
        lotada = [_toque(db, auto, dono, dia, f"10:{3 + i * 6:02d}") for i in range(9)]  # 9 na mesma hora; cabem 6
        for t in lotada[-2:]:  # estas duas já receberam o 1º toque: a conversa começou, ficam com a vaga
            _toque(db, auto, dono, hoje - timedelta(days=4), "09:13", status="feita", lead=t.lead)
        movidos = vagas.replanejar(db, so_campanhas={auto.id, clique.id, renovacao.id})
        assert movidos >= 1 and atrasado.data >= hoje
        assert (seguinte.data - atrasado.data).days >= 2  # o toque seguinte manteve o espaço
        assert parado_clique.data == ontem      # campanha que espera o clique: o atraso é o clique
        assert parado_renovacao.data == ontem   # Renovação: renovacao.ajustar_a_etapa cuida (tem prazo)
        assert com_sair.data == ontem           # quem pediu para sair não recebe: nada a remarcar
        assert all(t.data == dia for t in lotada)
        ficaram = [t for t in lotada if t.hora.startswith("10:")]
        assert len(ficaram) == 6 and all(t in ficaram for t in lotada[-2:])
        assert "ar_config" not in db.info
        db.rollback()


def _fila_de_teste(monkeypatch, enviados):
    """Fila do WhatsApp com tudo de mentira: número de cada pessoa = "teste-<id>", envio só anota (e dá o toque como
    feito, como o envio de verdade)."""
    from app.integracoes import whatsapp_leads

    def enviar(db, texto, u, lead=None, tarefa=None):
        enviados.append(lead.empresa)
        tarefa.status = "feita"

    monkeypatch.setattr(config, "ESPACAR_ENVIOS", True)
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True})
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario", lambda db, momento=None: True)
    monkeypatch.setattr(campanhas.mensagens, "dentro_do_horario_de_alguma_ar", lambda db: True)
    monkeypatch.setattr(feriados, "adiar_se_feriado", lambda db, t, pessoa=None, hoje=None: "")
    monkeypatch.setattr(campanhas, "_numero_do_envio", lambda db, t, guardados: f"teste-{t.lead.vendedor_id}")
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado", enviar)


def test_fila_da_a_vez_a_cada_numero(cliente, monkeypatch):
    enviados: list = []
    _fila_de_teste(monkeypatch, enviados)
    with sessao() as db:
        ar = _ar_ms(db)
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        usar_config_da_ar(db, ar)
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        usar_config_da_ar(db, None)
        ana, bia = _remetente(db, ar, "Vez Ana"), _remetente(db, ar, "Vez Bia")
        camp = _campanha(db, ana, ar, "Vagas vez por número")
        for pessoa in (ana, bia):
            gravar_config(db, f"proximo_envio_automatico:whatsapp:teste-{pessoa.id}", "")
            for i in range(3):
                _toque(db, camp, pessoa, date.today(), "00:01", nome=f"{pessoa.nome} {i}")

        def meus():
            return [e for e in enviados if e.startswith("Vez ")]

        campanhas.processar_fila_whatsapp(db, maximo=100)
        assert sorted(meus()) == ["Vez Ana 0", "Vez Bia 0"]  # um de cada número, ao mesmo tempo
        enviados.clear()
        campanhas.processar_fila_whatsapp(db, maximo=100)
        assert meus() == []  # os dois números no intervalo de 8 a 12 minutos
        gravar_config(db, f"proximo_envio_automatico:whatsapp:teste-{ana.id}", "2000-01-01T00:00:00")
        campanhas.processar_fila_whatsapp(db, maximo=100)
        assert meus() == ["Vez Ana 1"]  # passou o intervalo só do número da Ana
        proximo = datetime.fromisoformat(ler_config(db, f"proximo_envio_automatico:whatsapp:teste-{ana.id}"))
        assert 470 <= (proximo - agora()).total_seconds() <= 721
        db.rollback()


def test_toque_seguinte_sai_antes_do_primeiro_toque(cliente, monkeypatch):
    enviados: list = []
    _fila_de_teste(monkeypatch, enviados)
    with sessao() as db:
        ar = _ar_ms(db)
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        usar_config_da_ar(db, ar)
        gravar_config(db, "enviar_whatsapp_automatico", "1")
        usar_config_da_ar(db, None)
        dona = _remetente(db, ar, "Ordem Ana")
        gravar_config(db, f"proximo_envio_automatico:whatsapp:teste-{dona.id}", "")
        camp = _campanha(db, dona, ar, "Vagas ordem da fila")
        _toque(db, camp, dona, date.today(), "00:01", nome="Ordem primeiro toque")
        conversa = _toque(db, camp, dona, date.today(), "00:01", nome="Ordem toque seguinte")
        _toque(db, camp, dona, date.today() - timedelta(days=3), "09:13", status="feita", lead=conversa.lead)
        campanhas.processar_fila_whatsapp(db, maximo=100)
        assert [e for e in enviados if e.startswith("Ordem ")] == ["Ordem toque seguinte"]
        db.rollback()


def test_telas_mostram_as_vagas(cliente):
    assert "Vagas de WhatsApp no seu número" in cliente.get("/campanhas/nova").text
    assert "Vagas de WhatsApp no número de quem envia" in cliente.get("/empresas-novas").text
    with sessao() as db:
        ar = _ar_ms(db)
        admin = db.execute(select(Usuario).where(Usuario.email == "admin@teste.com.br")).scalars().one()
        camp = _campanha(db, admin, ar, "Vagas na aprovação", tipo="parceiros", status="aguardando_aprovacao")
        dia = _dia_util(db, admin)
        for _ in range(2):
            _toque(db, camp, admin, dia, "10:41", status="rascunho")
        sem_whatsapp = _toque(db, camp, admin, dia, "10:43", status="rascunho")
        sem_whatsapp.lead.whatsapp = ""  # campo em branco: não sai, não conta
        cid = camp.id
    try:
        pagina = cliente.get(f"/campanhas/{cid}").text
        assert 'id="vagas-whatsapp"' in pagina and "Esta campanha: <b>2</b> empresas" in pagina
        r = cliente.post(f"/campanhas/{cid}/aprovar", data={"csrf": csrf_de(pagina)}, follow_redirects=True)
        assert "Primeiro WhatsApp de cada empresa" in r.text
    finally:
        with sessao() as db:  # não deixa toques marcados para os outros testes
            db.execute(update(Tarefa).where(Tarefa.campanha_id == cid).values(status="cancelada"))
            db.execute(update(Campanha).where(Campanha.id == cid).values(status="cancelada"))
