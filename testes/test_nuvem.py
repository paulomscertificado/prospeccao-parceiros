"""Testes do modo nuvem (Vercel): trabalhos em etapas, agendador, ponte com o WhatsApp Leads e e-mail no banco.
Tudo roda neste computador, sem internet."""

import zipfile

import pytest
from sqlalchemy import delete, select

from app import arquivo_env, base_receita, campanhas, config, mensagens, pesquisa, sdr, trabalhos
from app.banco import gravar_config, ler_config, sessao
from app.integracoes import whatsapp_leads
from app.leads_servico import criar_lead
from app.modelos import Campanha, Configuracao, Lead, Mensagem, PonteWhatsApp, Tarefa, Trabalho, Usuario

SENHA_CRON = "senha-do-agendador-teste"
TOKEN_PONTE = "token-da-ponte-teste"


@pytest.fixture(autouse=True)
def sem_internet(monkeypatch):
    monkeypatch.setattr(pesquisa, "descobrir_site", lambda *a, **k: "")
    monkeypatch.setattr(pesquisa, "ler_site", lambda *a, **k: {})
    monkeypatch.setattr(pesquisa, "dados_do_cnpj", lambda *a, **k: {})
    monkeypatch.setattr(pesquisa, "dados_do_site", lambda *a, **k: {})


@pytest.fixture()
def nuvem(monkeypatch):
    """Liga o modo nuvem só durante o teste."""
    monkeypatch.setattr(config, "NA_NUVEM", True)
    monkeypatch.setattr(config, "CRON_SECRET", SENHA_CRON)
    monkeypatch.setattr(config, "WHATSAPP_PONTE", True)
    monkeypatch.setattr(config, "WHATSAPP_PONTE_TOKEN", TOKEN_PONTE)
    whatsapp_leads._cache["status"] = None
    yield
    whatsapp_leads._cache["status"] = None
    with sessao() as db:
        db.execute(delete(Configuracao).where(Configuracao.chave.in_(["wl_status", arquivo_env.CHAVE_NO_BANCO])))


def _base_ficticia(pasta):
    """Base da Receita mínima (empresas que só este arquivo de testes usa)."""
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
        estab("72000001", "ADM CONDOMINIOS NUVEM UM", "6822600", "contato@nuvemum-teste.com.br"),
        estab("72000002", "CONDOMINIO NUVEM DOIS", "6822600", "ola@nuvemdois-teste.com.br"),
    ])


def _admin(db) -> Usuario:
    return db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()


def test_trava_impede_trabalho_em_dobro(cliente):
    assert trabalhos.pegar_trava("teste-trava", 60)
    assert not trabalhos.pegar_trava("teste-trava", 60)  # outra cópia do sistema não entra
    trabalhos.soltar_trava("teste-trava")
    assert trabalhos.pegar_trava("teste-trava", 60)
    trabalhos.soltar_trava("teste-trava")


def test_agendador_exige_senha(cliente, nuvem, monkeypatch):
    rodadas = []
    monkeypatch.setattr("app.rotas.api.rodada", lambda numero: rodadas.append(numero))
    assert cliente.get("/api/cron").status_code == 403
    assert cliente.get("/api/cron", headers={"Authorization": "Bearer errada"}).status_code == 403
    r = cliente.get("/api/cron", headers={"Authorization": f"Bearer {SENHA_CRON}"})
    assert r.status_code == 200 and r.json()["rodada"] and rodadas == [None]
    monkeypatch.setattr(config, "CRON_SECRET", "")
    assert cliente.get("/api/cron", headers={"Authorization": "Bearer "}).status_code == 503


def test_campanha_montada_em_varias_etapas_pelo_agendador(cliente, nuvem, tmp_path, monkeypatch):
    _base_ficticia(tmp_path)
    base_receita.importar_pasta(str(tmp_path))
    with sessao() as db:
        camp = Campanha(nome="Nuvem em etapas", categorias="condominio", cidade="Recife", estado="PE", quantidade=5,
                        canais="email", status="gerando", usuario_id=_admin(db).id)
        db.add(camp)
        db.flush()
        cid = camp.id
    campanhas.gerar_em_segundo_plano(cid)  # na nuvem só entra na fila (nenhuma linha de execução é criada)
    with sessao() as db:
        t = db.execute(select(Trabalho).where(Trabalho.tipo == "campanha", Trabalho.ref_id == cid)).scalars().one()
        assert t.status == "na_fila" and "fila" in db.get(Campanha, cid).etapa

    original = trabalhos.em_lotes

    def um_lote_por_vez(itens, inicio, tamanho, prazo):  # simula o tempo da nuvem acabando a cada lote
        for lote in original(itens, inicio, 1, prazo):
            yield lote
            return

    monkeypatch.setattr(trabalhos, "em_lotes", um_lote_por_vez)
    for _ in range(20):
        assert cliente.get("/api/cron", headers={"Authorization": f"Bearer {SENHA_CRON}"}).status_code == 200
        with sessao() as db:
            if db.get(Trabalho, t.id).status != "na_fila":
                break
    with sessao() as db:
        trabalho, camp = db.get(Trabalho, t.id), db.get(Campanha, cid)
        assert trabalho.status == "feito" and trabalho.etapas >= 3, (trabalho.etapas, trabalho.erro)
        assert camp.status == "aguardando_aprovacao", camp.erro
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars().all()
        assert {t.lead.empresa for t in tarefas} == {"Adm Condominios Nuvem Um", "Condominio Nuvem Dois"}
        assert all(t.status == "rascunho" for t in tarefas)


def test_trabalho_com_erro_avisa_e_nao_trava_a_fila(cliente, nuvem):
    with sessao() as db:
        camp = Campanha(nome="Sem base", categorias="inexistente", cidade="X", estado="PE", quantidade=1,
                        status="gerando", usuario_id=_admin(db).id)
        db.add(camp)
        db.flush()
        cid = camp.id
    tid = trabalhos.iniciar("campanha", cid)
    original = base_receita.disponivel
    base_receita.disponivel = lambda db: False
    try:
        assert trabalhos.executar(tid, 30) == "erro"
    finally:
        base_receita.disponivel = original
    with sessao() as db:
        assert db.get(Campanha, cid).status == "erro" and "base da Receita" in db.get(Campanha, cid).erro
    assert trabalhos.executar(tid, 30) == "erro"  # não roda de novo


def test_ponte_whatsapp_leva_mensagem_e_traz_resposta(cliente, nuvem, monkeypatch):
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    cab = {"x-token": TOKEN_PONTE}
    assert cliente.get("/api/ponte/teste", headers={"x-token": "errado"}).status_code == 403
    assert cliente.get("/api/ponte/teste", headers=cab).json() == {"ok": True}
    with sessao() as db:
        lead, _ = criar_lead(db, {"empresa": "Contábil Ponte Nuvem", "whatsapp": "(81) 99876-0001"}, _admin(db))
        lead_id = lead.id
        # Computador desligado: o sistema avisa em vez de deixar a mensagem esperando sem prazo
        with pytest.raises(sdr.EnvioRecusado, match="WhatsApp Leads"):
            sdr.enviar_whatsapp_conectado(db, "Olá! Teste da ponte.", _admin(db), lead=lead)

    status = {"conectado": True, "tipo": "teste", "estado": "Conectado", "numero": "5581900000000",
              "enviadas_hoje": 3, "limite_diario": 200}
    r = cliente.post("/api/ponte/troca", json={"status": status}, headers=cab)
    assert r.status_code == 200 and r.json()["envios"] == []
    assert whatsapp_leads.status(usar_cache=False)["conectado"]  # o rodapé mostra "WhatsApp conectado"

    with sessao() as db:
        lead = db.get(Lead, lead_id)
        msg = sdr.enviar_whatsapp_conectado(db, "Olá! Teste da ponte.", _admin(db), lead=lead)
        assert msg.status == "na_fila" and msg.id_externo.startswith("p")
        msg_id = msg.id
    envios = cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()["envios"]
    assert len(envios) == 1 and envios[0]["texto"] == "Olá! Teste da ponte." and "99876" in envios[0]["telefone"]
    assert cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()["envios"] == []  # nunca em dobro

    novidades = {"recebidas": [{"id": 9001, "texto": "Tenho interesse sim, pode me explicar como funciona?",
                                "telefone": "5581998760001", "nome": "Fulano"}],
                 "envios": [{"id": 555, "status": "enviada", "erro": ""}], "bloqueados": [], "ultimo_id": 9001}
    r = cliente.post("/api/ponte/retorno", headers=cab,
                     json={"confirmados": [{"id": envios[0]["id"], "id_wl": 555}], "novidades": novidades})
    assert r.status_code == 200 and r.json()["respostas"] == 1
    with sessao() as db:
        msg = db.get(Mensagem, msg_id)
        assert msg.id_externo == "555" and msg.status == "enviada"
        assert db.get(PonteWhatsApp, envios[0]["id"]).status == "na_fila"
        assert db.get(Lead, lead_id).status not in ("Novo", "Contatado")  # a IA SDR leu a resposta
        assert ler_config(db, "wl_ultimo_id") == "9001"
    assert cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()["desde"] == 9001


def test_email_salvo_pela_tela_fica_criptografado_no_banco(nuvem, monkeypatch):
    for chave in ("SMTP_HOST", "SMTP_SENHA"):
        monkeypatch.setenv(chave, "")
        monkeypatch.setattr(config, chave, "")
    monkeypatch.setattr(arquivo_env, "_gravar_no_arquivo", lambda v: pytest.fail("na nuvem não existe .env"))
    arquivo_env.gravar({"SMTP_HOST": "smtp.gmail.com", "SMTP_SENHA": "senhadeappteste"})
    with sessao() as db:
        guardado = ler_config(db, arquivo_env.CHAVE_NO_BANCO)
    assert guardado and "senhadeappteste" not in guardado
    config.SMTP_SENHA = ""  # outra cópia do sistema, que ainda não sabe da senha
    arquivo_env.carregar_do_banco(forcar=True)
    assert config.SMTP_SENHA == "senhadeappteste" and config.SMTP_HOST == "smtp.gmail.com"


def test_rodada_da_nuvem_respeita_intervalos():
    from app import rotinas

    with sessao() as db:
        gravar_config(db, "teste_intervalo", "")
    assert rotinas._na_vez(None, "teste_intervalo", 5)
    assert not rotinas._na_vez(None, "teste_intervalo", 5)  # chamou de novo no mesmo minuto: espera
    assert rotinas._na_vez(10, "qualquer", 5) and not rotinas._na_vez(11, "qualquer", 5)


def test_tela_whatsapp_na_nuvem_manda_pedidos_pela_ponte(cliente, nuvem):
    from app.modelos import ComandoWhatsApp

    cab = {"x-token": TOKEN_PONTE}
    status = {"conectado": False, "tipo": "qr", "estado": "Aguardando leitura do QR code", "estado_codigo": "aguardando_qr",
              "qr": "data:image/png;base64,QRTESTE", "numero": "", "enviadas_hoje": 0, "limite_diario": 200,
              "regras": {"intervalo_min_seg": "8", "intervalo_max_seg": "20", "limite_diario": "200",
                         "horario_inicio": "08:00", "horario_fim": "20:00", "palavras_sair": "SAIR"}}
    # sem a tela aberta, a ponte troca a cada 30 s
    with sessao() as db:
        gravar_config(db, "wl_tela_vista_em", "")
    assert cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()["intervalo"] == 30
    pagina = cliente.get("/whatsapp")
    assert pagina.status_code == 200 and "Conectar com QR code" in pagina.text and "Regras de envio" in pagina.text
    assert 'href="/whatsapp"' in pagina.text  # está no menu
    estado = cliente.get("/whatsapp/estado").json()
    assert estado["situacao"]["qr"] == "data:image/png;base64,QRTESTE" and estado["situacao"]["disponivel"]
    csrf = pagina.text.split('name="csrf" content="')[1].split('"')[0]
    cliente.post("/whatsapp/comando", data={"csrf": csrf, "acao": "conectar", "tipo": "qr"})
    cliente.post("/whatsapp/comando", data={"csrf": csrf, "acao": "salvar_regras", "intervalo_min_seg": "30",
                                            "intervalo_max_seg": "10", "limite_diario": "50"})  # inválido: não vai
    r = cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()
    assert r["intervalo"] == 3  # tela aberta: troca rápida
    assert [(c["acao"], c["dados"]) for c in r["comandos"]] == [("conectar", {"tipo": "qr"})]
    assert cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()["comandos"] == []  # nunca em dobro
    novo = {**status, "conectado": True, "estado": "Conectado", "estado_codigo": "conectado", "qr": "", "numero": "5581999"}
    cliente.post("/api/ponte/retorno", headers=cab,
                 json={"confirmados": [], "novidades": {}, "comandos": [{"id": r["comandos"][0]["id"], "erro": ""}],
                       "status": novo})
    estado = cliente.get("/whatsapp/estado").json()
    assert estado["situacao"]["conectado"] and estado["pedido"]["status"] == "feito"
    with sessao() as db:
        assert db.execute(select(ComandoWhatsApp)).scalars().all()[-1].status == "feito"


def test_conversas_copiadas_e_envio_para_qualquer_numero(cliente, nuvem):
    from app.modelos import MensagemWhatsApp

    cab = {"x-token": TOKEN_PONTE}
    status = {"conectado": True, "tipo": "qr", "estado": "Conectado", "estado_codigo": "conectado", "numero": "x"}
    r = cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()
    assert "desde_conversas" in r
    inicio = r["desde_conversas"]
    conversas = {"mensagens": [
        {"id": inicio + 1, "direcao": "entrada", "texto": "Oi, vi o anúncio de vocês", "status": "recebida", "erro": "",
         "origem": "celular", "criado_em": "2026-10-23 09:00:00", "telefone": "+5581977770001", "nome": "Carla Cliente"},
        {"id": inicio + 2, "direcao": "saida", "texto": "Olá, Carla! Como posso ajudar?", "status": "na_fila", "erro": "",
         "origem": "manual", "criado_em": "2026-10-23 09:01:00", "telefone": "+5581977770001", "nome": "Carla Cliente"}],
        "status": [], "ultimo_id": inicio + 2}
    cliente.post("/api/ponte/retorno", headers=cab, json={"confirmados": [], "novidades": {}, "conversas": conversas})
    cliente.post("/api/ponte/retorno", headers=cab, json={"confirmados": [], "novidades": {}, "conversas": conversas})  # repetido: não duplica
    pagina = cliente.get("/conversas")
    assert pagina.status_code == 200 and "Nova mensagem" in pagina.text and 'href="/conversas"' in pagina.text
    lista = cliente.get("/conversas/api/lista").json()["conversas"]
    carla = next(c for c in lista if c["telefone"] == "81977770001")
    assert carla["nome"] == "Carla Cliente" and carla["nao_lidas"] == 1 and carla["ultima_direcao"] == "saida"
    assert cliente.get("/conversas/api/lista?busca=carla").json()["conversas"][0]["telefone"] == "81977770001"
    c = cliente.get("/conversas/api/conversa/81977770001").json()
    assert [m["direcao"] for m in c["mensagens"]] == ["entrada", "saida"]
    assert next(x for x in cliente.get("/conversas/api/lista").json()["conversas"]
                if x["telefone"] == "81977770001")["nao_lidas"] == 0  # abrir a conversa marca como lida
    # status atualizado depois (na fila -> enviada)
    cliente.post("/api/ponte/retorno", headers=cab, json={"confirmados": [], "novidades": {}, "conversas": {
        "mensagens": [], "status": [{"id": inicio + 2, "status": "enviada", "erro": ""}], "ultimo_id": inicio + 2}})
    assert cliente.get("/conversas/api/conversa/81977770001").json()["mensagens"][-1]["status"] == "enviada"

    csrf = pagina.text.split('name="csrf" content="')[1].split('"')[0]
    h = {"x-csrf-token": csrf}
    assert cliente.post("/conversas/api/enviar", json={"telefone": "123", "texto": "oi"}, headers=h).status_code == 400
    r = cliente.post("/conversas/api/enviar", json={"telefone": "(81) 96666-0002", "nome": "Novo Contato",
                                                   "texto": "Olá! Aqui é da MS."}, headers=h)
    assert r.status_code == 200 and r.json()["telefone"] == "81966660002"
    assert cliente.get("/conversas/api/conversa/81966660002").json()["enviando"][0]["texto"] == "Olá! Aqui é da MS."
    envios = cliente.post("/api/ponte/troca", json={"status": status}, headers=cab).json()["envios"]
    novo = next(e for e in envios if e["texto"] == "Olá! Aqui é da MS.")
    assert novo["manual"] and novo["telefone"] == "5581966660002" and novo["nome"] == "Novo Contato"
    with sessao() as db:  # quem pediu SAIR não recebe nem pela tela Conversas
        lead, _ = criar_lead(db, {"empresa": "Contábil Saiu Conversa", "whatsapp": "(81) 95555-0003"}, _admin(db))
        lead.opt_out = True
    r = cliente.post("/conversas/api/enviar", json={"telefone": "81955550003", "texto": "oi"}, headers=h)
    assert r.status_code == 409 and "opt-out" in r.json()["erro"]
    with sessao() as db:
        assert db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.telefone == "81977770001")).scalars().all().__len__() == 2
