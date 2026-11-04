"""A tela Configurações não pode contar a base da Receita inteira a cada abertura (lenta no banco da nuvem)."""

from sqlalchemy import event

from app import base_receita
from app.banco import gravar_config, motor, sessao


def test_resumo_usa_o_total_gravado_sem_contar_a_tabela(cliente):
    with sessao() as db:
        gravar_config(db, "receita_total", "")
        base_receita.resumo(db)  # sem número gravado: conta uma vez e grava
        assert base_receita.ler_config(db, "receita_total") in ("", "0") or base_receita.ler_config(db, "receita_total").isdigit()

    contagens = []

    def anotar(conn, cursor, sql, params, context, executemany):
        if "count(" in sql.lower() and "base_receita" in sql.lower():
            contagens.append(sql)

    event.listen(motor, "before_cursor_execute", anotar)
    try:
        with sessao() as db:
            gravar_config(db, "receita_total", "120000")
            for _ in range(3):
                base_receita.resumo(db)
                base_receita.disponivel(db)
    finally:
        event.remove(motor, "before_cursor_execute", anotar)
    assert contagens == []


def test_tela_configuracoes_abre(cliente):
    for aba in ("geral", "integracoes", "email"):
        assert cliente.get(f"/configuracoes?aba={aba}").status_code == 200
