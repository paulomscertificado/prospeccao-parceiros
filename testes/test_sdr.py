"""Testes da IA SDR (rodar com testar.bat). Nenhum teste acessa a internet nem a IA de verdade."""

import hashlib
import hmac
import json
import zipfile
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import agenda_horarios, base_receita, campanhas, config, mensagens, pesquisa, sdr, util
from app.banco import agora, gravar_config, migrar_status, sessao
from app.integracoes import email_smtp
from app.modelos import (Campanha, Categoria, Lead, Mensagem, Notificacao, Oportunidade, Tarefa, Usuario)
from app.leads_servico import criar_lead


@pytest.fixture(autouse=True)
def sem_internet(monkeypatch):
    """A pesquisa nunca sai para a internet nos testes."""
    monkeypatch.setattr(pesquisa, "descobrir_site", lambda *a, **k: "")
    monkeypatch.setattr(pesquisa, "ler_site", lambda *a, **k: {})
    monkeypatch.setattr(pesquisa, "dados_do_cnpj", lambda *a, **k: {})
    monkeypatch.setattr(pesquisa, "dados_do_site", lambda *a, **k: {})


@pytest.fixture(autouse=True)
def config_restaurada():
    """Testes que mexem em limites devolvem os valores padrão no final (mesmo se falharem)."""
    yield
    with sessao() as db:
        for chave in ("limite_hora_email", "horas_entre_contatos", "limite_diario_dominio"):
            gravar_config(db, chave, config.CONFIG_PADRAO[chave])


def _admin(db) -> Usuario:
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def _novo_lead(db, nome, **campos) -> Lead:
    dados = {"empresa": nome, "cidade": "Recife", "estado": "PE", **campos}
    lead, motivo = criar_lead(db, dados, _admin(db), checar_duplicado=False)
    db.flush()
    return lead


# ---------------------------------------------------------------- Regras puras

def test_migracao_de_status_antigos(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "SDR Migração")
        lead.status = "Contato realizado"
        outro = _novo_lead(db, "SDR Migração 2")
        outro.status = "Número inválido"
        db.flush()
        assert migrar_status(db) >= 2
        assert lead.status == "Contatado"
        assert outro.status == "Perdido" and outro.motivo_perda == "Contato inválido"


def test_regras_de_categoria():
    regras = [base_receita.Regra("nf", set(), {"6203100"}, ["nota fiscal", "emissor"]),
              base_receita.Regra("condominio", {"6822600"}, {"8211300"}, ["condom"]),
              base_receita.Regra("erp", {"6203100"}, set(), [])]
    assert base_receita.classificar(regras, "6203100", "EMISSOR FACIL NOTAS") == "nf"
    assert base_receita.classificar(regras, "6203100", "GESTAO TOTAL") == "erp"
    assert base_receita.classificar(regras, "8211300", "ADM DE CONDOMINIOS SOL") == "condominio"
    assert base_receita.classificar(regras, "8211300", "ESCRITORIO GENERICO") == ""


@pytest.mark.parametrize("texto, classe", [
    ("Tenho interesse. Como funciona?", "QUER SABER MAIS"),
    ("Pode me explicar como funciona?", "QUER SABER MAIS"),
    ("Vamos marcar uma reunião semana que vem", "QUER REUNIÃO"),
    ("Quanto custa o certificado pra vocês?", "QUER PREÇO"),
    ("Já trabalhamos com outra certificadora", "JÁ POSSUI PARCEIRO"),
    ("Não sou o responsável, fale com o Carlos", "NÃO É RESPONSÁVEL"),
    ("Não temos interesse, obrigado", "SEM INTERESSE"),
    ("Remova meu contato, não quero receber mensagens", "OPT-OUT"),
    ("SAIR", "OPT-OUT"),
    ("Manda por e-mail que eu vejo", "PEDIU PARA ENVIAR E-MAIL"),
    ("assim que der eu vejo", "RESPOSTA INDEFINIDA"),  # "sim" dentro de "assim" não conta
])
def test_classificacao_de_respostas_por_regras(texto, classe):
    assert sdr.classificar_por_regras(texto)["classe"] == classe


def test_mensagens_por_angulo_sem_spam(cliente):
    with sessao() as db:
        cat = db.execute(select(Categoria).where(Categoria.codigo == "condominio")).scalars().one()
        lead = _novo_lead(db, "Sol Administradora de Condomínios", responsavel="Maria Souza")
        lead.categoria = cat
        msgs = sdr.mensagens_por_regras(db, lead, _admin(db))
        # Mesma atividade na Receita, mas o nome não confirma o ramo: abordagem genérica (não inventa)
        imob = _novo_lead(db, "Jals Empreendimentos")
        imob.categoria = cat
        pesquisa.pesquisar_lead(db, imob, usar_ia=False)  # pesquisa sem site não pode "confirmar" o ramo
        generica = sdr.mensagens_por_regras(db, imob, _admin(db))["apresentacao"]["whatsapp"]
    assert "condomínio" not in generica and "trabalham diretamente com empresas" in generica
    assert "com quem posso falar sobre possíveis parcerias" in generica
    assert set(msgs) == set(config.ANGULOS)
    assert len({m["whatsapp"] for m in msgs.values()}) == 4  # cada toque é diferente
    assert msgs["apresentacao"]["whatsapp"].startswith("Olá, Maria! Tudo bem?")
    assert "condomínio" in msgs["apresentacao"]["whatsapp"] and msgs["apresentacao"]["fonte"] == "modelos do segmento"
    assert "{" not in " ".join(m["whatsapp"] + m["email"] + m["assunto"] for m in msgs.values())  # variáveis preenchidas
    assert "viu minha mensagem" not in " ".join(m["whatsapp"] for m in msgs.values()).lower()
    assert all(sdr.texto_seguro(m["whatsapp"]) and sdr.texto_seguro(m["email"]) for m in msgs.values())
    assert "Sol Administradora de Condomínios" in msgs["apresentacao"]["assunto"]
    assert not sdr.texto_seguro("Temos uma excelente oportunidade para você")
    assert not sdr.texto_seguro("Comissão de 20% por certificado")
    assert not sdr.texto_seguro("Fazemos desconto especial")


def test_ia_que_sai_das_regras_e_trocada_pela_versao_segura(cliente, monkeypatch):
    from app import ia

    monkeypatch.setattr(ia, "disponivel", lambda: True)
    resposta = {a: {"whatsapp": "Oi! Pagamos R$ 50 por indicação.", "assunto": "x", "email": "x"} for a in config.ANGULOS}
    resposta["fatos_usados"] = []
    monkeypatch.setattr(ia, "perguntar", lambda *a, **k: resposta)
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Segura")
        msgs = sdr.gerar_mensagens(db, lead, _admin(db))
    assert all(m["fonte"] == "regras" and "R$" not in m["whatsapp"] for m in msgs.values())


def test_trava_contra_invencao_no_perfil():
    texto = "Somos um escritório que atende mais de 300 empresas em Recife. Equipe: Ana Lima (sócia)."
    perfil = pesquisa._validar_perfil({"clientes_estimados": 2000, "evidencia_clientes": "mais de 2.000 clientes",
                                       "responsaveis": ["Ana Lima (sócia)", "João Inventado"]}, texto)
    assert perfil["clientes_estimados"] is None and perfil["responsaveis"] == ["Ana Lima (sócia)"]
    ok = pesquisa._validar_perfil({"clientes_estimados": 300, "evidencia_clientes": "mais de 300 empresas",
                                   "responsaveis": []}, texto)
    assert ok["clientes_estimados"] == 300
    sinais = pesquisa.sinais_por_regras(texto + " Seja um parceiro! Emitimos NF-e e cuidamos do eSocial.")
    assert sinais["clientes_estimados"] == 300 and sinais["programa_parceiros"] and sinais["possibilidade_indicacao"]


# ---------------------------------------------------------------- Respostas, oportunidade e handoff

def test_interesse_para_automacao_e_vira_oportunidade(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Quente", email="contato@quente-sdr.com.br", responsavel="João Silva")
        db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, canal="email", data=date.today() + timedelta(days=2),
                      mensagem="follow-up"))
        mensagens.registrar(db, lead.id, "email", "Primeira mensagem", None, status="enviada", angulo="apresentacao")
        lead.status = "Aguardando resposta"
        db.flush()
        analise = sdr.processar_resposta(db, lead, "Pode me explicar como funciona?", "email")
        assert analise["classe"] == "QUER SABER MAIS"
        assert "time comercial" in analise["resposta_sugerida"]
        assert lead.status == "Interessado" and lead.automacao_pausada
        assert db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id, Tarefa.status == "pendente")).first() is None
        op = db.get(Oportunidade, analise["oportunidade_id"])
        assert op.temperatura == "quente" and op.mensagem_enviada == "Primeira mensagem"
        enviada = db.execute(select(Mensagem).where(Mensagem.lead_id == lead.id, Mensagem.direcao == "saida")).scalars().one()
        assert enviada.respondida
        assert db.execute(select(Notificacao).where(Notificacao.link == f"/oportunidades#op-{op.id}")).first()
        lead_id = lead.id
    r = cliente.get("/oportunidades")
    assert "NOVO LEAD QUENTE" in r.text and "Contábil Quente" in r.text
    csrf = r.text.split('name="csrf" content="')[1].split('"')[0]
    cliente.post(f"/leads/{lead_id}/assumir", data={"csrf": csrf})
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        assert lead.status == "Humano assumiu" and lead.humano_id
        assert db.execute(select(Oportunidade).where(Oportunidade.lead_id == lead_id)).scalars().one().status == "assumida"
    assert "Resumo para o time humano" in cliente.get(f"/leads/{lead_id}").text


def test_opt_out_e_sem_interesse(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Opt SDR", email="a@optsdr.com.br")
        sdr.processar_resposta(db, lead, "Não quero receber mensagens, remova meu contato", "email")
        assert lead.opt_out and lead.status == "Perdido" and lead.motivo_perda == "Opt-out"
        assert mensagens.bloqueio_de_envio(db, lead, "email")
        outro = _novo_lead(db, "Contábil Frio SDR")
        sdr.processar_resposta(db, outro, "Não temos interesse", "whatsapp")
        assert outro.status == "Perdido" and outro.motivo_perda == "Sem interesse" and not outro.opt_out
        assert not db.execute(select(Oportunidade).where(Oportunidade.lead_id == outro.id)).first()


# ---------------------------------------------------------------- Agenda (horários reais)

def test_horarios_livres_respeitam_expediente_e_reunioes(cliente):
    dias, faixas = agenda_horarios.ler_expediente("seg-sex 09:00-12:00,14:00-18:00")
    assert dias == {0, 1, 2, 3, 4} and len(faixas) == 2
    assert agenda_horarios.ler_expediente("qualquer coisa") == (set(), [])
    with sessao() as db:
        u = _admin(db)
        u.expediente, u.duracao_reuniao = "seg-dom 00:00-23:59", 60
        livres = agenda_horarios.horarios_livres(db, u, quantidade=3)
        assert len(livres) == 3 and all(h >= agora() for h in livres)
        lead = _novo_lead(db, "Contábil Reunião")
        agenda_horarios.agendar(db, lead, u, livres[0], "video", u)
        assert lead.status == "Reunião"
        assert livres[0] not in agenda_horarios.horarios_livres(db, u, quantidade=50)
        with pytest.raises(agenda_horarios.HorarioIndisponivel):
            agenda_horarios.agendar(db, lead, u, livres[0], "video", u)


# ---------------------------------------------------------------- Campanha: aprovação, fila e limites

def _base_receita_ficticia(pasta):
    def zipar(nome, linhas):
        with zipfile.ZipFile(pasta / nome, "w") as z:
            z.writestr(nome.replace(".zip", ".CSV"),
                       "\n".join(";".join(f'"{c}"' for c in l) for l in linhas).encode("latin-1"))

    def estab(basico, nome, cnae, email):
        l = [""] * 30
        l[0], l[1], l[2], l[3], l[4], l[5], l[10], l[11] = basico, "0001", "00", "1", nome, "02", "20150101", cnae
        l[19], l[20], l[21], l[22], l[27] = "PE", "2531", "81", basico[-8:], email
        return l

    zipar("Municipios.zip", [["2531", "RECIFE"]])
    zipar("Estabelecimentos0.zip", [
        estab("71000001", "ADM CONDOMINIOS ALFA", "6822600", "contato@admalfa-sdr.com.br"),
        estab("71000002", "CONDOMINIO GESTAO BETA", "6822600", "ola@condobeta-sdr.com.br"),
        estab("71000003", "CONTABIL GAMA SDR", "6920601", "gama@gamasdr.com.br"),
        estab("71000004", "PADARIA DELTA", "1091101", "padaria@delta.com.br"),
    ])


def test_campanha_completa_com_aprovacao_e_fila(cliente, tmp_path, monkeypatch):
    _base_receita_ficticia(tmp_path)
    assert base_receita.importar_pasta(str(tmp_path)) == 3
    monkeypatch.setattr(campanhas, "gerar_em_segundo_plano", campanhas.gerar)  # roda na hora no teste
    r = cliente.get("/campanhas/nova?pedido=Quero+parceiros+entre+administradoras+de+condom%C3%ADnio+em+Recife")
    assert r.status_code == 200 and 'value="condominio" checked' in r.text and 'value="Recife"' in r.text
    assert "Software e tecnologia" in r.text and r.text.count('<label class="escolha">') == 15  # agrupado, sem repetir
    csrf = r.text.split('name="csrf" content="')[1].split('"')[0]
    r = cliente.post("/campanhas/nova", data={"csrf": csrf, "nome": "Admins Recife", "cidade": "Recife", "estado": "PE",
                                              "quantidade": "5", "categorias": ["condominio"], "canais": ["email"],
                                              "tom": "consultivo"}, follow_redirects=False)
    cid = int(r.headers["location"].rsplit("/", 1)[1])
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.status == "aguardando_aprovacao", camp.erro
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars().all()
        assert tarefas and all(t.status == "rascunho" for t in tarefas)
        assert {t.lead.empresa for t in tarefas} == {"Adm Condominios Alfa", "Condominio Gestao Beta"}
        assert all(t.canal == "email" and t.angulo for t in tarefas)
        assert db.execute(select(Mensagem).where(Mensagem.campanha_id == cid)).first() is None  # nada enviado
    pagina = cliente.get(f"/campanhas/{cid}").text
    assert "APROVAÇÃO NECESSÁRIA" in pagina and "APROVAR CAMPANHA" in pagina
    cliente.post(f"/campanhas/{cid}/aprovar", data={"csrf": csrf})

    enviados = []
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **k: enviados.append(para) or "id-teste")
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    with sessao() as db:
        assert db.get(Campanha, cid).status == "ativa"
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars():
            t.hora = "00:00"
            t.data = min(t.data, date.today())  # num fim de semana a campanha joga tudo para segunda
        # limite por hora = o que já saiu nesta hora (outros testes) + 1
        gravar_config(db, "limite_hora_email", str(mensagens.enviadas_na_hora(db, "email") + 1))
        gravar_config(db, "horas_entre_contatos", "0")
    with sessao() as db:
        r = campanhas.processar_fila(db)
    assert r["enviados"] == 1 and len(enviados) == 1, (r, enviados)  # limite por hora segurou o segundo e-mail
    with sessao() as db:
        msg = db.execute(select(Mensagem).where(Mensagem.campanha_id == cid)).scalars().one()
        assert msg.angulo == "apresentacao" and msg.status == "enviada"
        assert db.get(Lead, msg.lead_id).status == "Contatado"
    assert "Admins Recife" in cliente.get("/inteligencia").text


def test_fim_da_cadencia_vira_sem_resposta(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Silencioso")
        lead.status = "Aguardando resposta"
        db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, canal="email", data=date.today() - timedelta(days=10),
                      status="feita", concluida_em=agora() - timedelta(days=5)))
        db.flush()
        campanhas.finalizar_cadencias(db)
        assert lead.status == "Perdido" and lead.motivo_perda == "Sem resposta"


def test_limite_por_dominio(cliente):
    with sessao() as db:
        a = _novo_lead(db, "Dominio A", email="um@mesmodominio-sdr.com.br")
        b = _novo_lead(db, "Dominio B", email="dois@mesmodominio-sdr.com.br")
        gravar_config(db, "limite_diario_dominio", "1")
        mensagens.registrar(db, a.id, "email", "oi", None, status="enviada")
        db.flush()
        assert "domínio" in mensagens.bloqueio_de_envio(db, b, "email")


# ---------------------------------------------------------------- Webhook do WhatsApp e telas

def test_webhook_whatsapp_classifica_resposta(cliente, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", "segredo-teste")
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Whats SDR", whatsapp="(81) 93333-4444")
        lead_id = lead.id
    corpo = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"from": "5581933334444", "id": "wamid.1", "text": {"body": "Quero marcar uma reunião"}}]}}]}]}).encode()
    assinatura = "sha256=" + hmac.new(b"segredo-teste", corpo, hashlib.sha256).hexdigest()
    assert cliente.post("/api/webhooks/whatsapp", content=corpo, headers={"x-hub-signature-256": "sha256=errada"}).status_code == 403
    r = cliente.post("/api/webhooks/whatsapp", content=corpo, headers={"x-hub-signature-256": assinatura,
                                                                         "content-type": "application/json"})
    assert r.status_code == 200
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        assert lead.classificacao_resposta == "QUER REUNIÃO" and lead.automacao_pausada


def test_telas_da_ia_sdr(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Telas SDR", email="telas@telas-sdr.com.br")
        lead_id = lead.id
    csrf = cliente.get("/minha-conta").text.split('name="csrf" content="')[1].split('"')[0]
    cliente.post(f"/leads/{lead_id}/pesquisar", data={"csrf": csrf})
    cliente.post(f"/leads/{lead_id}/abordagem-sdr", data={"csrf": csrf})
    pagina = cliente.get(f"/leads/{lead_id}").text
    assert "Perfil do parceiro" in pagina and "Abordagem SDR" in pagina and "Encerramento educado" in pagina
    for url in ["/oportunidades", "/oportunidades?ver=tratadas", "/campanhas", "/campanhas/nova",
                "/campanhas/nova?pedido=empresas+que+atendem+PMEs+em+Recife", "/inteligencia",
                "/inteligencia?periodo=tudo&uf=PE&cidade=Recife", "/categorias", "/conhecimento", "/notificacoes",
                f"/leads/{lead_id}/agendar", "/configuracoes?aba=usuarios", "/leads/pipeline"]:
        r = cliente.get(url)
        assert r.status_code == 200, url
    pedido = cliente.get("/campanhas/nova?pedido=empresas+que+atendem+PMEs+em+Recife").text
    assert 'value="bpo" checked' in pedido and 'value="contabil" checked' in pedido


# ---------------------------------------------------------------- WhatsApp conectado (WhatsApp Leads)

class WhatsAppLeadsFalso:
    def __init__(self):
        self.enviados, self.proximo = [], 100

    def enviar(self, telefone, nome, texto, resposta=False, db=None, conexao="principal", **_):
        self.proximo += 1
        self.enviados.append({"id": self.proximo, "telefone": telefone, "texto": texto, "resposta": resposta,
                              "conexao": conexao})
        return self.proximo


def test_envio_e_respostas_pelo_whatsapp_conectado(cliente, monkeypatch):
    from app.integracoes import whatsapp_leads

    falso = WhatsAppLeadsFalso()
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "enviar", falso.enviar)
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": True, "conectado": True})
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Zap SDR", whatsapp="(81) 98877-6655", responsavel="Rita Lima")
        tarefa = Tarefa(tipo="prospeccao", lead_id=lead.id, canal="whatsapp", data=date.today(), angulo="apresentacao",
                        mensagem="Olá, Rita! Mensagem da SDR.")
        db.add(tarefa)
        db.flush()
        msg = sdr.enviar_whatsapp_conectado(db, tarefa.mensagem, _admin(db), lead=lead, tarefa=tarefa)
        assert msg.status == "na_fila" and msg.modo == "whatsapp-leads" and msg.angulo == "apresentacao"
        assert tarefa.status == "feita" and lead.status == "Contatado"
        assert falso.enviados[0]["telefone"] == "(81) 98877-6655"
        with pytest.raises(sdr.EnvioRecusado):  # frequência: já houve mensagem hoje
            sdr.enviar_whatsapp_conectado(db, "de novo", _admin(db), lead=lead)
        id_enviado, lead_id = int(msg.id_externo), lead.id

    novidades = {"recebidas": [{"id": 7, "telefone": "5581988776655", "texto": "Tenho interesse, me liga"}],
                 "envios": [{"id": id_enviado, "status": "enviada", "erro": ""}], "bloqueados": [], "ultimo_id": 7}
    monkeypatch.setattr(whatsapp_leads, "novidades", lambda desde: novidades)
    with sessao() as db:
        r = sdr.sincronizar_whatsapp_conectado(db)
        assert r == {"respostas": 1, "status": 1, "opt_out": 0}
        lead = db.get(Lead, lead_id)
        assert lead.classificacao_resposta == "QUER LIGAÇÃO" and lead.automacao_pausada and lead.status == "Interessado"
        enviada = db.execute(select(Mensagem).where(Mensagem.id_externo == str(id_enviado))).scalars().one()
        assert enviada.status == "enviada" and enviada.respondida
        assert falso.enviados[-1]["resposta"] and "time comercial" in falso.enviados[-1]["texto"]  # SDR respondeu
        from app.banco import ler_config

        assert ler_config(db, "wl_ultimo_id") == "7"

    # Celular antigo chegando sem o nono dígito também é reconhecido
    with sessao() as db:
        outro = _novo_lead(db, "Contábil Nono Dígito", whatsapp="(81) 99123-4567")
        outro_id = outro.id
    novidades.update(recebidas=[{"id": 8, "telefone": "558191234567", "texto": "Não temos interesse"}], envios=[],
                     ultimo_id=8)
    with sessao() as db:
        sdr.sincronizar_whatsapp_conectado(db)
        assert db.get(Lead, outro_id).motivo_perda == "Sem interesse"

    novidades.update(recebidas=[], envios=[], bloqueados=["5581988776655"])
    with sessao() as db:
        sdr.sincronizar_whatsapp_conectado(db)
        assert db.get(Lead, lead_id).opt_out


def test_whatsapp_leads_fechado_nao_quebra(cliente):
    from app.integracoes import whatsapp_leads

    status = whatsapp_leads.status(usar_cache=False)
    assert status["conectado"] is False and status["erro"]
    with sessao() as db:
        assert sdr.sincronizar_whatsapp_conectado(db) == {"respostas": 0, "status": 0, "opt_out": 0}
        lead = _novo_lead(db, "Contábil Sem Zap", whatsapp="(81) 97766-5544")
        with pytest.raises(sdr.EnvioRecusado):
            sdr.enviar_whatsapp_conectado(db, "oi", _admin(db), lead=lead)


def test_botoes_do_whatsapp_conectado(cliente, monkeypatch):
    from app.integracoes import whatsapp_leads

    falso = WhatsAppLeadsFalso()
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {
        "disponivel": True, "conectado": True, "tipo": "teste", "estado": "Conectado", "erro": ""})
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "enviar", falso.enviar)
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": True, "conectado": True})
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Botão Zap", whatsapp="(81) 96655-4433")
        lead.vendedor_id = _admin(db).id
        t = Tarefa(tipo="prospeccao", lead_id=lead.id, canal="whatsapp", data=date.today(), hora="00:00",
                   mensagem="Olá! Mensagem pela Agenda.", usuario_id=_admin(db).id)
        db.add(t)
        db.flush()
        tid, lead_id = t.id, lead.id
    agenda = cliente.get("/agenda").text
    assert "Enviar pelo WhatsApp conectado" in agenda and "WhatsApp conectado" in agenda
    csrf = agenda.split('name="csrf" content="')[1].split('"')[0]
    cliente.post(f"/agenda/{tid}/enviar-whatsapp", data={"csrf": csrf})
    with sessao() as db:
        assert db.get(Tarefa, tid).status == "feita"
    assert falso.enviados and falso.enviados[-1]["texto"] == "Olá! Mensagem pela Agenda."
    assert "Enviar pelo WhatsApp conectado" in cliente.get(f"/leads/{lead_id}").text


def test_fila_de_whatsapp_so_para_quem_ja_conversou(cliente, monkeypatch):
    """Celular conectado: a IA SDR manda sozinha só para quem autorizou ou já escreveu; contato frio espera o clique."""
    from app.integracoes import whatsapp_leads

    falso = WhatsAppLeadsFalso()
    monkeypatch.setattr(whatsapp_leads, "configurado", lambda: True)
    monkeypatch.setattr(whatsapp_leads, "enviar", falso.enviar)
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": True, "conectado": True})
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": True, "conectado": True})
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    with sessao() as db:
        gravar_config(db, "horas_entre_contatos", "0")
        camp = Campanha(nome="Zap automático", status="ativa", aprovado_em=agora(), usuario_id=_admin(db).id)
        db.add(camp)
        db.flush()
        frio = _novo_lead(db, "Contábil Zap Frio", whatsapp="(81) 98111-0001")
        autorizou = _novo_lead(db, "Contábil Zap Autorizou", whatsapp="(81) 98111-0002", consentimento=True)
        escreveu = _novo_lead(db, "Contábil Zap Escreveu", whatsapp="(81) 98111-0003")
        mensagens.registrar(db, escreveu.id, "whatsapp", "Oi, quero saber mais", None, status="recebida")
        for lead in (frio, autorizou, escreveu):
            db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, canal="whatsapp", data=date.today(), hora="00:00",
                          campanha_id=camp.id, angulo="lembrete", mensagem=f"Olá, {lead.empresa}!"))
        db.flush()
        assert autorizou.consentimento_em is None or autorizou.consentimento  # registrado na criação
        ids = {frio.id: "frio", autorizou.id: "autorizou", escreveu.id: "escreveu"}

    with sessao() as db:
        monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": True, "conectado": False})
        assert campanhas.processar_fila_whatsapp(db)["enviados"] == 0  # celular desconectado: nada sai
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": True, "conectado": True})
    with sessao() as db:
        assert campanhas.processar_fila_whatsapp(db)["enviados"] == 2
    enviados = {e["telefone"] for e in falso.enviados}
    assert enviados == {"(81) 98111-0002", "(81) 98111-0003"}  # o contato frio não recebeu nada
    with sessao() as db:
        tarefas = {ids[t.lead_id]: t for t in db.execute(select(Tarefa).where(Tarefa.campanha_id.isnot(None),
                                                                           Tarefa.lead_id.in_(ids))).scalars()}
        assert tarefas["frio"].status == "pendente" and tarefas["autorizou"].status == "feita"
        assert "sozinha" in tarefas["escreveu"].resultado
        gravar_config(db, "enviar_whatsapp_automatico", "0")
    try:
        with sessao() as db:
            assert campanhas.processar_fila_whatsapp(db)["enviados"] == 0  # desligado em Configurações
    finally:
        with sessao() as db:
            gravar_config(db, "enviar_whatsapp_automatico", "1")


def test_marcar_autorizacao_de_whatsapp_na_ficha(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "Contábil Autoriza Ficha", whatsapp="(81) 98222-0001")
        lead_id = lead.id
    pagina = cliente.get(f"/leads/{lead_id}").text
    assert "Autorizou receber mensagens da MS pelo WhatsApp" in pagina
    from app.leads_servico import preencher

    with sessao() as db:
        lead = db.get(Lead, lead_id)
        preencher(lead, {"consentimento": True})
        assert lead.consentimento and lead.consentimento_em is not None
        assert campanhas.whatsapp_liberado(db, lead)


def test_tela_de_envios_mostra_o_que_saiu_e_o_andamento(cliente):
    with sessao() as db:
        admin = _admin(db)
        camp = Campanha(nome="Campanha Envios", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        aprovado_em=agora(), usuario_id=admin.id)
        db.add(camp)
        db.flush()
        lead = _novo_lead(db, "Contábil Envio Visível", email="ola@enviovisivel-teste.com.br")
        t1 = Tarefa(tipo="prospeccao", lead_id=lead.id, canal="email", data=date.today(), campanha_id=camp.id,
                    status="feita", angulo="apresentacao", assunto="Parceria MS", mensagem="Olá!")
        t2 = Tarefa(tipo="prospeccao", lead_id=lead.id, canal="email", data=date.today() + timedelta(days=2),
                    campanha_id=camp.id, status="pendente", angulo="praticidade", mensagem="Seguindo...")
        db.add_all([t1, t2])
        db.flush()
        m = mensagens.registrar(db, lead.id, "email", "Olá!", None, modo="api", status="enviada", assunto="Parceria MS",
                                tarefa_id=t1.id, campanha_id=camp.id, angulo="apresentacao")
        m.respondida = True
        mensagens.registrar(db, lead.id, "email", "Erro", None, modo="api", status="falhou", erro="Caixa cheia",
                            campanha_id=camp.id)
        cid, lead_id = camp.id, lead.id
    pagina = cliente.get("/envios").text
    assert "Contábil Envio Visível" in pagina and "Parceria MS" in pagina and "Respondeu ✓" in pagina
    assert "Não saiu" in pagina and "Caixa cheia" in pagina and "Como funcionam os disparos" in pagina
    assert "Seguindo" not in pagina or "Próximos envios" in pagina
    assert "Contábil Envio Visível" in cliente.get(f"/envios?lead={lead_id}").text
    assert "Contábil Envio Visível" not in cliente.get("/envios?canal=whatsapp").text
    camp_pag = cliente.get(f"/campanhas/{cid}").text
    assert "Andamento por empresa" in camp_pag and "Respondeu ✓" in camp_pag
    assert 'href="/envios"' in camp_pag  # no menu


def test_teste_da_campanha_vai_so_para_quem_testa(cliente, monkeypatch):
    enviados = []
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, **k: enviados.append((para, assunto, corpo)) or "id")
    with sessao() as db:
        admin = _admin(db)
        camp = Campanha(nome="Campanha Para Testar", categorias="contabil", cidade="Recife", estado="PE",
                        status="aguardando_aprovacao", usuario_id=admin.id)
        db.add(camp)
        db.flush()
        for nome in ("Contábil Teste A", "Contábil Teste B"):
            lead = _novo_lead(db, nome, email=f"x@{nome[-1].lower()}-teste-camp.com.br")
            for dia, ang, canal in ((0, "apresentacao", "email"), (2, "praticidade", "email"), (4, "seguranca", "whatsapp")):
                db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, canal=canal, data=date.today() + timedelta(days=dia),
                              campanha_id=camp.id, status="rascunho", angulo=ang, assunto=f"Assunto {ang}", mensagem="Oi!"))
        cid = camp.id
    pagina = cliente.get(f"/campanhas/{cid}").text
    assert "Testar antes de aprovar" in pagina
    csrf = pagina.split('name="csrf" content="')[1].split('"')[0]
    r = cliente.post(f"/campanhas/{cid}/testar", data={"csrf": csrf, "email_teste": "maria@exemplo.com", "canal_teste": "email",
                                                      "empresas": "2", "toques": "primeiro"})
    assert "enviado: 2 e-mail(s)" in r.text and "Nenhum lead recebeu nada" in r.text
    assert len(enviados) == 2 and all(p == "maria@exemplo.com" and a.startswith("[TESTE]") for p, a, _ in enviados)
    enviados.clear()
    cliente.post(f"/campanhas/{cid}/testar", data={"csrf": csrf, "email_teste": "maria@exemplo.com", "canal_teste": "email",
                                                   "empresas": "1", "toques": "todos"})
    assert len(enviados) == 2 and "Contábil Teste A" in enviados[0][2]
    with sessao() as db:
        assert db.get(Campanha, cid).status == "aguardando_aprovacao"
        assert not db.execute(select(Mensagem).where(Mensagem.campanha_id == cid)).first()  # nada registrado nos leads
    # WhatsApp sem celular informado: pede o número e não envia nada
    r = cliente.post(f"/campanhas/{cid}/testar", data={"csrf": csrf, "canal_teste": "whatsapp", "whatsapp_teste": ""})
    assert "celular com DDD" in r.text


def test_controle_de_frequencia_separado_por_canal(cliente):
    with sessao() as db:
        gravar_config(db, "horas_entre_contatos", "20")
        lead = _novo_lead(db, "Contabil Freq Canal", email="x@freq-canal-teste.com.br")
        mensagens.registrar(db, lead.id, "email", "Oi", None, status="enviada")
        db.flush()
        assert "e-mail" in mensagens.bloqueio_de_envio(db, lead, "email")
        assert "há menos de" not in mensagens.bloqueio_de_envio(db, lead, "whatsapp")  # e-mail não segura o WhatsApp
        gravar_config(db, "horas_entre_contatos", "0")


def test_envios_mostra_a_empresa_e_vamos_conversar_e_interesse(cliente):
    from app.integracoes.email_imap import sem_citacao

    with sessao() as db:
        lead = _novo_lead(db, "Contabil Envio Nome", email="x@envio-nome-teste.com.br")
        mensagens.registrar(db, lead.id, "email", "Oi", None, status="enviada", assunto="Assunto")
        assert sdr.classificar_resposta(db, lead, "vamos conversar")["classe"] in config.CLASSES_QUENTES
    assert "Contabil Envio Nome" in cliente.get("/envios?periodo=hoje").text
    resposta = ("teste, de resposta lead.\n\n\nAtenciosamente,\n\n\nEm dom., 25 de out. de 2026 às 17:42, "
                "MS Certificação Digital <\ncontato@mscertificados.com.br> escreveu:\n> texto antigo")
    assert sem_citacao(resposta) == "teste, de resposta lead."



def test_quinze_modelos_por_segmento_seguros(cliente):
    from app import modelos_segmento
    from app.modelos import Template

    for codigo in modelos_segmento.SEGMENTOS:
        lista = modelos_segmento.modelos_do_segmento(codigo)
        assert len(lista) == 15 and sum(m["canal"] == "whatsapp" for m in lista) == 8
        assert {m["angulo"] for m in lista} == set(config.ANGULOS)
        assert all(sdr.texto_seguro(m["corpo"]) and "{quem}" not in m["corpo"] and "{{nome}}" in m["corpo"] for m in lista)
    with sessao() as db:
        assert db.execute(select(func.count(Template.id)).where(Template.categoria == "contabil")).scalar() == 15


def test_prospeccao_por_cnae(cliente, tmp_path):
    from app.rotas.leads import _cnaes_do_formulario

    class F(dict):
        def getlist(self, k):
            return self.get(k + "_lista", [])

    assert _cnaes_do_formulario(F(cnaes_lista=["6319400"], cnaes_outros="6311-9/00, 70.20-4-00, 12")) == \
        ["6319400", "6311900", "7020400"]
    assert "Pesquisar por CNAE" in cliente.get("/prospeccao").text


def test_segmento_novo_de_internet_reclassifica_a_base(cliente):
    from app import modelos, modelos_segmento
    from app.base_receita import EmpresaReceita

    with sessao() as db:
        db.execute(select(Categoria).where(Categoria.codigo == "internet")).scalars().one().ativa = True
        db.delete(db.execute(select(Categoria).where(Categoria.codigo == "internet")).scalars().one())
        tec = db.execute(select(Categoria).where(Categoria.codigo == "tecnologia")).scalars().one()
        tec.cnaes = "6204000,6209100,6319400"
        db.add(EmpresaReceita(cnpj="77000001000100", cnpj_basico="77000001", cnae="6319400", categoria="tecnologia",
                              uf="PE", municipio="RECIFE", municipio_chave="recife"))
        db.flush()
        modelos._categorias_novas(db)
        assert db.execute(select(Categoria).where(Categoria.codigo == "internet")).scalars().one().cnaes == "6319400"
        assert "6319400" not in tec.cnaes
        assert db.get(EmpresaReceita, "77000001000100").categoria == "internet"
    assert len(modelos_segmento.modelos_do_segmento("internet")) == 15


def test_admin_escolhe_o_numero_da_campanha(cliente, monkeypatch):
    from app import conexoes
    from app.integracoes import whatsapp_leads

    with sessao() as db:
        principal = conexoes.garantir_principal(db)
        camp = Campanha(nome="Numero fixo", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        usuario_id=_admin(db).id)
        db.add(camp)
        db.commit()
        cid, numero = camp.id, principal.id
        assert conexoes.da_campanha(db, camp) == ""  # automático
    r = cliente.get(f"/campanhas/{cid}")
    assert "WhatsApp que dispara esta campanha" in r.text
    csrf = r.text.split('name="csrf" content="')[1].split('"')[0]
    cliente.post(f"/campanhas/{cid}/numero", data={"csrf": csrf, "conexao_id": numero})
    with sessao() as db:
        camp = db.get(Campanha, cid)
        assert camp.conexao_id == numero
        monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True,
                                                               "conexoes": {numero: {"conectado": True}}})
        assert conexoes.da_campanha(db, camp) == numero
        monkeypatch.setattr(whatsapp_leads, "status", lambda: {"disponivel": True, "conexoes": {}})
        with pytest.raises(conexoes.SemNumero):
            conexoes.da_campanha(db, camp)  # desconectado: avisa em vez de sair por outro número


def test_teste_de_whatsapp_usa_o_modelo_guardado_em_toque_de_email():
    with sessao() as db:
        lead = _novo_lead(db, "Modelo Duplo Ltda")
        camp = Campanha(nome="So email", categorias="contabil", cidade="Recife", estado="PE",
                        status="aguardando_aprovacao")
        db.add(camp)
        db.flush()
        db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", status="rascunho", data=date.today(),
                      acao="email", mensagem="Texto do e-mail", assunto="Assunto",
                      mensagem_whatsapp="Texto do WhatsApp"))
        db.commit()
        assert campanhas.mensagens_para_teste(db, [camp.id])[camp.id] == {"email": 1, "whatsapp": 1}


def test_tirar_da_campanha_exige_e_guarda_o_motivo(cliente):
    with sessao() as db:
        lead = _novo_lead(db, "Retirada Motivo Ltda")
        camp = Campanha(nome="Com retirada", categorias="contabil", cidade="Recife", estado="PE",
                        status="aguardando_aprovacao")
        db.add(camp)
        db.flush()
        db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", status="rascunho", data=date.today(),
                      acao="email", mensagem="Oi"))
        db.commit()
        cid, lid = camp.id, lead.id
    r = cliente.get(f"/campanhas/{cid}")
    csrf = r.text.split('name="csrf" content="')[1].split('"')[0]
    cliente.post(f"/campanhas/{cid}/remover-lead", data={"csrf": csrf, "lead_id": lid})  # sem motivo: não tira
    with sessao() as db:
        assert db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalar_one().status == "rascunho"
    cliente.post(f"/campanhas/{cid}/remover-lead", data={"csrf": csrf, "lead_id": lid, "motivo": "Já fiz campanha"})
    with sessao() as db:
        t = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalar_one()
        assert t.status == "cancelada" and t.resultado.endswith("Já fiz campanha")
        assert campanhas.andamento(db, db.get(Campanha, cid))[0]["motivo"] == "Já fiz campanha"


def test_disparar_campanha_por_email_e_contar_whatsapp(monkeypatch):
    enviados = []
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db: True)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, texto, **k: enviados.append(para) or "id-1")
    with sessao() as db:
        lead = _novo_lead(db, "Disparo Clique Ltda", email="contato@disparoclique.com.br", whatsapp="81999990001")
        camp = Campanha(nome="Disparo", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        aprovado_em=agora())
        db.add(camp)
        db.flush()
        db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="whatsapp", status="pendente", data=date.today(),
                      tipo="prospeccao", acao="whatsapp", mensagem="Oi pelo WhatsApp",
                      mensagem_email="Oi por e-mail", assunto_email="Parceria"))
        db.commit()
        assert {k: len(v) for k, v in campanhas.para_disparar(db, camp).items()} == {"whatsapp": 1, "email": 1}
        r = campanhas.disparar(db, camp, _admin(db), "email")
        db.commit()
        assert r["enviados"] == 1 and enviados == ["contato@disparoclique.com.br"]
        t = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id)).scalar_one()
        assert t.status == "feita" and t.canal == "email" and t.mensagem == "Oi por e-mail"
        assert t.mensagem_whatsapp == "Oi pelo WhatsApp"  # o modelo do outro canal fica guardado
        assert campanhas.para_disparar(db, camp)["email"] == []  # não manda de novo


def test_minha_fila_mostra_pendentes_fila_e_historico(cliente):
    with sessao() as db:
        admin = _admin(db)
        lead = _novo_lead(db, "Fila Visivel Ltda", email="fila@visivel.com.br")
        camp = Campanha(nome="Campanha da fila", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        aprovado_em=agora(), usuario_id=admin.id)
        db.add(camp)
        db.flush()
        db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="whatsapp", status="pendente", tipo="prospeccao",
                      data=date.today() - timedelta(days=1), acao="whatsapp", mensagem="Oi"))
        db.add(Mensagem(lead_id=lead.id, canal="whatsapp", corpo="Na fila agora", status="na_fila",
                        campanha_id=camp.id, usuario_id=admin.id))
        db.add(Mensagem(lead_id=lead.id, canal="email", corpo="x", assunto="Parceria", status="falhou",
                        erro="Caixa cheia", campanha_id=camp.id, usuario_id=admin.id))
        db.commit()
    r = cliente.get("/fila")
    assert r.status_code == 200
    for texto in ("Minha fila de disparos", "Fila Visivel Ltda", "Na fila agora", "Caixa cheia", "atrasado",
                  "Sem WhatsApp: pesquise o número na campanha"):
        assert texto in r.text, texto
    assert cliente.get("/fila?de=todos&canal=email").status_code == 200


def test_horario_das_mensagens_e_quebrado_e_fora_do_almoco():
    from app import cadencias

    with sessao() as db:
        horas = {cadencias.hora_natural(db) for _ in range(300)}
    assert len(horas) > 50  # cada mensagem num horário diferente
    for h in horas:
        minutos = int(h[:2]) * 60 + int(h[3:])
        assert minutos % 5 != 0 and not (720 <= minutos < 810) and 8 * 60 + 30 <= minutos <= 18 * 60, h


def test_minha_fila_mostra_hora_e_envia_agora(cliente, monkeypatch):
    enviados = []
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, texto, **k: enviados.append(para) or "id-2")
    with sessao() as db:
        admin = _admin(db)
        lead = _novo_lead(db, "Envio Agora Ltda", email="agora@envioagora.com.br")
        camp = Campanha(nome="Campanha agora", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        aprovado_em=agora(), usuario_id=admin.id)
        db.add(camp)
        db.flush()
        t = Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", status="pendente", tipo="prospeccao",
                   data=date.today() + timedelta(days=2), hora="14:13", acao="email", mensagem="Oi", assunto="Oi")
        db.add(t)
        db.commit()
        tid = t.id
    r = cliente.get("/fila")
    assert "14:13" in r.text and "Enviar por e-mail" in r.text
    csrf = r.text.split('name="csrf" content="')[1].split('"')[0]
    cliente.post(f"/fila/enviar/{tid}", data={"csrf": csrf})
    assert enviados == ["agora@envioagora.com.br"]
    with sessao() as db:
        assert db.get(Tarefa, tid).status == "feita"
    pagina = cliente.get("/fila").text
    assert "Reenviar por E-mail" in pagina and f"hist-" in pagina


def test_minha_fila_filtro_whatsapp_mostra_toque_de_email_com_versao_whatsapp(cliente):
    with sessao() as db:
        admin = _admin(db)
        lead = _novo_lead(db, "Versao Reserva Ltda", email="r@versaoreserva.com.br")
        camp = Campanha(nome="Reserva", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        aprovado_em=agora(), usuario_id=admin.id)
        db.add(camp)
        db.flush()
        db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", status="pendente", tipo="prospeccao",
                      data=date.today() + timedelta(days=1), acao="email", mensagem="Oi", mensagem_whatsapp="Oi zap"))
        db.commit()
    r = cliente.get("/fila?canal=whatsapp")
    assert "Versao Reserva Ltda" in r.text and "Enviar por WhatsApp" in r.text and "Enviar por e-mail" in r.text



def test_enviar_toque_de_email_pelo_whatsapp_troca_o_canal(monkeypatch):
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    monkeypatch.setattr(sdr, "enviar_whatsapp_conectado", lambda db, texto, usuario, lead=None, tarefa=None, **k:
                        setattr(tarefa, "status", "feita"))
    with sessao() as db:
        lead = _novo_lead(db, "Troca Canal Ltda", email="t@trocacanal.com.br", whatsapp="81999990002")
        camp = Campanha(nome="Troca", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        aprovado_em=agora())
        db.add(camp)
        db.flush()
        t = Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", status="pendente", tipo="prospeccao",
                   data=date.today(), acao="email", mensagem="Texto e-mail", assunto="A", mensagem_whatsapp="Texto zap")
        db.add(t)
        db.flush()
        assert campanhas.canais_do_toque(t) == ["email", "whatsapp"]
        assert campanhas.enviar_toque_agora(db, t, _admin(db), "whatsapp") == ""
        assert t.canal == "whatsapp" and t.mensagem == "Texto zap" and t.mensagem_email == "Texto e-mail"
        db.rollback()


def test_minha_fila_popup_edita_a_versao_whatsapp(cliente):
    with sessao() as db:
        admin = _admin(db)
        lead = _novo_lead(db, "Popup Edita Ltda", email="p@popupedita.com.br")
        camp = Campanha(nome="Popup", categorias="contabil", cidade="Recife", estado="PE", status="ativa",
                        aprovado_em=agora(), usuario_id=admin.id)
        db.add(camp)
        db.flush()
        t = Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", status="pendente", tipo="prospeccao",
                   data=date.today() + timedelta(days=1), acao="email", mensagem="Texto e-mail", assunto="A",
                   mensagem_whatsapp="Texto zap antigo")
        db.add(t)
        db.commit()
        tid = t.id
    r = cliente.get("/fila")
    assert f'id="msg-{tid}-whatsapp"' in r.text and "Texto zap antigo" in r.text
    csrf = r.text.split('name="csrf" content="')[1].split('"')[0]
    cliente.post(f"/fila/mensagem/{tid}", data={"csrf": csrf, "canal": "whatsapp", "texto": "Texto zap novo"})
    cliente.post(f"/fila/mensagem/{tid}", data={"csrf": csrf, "canal": "email", "texto": "E-mail novo", "assunto": "B"})
    with sessao() as db:
        t = db.get(Tarefa, tid)
        assert (t.mensagem_whatsapp, t.mensagem, t.assunto, t.canal) == ("Texto zap novo", "E-mail novo", "B", "email")
