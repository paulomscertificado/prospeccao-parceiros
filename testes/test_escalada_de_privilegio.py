"""Ninguém abaixo de administrador vira administrador (pedido da Maria em 13/11/2026: "valide se os usuários abaixo de
admin conseguem subir de escala de privilégio e virar admin ou admin master").

Gestor, funcionário, vendedor e parceiro tentam, com o próprio login (como faria alguém mexendo nas requisições do
navegador), todos os caminhos que dão poder de administrador: virar admin, criar um admin, tomar a conta de um admin,
zerar o 2FA dele, dar a si mesmo permissões de administração, mexer nos papéis, nos módulos e nas equipes, e enfiar
"perfil=admin" num formulário comum. O resultado tem de ser sempre 403 e o banco não pode mudar."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import autorizacao
from app.banco import ler_config, sessao
from app.main import app
from app.modelos import Equipe, ExcecaoPermissao, Papel, Parceiro, PermissaoPapel, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import csrf_de

SENHA = "senhaEscalada123"
PODERES_DE_ADMIN = ("usuarios.gerenciar", "permissoes.gerenciar", "configuracoes.alterar", "configuracoes.ver")


def _usuario(email: str, perfil: str, nome: str, **extra) -> int:
    with sessao() as db:
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if u is None:
            u = Usuario(nome=nome, email=email, perfil=perfil, senha_hash=resumir_senha(SENHA), **extra)
            db.add(u)
            db.flush()
        return u.id


def _entrar(email: str) -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _foto() -> dict:
    """Tudo o que dá (ou mostra) poder de administrador, para comparar antes e depois das tentativas."""
    with sessao() as db:
        return {
            "usuarios": sorted((u.id, u.email, u.perfil, u.papel_id, u.ativo, u.senha_hash, u.versao_sessao,
                                u.totp_segredo, u.totp_ativo) for u in db.execute(select(Usuario)).scalars()),
            "papeis": sorted((p.id, p.codigo, p.nome, p.base) for p in db.execute(select(Papel)).scalars()),
            "permissoes": sorted((r.papel_id, r.permissao, r.escopo)
                                 for r in db.execute(select(PermissaoPapel)).scalars()),
            "excecoes": sorted((e.usuario_id, e.permissao, e.efeito)
                               for e in db.execute(select(ExcecaoPermissao)).scalars()),
            "equipes": sorted((e.id, e.nome) for e in db.execute(select(Equipe)).scalars()),
            "modulos": {m: ler_config(db, chave) for m, (_, chave) in autorizacao.MODULOS.items()},
        }


def _zerar_limite_de_pedidos():
    """As tentativas somam dezenas de pedidos: o limite por minuto (240) não pode atrapalhar os outros testes."""
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)


def test_ninguem_abaixo_de_admin_vira_admin(cliente, csrf):
    _zerar_limite_de_pedidos()
    try:
        _tentativas(cliente, csrf)
    finally:
        _zerar_limite_de_pedidos()


def _tentativas(cliente, csrf):
    with sessao() as db:
        admin = db.execute(select(Usuario).where(Usuario.perfil == "admin").order_by(Usuario.id)).scalars().first()
        parceiro = Parceiro(escritorio="Escritório Escalada", vendedor_id=admin.id, status="ATIVO")
        db.add(parceiro)
        db.flush()
        admin_id, parceiro_id = admin.id, parceiro.id
    pessoas = {
        "gestor": _usuario("gestor.escalada@teste.com.br", "gestor", "Gestor Escalada"),
        "funcionario": _usuario("func.escalada@teste.com.br", "funcionario", "Funcionário Escalada"),
        "vendedor": _usuario("vend.escalada@teste.com.br", "vendedor", "Vendedor Escalada"),
        "parceiro": _usuario("parc.escalada@teste.com.br", "parceiro", "Parceiro Escalada", parceiro_id=parceiro_id),
    }
    antes = _foto()
    for perfil, eu in pessoas.items():
        email = {"gestor": "gestor", "funcionario": "func", "vendedor": "vend", "parceiro": "parc"}[perfil]
        email = f"{email}.escalada@teste.com.br"
        with sessao() as db:
            u = db.get(Usuario, eu)
            assert not any(autorizacao.pode(u, p) for p in PODERES_DE_ADMIN), perfil
            meu_papel = db.execute(select(Papel).where(Papel.codigo == perfil)).scalars().one().id
        c = _entrar(email)
        assert c.get("/minha-conta").status_code == 200, f"{perfil} não conseguiu entrar"
        token = csrf_de(c.get("/minha-conta").text)
        forte = "SenhaForte!2026escalada"
        tentativas = [
            # virar admin editando o próprio cadastro
            (f"/configuracoes/usuarios/{eu}", {"nome": "Eu Admin", "email": email, "perfil": "admin", "ativo": "on"}),
            # criar um administrador novo com senha conhecida
            ("/configuracoes/usuarios/0", {"nome": "Admin Novo", "email": f"novo.{perfil}@escalada.com.br",
                                           "perfil": "admin", "ativo": "on", "senha": forte}),
            # tomar a conta do administrador (trocar e-mail e senha) e zerar o 2FA dele
            (f"/configuracoes/usuarios/{admin_id}", {"nome": "Admin", "email": f"tomada.{perfil}@escalada.com.br",
                                                     "perfil": "admin", "ativo": "on", "senha": forte}),
            (f"/configuracoes/usuarios/{admin_id}/zerar-2fa", {}),
            # dar a si mesmo as permissões de administração
            ("/permissoes/excecao", {"usuario_id": eu, "permissao": "usuarios.gerenciar", "efeito": "permitir"}),
            ("/permissoes/excecao", {"usuario_id": eu, "permissao": "permissoes.gerenciar", "efeito": "permitir"}),
            ("/permissoes/excecao", {"usuario_id": admin_id, "permissao": "usuarios.gerenciar", "efeito": "negar"}),
            # pôr as permissões de administração no próprio papel, criar um papel novo, mexer em módulos e equipes
            (f"/permissoes/papel/{meu_papel}", {f"p__{p}": "tudo" for p in PODERES_DE_ADMIN}),
            ("/permissoes/papel/novo", {"nome": "Super Escalada", "copiar_de": "gestor"}),
            ("/permissoes/modulos", {f"m__{m}": "on" for m in autorizacao.MODULOS}),
            ("/permissoes/equipes/0", {"nome": "Equipe Escalada"}),
            # mexer nas configurações gerais
            ("/configuracoes/geral", {"limite_frios_whatsapp": "999"}),
        ]
        for caminho, dados in tentativas:
            r = c.post(caminho, data={"csrf": token, **dados}, follow_redirects=False)
            assert r.status_code == 403, (perfil, caminho, r.status_code)
            # recusado por falta de permissão (e não por formulário vencido ou limite de pedidos)
            assert "não tem permissão" in r.text, (perfil, caminho, r.text[-400:])
        for tela in ("/configuracoes", "/permissoes", "/configuracoes?aba=usuarios"):
            assert c.get(tela, follow_redirects=False).status_code == 403, (perfil, tela)
        # "perfil=admin" enfiado num formulário que a pessoa pode usar não muda nada além do que ele salva
        c.post("/minha-conta/empresa", data={"csrf": token, "nome": "Minha Empresa", "perfil": "admin",
                                             "papel_id": "1", "ativo": "on", "versao_sessao": "99"})
    depois = _foto()
    for chave in antes:
        assert depois[chave] == antes[chave], f"mudou: {chave}"
    with sessao() as db:
        for perfil, eu in pessoas.items():
            u = db.get(Usuario, eu)
            assert u.perfil == perfil and u.papel_id is None
            assert not any(autorizacao.pode(u, p) for p in PODERES_DE_ADMIN), perfil
    # controle: o mesmo tipo de pedido, feito pelo administrador, funciona (as recusas acima são de permissão)
    r = cliente.post("/permissoes/equipes/0", data={"csrf": csrf, "nome": "Equipe Controle Escalada"},
                     follow_redirects=False)
    assert r.status_code == 303
    with sessao() as db:
        equipe = db.execute(select(Equipe).where(Equipe.nome == "Equipe Controle Escalada")).scalars().one()
        db.delete(equipe)


# ---------------------------------------------------------------- Correções de 13/11/2026 ("Sim, corrigir")

def _post(c: TestClient, caminho: str, dados: dict, token: str):
    return c.post(caminho, data={"csrf": token, **dados})


def test_admin_comum_nao_toma_a_conta_do_master_nem_cria_admin(cliente, csrf):
    """Risco 1: todo administrador era igual e um podia tomar a conta do outro (inclusive do Paulo Marinho). Agora o
    admin master só é alterado por ele mesmo, e só ele cria ou promove administradores e dá poderes de administração."""
    _zerar_limite_de_pedidos()
    try:
        with sessao() as db:
            master = db.execute(select(Usuario).where(Usuario.email == "admin@teste.com.br")).scalars().one()
            assert master.master and autorizacao.e_master(master)  # quem criou o sistema (primeiro acesso)
            master_id = master.id
            gestor_papel = db.execute(select(Papel).where(Papel.codigo == "gestor")).scalars().one().id
        comum = _usuario("admin.comum@teste.com.br", "admin", "Admin Comum")
        outro = _usuario("admin.outro@teste.com.br", "admin", "Admin Outro")
        alvo = _usuario("vend.alvo@teste.com.br", "vendedor", "Vendedor Alvo")
        antes = _foto()
        c = _entrar("admin.comum@teste.com.br")
        token = csrf_de(c.get("/minha-conta").text)
        forte = "SenhaForte!2026tomada"
        r = _post(c, f"/configuracoes/usuarios/{master_id}", {"nome": "Maria Admin", "email": "tomada@teste.com.br",
                                                              "perfil": "admin", "ativo": "on", "senha": forte}, token)
        assert "Só o próprio admin master" in r.text
        _post(c, f"/configuracoes/usuarios/{master_id}/zerar-2fa", {}, token)
        _post(c, f"/configuracoes/usuarios/{master_id}", {"nome": "Maria Admin", "email": "admin@teste.com.br",
                                                          "perfil": "vendedor", "ativo": ""}, token)
        r = _post(c, f"/configuracoes/usuarios/{outro}", {"nome": "Admin Outro", "email": "admin.outro@teste.com.br",
                                                          "perfil": "admin", "ativo": "on", "senha": forte}, token)
        assert "Só o admin master altera" in r.text
        _post(c, f"/configuracoes/usuarios/{outro}/zerar-2fa", {}, token)
        r = _post(c, "/configuracoes/usuarios/0", {"nome": "Admin Novo", "email": "admin.novo@escalada.com.br",
                                                   "perfil": "admin", "ativo": "on", "senha": forte}, token)
        assert "Só o admin master dá o papel de administrador" in r.text
        _post(c, f"/configuracoes/usuarios/{alvo}", {"nome": "Vendedor Alvo", "email": "vend.alvo@teste.com.br",
                                                     "perfil": "admin", "ativo": "on"}, token)
        _post(c, f"/configuracoes/usuarios/{comum}", {"nome": "Admin Comum", "email": "admin.comum@teste.com.br",
                                                      "perfil": "admin", "ativo": ""}, token)  # desativar a si mesmo
        r = _post(c, "/permissoes/excecao", {"usuario_id": alvo, "permissao": "usuarios.gerenciar",
                                             "efeito": "permitir"}, token)
        assert "Só o admin master dá poderes de administração" in r.text
        _post(c, "/permissoes/excecao", {"usuario_id": master_id, "permissao": "leads.ver", "efeito": "negar"}, token)
        _post(c, "/permissoes/excecao", {"usuario_id": comum, "permissao": "leads.ver", "efeito": "negar"}, token)
        r = _post(c, f"/permissoes/papel/{gestor_papel}", {f"p__{p}": "tudo" for p in PODERES_DE_ADMIN}, token)
        assert "Só o admin master põe poderes de administração" in r.text
        assert _foto() == antes  # nada mudou
        # o que é dele continua podendo: cuidar de quem não é administrador
        r = _post(c, f"/configuracoes/usuarios/{alvo}", {"nome": "Vendedor Alvo Editado",
                                                         "email": "vend.alvo@teste.com.br", "perfil": "vendedor",
                                                         "ativo": "on"}, token)
        assert "Usuário salvo" in r.text
        # e o admin master pode promover (controle); depois volta como estava
        r = cliente.post(f"/configuracoes/usuarios/{alvo}", data={"csrf": csrf, "nome": "Vendedor Alvo",
                                                                  "email": "vend.alvo@teste.com.br", "perfil": "admin",
                                                                  "ativo": "on"})
        assert "Usuário salvo" in r.text
        with sessao() as db:
            u = db.get(Usuario, alvo)
            assert u.perfil == "admin"
            u.perfil, u.ativo = "vendedor", False
            for i in (comum, outro):
                db.get(Usuario, i).ativo = False
    finally:
        _zerar_limite_de_pedidos()


def test_quem_recebe_gerenciar_usuarios_nao_se_promove(cliente):
    """Risco 2: um gestor que ganhou "Criar e editar usuários" podia se promover a administrador. Agora ninguém muda o
    próprio papel, e só o admin master dá o papel de administrador."""
    _zerar_limite_de_pedidos()
    try:
        gid = _usuario("gestor.delegado@teste.com.br", "gestor", "Gestor Delegado")
        with sessao() as db:
            db.add(ExcecaoPermissao(usuario_id=gid, permissao="usuarios.gerenciar", efeito="permitir"))
            master_id = db.execute(select(Usuario.id).where(Usuario.email == "admin@teste.com.br")).scalar()
        antes = _foto()
        c = _entrar("gestor.delegado@teste.com.br")
        token = csrf_de(c.get("/minha-conta").text)
        for caminho, dados in [
            (f"/configuracoes/usuarios/{gid}", {"nome": "Gestor Delegado", "email": "gestor.delegado@teste.com.br",
                                                "perfil": "admin", "ativo": "on"}),
            ("/configuracoes/usuarios/0", {"nome": "Admin do Gestor", "email": "admin.do.gestor@escalada.com.br",
                                           "perfil": "admin", "ativo": "on", "senha": "SenhaForte!2026gestor"}),
            (f"/configuracoes/usuarios/{master_id}", {"nome": "Maria Admin", "email": "tomada2@teste.com.br",
                                                      "perfil": "admin", "ativo": "on"}),
            (f"/configuracoes/usuarios/{master_id}/zerar-2fa", {}),
        ]:
            _post(c, caminho, dados, token)
        assert _foto() == antes
        # a delegação legítima continua: criar um vendedor
        _post(c, "/configuracoes/usuarios/0", {"nome": "Vendedor do Gestor", "email": "vend.do.gestor@escalada.com.br",
                                               "perfil": "vendedor", "ativo": "on", "senha": "SenhaForte!2026vend"},
              token)
        with sessao() as db:
            novo = db.execute(select(Usuario).where(Usuario.email == "vend.do.gestor@escalada.com.br")).scalars().one()
            assert novo.perfil == "vendedor"
            novo.ativo = False
            for e in db.execute(select(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == gid)).scalars():
                db.delete(e)
    finally:
        _zerar_limite_de_pedidos()


def test_quem_compartilha_nao_se_inclui(cliente):
    """Risco 3: o gestor ("compartilhar o WhatsApp de qualquer pessoa") se punha no número de um administrador, via as
    conversas e disparava por ele. Agora quem não é o dono não se inclui, não libera para toda a equipe e não mexe no
    WhatsApp/e-mail de administradores; compartilhar entre as outras pessoas continua."""
    import json

    from app import conexoes, contas_email
    from app.modelos import ConexaoWhatsApp, ContaEmail

    _zerar_limite_de_pedidos()
    try:
        gid = _usuario("gestor.zap@teste.com.br", "gestor", "Gestor Zap")
        aid = _usuario("admin.zap@teste.com.br", "admin", "Admin Zap")
        fid = _usuario("func.zap@teste.com.br", "funcionario", "Funcionário Zap")
        vid = _usuario("vend.zap@teste.com.br", "vendedor", "Vendedor Zap")
        with sessao() as db:
            for dono in (aid, fid):
                if db.get(ConexaoWhatsApp, f"u{dono}") is None:
                    db.add(ConexaoWhatsApp(id=f"u{dono}", nome=f"WhatsApp {dono}", dono_id=dono))
            conta = ContaEmail(dono_id=fid, nome="E-mail do funcionário", endereco="func.zap@mscertificados.com.br")
            db.add(conta)
            db.flush()
            conta_id = conta.id
        c = _entrar("gestor.zap@teste.com.br")
        token = csrf_de(c.get("/minha-conta").text)
        _post(c, "/whatsapp/compartilhar", {"numero": f"u{aid}", "usuarios": [str(gid)]}, token)  # admin: se incluir
        _post(c, "/whatsapp/compartilhar", {"numero": f"u{aid}", "usuarios": [str(vid)]}, token)  # admin: com outro
        _post(c, "/whatsapp/compartilhar", {"numero": f"u{fid}", "usuarios": [str(gid)]}, token)  # se incluir
        _post(c, "/whatsapp/compartilhar", {"numero": f"u{fid}", "todos": "on"}, token)          # toda a equipe
        _post(c, "/email/compartilhar", {"conta": conta_id, "usuarios": [str(gid)]}, token)
        with sessao() as db:
            gestor = db.get(Usuario, gid)
            for numero in (f"u{aid}", f"u{fid}"):
                n = db.get(ConexaoWhatsApp, numero)
                assert not n.compartilhada_todos and json.loads(n.compartilhada_com or "[]") == [], numero
                assert not conexoes.pode_disparar(gestor, n)
            assert contas_email.compartilhada_com(db.get(ContaEmail, conta_id)) == []
        # entre as outras pessoas continua: o gestor compartilha o número do funcionário com o vendedor
        _post(c, "/whatsapp/compartilhar", {"numero": f"u{fid}", "usuarios": [str(vid)]}, token)
        with sessao() as db:
            assert json.loads(db.get(ConexaoWhatsApp, f"u{fid}").compartilhada_com) == [vid]
            for numero in (f"u{aid}", f"u{fid}"):
                db.delete(db.get(ConexaoWhatsApp, numero))
            db.delete(db.get(ContaEmail, conta_id))
    finally:
        _zerar_limite_de_pedidos()
