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
