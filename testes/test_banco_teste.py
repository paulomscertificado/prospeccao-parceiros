"""Banco de TESTE (salvar_banco_teste.py / copiar_para_teste.py): nunca pode ser confundido com o da nuvem."""
import salvar_banco_teste as bt


def test_senha_entra_no_lugar_da_marca_e_com_escape():
    modelo = "postgresql://postgres.abc:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    assert bt.montar(f' "{modelo}" ', "s3nh@ #1") == modelo.replace("[YOUR-PASSWORD]", "s3nh%40%20%231")
    assert bt.montar("postgresql://u:pronta@h:6543/postgres", "ignorada") == "postgresql://u:pronta@h:6543/postgres"


def test_reconhece_o_mesmo_banco_mesmo_com_outra_senha():
    nuvem = "postgresql://postgres.abc:senha1@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    assert bt.mesmo_banco(nuvem.replace("senha1", "outra"), nuvem)
    assert bt.mesmo_banco("postgresql+psycopg://" + nuvem.split("://")[1], nuvem)
    assert not bt.mesmo_banco(nuvem.replace("postgres.abc", "postgres.xyz"), nuvem)
    assert not bt.mesmo_banco("", nuvem)
    # o mesmo projeto pelo Session pooler (5432), pelo Transaction pooler (6543) ou pela conexão direta
    assert bt.mesmo_banco(nuvem.replace(":6543", ":5432"), nuvem)
    assert bt.mesmo_banco("postgresql://postgres:[YOUR-PASSWORD]@db.abc.supabase.co:5432/postgres", nuvem)
    assert bt.mesmo_banco(nuvem.replace("aws-0-us-east-1", "aws-1-us-east-1"), nuvem)


def test_le_o_endereco_do_arquivo(tmp_path):
    arquivo = tmp_path / "supabase_teste.txt"
    arquivo.write_text("# comentario\nDATABASE_URL=postgresql://u:s@h:6543/postgres\n", encoding="utf-8")
    assert bt.endereco_do_arquivo(arquivo) == "postgresql://u:s@h:6543/postgres"
    assert bt.endereco_do_arquivo(tmp_path / "nao_existe.txt") == ""


def test_avisa_quando_colam_o_direct_connection():
    assert bt.e_conexao_direta("postgresql://postgres:[YOUR-PASSWORD]@db.abcdefgh.supabase.co:5432/postgres")
    assert not bt.e_conexao_direta(
        "postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres")


def test_esvaziar_um_banco_novo_sem_tabelas_nao_da_erro(tmp_path):
    """A primeira cópia para o banco de teste: ele ainda não tem tabelas (antes dava erro no TRUNCATE vazio)."""
    from sqlalchemy import create_engine

    from enviar_para_nuvem import esvaziar

    esvaziar(create_engine(f"sqlite:///{(tmp_path / 'novo.db').as_posix()}"))


def test_restaurar_pede_de_novo_as_conversas_que_faltam(tmp_path):
    """As conversas do WhatsApp não vão no backup: depois de restaurar, o marcador volta para a maior mensagem que
    ficou no banco e o WhatsApp Leads manda de novo o que faltar."""
    from sqlalchemy import create_engine, text

    import restaurar_backup
    from app import modelos  # noqa: F401  (registra as tabelas)
    from app.banco import Base
    from fazer_backup import FORA_DO_BACKUP

    assert "mensagens_whatsapp" in FORA_DO_BACKUP
    motor = create_engine(f"sqlite:///{(tmp_path / 'restaurado.db').as_posix()}")
    Base.metadata.create_all(motor)
    with motor.begin() as c:
        c.execute(text("INSERT INTO configuracoes (chave, valor) VALUES ('wl_conv_ultimo_id', '5000')"))
        c.execute(text("INSERT INTO mensagens_whatsapp (id_wl, telefone, conexao, nome, direcao, texto, status, erro, "
                       "origem, lida, criado_em) VALUES (1200, '81999990000', 'principal', '', 'entrada', 'oi', '', "
                       "'', '', 0, '2026-11-14 10:00:00')"))
    restaurar_backup._reabrir_conversas(motor)
    with motor.connect() as c:
        assert c.execute(text("SELECT valor FROM configuracoes WHERE chave = 'wl_conv_ultimo_id'")).scalar() == "1200"


def test_leitura_de_emails_pergunta_so_pelos_remetentes(cliente):
    from app.leads_servico import criar_lead
    from app.banco import sessao
    from app.rotinas import _EmailsDeLeads

    with sessao() as db:
        criar_lead(db, {"empresa": "Remetente Conhecido Ltda", "email": "contato@remetente-conhecido.com.br"}, None)
    emails = _EmailsDeLeads()
    assert "Contato@Remetente-Conhecido.com.br" in emails
    assert "ninguem@nao-e-lead.com.br" not in emails and "" not in emails
