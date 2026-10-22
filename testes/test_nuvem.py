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
