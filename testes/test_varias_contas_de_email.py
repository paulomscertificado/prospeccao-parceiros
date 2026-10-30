"""Um e-mail por pessoa (como o WhatsApp) e compartilhamento de e-mail e WhatsApp pelo administrador e pelo gestor."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import arquivo_env, campanhas, config, contas_email, mensagens, rotinas
from app.banco import agora, gravar_config, ler_config, sessao
from app.integracoes import email_imap, email_smtp
from app.leads_servico import criar_lead
from app.main import app
from app.modelos import Campanha, ConexaoWhatsApp, ContaEmail, Lead, Mensagem, Tarefa, Usuario
from app.seguranca import criptografar, resumir_senha
from conftest import csrf_de

SENHA = "senhaEquipe123"
CHAVES = ("enviar_email_automatico", "horas_entre_contatos", "limite_hora_email", "sdr_resposta_automatica",
          "imap_ler_desde")


@pytest.fixture(autouse=True)
def arrumar(monkeypatch):
    monkeypatch.setattr(arquivo_env, "carregar_do_banco", lambda forcar=False: None)

    def sem_internet(*a, **k):
        raise OSError("teste sem internet")

    monkeypatch.setattr(email_imap.imaplib, "IMAP4_SSL", sem_internet)
    monkeypatch.setattr(config, "EMAIL_DOMINIO", "mscertificados.com.br")
    with sessao() as db:
        antes = {c: ler_config(db, c) for c in CHAVES}
    yield
    with sessao() as db:
        for c, v in antes.items():
            gravar_config(db, c, v)
        p = contas_email.garantir_principal(db)
        p.compartilhada_todos, p.compartilhada_com = True, "[]"
        for c in db.execute(select(ContaEmail).where(ContaEmail.principal.is_(False))).scalars():
            c.ler_respostas = False  # o relógio do sistema não tenta ler caixas de teste depois


def _pessoa(db, nome, perfil="funcionario") -> Usuario:
    u = Usuario(nome=nome, email=f"{nome.lower().replace(' ', '.')}@equipe.com.br", senha_hash=resumir_senha(SENHA),
                perfil=perfil)
    db.add(u)
    db.flush()
    return u


def _conta(db, dono: Usuario, endereco: str, **campos) -> ContaEmail:
    c = ContaEmail(dono_id=dono.id, endereco=endereco, login=endereco, senha_cripto=criptografar("abcdefghijklmnop"),
                   nome=f"E-mail de {dono.nome}", **contas_email.GOOGLE, **{"ler_respostas": False, **campos})
    db.add(c)
    db.flush()
    return c


def _entrar(c: TestClient, email: str):
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})


def test_ordem_da_conta_que_envia(cliente):
    with sessao() as db:
        ana, beto = _pessoa(db, "Ana Ordem"), _pessoa(db, "Beto Ordem")
        propria = _conta(db, ana, "ana.ordem@mscertificados.com.br")
        da_beto = _conta(db, beto, "beto.ordem@mscertificados.com.br", compartilhada_com=json.dumps([ana.id]))
        principal = contas_email.garantir_principal(db)
        assert contas_email.para_enviar(db, ana).id == propria.id          # 1º a própria
        propria.ativa = False
        assert contas_email.para_enviar(db, ana).id == da_beto.id          # 2º a compartilhada com ela
        da_beto.compartilhada_com = "[]"
        assert contas_email.para_enviar(db, ana).id == principal.id        # 3º a principal (liberada para todos)
        principal.compartilhada_todos = False
        with pytest.raises(contas_email.SemConta):                         # principal restrita: espera
            contas_email.para_enviar(db, ana)
        principal.compartilhada_com = json.dumps([ana.id])
        assert contas_email.para_enviar(db, ana).id == principal.id
        assert contas_email.credenciais(propria).senha == "abcdefghijklmnop"  # guardada criptografada
        assert propria.senha_cripto != "abcdefghijklmnop"


def test_fila_sai_pela_conta_do_responsavel_e_erro_pausa_so_ela(cliente, monkeypatch):
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    monkeypatch.setattr(mensagens, "dentro_do_horario", lambda db, momento=None: True)
    saidas, quebrada = [], set()

    def enviar(para, assunto, corpo, conta=None, **k):
        rotulo = contas_email.credenciais(conta).rotulo
        if rotulo in quebrada:
            raise email_smtp.ErroEmail("O Google recusou a senha.")
        saidas.append((para, rotulo))
        return f"<{len(saidas)}@teste>"

    monkeypatch.setattr(email_smtp, "enviar", enviar)
    with sessao() as db:
        for c, v in (("enviar_email_automatico", "1"), ("horas_entre_contatos", "0"), ("limite_hora_email", "1000")):
            gravar_config(db, c, v)
        carla, davi = _pessoa(db, "Carla Fila"), _pessoa(db, "Davi Fila")
        conta_carla = _conta(db, carla, "carla.fila@mscertificados.com.br")
        camp = Campanha(nome="Fila por conta", status="ativa", aprovado_em=agora(), usuario_id=carla.id)
        db.add(camp)
        db.flush()
        ids = {}
        for dono, email in ((carla, "lead1@contasfila.com.br"), (carla, "lead2@contasfila.com.br"),
                            (davi, "lead3@contasfila.com.br")):
            lead, _ = criar_lead(db, {"empresa": f"Contas Fila {email}", "email": email, "cidade": "Recife",
                                      "estado": "PE"}, dono, checar_duplicado=False)
            lead.vendedor_id = dono.id
            db.flush()
            db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, canal="email", data=date.today(), hora="00:00",
                          campanha_id=camp.id, angulo="apresentacao", mensagem="Olá!", assunto="Parceria"))
            ids[email] = lead.id
        conta_id = conta_carla.id
    quebrada.add("carla.fila@mscertificados.com.br")
    with sessao() as db:
        campanhas.processar_fila(db)
    # a conta da Carla falhou e pausou; o lead do Davi saiu pela principal mesmo assim
    assert ("lead3@contasfila.com.br", "principal") in saidas
    assert not any(p.startswith("lead1") or p.startswith("lead2") for p, _ in saidas)
    with sessao() as db:
        assert ler_config(db, f"fila_email_pausada_ate:email:{conta_id}") > agora().isoformat()
        gravar_config(db, f"fila_email_pausada_ate:email:{conta_id}", "")
    quebrada.clear()
    with sessao() as db:
        campanhas.processar_fila(db)
    assert ("lead1@contasfila.com.br", "carla.fila@mscertificados.com.br") in saidas
    with sessao() as db:
        msg = db.execute(select(Mensagem).where(Mensagem.lead_id == ids["lead1@contasfila.com.br"],
                                                Mensagem.status == "enviada")).scalars().one()
        assert msg.conexao == f"email:{conta_id}"


def test_respostas_lidas_na_caixa_de_cada_pessoa_e_respondidas_por_ela(cliente, monkeypatch):
    monkeypatch.setattr(email_smtp, "configurado", lambda: True)
    lidas, respostas = [], []
    with sessao() as db:
        gravar_config(db, "sdr_resposta_automatica", "1")
        eva = _pessoa(db, "Eva Caixa")
        conta = _conta(db, eva, "eva.caixa@mscertificados.com.br", ler_respostas=True)
        lead, _ = criar_lead(db, {"empresa": "Caixa da Eva Ltda", "email": "dono@caixadaeva.com.br", "cidade": "Recife",
                                  "estado": "PE"}, eva, checar_duplicado=False)
        endereco = conta.endereco

    def ler(emails, enviados=None, ja=None, desde=None, maximo=30, conta=None):
        lidas.append(contas_email.credenciais(conta).rotulo)
        if conta is not None and not conta.principal:
            return [{"de": "dono@caixadaeva.com.br", "assunto": "Re: Parceria", "texto": "Tenho interesse, como funciona?",
                     "message_id": "<eva1@cliente>", "responde_a": []}]
        return []

    monkeypatch.setattr(email_imap, "ler_respostas", ler)
    monkeypatch.setattr(email_smtp, "enviar", lambda para, assunto, corpo, conta=None, **k:
                        respostas.append((para, contas_email.credenciais(conta).rotulo)) or "<r@teste>")
    assert rotinas.ler_respostas_por_email() == 1
    assert endereco in lidas and ("dono@caixadaeva.com.br", endereco) in respostas  # a resposta sai pela mesma caixa


def test_cada_pessoa_cadastra_o_proprio_email(cliente):
    with sessao() as db:
        _pessoa(db, "Fabi Cadastro")
    with TestClient(app) as c:
        _entrar(c, "fabi.cadastro@equipe.com.br")
        pagina = c.get("/email").text
        assert "Cadastrar o meu e-mail" in pagina
        csrf = csrf_de(pagina)
        r = c.post("/email/minha", data={"csrf": csrf, "endereco": "fabi@gmail.com", "senha": "abcdefghijklmnop"})
        assert "precisa ser do domínio" in r.text
        r = c.post("/email/minha", data={"csrf": csrf, "endereco": "fabi@mscertificados.com.br", "senha": "senha123"})
        assert "16 letras" in r.text
        r = c.post("/email/minha", data={"csrf": csrf, "endereco": "fabi@mscertificados.com.br",
                                         "senha": "abcd efgh ijkl mnop", "ler_respostas": "on"})
        assert "E-mail salvo" in r.text and "saem por <b>fabi@mscertificados.com.br</b>" in r.text
    with sessao() as db:
        conta = db.execute(select(ContaEmail).where(ContaEmail.endereco == "fabi@mscertificados.com.br")).scalars().one()
        assert conta.ler_respostas and contas_email.credenciais(conta).senha == "abcdefghijklmnop"


def test_gestor_compartilha_email_e_whatsapp_e_vendedor_nao(cliente):
    with sessao() as db:
        gil = _pessoa(db, "Gil Gestor", "gestor")
        hugo = _pessoa(db, "Hugo Dono")
        ivo = _pessoa(db, "Ivo Vendedor", "vendedor")
        conta = _conta(db, hugo, "hugo.dono@mscertificados.com.br")
        db.add(ConexaoWhatsApp(id=f"u{hugo.id}", nome="WhatsApp do Hugo", dono_id=hugo.id))
        conta_id, numero, ivo_id, gil_id = conta.id, f"u{hugo.id}", ivo.id, gil.id
    with TestClient(app) as c:
        _entrar(c, "gil.gestor@equipe.com.br")
        pagina = c.get("/email").text
        assert "hugo.dono@mscertificados.com.br" in pagina and "Compartilhar esta conta" in pagina
        csrf = csrf_de(pagina)
        c.post("/email/compartilhar", data={"csrf": csrf, "conta": conta_id, "usuarios": [str(ivo_id)]})
        c.post("/whatsapp/compartilhar", data={"csrf": csrf, "numero": numero, "usuarios": [str(ivo_id)]})
    with sessao() as db:
        from app.rotas import whatsapp as tela_whatsapp

        cartoes = tela_whatsapp._estado(db, db.get(Usuario, gil_id))["numeros"]
        assert any(n["id"] == numero and n["compartilhar"] and not n["gerenciar"] for n in cartoes)  # vê e compartilha
        assert contas_email.compartilhada_com(db.get(ContaEmail, conta_id)) == [ivo_id]
        assert json.loads(db.get(ConexaoWhatsApp, numero).compartilhada_com) == [ivo_id]
        ivo = db.get(Usuario, ivo_id)
        assert contas_email.para_enviar(db, ivo).id == conta_id  # o vendedor passa a enviar pela conta do Hugo
    with TestClient(app) as c:
        _entrar(c, "ivo.vendedor@equipe.com.br")
        csrf = csrf_de(c.get("/email").text)
        r = c.post("/email/compartilhar", data={"csrf": csrf, "conta": conta_id, "todos": "on"})
        assert "Só o dono da conta" in r.text
    with sessao() as db:
        assert not db.get(ContaEmail, conta_id).compartilhada_todos
