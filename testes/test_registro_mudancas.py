"""Plano de segurança: o registro de atividades guarda o módulo e o "antes e depois" das mudanças (seguranca.registrar_log,
`mudancas`), com e-mail e telefone mascarados, e a tela Configurações > Registro de atividades mostra os dois."""
import json

from sqlalchemy import select

from app.banco import ler_config, sessao
from app.modelos import LogAuditoria, Usuario
from app.seguranca import diferencas, resumir_senha
from conftest import SENHA


def _ultimo(acao: str) -> LogAuditoria:
    with sessao() as db:
        return db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao)
                          .order_by(LogAuditoria.id.desc())).scalars().first()


def test_diferencas_so_do_que_mudou():
    assert diferencas({"a": "1", "b": "2"}, {"a": "1", "b": "3", "c": ""}) == {"b": ["2", "3"]}


def test_configuracoes_gerais_guardam_o_antes_e_o_depois(cliente, csrf):
    with sessao() as db:
        antes = ler_config(db, "limite_diario_whatsapp")
    novo = "35" if antes != "35" else "36"
    cliente.post("/configuracoes/geral", data={"csrf": csrf, "limite_diario_whatsapp": novo})
    try:
        log = _ultimo("salvou_configuracoes")
        assert log.modulo == "Configurações"
        assert json.loads(log.mudancas) == {"limite_diario_whatsapp": [antes, novo]}
        pagina = cliente.get("/configuracoes?aba=logs").text
        assert "<b>limite_diario_whatsapp</b>: " + antes + " → " + novo in pagina
    finally:
        cliente.post("/configuracoes/geral", data={"csrf": csrf, "limite_diario_whatsapp": antes})


def test_cadastro_de_pessoa_guarda_o_antes_e_o_depois_mascarado(cliente, csrf):
    with sessao() as db:
        pessoa = Usuario(nome="Pessoa Registro", email="pessoa.registro@exemplo.com.br", perfil="vendedor",
                         senha_hash=resumir_senha(SENHA))
        db.add(pessoa)
        db.flush()
        pid = pessoa.id
    cliente.post(f"/configuracoes/usuarios/{pid}", data={"csrf": csrf, "nome": "Pessoa Registro Nova",
                                                         "email": "nova.registro@exemplo.com.br", "perfil": "vendedor",
                                                         "ativo": "on", "equipe_id": "manter"})
    log = _ultimo("salvou_usuario")
    assert log.modulo == "Usuários" and log.entidade_id == pid
    mudancas = json.loads(log.mudancas)
    assert mudancas["nome"] == ["Pessoa Registro", "Pessoa Registro Nova"]
    assert mudancas["email"] == ["pe***@exemplo.com.br", "no***@exemplo.com.br"]  # e-mail mascarado
