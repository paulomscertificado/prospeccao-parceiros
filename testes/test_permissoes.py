"""Permissões em camadas: papéis, alcance (próprios/equipe/tudo), exceções PERMITIR/NEGAR, módulos e acesso indevido
trocando o número (ID) no endereço."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import autorizacao, config, dois_fatores
from app.banco import sessao
from app.leads_servico import criar_lead
from app.main import app
from app.modelos import (Campanha, Certificado, Cliente, Equipe, ExcecaoPermissao, Lead, Papel, Parceiro,
                         PermissaoPapel, Usuario)
from app.seguranca import resumir_senha
from conftest import csrf_de, ligar_modulos

SENHA = "senhaPerm123"


def _usuario(email, perfil, nome, **extra) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if not u:
            u = Usuario(nome=nome, email=email, perfil=perfil, senha_hash=resumir_senha(SENHA), **extra)
            db.add(u)
            db.flush()
        return u.id


def _entrar(email) -> TestClient:
    c = TestClient(app)
    pagina = c.get("/login")
    c.post("/login", data={"csrf": csrf_de(pagina.text), "email": email, "senha": SENHA})
    return c


def _csrf(c: TestClient) -> str:
    return csrf_de(c.get("/minha-conta").text)


def _excecao(uid, permissao, efeito, escopo="", ate=None):
    with sessao() as db:
        db.add(ExcecaoPermissao(usuario_id=uid, permissao=permissao, efeito=efeito, escopo=escopo, ate=ate))


def _limpar_excecoes(uid):
    from sqlalchemy import delete

    with sessao() as db:
        db.execute(delete(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == uid))


_CENARIO: dict = {}


def _cenario():
    """Duas vendedoras, cada uma com lead, parceiro, cliente, certificado e campanha próprios (criados uma vez só:
    outros testes escolhem a variação da mensagem pelo número do lead)."""
    if _CENARIO:
        return _CENARIO
    ana = _usuario("ana.perm@teste.com.br", "vendedor", "Ana Permissão")
    bia = _usuario("bia.perm@teste.com.br", "vendedor", "Bia Permissão")
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin")).scalars().first()
        ids = {}
        for nome, uid in (("ana", ana), ("bia", bia)):
            lead, _ = criar_lead(db, {"empresa": f"Contábil Permissão {nome}", "vendedor_id": uid}, admin,
                                 checar_duplicado=False)
            parc = Parceiro(escritorio=f"Escritório Permissão {nome}", vendedor_id=uid, status="ATIVO")
            db.add(parc)
            db.flush()
            cli = Cliente(nome=f"Cliente Permissão {nome}", parceiro_id=parc.id)
            db.add(cli)
            db.flush()
            cert = Certificado(cliente_id=cli.id, cliente_nome=f"Certificado Permissão {nome}", parceiro_id=parc.id,
                               data_vencimento=date.today() + timedelta(days=10))
            camp = Campanha(nome=f"Campanha Permissão {nome}", usuario_id=uid)
            db.add_all([cert, camp])
            db.flush()
            ids[nome] = {"usuario": uid, "lead": lead.id, "parceiro": parc.id, "cliente": cli.id, "cert": cert.id,
                         "camp": camp.id}
    _CENARIO.update(ids)
    return ids


# ---------------------------------------------------------------- Migração: ninguém ganha nem perde acesso

def test_papeis_do_sistema_tem_o_acesso_de_antes(cliente):
    with sessao() as db:
        papeis = {p.codigo: p for p in db.execute(select(Papel)).scalars()}
        assert set(autorizacao.PERFIS_BASE) <= set(papeis)

        def tem(codigo):
            return {r.permissao: r.escopo for r in db.execute(
                select(PermissaoPapel).where(PermissaoPapel.papel_id == papeis[codigo].id)).scalars()}

        admin, gestor, func, vend, parc = (tem(c) for c in autorizacao.PERFIS_BASE)
    assert len(admin) == len([p for p in autorizacao.CATALOGO if p.modulo != "portal"])
    assert set(admin.values()) == {"tudo"}
    assert gestor["leads.ver"] == "tudo" and "leads.atribuir" in gestor and "configuracoes.ver" not in gestor
    assert "vendas.excluir" not in gestor and "comissoes.pagar" not in gestor and "vencimentos.importar" in gestor
    assert func["leads.ver"] == "proprios" and "cadencias.editar" in func and "leads.atribuir" not in func
    assert vend["leads.ver"] == "proprios" and set(vend) < set(func)
    assert "cadencias.editar" not in vend and "categorias.ver" not in vend and "cadencias.ver" in vend
    assert set(parc) == {"portal.usar"}
    # rodar o preparo de novo não duplica nem desfaz nada
    with sessao() as db:
        antes = db.execute(select(PermissaoPapel.id)).all()
        autorizacao.preparar(db)
        assert db.execute(select(PermissaoPapel.id)).all() == antes


def test_toda_rota_da_equipe_confere_permissao():
    """Nenhuma tela fica sem porteiro: só login, descadastro, webhooks e a ponte (com senha própria) são abertos."""
    abertas = {"/login", "/login/ativar-codigo", "/login/codigo", "/primeiro-acesso", "/sair",
               "/descadastrar/{lead_id:int}/{assinatura}", "/api/saude", "/api/webhooks/whatsapp", "/api/cron",
               "/api/ponte/teste", "/api/ponte/troca", "/api/ponte/retorno", "/static"}
    sem_porteiro = []
    for rota in app.routes:
        caminho = getattr(rota, "path", "")
        if caminho in abertas or not hasattr(rota, "dependant"):
            continue
        nomes = set()

        def juntar(d):
            for sub in d.dependencies:
                nomes.add(getattr(sub.call, "__name__", ""))
                juntar(sub)

        juntar(rota.dependant)
        if not nomes & {"_checar", "usuario_logado"}:
            sem_porteiro.append(caminho)
    assert sem_porteiro == []


# ---------------------------------------------------------------- Trocar o ID no endereço

def test_vendedora_nao_abre_dados_da_outra_trocando_o_id(cliente):
    ids = _cenario()
    ana, bia = ids["ana"], ids["bia"]
    c = _entrar("ana.perm@teste.com.br")
    t = _csrf(c)
    # o que é dela abre
    assert c.get(f"/leads/{ana['lead']}").status_code == 200
    assert c.get(f"/parceiros/{ana['parceiro']}").status_code == 200
    # o da Bia não abre (404 = igual a "não existe")
    assert c.get(f"/leads/{bia['lead']}").status_code == 404
    assert c.get(f"/parceiros/{bia['parceiro']}").status_code == 404
    assert c.get(f"/campanhas/{bia['camp']}").status_code == 404
    assert c.get(f"/leads/{bia['lead']}/agendar").status_code == 404
    assert c.post(f"/leads/{bia['lead']}/nota", data={"csrf": t, "texto": "invasão"}).status_code == 404
    assert c.post(f"/leads/{bia['lead']}/agendar", data={"csrf": t, "responsavel_id": ana["usuario"],
                                                         "quando": "2030-01-02T10:00"}).status_code == 404
    # furos que existiam antes das permissões em camadas
    r = c.post(f"/clientes/{bia['cliente']}", data={"csrf": t, "nome": "Cliente Roubado"})
    assert r.status_code == 404
    r = c.post(f"/clientes/{ana['cliente']}", data={"csrf": t, "nome": "Cliente Permissão ana",
                                                    "parceiro_id": bia["parceiro"]}, follow_redirects=False)
    assert r.status_code == 303
    assert c.post(f"/vencimentos/{bia['cert']}/status", data={"csrf": t, "status": "Renovado"}).status_code == 404
    assert c.post("/vendas/nova", data={"csrf": t, "cliente_id": bia["cliente"], "valor": "100"}).status_code == 404
    assert c.post("/vendas/nova", data={"csrf": t, "cliente_nome": "Novo", "parceiro_id": bia["parceiro"],
                                        "valor": "100"}).status_code == 404
    with sessao() as db:
        assert db.get(Cliente, bia["cliente"]).nome == "Cliente Permissão bia"
        assert db.get(Cliente, ana["cliente"]).parceiro_id == ana["parceiro"]  # não foi para o parceiro da Bia
        assert db.get(Certificado, bia["cert"]).status == "Ativo"
    # listas e exportações só com o que é dela
    assert "Certificado Permissão bia" not in c.get("/exportar/vencimentos.csv").content.decode("utf-8")
    assert "Certificado Permissão ana" in c.get("/exportar/vencimentos.csv").content.decode("utf-8")
    assert "Contábil Permissão bia" not in c.get("/exportar/leads.csv").content.decode("utf-8")
    assert "Cliente Permissão bia" not in c.get("/vendas").text
    assert "Cliente Permissão bia" not in c.get("/clientes").text
    # ações de administrador
    assert c.get("/permissoes").status_code == 403
    assert c.get("/configuracoes").status_code == 403


# ---------------------------------------------------------------- Exceções por usuário

def test_excecao_negar_vence_o_papel_e_permitir_amplia(cliente):
    ids = _cenario()
    ana = ids["ana"]["usuario"]
    try:
        _excecao(ana, "leads.exportar", "negar")
        c = _entrar("ana.perm@teste.com.br")
        assert c.get("/exportar/leads.csv").status_code == 403
        assert c.get("/leads").status_code == 200  # o resto continua
        # PERMITIR com alcance "tudo": passa a ver o lead da Bia
        _excecao(ana, "leads.ver", "permitir", "tudo")
        assert c.get(f"/leads/{ids['bia']['lead']}").status_code == 200
        # NEGAR vence PERMITIR (e o papel)
        _excecao(ana, "leads.ver", "negar")
        assert c.get("/leads").status_code == 403
    finally:
        _limpar_excecoes(ana)
    _excecao(ana, "leads.ver", "negar", ate=date.today() - timedelta(days=1))  # vencida: não vale mais
    try:
        assert _entrar("ana.perm@teste.com.br").get("/leads").status_code == 200
    finally:
        _limpar_excecoes(ana)


def test_tela_de_excecao_valida_e_registra(cliente, csrf):
    ids = _cenario()
    ana = ids["ana"]["usuario"]
    r = cliente.post("/permissoes/excecao", data={"csrf": csrf, "usuario_id": ana, "permissao": "vendas.ver",
                                                  "efeito": "negar", "motivo": "teste"})
    assert r.status_code == 200 and "Exceção salva" in r.text
    assert "exceção NEGAR" in cliente.get(f"/permissoes?aba=usuarios&pessoa={ana}").text
    # ninguém tranca o sistema negando "mudar permissões"
    admin_id = _usuario("admin@teste.com.br", "admin", "Maria Admin")
    r = cliente.post("/permissoes/excecao", data={"csrf": csrf, "usuario_id": admin_id,
                                                  "permissao": "permissoes.gerenciar", "efeito": "negar"})
    assert "não pode ser negada" in r.text
    # parceiro nunca recebe permissão da equipe
    with sessao() as db:
        pid = db.execute(select(Parceiro.id)).scalars().first()
    parc = _usuario("parc.perm@teste.com.br", "parceiro", "Parceiro Permissão", parceiro_id=pid)
    r = cliente.post("/permissoes/excecao", data={"csrf": csrf, "usuario_id": parc, "permissao": "leads.ver",
                                                  "efeito": "permitir", "escopo": "tudo"})
    assert "não vale para este tipo de usuário" in r.text
    _excecao(parc, "leads.ver", "permitir", "tudo")  # mesmo gravada direto no banco, não vale
    try:
        assert _entrar("parc.perm@teste.com.br").get("/leads").status_code == 403
    finally:
        _limpar_excecoes(parc)
        _limpar_excecoes(ana)


def test_quem_recebe_poder_de_administrar_precisa_do_codigo_do_celular(cliente, monkeypatch):
    ana = _cenario()["ana"]["usuario"]
    monkeypatch.setattr(config, "EXIGIR_2FA", True)
    with sessao() as db:
        assert not dois_fatores.precisa(db.get(Usuario, ana))
    _excecao(ana, "usuarios.gerenciar", "permitir")
    try:
        with sessao() as db:
            assert dois_fatores.precisa(db.get(Usuario, ana))
    finally:
        _limpar_excecoes(ana)


# ---------------------------------------------------------------- Equipes e papéis novos

def test_papel_novo_com_alcance_da_equipe(cliente, csrf):
    ids = _cenario()
    with sessao() as db:
        equipe = Equipe(nome="Unidade Teste Permissões")
        db.add(equipe)
        db.flush()
        eid = equipe.id
    lider = _usuario("lider.perm@teste.com.br", "vendedor", "Líder Permissão")
    r = cliente.post("/permissoes/papel/novo", data={"csrf": csrf, "nome": "Líder de equipe", "copiar_de": "vendedor"})
    assert r.status_code == 200
    with sessao() as db:
        papel = db.execute(select(Papel).where(Papel.nome == "Líder de equipe")).scalars().first()
        assert papel.base == "vendedor" and not papel.sistema
        pid, codigo = papel.id, papel.codigo
    form = {f"p__{r_}": e for r_, e in [("painel.ver", "equipe"), ("leads.ver", "equipe"), ("leads.editar", "proprios")]}
    cliente.post(f"/permissoes/papel/{pid}", data={"csrf": csrf, **form})
    cliente.post(f"/configuracoes/usuarios/{lider}", data={"csrf": csrf, "nome": "Líder Permissão",
                                                          "email": "lider.perm@teste.com.br", "perfil": codigo,
                                                          "ativo": "on", "equipe_id": eid})
    with sessao() as db:
        db.get(Usuario, ids["ana"]["usuario"]).equipe_id = eid  # Ana na equipe; Bia fora
        u = db.get(Usuario, lider)
        assert u.papel_id == pid and u.perfil == "vendedor" and u.equipe_id == eid
    c = _entrar("lider.perm@teste.com.br")
    assert c.get(f"/leads/{ids['ana']['lead']}").status_code == 200   # da equipe
    assert c.get(f"/leads/{ids['bia']['lead']}").status_code == 404   # de fora
    assert c.get("/parceiros").status_code == 403                     # tirado do papel
    assert "Líder de equipe" in c.get("/leads").text
    # o papel Administrador não se altera
    with sessao() as db:
        adm = db.execute(select(Papel).where(Papel.codigo == "admin")).scalars().first().id
    r = cliente.post(f"/permissoes/papel/{adm}", data={"csrf": csrf})
    assert "sempre acesso a tudo" in r.text
    with sessao() as db:
        assert db.execute(select(PermissaoPapel).where(PermissaoPapel.papel_id == adm)).first() is not None


# ---------------------------------------------------------------- Módulos

def test_modulo_desligado_bloqueia_ate_o_administrador(cliente, csrf):
    assert cliente.get("/campanhas").status_code == 200
    ligar_modulos("campanhas", ligado=False)
    try:
        r = cliente.get("/campanhas")
        assert r.status_code == 403 and "desligada" in r.text
        assert 'href="/campanhas"' not in cliente.get("/").text
    finally:
        ligar_modulos("campanhas")
    # pela tela
    form = {"csrf": csrf, **{f"m__{m}": "on" for m in autorizacao.MODULOS if m != "ia_comercial"}}
    cliente.post("/permissoes/modulos", data=form)
    try:
        assert cliente.get("/ia").status_code == 403
        assert "módulo desligado" in cliente.get(
            f"/permissoes?aba=usuarios&pessoa={_usuario('admin@teste.com.br', 'admin', '')}").text
    finally:
        ligar_modulos("ia_comercial")
    assert cliente.get("/ia").status_code == 200


def test_tela_de_permissoes_abre_em_todas_as_abas(cliente):
    for aba in ("papeis", "usuarios", "equipes", "modulos"):
        assert cliente.get(f"/permissoes?aba={aba}").status_code == 200
    assert cliente.get("/permissoes?papel=vendedor").status_code == 200
    assert 'href="/permissoes"' in cliente.get("/").text
