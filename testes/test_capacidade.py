"""Quanto cabe por dia na marca (app/capacidade.py; pedido da Maria em 25/11/2026: "quantas empresas novas e quantas
campanhas eu consigo fazer no máximo diariamente de forma automática", com uma cadência de 4 toques, e "faça aparecer
isso nas marcas que têm e-mail cadastrado no nosso sistema").

- WhatsApp: cada número de verdade manda o que cabe no dia (6 por hora, das 07:30 às 20:00, sem o almoço = 64), até o
  limite por dia do número e o de contatos frios; número em modo teste ou desconectado não conta;
- e-mail: os limites da marca (80 por dia), somando as contas;
- 4 toques: 64 ÷ 4 = 16 pelo WhatsApp e 80 ÷ 4 = 20 pelo e-mail: vale o menor, 16 empresas novas por dia, 80 por
  semana;
- campanhas: sem limite de quantas; cada uma manda até 60 mensagens por dia, então 16 empresas por dia (128 mensagens)
  pedem pelo menos 3 campanhas em andamento;
- o quadro aparece na tela Campanhas só nas marcas com conta de e-mail cadastrada; o Admin Master vê o de cada uma."""

import json
from collections import Counter
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import capacidade, conexoes, feriados, marca
from app.ars import apagar
from app.banco import agora, gravar_config, ler_config, motor, sessao, usar_config_da_ar
from app.main import app
from app.modelos import Campanha, ConexaoWhatsApp, ContaEmail, Lead, Tarefa, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

REGRAS = {"horario_envio_inicio": "07:30", "horario_envio_fim": "20:00", "limite_hora_whatsapp": "6",
          "limite_diario_whatsapp": "0", "limite_hora_email": "20", "limite_diario_email": "80",
          "limite_diario_campanha": "60", "pular_fim_de_semana": "1"}
DA_PLATAFORMA = {"intervalo_whatsapp_min": "8", "intervalo_whatsapp_max": "12", "limite_frios_whatsapp": "0"}
_contador = Counter()


@pytest.fixture()
def regras_da_plataforma(cliente):
    """8 a 12 minutos entre um WhatsApp e outro e sem teto de contatos frios (como no sistema de verdade), voltando ao
    que estava depois do teste (essas regras são da plataforma)."""
    with sessao() as db:
        antes = {chave: ler_config(db, chave) for chave in DA_PLATAFORMA}
        for chave, valor in DA_PLATAFORMA.items():
            gravar_config(db, chave, valor)
    yield
    with sessao() as db:
        for chave, valor in antes.items():
            gravar_config(db, chave, valor)


def _marca(db, nome="Marca capacidade") -> int:
    _contador["marca"] += 1
    ar = Tenant(slug=f"capacidade-{_contador['marca']}", nome=f"{nome} {_contador['marca']}")
    db.add(ar)
    db.flush()
    marca.esquecer(ar.id)  # os testes desfazem as marcas: o número volta e o nome guardado seria o da anterior
    usar_config_da_ar(db, ar.id)
    for chave, valor in REGRAS.items():
        gravar_config(db, chave, valor)
    usar_config_da_ar(db, None)
    return ar.id


def _pessoa(db, ar, nome, numero=False, conta=True) -> Usuario:
    """Uma pessoa da marca com o próprio número de WhatsApp e/ou o próprio e-mail para os disparos."""
    _contador["pessoa"] += 1
    endereco = f"capacidade.{_contador['pessoa']}@capacidade-teste.com.br"
    pessoa = Usuario(nome=nome, email=endereco, perfil="admin", senha_hash=resumir_senha(SENHA), tenant_id=ar)
    db.add(pessoa)
    db.flush()
    if numero:
        db.add(ConexaoWhatsApp(id=conexoes.id_do_usuario(pessoa.id), nome=f"WhatsApp de {nome}", dono_id=pessoa.id,
                               tenant_id=ar))
    if conta:
        db.add(ContaEmail(nome=f"E-mail de {nome}", dono_id=pessoa.id, endereco=endereco, tenant_id=ar, ativa=True))
    db.flush()
    return pessoa


def _whatsapp(monkeypatch, numeros: dict) -> None:
    """O WhatsApp Leads diz quais números estão conectados: {id: "qr" (de verdade) ou "teste" (modo teste)}."""
    from app.integracoes import whatsapp_leads

    situacao = {"disponivel": True, "conexoes": {i: {"conectado": True, "tipo": tipo} for i, tipo in numeros.items()}}
    monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: situacao)


def _dia_util(db, pessoa) -> date:
    """Um dia de envio (seg a sex, sem feriado de quem envia) daqui a pelo menos 3 dias."""
    sem = feriados.dias_sem_envio(db, pessoa)
    dia = date.today() + timedelta(days=3)
    while dia.weekday() >= 5 or dia in sem:
        dia += timedelta(days=1)
    return dia


def _toques(db, ar, dono, dia, canal, quantos):
    camp = Campanha(nome=f"Capacidade {canal}", tipo="parceiros", status="ativa", usuario_id=dono.id,
                    canais="whatsapp,email", whatsapp_sozinho=True, aprovado_em=agora(), tenant_id=ar)
    db.add(camp)
    db.flush()
    for i in range(quantos):
        _contador["lead"] += 1
        n = _contador["lead"]
        lead = Lead(empresa=f"Empresa capacidade {n}", whatsapp=f"(81) 9{87000000 + n}",
                    email=f"contato{n}@capacidade-empresa.com.br", status="Abordagem criada", vendedor_id=dono.id,
                    tenant_id=ar)
        db.add(lead)
        db.flush()
        db.add(Tarefa(tipo="prospeccao", lead_id=lead.id, campanha_id=camp.id, canal=canal, data=dia,
                      hora=f"{9 + i:02d}:17", status="pendente", mensagem="Olá!", assunto="Parceria",
                      usuario_id=dono.id, tenant_id=ar))
    db.flush()


def test_quatro_toques_cabem_16_empresas_por_dia(regras_da_plataforma, monkeypatch):
    """A conta que a Maria pediu: um número de verdade (64 WhatsApps por dia) e o e-mail da marca (80 por dia)."""
    with sessao() as db:
        ar = _marca(db)
        dona = _pessoa(db, ar, "Capacidade Dona", numero=True)
        usa = _pessoa(db, ar, "Capacidade Usa", conta=False)  # dispara pelo número que a Dona compartilhou com ela
        so_teste = _pessoa(db, ar, "Capacidade Teste", numero=True, conta=False)  # só tem um número em modo teste
        numero = db.get(ConexaoWhatsApp, conexoes.id_do_usuario(dona.id))
        numero.compartilhada_com = json.dumps([usa.id])
        _whatsapp(monkeypatch, {numero.id: "qr", conexoes.id_do_usuario(so_teste.id): "teste"})
        dia = _dia_util(db, dona)
        _toques(db, ar, dona, dia, "whatsapp", 3)
        _toques(db, ar, dona, dia, "email", 2)

        c = capacidade.da_marca(db, ar)
        assert c["zap_por_numero"] == 64 and c["zap_dia"] == 64 and c["numeros_de_verdade"] == 1
        assert c["zap_por_hora"] == 6 and c["horario"] == "07:30 às 20:00"
        assert c["email_dia"] == 80 and c["email_por_hora"] == 17
        assert (c["whatsapp"], c["email"], c["empresas"], c["por_semana"]) == (16, 20, 16, 80)
        assert [(o["toques"], o["empresas"]) for o in c["outras"]] == [(2, 32), (3, 21), (5, 12)]
        assert c["mensagens_dia"] == 128 and c["campanhas_minimas"] == 3  # cada campanha manda até 60 por dia
        assert c["um_numero_a_mais"] == 16
        numeros = {n["id"]: n for n in c["numeros"]}
        assert numeros[numero.id]["conta"] and numeros[numero.id]["quem"] == ["Capacidade Dona", "Capacidade Usa"]
        modo_teste = numeros[conexoes.id_do_usuario(so_teste.id)]
        assert modo_teste["estado"] == "teste" and not modo_teste["conta"]  # só simula: não conta
        assert c["sem_numero"] == ["Capacidade Teste"]
        assert c["sem_conta"] == ["Capacidade Teste", "Capacidade Usa"]
        assert [(conta["nome"], conta["quem"]) for conta in c["contas"]] == [(dona.email, ["Capacidade Dona"])]
        assert c["ocupacao"]["marcados"] == 3 and c["ocupacao"]["cabem"] >= 9 * 64  # 10 dias de envio (hoje, o resto)
        assert c["ocupacao_email"]["marcados"] == 2
        db.rollback()


def test_limites_do_numero_e_mais_numeros(regras_da_plataforma, monkeypatch):
    with sessao() as db:
        ar = _marca(db)
        um = _pessoa(db, ar, "Capacidade Um", numero=True)
        dois = _pessoa(db, ar, "Capacidade Dois", numero=True, conta=False)
        desligado = _pessoa(db, ar, "Capacidade Desligado", numero=True, conta=False)
        _whatsapp(monkeypatch, {conexoes.id_do_usuario(um.id): "qr", conexoes.id_do_usuario(dois.id): "qr"})
        c = capacidade.da_marca(db, ar)
        # dois números de verdade: 16 + 16 pelo WhatsApp, mas o e-mail da marca segura em 20
        assert (c["numeros_de_verdade"], c["zap_dia"], c["whatsapp"], c["email"], c["empresas"]) == (2, 128, 32, 20, 20)
        numeros = {n["id"]: n for n in c["numeros"]}
        assert numeros[conexoes.id_do_usuario(desligado.id)]["estado"] == "desconectado"
        assert c["sem_numero"] == ["Capacidade Desligado"]

        usar_config_da_ar(db, ar)
        gravar_config(db, "limite_diario_whatsapp", "40")  # limite por dia de cada número: 40 ÷ 4 = 10
        usar_config_da_ar(db, None)
        c = capacidade.da_marca(db, ar)
        assert (c["zap_por_numero"], c["whatsapp"], c["empresas"]) == (40, 20, 20)
        gravar_config(db, "limite_frios_whatsapp", "20")  # contatos frios por número (da plataforma): 20 ÷ 4 = 5
        c = capacidade.da_marca(db, ar)
        assert (c["zap_por_numero"], c["whatsapp"], c["empresas"]) == (20, 10, 10)
        db.rollback()


def test_sem_numero_de_verdade_so_o_email_conta(regras_da_plataforma, monkeypatch):
    with sessao() as db:
        ar = _marca(db)
        _pessoa(db, ar, "Capacidade So Email")
        _whatsapp(monkeypatch, {})
        c = capacidade.da_marca(db, ar)
        assert (c["whatsapp"], c["email"], c["empresas"], c["mensagens_dia"], c["campanhas_minimas"]) == (0, 20, 20, 80, 2)
        assert c["sem_numero"] == ["Capacidade So Email"] and not c["whatsapp_fora"]
        from app.integracoes import whatsapp_leads

        monkeypatch.setattr(whatsapp_leads, "status", lambda usar_cache=True: {"disponivel": False, "erro": "desligado"})
        c = capacidade.da_marca(db, ar)
        assert c["whatsapp_fora"] and c["sem_numero"] == []  # sem notícia do WhatsApp Leads: não acusa ninguém
        db.rollback()


def test_marca_sem_email_cadastrado_nao_tem_o_quadro(regras_da_plataforma, monkeypatch):
    with sessao() as db:
        ar = _marca(db)
        pessoa = _pessoa(db, ar, "Capacidade Sem Email", numero=True, conta=False)
        _whatsapp(monkeypatch, {conexoes.id_do_usuario(pessoa.id): "qr"})
        assert capacidade.da_marca(db, ar) is None
        db.rollback()


def _entrar(email: str) -> TestClient:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def test_tela_campanhas_mostra_o_quadro_nas_marcas_com_email(cliente, regras_da_plataforma, monkeypatch):
    with sessao() as db:
        com_email, outra_com_email, sem_email = _marca(db, "Marca com e-mail"), _marca(db, "Outra marca"), _marca(db)
        dona = _pessoa(db, com_email, "Capacidade Tela Dona", numero=True)
        outra = _pessoa(db, outra_com_email, "Capacidade Tela Outra", numero=True)
        sem = _pessoa(db, sem_email, "Capacidade Tela Sem Email", numero=True, conta=False)
        nomes = {ar: db.get(Tenant, ar).nome for ar in (com_email, outra_com_email, sem_email)}
        emails = (dona.email, outra.email, sem.email)
        _whatsapp(monkeypatch, {conexoes.id_do_usuario(p.id): "qr" for p in (dona, outra, sem)})
    try:
        pagina = _entrar(emails[0]).get("/campanhas").text
        assert f'id="capacidade-{com_email}"' in pagina and "Quanto cabe por dia" in pagina
        assert "até <b>16 empresas novas por dia</b> (80 por semana)" in pagina
        assert "64 ÷ 4 toques = <b>16</b> empresas por dia" in pagina and "80 ÷ 4 toques = <b>20</b>" in pagina
        assert "pelo menos 3 campanhas em andamento" in pagina
        # white label: só a marca de quem vê, sem o nome dela no título nem nada da outra marca
        assert f'id="capacidade-{outra_com_email}"' not in pagina and "Capacidade Tela Outra" not in pagina
        assert nomes[com_email] not in pagina.split('id="capacidade-')[1].split("</summary>")[0]
        # marca sem conta de e-mail cadastrada: sem o quadro
        assert "Quanto cabe por dia" not in _entrar(emails[2]).get("/campanhas").text
        # o Admin Master vê o quadro de cada marca que tem e-mail, com o nome dela
        mestre = cliente.get("/campanhas").text
        assert f'id="capacidade-{com_email}"' in mestre and f'id="capacidade-{outra_com_email}"' in mestre
        assert f"Quanto cabe por dia · {nomes[com_email]}" in mestre
        assert f'id="capacidade-{sem_email}"' not in mestre
    finally:
        with motor.begin() as con:
            for ar in (com_email, outra_com_email, sem_email):
                apagar(con, ar)
        for ar in (com_email, outra_com_email, sem_email):
            marca.esquecer(ar)
        with sessao() as db:
            assert db.execute(select(Usuario.id).where(Usuario.email.in_(emails))).first() is None
