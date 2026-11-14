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


def test_le_o_endereco_do_arquivo(tmp_path):
    arquivo = tmp_path / "supabase_teste.txt"
    arquivo.write_text("# comentario\nDATABASE_URL=postgresql://u:s@h:6543/postgres\n", encoding="utf-8")
    assert bt.endereco_do_arquivo(arquivo) == "postgresql://u:s@h:6543/postgres"
    assert bt.endereco_do_arquivo(tmp_path / "nao_existe.txt") == ""


def test_avisa_quando_colam_o_direct_connection():
    assert bt.e_conexao_direta("postgresql://postgres:[YOUR-PASSWORD]@db.abcdefgh.supabase.co:5432/postgres")
    assert not bt.e_conexao_direta(
        "postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres")
