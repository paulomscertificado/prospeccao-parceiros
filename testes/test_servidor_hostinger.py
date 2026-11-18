"""Migração para o servidor da Hostinger (docs/migracao-hostinger.md, opção B do plano de 17/11/2026): as ferramentas
que rodam no computador da MS e no servidor, testadas aqui sem internet e sem servidor."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "servidor"


def _modulo(caminho: str, nome: str):
    spec = importlib.util.spec_from_file_location(nome, RAIZ / caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture()
def preparar():
    return _modulo("servidor/pc/preparar_migracao.py", "preparar_migracao")


def test_endereco_do_supabase_vai_para_o_modo_sessao(preparar):
    url = preparar.endereco_sessao(
        '"postgresql://postgres.abc:s%40nha@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?pgbouncer=true"')
    assert url == "postgresql://postgres.abc:s%40nha@aws-0-sa-east-1.pooler.supabase.com:5432/postgres?sslmode=require"
    assert preparar.endereco_sessao("postgresql+psycopg://u:p@h.com:6543/postgres").startswith("postgresql://u:p@h.com:5432/")
    with pytest.raises(ValueError):
        preparar.endereco_sessao("sqlite:///dados/banco.db")


def test_linhas_do_arquivo_de_configuracao_do_servidor(preparar):
    assert preparar.linha_de_ambiente("A", "abc-123_=/+") == "A=abc-123_=/+"
    assert preparar.linha_de_ambiente("B", "MS Certificados <a@b.com>") == "B='MS Certificados <a@b.com>'"
    assert preparar.linha_de_ambiente("C", "it's \"x\"") == 'C="it\'s \\"x\\""'


def _computador_de_mentira(raiz: Path, com_agendador: bool = True) -> None:
    dados = raiz / "dados"
    dados.mkdir()
    (dados / "chave_sessao.txt").write_text("sessao-123\n", encoding="utf-8")
    (dados / "chave_criptografia.txt").write_text("cripto-456=\n", encoding="utf-8")
    if com_agendador:
        (dados / "agendador.txt").write_text("# NAO compartilhar\nSITE=https://antigo.vercel.app\nCRON_SECRET=cron-789\n"
                                             "WHATSAPP_PONTE_TOKEN=ponte-000\n", encoding="utf-8")
    (dados / "supabase.txt").write_text("DATABASE_URL=postgresql://postgres.ref:segredo@pooler.supabase.com:6543/postgres\n",
                                        encoding="utf-8")
    (dados / "senha_backup.txt").write_text("senha-das-copias\n", encoding="utf-8")
    (raiz / ".env").write_text("IA_MODELO=claude-x\nANTHROPIC_API_KEY=nao-levar\nOSM_CONTATO=a@b.com\n", encoding="utf-8")


def test_configuracoes_saem_deste_computador_e_nao_levam_a_ia(preparar, tmp_path, monkeypatch):
    _computador_de_mentira(tmp_path)
    monkeypatch.setattr(preparar, "RAIZ", tmp_path)
    monkeypatch.setattr(preparar, "DADOS", tmp_path / "dados")
    valores, faltou = preparar.configuracoes("srv1.hstgr.cloud")
    assert faltou == []
    assert valores["SECRET_KEY"] == "sessao-123" and valores["CHAVE_CRIPTOGRAFIA"] == "cripto-456="
    assert valores["CRON_SECRET"] == "cron-789" and valores["WHATSAPP_PONTE_TOKEN"] == "ponte-000"
    assert valores["AMBIENTE"] == "producao" and valores["IA_MODELO"] == "claude-x" and valores["OSM_CONTATO"] == "a@b.com"
    assert "ANTHROPIC_API_KEY" not in valores  # a IA não está ligada na nuvem (decisão da Maria): não liga no servidor
    assert valores["URL_PUBLICA"] == "https://srv1.hstgr.cloud" and valores["MODO_NUVEM"] == "1"


def test_preparar_grava_os_arquivos_e_so_mostra_nomes(preparar, tmp_path, monkeypatch, capsys):
    _computador_de_mentira(tmp_path)
    monkeypatch.setattr(preparar, "RAIZ", tmp_path)
    monkeypatch.setattr(preparar, "DADOS", tmp_path / "dados")
    monkeypatch.setattr(preparar, "SAIDA", tmp_path / "dados" / "migracao")
    monkeypatch.setattr("sys.argv", ["preparar_migracao.py", "https://srv1.hstgr.cloud/"])
    assert preparar.main() == 0
    saida = tmp_path / "dados" / "migracao"
    base = (saida / "ambiente.base").read_text(encoding="utf-8")
    assert "SECRET_KEY=sessao-123" in base and "URL_PUBLICA=https://srv1.hstgr.cloud" in base and "\r" not in base
    assert "PROSPECCAO_TOKEN=ponte-000" in (saida / "wl_ambiente").read_text(encoding="utf-8")
    assert ":5432/postgres?sslmode=require" in (saida / "supabase_sessao.url").read_text(encoding="utf-8")
    assert (saida / "senha_backup.txt").read_text(encoding="utf-8").strip() == "senha-das-copias"
    mostrado = capsys.readouterr().out
    for segredo in ("sessao-123", "cripto-456", "cron-789", "ponte-000", "segredo", "senha-das-copias"):
        assert segredo not in mostrado


def test_preparar_para_se_faltar_chave(preparar, tmp_path, monkeypatch):
    _computador_de_mentira(tmp_path, com_agendador=False)
    monkeypatch.setattr(preparar, "RAIZ", tmp_path)
    monkeypatch.setattr(preparar, "DADOS", tmp_path / "dados")
    monkeypatch.setattr(preparar, "SAIDA", tmp_path / "dados" / "migracao")
    monkeypatch.setattr("sys.argv", ["preparar_migracao.py", "srv1.hstgr.cloud"])
    assert preparar.main() == 1
    assert not (tmp_path / "dados" / "migracao").exists()


def test_conferencia_das_contagens():
    conferir = _modulo("servidor/conferir_contagens.py", "conferir_contagens")
    assert conferir.comparar({"leads": 10, "tarefas": 5}, {"leads": 10, "tarefas": 5}) == []
    assert conferir.comparar({"leads": 10, "tarefas": 5}, {"leads": 9, "extra": 1}) == [
        "extra: só existe no destino", "leads: origem 10 x destino 9", "tarefas: falta no destino"]


def test_backup_acha_o_banco_do_servidor(monkeypatch, tmp_path):
    import fazer_backup

    monkeypatch.setattr(fazer_backup, "ARQUIVO_SUPABASE", tmp_path / "nao_existe.txt")
    monkeypatch.setenv("DATABASE_URL", "postgresql://prospeccao:x@127.0.0.1:5432/prospeccao")
    assert fazer_backup.endereco_da_nuvem() == "postgresql+psycopg://prospeccao:x@127.0.0.1:5432/prospeccao"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///dados/banco.db")  # o banco local nunca vira "banco da nuvem"
    assert fazer_backup.endereco_da_nuvem() == ""


def test_copias_baixadas_ficam_so_as_mais_novas(tmp_path):
    baixar = _modulo("servidor/pc/baixar_copias.py", "baixar_copias")
    for dia in range(1, 21):
        (tmp_path / f"nuvem_2026-11-{dia:02d}.db.cripto").write_text("x", encoding="utf-8")
    (tmp_path / "whatsapp_2026-11-01.db.cripto").write_text("x", encoding="utf-8")
    baixar.limpar(tmp_path, "nuvem_")
    restantes = sorted(a.name for a in tmp_path.glob("nuvem_*"))
    assert len(restantes) == baixar.FICAM and restantes[0] == "nuvem_2026-11-07.db.cripto"
    assert (tmp_path / "whatsapp_2026-11-01.db.cripto").exists()  # cada sistema limpa só as suas


def test_arquivos_do_servidor_com_fim_de_linha_do_linux_e_bash_valido():
    do_linux = [a for a in SERVIDOR.rglob("*") if a.is_file() and (
        a.suffix in (".sh", ".service", ".timer") or a.name.startswith("Caddyfile"))]
    assert len(do_linux) >= 14
    for arquivo in do_linux:
        assert b"\r\n" not in arquivo.read_bytes(), arquivo.name
    bash = next((b for b in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash") or "") if b and Path(b).is_file()), "")
    if not bash:
        pytest.skip("sem bash neste computador")
    for script in SERVIDOR.rglob("*.sh"):
        r = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True)
        assert r.returncode == 0, f"{script.name}: {r.stderr}"


def test_relogio_e_copias_do_servidor_apontam_para_o_lugar_certo():
    relogio = (SERVIDOR / "prospeccao-relogio.service").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8001/api/cron" in relogio and "Bearer ${CRON_SECRET}" in relogio and "%" not in relogio
    site = (SERVIDOR / "prospeccao.service").read_text(encoding="utf-8")
    assert "api.index:app" in site and "--host 127.0.0.1" in site and "--proxy-headers" in site
    assert "__DOMINIO__" in (SERVIDOR / "Caddyfile.modelo").read_text(encoding="utf-8")
    # endereços antigos levam para o novo (18/11/2026: srv2170631.hstgr.cloud -> sistema.mscertificados.com.br)
    assert "__REDIRECIONAMENTOS__" in (SERVIDOR / "Caddyfile.modelo").read_text(encoding="utf-8")
    assert "redir https://%s{uri} 307" in (SERVIDOR / "instalar_sistema.sh").read_text(encoding="utf-8")
    instalar = (SERVIDOR / "instalar_sistema.sh").read_text(encoding="utf-8")
    assert "enable --now prospeccao-relogio" not in instalar.replace("systemctl enable --now prospeccao-relogio.timer)", "")
    assert "MODO_NUVEM=1" in instalar and "PP_PASTA_DADOS" in instalar


def test_roteiros_sem_quebra_de_linha_escrita_por_engano():
    """Um "\n" escrito no lugar da quebra de linha passa no bash -n, mas vira um argumento "n" (17/11/2026)."""
    import re

    for script in SERVIDOR.rglob("*.sh"):
        for numero, linha in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
            assert not re.search(r"\n\s+--", linha), f"{script.name}:{numero}"
