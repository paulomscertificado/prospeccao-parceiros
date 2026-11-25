"""Vagas de e-mail da marca (app/vagas_email.py; pedido da Maria em 25/11/2026, sobre o quadro de vagas de WhatsApp:
"gostei muito disso aqui e agora desenvolva a mesma coisa para os emails!").

- cabem uns 17 e-mails por hora (um a cada 3 a 4 minutos) e o limite do dia da marca (80 por dia);
- os limites são da marca: as contas de e-mail dela dividem as vagas; sem conta, o e-mail espera e não ocupa vaga;
- ao aprovar, cada e-mail entra numa vaga (o que não cabe vai para a hora mais vazia ou para o próximo dia com vaga),
  sem nunca ir para antes de onde estava (continua depois do WhatsApp do toque) e com 20 h entre dois e-mails para a
  mesma empresa;
- de hora em hora, o atrasado e o que está numa hora ou num dia lotado vão para a próxima vaga; o atrasado de Empresas
  novas cuja empresa ainda tem WhatsApp por sair fica (sai sem esperar o WhatsApp, regra de 17/11/2026);
- as vagas aparecem ao lado das de WhatsApp na Nova campanha, no Buscar agora das Empresas novas e na aprovação."""

from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import select, update

from app import campanhas, feriados, vagas_email
from app.banco import agora, gravar_config, sessao, usar_config_da_ar
from app.modelos import Campanha, ContaEmail, Lead, Mensagem, Tarefa, Tenant, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de

REGRAS = {"horario_envio_inicio": "07:30", "horario_envio_fim": "20:00", "limite_hora_email": "20",
          "limite_diario_email": "80", "pular_fim_de_semana": "1", "enviar_email_automatico": "1"}
_contador = Counter()


def _marca(db, nome="Marca vagas de e-mail") -> int:
    """Uma marca só do teste, com horário 07:30-20:00, 20 e-mails por hora e 80 por dia (as vagas de e-mail são da marca:
    as campanhas que os outros testes deixam no banco não entram na conta)."""
    _contador["marca"] += 1
    ar = Tenant(slug=f"vagas-email-{_contador['marca']}", nome=f"{nome} {_contador['marca']}")
    db.add(ar)
    db.flush()
    usar_config_da_ar(db, ar.id)
    for chave, valor in REGRAS.items():
        gravar_config(db, chave, valor)
    usar_config_da_ar(db, None)
    return ar.id


def _remetente(db, ar, nome, com_conta=True):
    """Uma pessoa da marca com o próprio e-mail para os disparos (ou sem nenhum: os e-mails dela esperam)."""
    _contador["pessoa"] += 1
    endereco = f"vagas.email.{_contador['pessoa']}@vagas-email.teste"
    pessoa = Usuario(nome=nome, email=endereco, perfil="vendedor", senha_hash=resumir_senha(SENHA), tenant_id=ar)
    db.add(pessoa)
    db.flush()
    if com_conta:
        db.add(ContaEmail(nome=f"E-mail de {nome}", dono_id=pessoa.id, endereco=endereco, tenant_id=ar, ativa=True))
        db.flush()
    return pessoa


def _campanha(db, dono, ar, nome, tipo="parceiros", status="ativa", canais="whatsapp,email"):
    camp = Campanha(nome=nome, tipo=tipo, status=status, usuario_id=dono.id, canais=canais, whatsapp_sozinho=True,
                    aprovado_em=agora() if status == "ativa" else None, tenant_id=ar)
    db.add(camp)
    db.flush()
    return camp


def _toque(db, camp, dono, dia, hora, canal="email", status="pendente", lead=None, nome=""):
    if lead is None:
        _contador["lead"] += 1
        n = _contador["lead"]
        lead = Lead(empresa=nome or f"Empresa vagas de e-mail {n}", whatsapp=f"(81) 9{86000000 + n}",
                    email=f"contato{n}@vagas-email-teste.com.br", status="Abordagem criada", vendedor_id=dono.id,
                    tenant_id=camp.tenant_id)
        db.add(lead)
        db.flush()
    t = Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal=canal, data=dia, hora=hora, status=status,
               mensagem="Olá! Tudo bem?", assunto="Parceria", usuario_id=dono.id, tenant_id=camp.tenant_id)
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


def _lotar(db, ar, dono, dia, quantos=80):
    """Ocupa o dia da marca com outra campanha: `quantos` e-mails nas primeiras vagas das horas (80 = o dia inteiro)."""
    cheia = _campanha(db, dono, ar, f"Vagas de e-mail lotam o dia {dono.nome}")
    usar_config_da_ar(db, ar)
    try:
        horas = vagas_email.vagas_por_hora(db)
    finally:
        usar_config_da_ar(db, None)
    vagas_do_dia = [de + i * 3 for _hora, (n, de, _ate) in sorted(horas.items()) for i in range(n)]
    toques = [_toque(db, cheia, dono, dia, f"{m // 60:02d}:{m % 60:02d}") for m in vagas_do_dia[:quantos]]
    return cheia, toques


def _quando(t: Tarefa) -> datetime:
    h, m = t.hora.split(":")
    return datetime.combine(t.data, time(int(h), int(m)))


def test_vagas_de_email_seguem_o_horario_e_os_limites(cliente):
    with sessao() as db:
        ar = _marca(db)
        usar_config_da_ar(db, ar)
        try:
            assert vagas_email.ritmo_por_hora(db) == 17  # um a cada 3 a 4 minutos (o relógio roda a cada minuto)
            assert vagas_email.por_hora(db) == 17          # o limite de 20 por hora fica acima do ritmo da fila
            assert vagas_email.texto_do_intervalo(db) == "3 a 4 minutos"
            horas = vagas_email.vagas_por_hora(db)
            assert horas[7] == (8, 7 * 60 + 30, 7 * 60 + 59)  # começa às 07:30
            assert [horas[h][0] for h in (8, 9, 10, 11, 14, 15, 16, 17, 18)] == [17] * 9
            assert 12 not in horas and horas[13][0] == 8  # almoço: 12:00-13:30
            assert horas[19] == (11, 19 * 60, 19 * 60 + 40)  # 20 minutos de folga antes das 20:00
            assert vagas_email.por_dia(db, horas) == 80  # o limite do dia da marca
            gravar_config(db, "limite_diario_email", "0")  # sem limite por dia: o que as horas comportam
            assert vagas_email.por_dia(db) == sum(n for n, _de, _ate in horas.values()) == 180
            gravar_config(db, "limite_hora_email", "10")  # limite por hora menor que o ritmo: vale o limite
            assert vagas_email.por_hora(db) == 10
        finally:
            usar_config_da_ar(db, None)
        db.rollback()


def test_sem_conta_o_email_espera_e_nao_ocupa_vaga(cliente):
    """Cada pessoa dispara só pelo e-mail dela (ou por um compartilhado com ela): sem conta, os e-mails dela esperam e
    não tiram a vaga de quem tem conta; o quadro avisa."""
    with sessao() as db:
        ar = _marca(db)
        com = _remetente(db, ar, "Vagas Email Com Conta")
        sem = _remetente(db, ar, "Vagas Email Sem Conta", com_conta=False)
        dia = _dia_util(db, com)
        for pessoa in (com, sem):
            camp = _campanha(db, pessoa, ar, f"Vagas de e-mail de {pessoa.nome}")
            for hora in ("09:13", "10:22", "14:41"):
                _toque(db, camp, pessoa, dia, hora)
        usar_config_da_ar(db, ar)
        try:
            tela_sem = vagas_email.para_tela(db, sem, dias=10)
            tela_com = vagas_email.para_tela(db, com, dias=10)
        finally:
            usar_config_da_ar(db, None)
        assert tela_sem["conta"] is None and tela_sem["nome"] == ""  # "Ainda sem conta de e-mail"
        assert tela_com["nome"] == com.email
        assert next(d for d in tela_com["dias"] if d["dia"] == dia)["marcados"] == 3  # só os de quem tem conta
        db.rollback()


def test_contas_da_marca_dividem_as_vagas(cliente):
    """Os limites de e-mail são da marca, somando as contas dela (mesmo domínio, mesma reputação); a outra marca tem as
    vagas dela."""
    with sessao() as db:
        ar, outra = _marca(db), _marca(db, "Outra marca")
        ana, bia = _remetente(db, ar, "Vagas Email Ana"), _remetente(db, ar, "Vagas Email Bia")
        cleo = _remetente(db, outra, "Vagas Email Cleo")
        dia = _dia_util(db, ana)
        for pessoa, da_marca in ((ana, ar), (bia, ar), (cleo, outra)):
            camp = _campanha(db, pessoa, da_marca, f"Vagas de e-mail de {pessoa.nome}")
            for hora in ("09:13", "10:22"):
                _toque(db, camp, pessoa, dia, hora)
        usar_config_da_ar(db, ar)
        try:
            do_dia = next(d for d in vagas_email.resumo(db, ana, dias=10)["dias"] if d["dia"] == dia)
        finally:
            usar_config_da_ar(db, None)
        assert (do_dia["marcados"], do_dia["cabem"], do_dia["livres"]) == (4, 80, 76)  # Ana e Bia; a Cleo é da outra
        db.rollback()


def test_campanha_que_cabe_fica_como_esta(cliente):
    with sessao() as db:
        ar = _marca(db)
        dono = _remetente(db, ar, "Vagas Email Cabe")
        camp = _campanha(db, dono, ar, "Vagas de e-mail que cabem")
        dia = _dia_util(db, dono)
        horas = ["08:13", "09:22", "10:41", "14:07", "15:33", "19:43"]  # 19:43: o horário natural vai até 19:44
        toques = [_toque(db, camp, dono, dia, h) for h in horas]
        usar_config_da_ar(db, ar)
        feito = vagas_email.planejar(db, toques)
        usar_config_da_ar(db, None)
        assert feito["movidos"] == 0 and feito["empresas"] == 6 and feito["de"] == feito["ate"] == dia
        assert [(t.data, t.hora) for t in toques] == [(dia, h) for h in horas]  # nada mudou
        db.rollback()


def test_hora_lotada_espalha_no_mesmo_dia_sem_andar_para_tras(cliente):
    with sessao() as db:
        ar = _marca(db)
        dono = _remetente(db, ar, "Vagas Email Hora Cheia")
        camp = _campanha(db, dono, ar, "Vagas de e-mail hora cheia")
        dia = _dia_util(db, dono)
        horas = [f"09:{2 + i * 2:02d}" for i in range(25)]  # 25 na mesma hora; cabem 17
        toques = [_toque(db, camp, dono, dia, h) for h in horas]
        usar_config_da_ar(db, ar)
        vagas_email.planejar(db, toques)
        usar_config_da_ar(db, None)
        por_hora = Counter(int(t.hora[:2]) for t in toques)
        assert all(t.data == dia for t in toques)  # coube no mesmo dia, em outras horas
        assert por_hora[9] == 17 and max(por_hora.values()) <= 17
        assert [t.hora for t in toques[:17]] == horas[:17]  # os primeiros ficaram onde estavam
        assert all(t.hora >= h for t, h in zip(toques, horas))  # nunca vai para antes de onde estava
        assert all(not t.hora.endswith(("0", "5")) or t.hora in horas for t in toques)  # nada de horário redondo
        db.rollback()


def test_dia_lotado_vai_para_o_proximo_dia_com_vaga(cliente):
    with sessao() as db:
        ar = _marca(db)
        dono = _remetente(db, ar, "Vagas Email Dia Cheio")
        dia = _dia_util(db, dono)
        seguinte = _dia_util(db, dono, dia)
        _lotar(db, ar, dono, dia)
        usar_config_da_ar(db, ar)
        resumo = vagas_email.resumo(db, dono, dias=10)
        do_dia = next(d for d in resumo["dias"] if d["dia"] == dia)
        assert do_dia["marcados"] == do_dia["cabem"] == 80 and do_dia["livres"] == 0  # o limite do dia da marca
        nova = _campanha(db, dono, ar, "Vagas de e-mail campanha nova")
        toques = [_toque(db, nova, dono, dia, "16:41") for _ in range(5)]  # a hora tem vaga, o dia não
        feito = vagas_email.planejar(db, toques)
        usar_config_da_ar(db, None)
        assert feito["movidos"] == 5 and feito["de"] == feito["ate"] == seguinte
        assert all(t.data == seguinte for t in toques)
        db.rollback()


def test_email_fica_depois_do_whatsapp_e_20_horas_entre_emails(cliente):
    """Empresas novas: o e-mail do toque sai umas 2 h depois do WhatsApp; o que não cabe na hora nunca vai para antes
    dele, e o e-mail seguinte da empresa fica a pelo menos 20 h (a fila não manda dois antes disso)."""
    with sessao() as db:
        ar = _marca(db)
        dono = _remetente(db, ar, "Vagas Email Depois")
        dia = _dia_util(db, dono)
        amanha = _dia_util(db, dono, dia)
        outra = _campanha(db, dono, ar, "Vagas de e-mail lotam as 11h")
        for i in range(17):
            _toque(db, outra, dono, dia, f"11:{2 + i * 3:02d}")  # a hora das 11 já está cheia
        camp = _campanha(db, dono, ar, "Vagas de e-mail depois do WhatsApp", tipo="empresas_novas")
        zap = _toque(db, camp, dono, dia, "09:47", canal="whatsapp")
        email1 = _toque(db, camp, dono, dia, "11:52", lead=zap.lead)
        email2 = _toque(db, camp, dono, amanha, "08:13", lead=zap.lead)  # toque seguinte, menos de 20 h depois
        usar_config_da_ar(db, ar)
        vagas_email.planejar(db, [zap, email1, email2])
        usar_config_da_ar(db, None)
        assert (zap.data, zap.hora) == (dia, "09:47")  # o WhatsApp tem as vagas dele: o e-mail não mexe nele
        assert email1.data == dia and email1.hora > "11:52" and not email1.hora.startswith("11:")
        assert _quando(email1) > _quando(zap) + timedelta(hours=2)
        assert email2.data >= amanha and _quando(email2) - _quando(email1) >= timedelta(hours=20)
        db.rollback()


def test_aprovar_encaixa_os_emails_nas_vagas(cliente):
    with sessao() as db:
        ar = _marca(db)
        dono = _remetente(db, ar, "Vagas Email Aprovar")
        dia = _dia_util(db, dono)
        seguinte = _dia_util(db, dono, dia)
        _lotar(db, ar, dono, dia)
        camp = _campanha(db, dono, ar, "Vagas de e-mail para aprovar", status="aguardando_aprovacao", canais="email")
        rascunhos = [_toque(db, camp, dono, dia, "10:41", status="rascunho") for _ in range(3)]
        sem_email = _toque(db, camp, dono, dia, "10:43", status="rascunho")
        sem_email.lead.email = ""  # campo em branco: não sai, não conta
        previa = vagas_email.da_campanha(db, camp)
        assert previa["empresas"] == 3 and previa["emails"] == 3 and len(previa["dias"]) == 7
        assert previa["nome"] == dono.email  # a conta de quem é a campanha
        assert previa["primeiros"]["de"]["dia"] == previa["primeiros"]["ate"]["dia"] == seguinte  # o dia dela está cheio
        nas_vagas: dict = {}
        assert campanhas.aprovar(db, camp, dono, nas_vagas) == 4
        assert camp.status == "ativa"
        assert all(t.status == "pendente" and t.data == seguinte for t in rascunhos)
        assert nas_vagas["email"]["movidos"] == 3 and nas_vagas["email"]["de"] == seguinte
        assert "ar_config" not in db.info  # a aprovação devolve as configurações como estavam
        renovacao = _campanha(db, dono, ar, "Vagas de e-mail renovação", tipo="renovacao", status="aguardando_aprovacao")
        assert vagas_email.da_campanha(db, renovacao) is None  # a Renovação tem prazo: datas pelo vencimento
        so_whatsapp = _campanha(db, dono, ar, "Vagas de e-mail só WhatsApp", status="aguardando_aprovacao",
                                canais="whatsapp")
        assert vagas_email.da_campanha(db, so_whatsapp) is None
        db.rollback()


def test_replanejar_leva_atrasados_e_dia_lotado(cliente):
    with sessao() as db:
        ar = _marca(db)
        dono = _remetente(db, ar, "Vagas Email Replanejar")
        sem_conta = _remetente(db, ar, "Vagas Email Replanejar Sem Conta", com_conta=False)
        hoje = date.today()
        ontem = hoje - timedelta(days=1)
        dia = _dia_util(db, dono, hoje + timedelta(days=7))  # longe: os atrasados vão para os primeiros dias de envio
        seguinte_dia = _dia_util(db, dono, dia)
        parceiros = _campanha(db, dono, ar, "Vagas de e-mail parceiros")
        novas = _campanha(db, dono, ar, "Vagas de e-mail empresas novas", tipo="empresas_novas")
        renovacao = _campanha(db, dono, ar, "Vagas de e-mail renovação ativa", tipo="renovacao")
        de_quem_nao_tem = _campanha(db, sem_conta, ar, "Vagas de e-mail sem conta")
        atrasado = _toque(db, parceiros, dono, ontem, "10:41")
        seguinte = _toque(db, parceiros, dono, ontem + timedelta(days=2), "10:13", lead=atrasado.lead)
        espera_zap = _toque(db, novas, dono, ontem, "11:52")  # o WhatsApp da empresa ainda vai sair
        _toque(db, novas, dono, hoje + timedelta(days=1), "09:47", canal="whatsapp", lead=espera_zap.lead)
        zap_ja_saiu = _toque(db, novas, dono, ontem, "11:58")  # o WhatsApp da empresa já saiu
        _toque(db, novas, dono, ontem, "09:51", canal="whatsapp", status="feita", lead=zap_ja_saiu.lead)
        parado_renovacao = _toque(db, renovacao, dono, ontem, "10:41")
        com_sair = _toque(db, parceiros, dono, ontem, "10:41")
        com_sair.lead.opt_out = True
        sem_conta_atrasado = _toque(db, de_quem_nao_tem, sem_conta, ontem, "10:41")
        cheia, lotado = _lotar(db, ar, dono, dia, quantos=85)  # 85 no dia; cabem 80
        for t in lotado[-2:]:  # estas duas já receberam o 1º toque: a conversa começou, ficam com a vaga
            _toque(db, cheia, dono, hoje - timedelta(days=4), "09:13", status="feita", lead=t.lead)
        ids = {parceiros.id, novas.id, renovacao.id, de_quem_nao_tem.id, cheia.id}
        movidos = vagas_email.replanejar(db, so_campanhas=ids)
        assert movidos >= 7
        assert atrasado.data >= hoje and zap_ja_saiu.data >= hoje  # atrasados: para a próxima vaga
        assert (seguinte.data - atrasado.data).days >= 2  # o e-mail seguinte manteve o espaço
        assert espera_zap.data == ontem  # sai já, sem esperar o WhatsApp (17/11/2026)
        assert parado_renovacao.data == ontem  # Renovação: renovacao.ajustar_a_etapa cuida (tem prazo)
        assert com_sair.data == ontem  # quem pediu para sair não recebe: nada a remarcar
        assert sem_conta_atrasado.data == ontem  # sem conta: espera a conta (não toma a vaga de ninguém)
        ficaram = [t for t in lotado if t.data == dia]
        assert len(ficaram) == 80 and all(t in ficaram for t in lotado[-2:])
        assert all(t.data == seguinte_dia for t in lotado if t not in ficaram)
        assert "ar_config" not in db.info
        db.rollback()


def test_marca_com_o_envio_automatico_desligado_nao_mexe(cliente):
    """Sem o envio automático de e-mail, os e-mails da marca esperam o clique: o atraso é o clique, nada muda de dia."""
    with sessao() as db:
        ar = _marca(db)
        usar_config_da_ar(db, ar)
        gravar_config(db, "enviar_email_automatico", "0")
        usar_config_da_ar(db, None)
        dono = _remetente(db, ar, "Vagas Email Clique")
        camp = _campanha(db, dono, ar, "Vagas de e-mail por clique")
        atrasado = _toque(db, camp, dono, date.today() - timedelta(days=1), "10:41")
        assert vagas_email.replanejar(db, so_campanhas={camp.id}) == 0
        assert atrasado.data == date.today() - timedelta(days=1)
        db.rollback()


def test_hoje_conta_os_que_ja_sairam_e_os_atrasados(cliente, monkeypatch):
    """O limite é do dia: os e-mails que já saíram hoje gastam as vagas de hoje, e os atrasados (a fila manda primeiro)
    também ocupam."""
    with sessao() as db:
        ar = _marca(db)
        dono = _remetente(db, ar, "Vagas Email Hoje")
        dia = _dia_util(db, dono)
        monkeypatch.setattr(vagas_email, "agora", lambda: datetime.combine(dia, time(9, 0)))  # "hoje" às 09:00
        camp = _campanha(db, dono, ar, "Vagas de e-mail de hoje")
        for _ in range(30):
            db.add(Mensagem(canal="email", direcao="saida", status="enviada", corpo="Olá", tenant_id=ar,
                            campanha_id=camp.id, criado_em=datetime.combine(dia, time(8, 15))))
        _toque(db, camp, dono, dia - timedelta(days=7), "10:41")  # atrasado: sai primeiro, ocupa hoje
        db.flush()
        usar_config_da_ar(db, ar)
        try:
            hoje = vagas_email.resumo(db, dono, dias=3)["dias"][0]
        finally:
            usar_config_da_ar(db, None)
        # às 09:00 (+15 min de folga) ainda cabem 150 pelas horas; o limite do dia deixa 80 - 30 = 50
        assert hoje["titulo"] == "hoje" and (hoje["cabem"], hoje["marcados"], hoje["livres"]) == (50, 1, 49)
        db.rollback()


def test_telas_mostram_as_vagas_de_email(cliente):
    nova = cliente.get("/campanhas/nova").text
    assert 'id="vagas-email"' in nova and "Vagas de e-mail na sua conta" in nova and "vagas-lado-a-lado" in nova
    assert "Vagas de e-mail na conta de quem envia" in cliente.get("/empresas-novas").text
    with sessao() as db:
        ar = db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar_one()
        admin = db.execute(select(Usuario).where(Usuario.email == "admin@teste.com.br")).scalars().one()
        camp = _campanha(db, admin, ar, "Vagas de e-mail na aprovação", status="aguardando_aprovacao")
        dia = _dia_util(db, admin)
        for _ in range(2):
            _toque(db, camp, admin, dia, "10:41", status="rascunho")
        sem_email = _toque(db, camp, admin, dia, "10:43", status="rascunho")
        sem_email.lead.email = ""  # campo em branco: não sai, não conta
        cid = camp.id
    try:
        pagina = cliente.get(f"/campanhas/{cid}").text
        assert 'id="vagas-email"' in pagina and "Esta campanha: <b>2</b> empresas com e-mail" in pagina
        r = cliente.post(f"/campanhas/{cid}/aprovar", data={"csrf": csrf_de(pagina)}, follow_redirects=True)
        assert "Primeiro e-mail de cada empresa" in r.text
    finally:
        with sessao() as db:  # não deixa toques marcados para os outros testes
            db.execute(update(Tarefa).where(Tarefa.campanha_id == cid).values(status="cancelada"))
            db.execute(update(Campanha).where(Campanha.id == cid).values(status="cancelada"))


def test_conta_de_outra_marca_nao_aparece(cliente):
    """White label: as Empresas novas são da plataforma e quem envia pode ser de outra marca; o quadro de quem está
    vendo mostra as vagas da marca dele, sem o endereço da conta da outra marca."""
    with sessao() as db:
        ar, outra = _marca(db), _marca(db, "Outra marca")
        dono = _remetente(db, ar, "Vagas Email Da Plataforma")
        usar_config_da_ar(db, outra)
        try:
            tela = vagas_email.para_tela(db, dono, dias=3, ar=outra)
        finally:
            usar_config_da_ar(db, None)
        assert tela["outra_marca"] and tela["conta"] is None and tela["nome"] == ""
        assert vagas_email.para_tela(db, dono, dias=3, ar=ar)["nome"] == dono.email
        db.rollback()
