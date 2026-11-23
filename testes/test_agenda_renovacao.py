"""O calendário da Renovação (pedido da Maria em 23/11/2026: "em caso deles responderem que querem renovar, dar a
opção de um calendário e ele informar a data e horário que ele quer"). Quem toca em "Quero renovar" recebe pelo número
oficial o formulário do WhatsApp (Flow) com o calendário dos próximos 15 dias e os horários livres de quem atende (a
Maria escolheu o Paulo Lucas); a escolha vira reunião na Agenda dessa pessoa, nunca duas no mesmo horário, e o cliente
recebe a confirmação "Nossa equipe vai falar com você ...". A Meta é imitada: nada sai de verdade."""

import json
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app import renovacao, whatsapp_oficial
from app.banco import agora, gravar_config, ler_config, sessao, usar_config_da_ar
from app.integracoes import whatsapp_cloud
from app.modelos import AgendamentoOficial, Lead, MensagemOficial, Tarefa, Usuario
from app.seguranca import resumir_senha
from conftest import SENHA, csrf_de
from test_whatsapp_oficial import _entrar, _zerar_limite
from test_whatsapp_oficial_renovacao import NUMERO_ID, _ar_ms, _assinado, _aviso, _botao, _conta, _limpar, _no_horario

ATENDENTE = "atendente.agenda@ms-oficial-teste.com.br"
ADMIN_TESTE = "admin.agenda@ms-oficial-teste.com.br"
FLOW_ID = "flow-agenda-teste"
CHAVES = ("renov_agenda", "renov_agenda_usuario_id")


class _Resposta:  # imita a resposta do httpx
    def __init__(self, dados: dict, status: int = 200):
        self._dados, self.status_code, self.text = dados, status, json.dumps(dados)
        self.content = self.text.encode()

    def json(self):
        return self._dados


def _meta(monkeypatch, erros_de_validacao: list | None = None) -> list:
    """A Meta imitada: cria, recebe o JSON e publica o formulário; as mensagens ganham um id único."""
    chamadas = []

    def pedir(metodo, url, **kw):
        chamadas.append((metodo, url, kw))
        if url.endswith("/flows"):
            return _Resposta({"id": FLOW_ID})
        if url.endswith("/assets"):
            return _Resposta({"success": True, "validation_errors": erros_de_validacao or []})
        if url.endswith("/publish") or metodo == "DELETE":
            return _Resposta({"success": True})
        if url.endswith("/messages"):
            return _Resposta({"messages": [{"id": f"wamid.agenda-{uuid.uuid4().hex[:10]}"}]})
        return _Resposta({})

    monkeypatch.setattr(whatsapp_cloud.httpx, "request", pedir)
    return chamadas


def _enviadas(chamadas: list, tipo: str) -> list[dict]:
    return [kw["json"] for _metodo, url, kw in chamadas
            if url.endswith("/messages") and (kw.get("json") or {}).get("type") == tipo]


def _atendente(db) -> Usuario:
    """Quem atende: expediente de segunda a sexta, 9-12 e 14-18, reuniões de 30 minutos. Funcionário (não
    administrador: os avisos por e-mail dos outros testes contam os administradores)."""
    u = db.execute(select(Usuario).where(Usuario.email == ATENDENTE)).scalars().first()
    if u is None:
        u = Usuario(nome="Atendente Agenda", email=ATENDENTE, perfil="funcionario", senha_hash=resumir_senha(SENHA),
                    empresa_nome="MS Certificação Digital", tenant_id=_ar_ms(db))
        db.add(u)
    u.ativo, u.expediente, u.duracao_reuniao = True, "seg-sex 09:00-12:00,14:00-18:00", 30
    db.flush()
    return u


def _ligar(db, pessoa_id: int) -> dict:
    """Liga o calendário na marca MS (como a tela Renovação) e devolve o que estava antes."""
    usar_config_da_ar(db, _ar_ms(db))
    antes = {c: ler_config(db, c) for c in CHAVES}
    gravar_config(db, "renov_agenda", "1")
    gravar_config(db, "renov_agenda_usuario_id", str(pessoa_id))
    usar_config_da_ar(db, None)
    return antes


def _voltar(db, antes: dict, ar: int | None = None) -> None:
    usar_config_da_ar(db, ar)
    for chave, valor in antes.items():
        gravar_config(db, chave, valor or "")
    usar_config_da_ar(db, None)
    db.commit()


def _formulario(telefone: str, token: str, dia: str, hora: str, wamid: str) -> dict:
    """A resposta do formulário como a Meta manda (interactive nfm_reply, com o flow_token no response_json)."""
    resposta = json.dumps({"dia": dia, "horario": hora, "flow_token": token})
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": NUMERO_ID},
        "contacts": [{"wa_id": telefone, "profile": {"name": "Cliente Agenda"}}],
        "messages": [{"from": telefone, "id": wamid, "type": "interactive", "interactive": {
            "type": "nfm_reply", "nfm_reply": {"name": "flow", "body": "Sent", "response_json": resposta}}}]}}]}]}


def _um_dia_livre(dados: dict) -> str:
    """Um dia que o calendário deixa escolher, depois de hoje (hoje depende da hora em que o teste roda)."""
    fim = date.fromisoformat(dados["data_maxima"])
    bloqueados = set(dados["datas_bloqueadas"])
    dia = max(date.fromisoformat(dados["data_minima"]), agora().date() + timedelta(days=1))
    while dia.isoformat() in bloqueados or dia.weekday() >= 5:
        dia += timedelta(days=1)
    assert dia <= fim
    return dia.isoformat()


def test_quero_renovar_manda_o_calendario_e_marca_na_agenda(cliente, monkeypatch):
    chamadas = _meta(monkeypatch)
    _no_horario(monkeypatch)
    with sessao() as db:
        conta = _conta(db)
        conta.flow_agenda_id = FLOW_ID
        pessoa_id = _atendente(db).id
        antes = _ligar(db, pessoa_id)
        t1 = _aviso(db, "VIDRACARIA AGENDA LTDA", "(81) 99448-0001")
        t2 = _aviso(db, "SERRALHERIA AGENDA LTDA", "(81) 99448-0002")
        db.commit()
        t1_id, t2_id, lead1, lead2 = t1.id, t2.id, t1.lead_id, t2.lead_id
    try:
        for tid, fone in ((t1_id, "5581994480001"), (t2_id, "5581994480002")):
            assert _assinado(cliente, _botao(fone, f"renov:renovar:{tid}", "Quero renovar")).status_code == 200
        with sessao() as db:
            ags = {a.lead_id: a for a in db.execute(select(AgendamentoOficial).where(
                AgendamentoOficial.lead_id.in_([lead1, lead2]))).scalars()}
            assert {a.situacao for a in ags.values()} == {"a_enviar"} and {a.usuario_id for a in ags.values()} == {pessoa_id}
            tokens = {lead: a.token for lead, a in ags.items()}
            assert all(t.startswith("agenda:") for t in tokens.values())
            assert whatsapp_oficial.processar_agendamentos(db, maximo=200)["calendarios"] >= 2
            db.commit()
        calendario = _enviadas(chamadas, "interactive")[0]["interactive"]
        parametros = calendario["action"]["parameters"]
        assert parametros["flow_id"] == FLOW_ID and parametros["flow_action"] == "navigate"
        assert parametros["flow_cta"] == "Escolher o horário" and calendario["body"]["text"].startswith("Que bom!")
        dados = parametros["flow_action_payload"]["data"]
        assert parametros["flow_action_payload"]["screen"] == "AGENDAR"
        assert {"id": "09:00", "title": "09:00"} in dados["horarios"] and {"id": "12:00", "title": "12:00"} not in dados["horarios"]
        inicio, fim = date.fromisoformat(dados["data_minima"]), date.fromisoformat(dados["data_maxima"])
        assert fim <= agora().date() + timedelta(days=15)  # os próximos 15 dias (escolha da Maria)
        dias = [inicio + timedelta(days=n) for n in range((fim - inicio).days + 1)]
        assert {d.isoformat() for d in dias if d.weekday() >= 5} <= set(dados["datas_bloqueadas"])  # fim de semana
        dia = _um_dia_livre(dados)
        # o 1º cliente escolhe às 10:00; o 2º escolhe o mesmo horário e fica com o livre mais perto
        assert _assinado(cliente, _formulario("5581994480001", tokens[lead1], dia, "10:00", "wamid.agenda-form-1")).status_code == 200
        assert _assinado(cliente, _formulario("5581994480002", tokens[lead2], dia, "10:00", "wamid.agenda-form-2")).status_code == 200
        with sessao() as db:
            a1, a2 = (db.execute(select(AgendamentoOficial).where(AgendamentoOficial.lead_id == lead)).scalars().one()
                      for lead in (lead1, lead2))
            assert a1.situacao == "marcado" and a1.dia.isoformat() == dia and a1.hora == "10:00"
            assert a2.situacao == "marcado" and a2.dia.isoformat() == dia and a2.hora in ("09:30", "10:30")
            reuniao = db.get(Tarefa, a1.reuniao_id)
            assert reuniao.tipo == "reuniao" and reuniao.usuario_id == pessoa_id and reuniao.status == "pendente"
            assert reuniao.data.isoformat() == dia and reuniao.hora == "10:00" and "Renovação" in reuniao.acao
            assert db.get(Lead, lead1).status == "Reunião"
            escolha = db.execute(select(MensagemOficial).where(MensagemOficial.wamid == "wamid.agenda-form-1")).scalars().one()
            assert escolha.tipo == "formulario" and escolha.texto == f"Escolheu {dia[8:10]}/{dia[5:7]}/{dia[:4]} às 10:00"
            assert whatsapp_oficial.processar_agendamentos(db, maximo=200)["confirmacoes"] >= 2
            db.commit()
        textos = [m["text"]["body"] for m in _enviadas(chamadas, "text")]
        dd = f"{dia[8:10]}/{dia[5:7]}"
        assert any(t.startswith("Combinado! Nossa equipe vai falar com você na") and f", {dd}, às 10:00 para fazer a sua "
                   "renovação." in t for t in textos), textos
        assert any(t.startswith("O horário das 10:00 não estava livre, então marquei o mais próximo.") for t in textos)
        tela = cliente.get("/oficial?telefone=81994480001").text  # a tela API Oficial mostra tudo
        assert "calendário para marcar a renovação" in tela and "escolheu no calendário" in tela and "Combinado!" in tela
    finally:
        with sessao() as db:
            for a in db.execute(select(AgendamentoOficial).where(AgendamentoOficial.lead_id.in_([lead1, lead2]))).scalars():
                if a.reuniao_id:
                    db.get(Tarefa, a.reuniao_id).status = "cancelada"  # a agenda de quem atende fica livre
            _voltar(db, antes, _ar_ms(db))
            _limpar(db, [t1_id, t2_id])


def test_sem_o_calendario_ligado_nada_muda(cliente, monkeypatch):
    _meta(monkeypatch)
    _no_horario(monkeypatch)
    with sessao() as db:
        _conta(db).flow_agenda_id = FLOW_ID
        t = _aviso(db, "TORNEARIA SEM AGENDA LTDA", "(81) 99448-0003")
        db.commit()
        tid, lead_id = t.id, t.lead_id
    assert _assinado(cliente, _botao("5581994480003", f"renov:renovar:{tid}", "Quero renovar")).status_code == 200
    with sessao() as db:
        assert db.execute(select(AgendamentoOficial.id).where(AgendamentoOficial.lead_id == lead_id)).first() is None
        _limpar(db, [tid])


def test_janela_de_24_horas_fechada_nao_manda(cliente, monkeypatch):
    chamadas = _meta(monkeypatch)
    with sessao() as db:
        conta = _conta(db)
        conta.flow_agenda_id = FLOW_ID
        ag = AgendamentoOficial(tenant_id=conta.tenant_id, conta_id=conta.id, usuario_id=_atendente(db).id,
                                telefone="81994480004", token=f"agenda:velho-{uuid.uuid4().hex[:8]}",
                                criado_em=agora() - timedelta(hours=25))
        db.add(ag)
        db.commit()
        aid = ag.id
        whatsapp_oficial.processar_agendamentos(db, maximo=200)
        db.commit()
        assert db.get(AgendamentoOficial, aid).situacao == "vencido"
    assert not [1 for _m, url, kw in chamadas if url.endswith("/messages") and "994480004" in json.dumps(kw.get("json"))]


def test_publica_o_calendario_na_meta(cliente, monkeypatch):
    chamadas = _meta(monkeypatch)
    with sessao() as db:
        conta = _conta(db)
        conta.flow_agenda_id = ""
        assert whatsapp_oficial.garantir_flow_agenda(db, conta) == "" and conta.flow_agenda_id == FLOW_ID
        db.commit()
    assert [(m, u.rsplit("/", 1)[-1]) for m, u, _ in chamadas] == [("POST", "flows"), ("POST", "assets"), ("POST", "publish")]
    subido = json.loads(next(kw["files"]["file"][1] for _m, u, kw in chamadas if u.endswith("/assets")))
    componentes = [c["type"] for c in subido["screens"][0]["layout"]["children"]]
    assert subido["version"] == "7.3" and componentes == ["TextBody", "CalendarPicker", "Dropdown", "Footer"]
    # a Meta recusou: o rascunho é apagado, o problema aparece e nada fica guardado
    chamadas = _meta(monkeypatch, erros_de_validacao=[{"message": "Campo inválido"}])
    with sessao() as db:
        conta = _conta(db)
        conta.flow_agenda_id = ""
        problema = whatsapp_oficial.garantir_flow_agenda(db, conta)
        assert "Campo inválido" in problema and conta.flow_agenda_id == ""
        conta.flow_agenda_id = FLOW_ID
        db.commit()
    assert any(m == "DELETE" for m, _u, _kw in chamadas) and not any(u.endswith("/publish") for _m, u, _kw in chamadas)


def test_teste_da_tela_confirma_sem_marcar_reuniao(cliente, monkeypatch):
    chamadas = _meta(monkeypatch)
    _zerar_limite()
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.email == ADMIN_TESTE)).scalars().first()
        if admin is None:
            admin = Usuario(nome="Admin Agenda", email=ADMIN_TESTE, perfil="admin", senha_hash=resumir_senha(SENHA),
                            empresa_nome="MS Certificação Digital", tenant_id=_ar_ms(db))
            db.add(admin)
        admin.ativo = True
        _conta(db).flow_agenda_id = FLOW_ID
        antes = _ligar(db, _atendente(db).id)
        db.commit()
    try:
        c = _entrar(ADMIN_TESTE)
        tela = c.get("/whatsapp").text
        assert "Testar o calendário" in tela
        r = c.post("/whatsapp/oficial/calendario/teste", data={"csrf": csrf_de(tela), "telefone": "(81) 98888-4444"})
        assert "Calendário enviado pelo número oficial" in r.text, r.text[:300]
        with sessao() as db:
            ag = db.execute(select(AgendamentoOficial).where(AgendamentoOficial.telefone == "81988884444")
                            .order_by(AgendamentoOficial.id.desc())).scalars().first()
            assert ag.teste and ag.situacao == "enviado"
            token = ag.token
        dados = _enviadas(chamadas, "interactive")[-1]["interactive"]["action"]["parameters"]["flow_action_payload"]["data"]
        dia = _um_dia_livre(dados)
        assert _assinado(cliente, _formulario("5581988884444", token, dia, "14:30", "wamid.agenda-teste-1")).status_code == 200
        with sessao() as db:
            ag = db.execute(select(AgendamentoOficial).where(AgendamentoOficial.token == token)).scalars().one()
            assert ag.situacao == "marcado" and ag.reuniao_id is None and ag.hora == "14:30"  # o teste não marca reunião
            whatsapp_oficial.processar_agendamentos(db, maximo=200)
            db.commit()
        textos = [m["text"]["body"] for m in _enviadas(chamadas, "text")]
        assert any(t.startswith("[TESTE] Combinado!") and "às 14:30" in t for t in textos), textos
    finally:
        with sessao() as db:
            # inativo: não vira destinatário dos avisos por e-mail dos outros testes (test_alertas)
            db.execute(select(Usuario).where(Usuario.email == ADMIN_TESTE)).scalars().one().ativo = False
            _voltar(db, antes, _ar_ms(db))


def test_tela_renovacao_liga_o_calendario_e_publica(cliente, monkeypatch):
    _meta(monkeypatch)
    with sessao() as db:
        _conta(db).flow_agenda_id = ""
        pessoa_id = _atendente(db).id
        antes = {c: ler_config(db, c) for c in renovacao.PADRAO}  # o formulário grava todo o quadro: tudo volta
        db.commit()
    try:
        pagina = cliente.get("/renovacao").text
        assert 'name="agenda"' in pagina and "Agenda de quem atende" in pagina
        r = cliente.post("/renovacao/configurar", data={
            "csrf": csrf_de(pagina), "canal_whatsapp": "on", "canal_email": "on", "arte": "on", "maximo_dia": "40",
            "hora": "07:45", "hora_fim": "18:00", "agenda": "on", "agenda_usuario_id": str(pessoa_id)})
        assert r.status_code == 200 and "passa a receber o calendário" in r.text
        with sessao() as db:
            assert ler_config(db, "renov_agenda") == "1" and ler_config(db, "renov_agenda_usuario_id") == str(pessoa_id)
            assert whatsapp_oficial.conta_da_ar(db, _ar_ms(db)).flow_agenda_id == FLOW_ID  # publicado ao ligar
    finally:
        with sessao() as db:
            _voltar(db, antes)


def test_le_a_resposta_do_calendario_no_webhook():
    recebidas, _ = whatsapp_cloud.ler_webhook(_formulario("5581900000009", "agenda:abc", "2026-11-25", "10:00", "w1"))
    r = recebidas[0]
    assert r["tipo"] == "nfm_reply" and r["texto"] == "Escolheu 25/11/2026 às 10:00"
    assert r["formulario"] == {"dia": "2026-11-25", "horario": "10:00", "flow_token": "agenda:abc"}
    assert whatsapp_oficial.TIPO_QUE_CHEGA[r["tipo"]] == "formulario"
