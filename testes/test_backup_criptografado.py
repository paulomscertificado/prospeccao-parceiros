"""Auditoria de 11/11/2026, P0.5: backup criptografado, conferido todo dia, com cópia fora do computador e aviso
na nuvem quando fica dias sem backup."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine

import fazer_backup
import restaurar_backup
from app import alertas, config
from app.banco import agora, gravar_config, ler_config_json, sessao


@pytest.fixture()
def pastas(tmp_path, monkeypatch):
    """Backup do banco de teste (no lugar da nuvem) em pastas temporárias."""
    monkeypatch.setattr(fazer_backup, "PASTA", tmp_path / "backups")
    monkeypatch.setattr(fazer_backup, "TENTATIVA", tmp_path / "backups" / "ultima_tentativa.txt")
    monkeypatch.setattr(fazer_backup, "ARQUIVO_SENHA", tmp_path / "senha_backup.txt")
    monkeypatch.setattr(restaurar_backup, "PASTA", tmp_path / "backups")
    monkeypatch.setattr(fazer_backup, "endereco_da_nuvem", lambda: config.DATABASE_URL)
    monkeypatch.setattr(fazer_backup, "motor_da_nuvem", lambda endereco: create_engine(endereco))
    monkeypatch.setattr(fazer_backup, "pasta_fora_do_pc", lambda: tmp_path / "Meu Drive" / fazer_backup.NOME_PASTA_FORA)
    return tmp_path


def test_backup_sai_criptografado_conferido_e_fora_do_pc(cliente, pastas):
    from app.modelos import Lead

    with sessao() as db:
        db.add(Lead(empresa="Backup Secreto Contabilidade Ltda"))
    r = fazer_backup.fazer(avisar=lambda _t: None)
    arquivo = pastas / "backups" / f"nuvem_{agora():%Y-%m-%d}.db.cripto"
    assert r["arquivo"] == str(arquivo) and r["conferido"] and r["leads"] > 0
    bruto = arquivo.read_bytes()
    assert bruto.startswith(fazer_backup.CABECALHO) and b"SQLite format" not in bruto
    assert b"Backup Secreto" not in bruto and b"Maria Admin" not in bruto  # ninguém lê sem a senha
    assert [p.name for p in (pastas / "backups").iterdir() if p.suffix in (".db", ".parcial")] == []  # nada aberto
    assert (pastas / "Meu Drive" / fazer_backup.NOME_PASTA_FORA / arquivo.name).read_bytes() == bruto
    assert "GUARDE UMA CÓPIA DELA FORA DESTE COMPUTADOR" in (pastas / "senha_backup.txt").read_text(encoding="utf-8")
    with sessao() as db:  # a nuvem ficou sabendo
        anotado = ler_config_json(db, "backup_ultimo", {})
        assert anotado["conferido"] and anotado["fora_do_pc"].endswith(fazer_backup.NOME_PASTA_FORA)

    # restaurar: com a senha certa volta tudo; com a errada não mexe em nada
    destino = create_engine(f"sqlite:///{(pastas / 'restaurado.db').as_posix()}")
    contagem = restaurar_backup.restaurar(arquivo, destino, avisar=lambda _t: None)
    assert contagem["leads"] == r["leads"] and contagem["usuarios"] > 0
    with pytest.raises(fazer_backup.SenhaErrada):
        restaurar_backup.restaurar(arquivo, destino, avisar=lambda _t: None, senha="senha-errada")
    assert not list((pastas / "backups").glob("restaurando_*"))  # a cópia aberta temporária foi apagada


def test_ficam_so_14_dias_contando_as_antigas_abertas(tmp_path):
    for dia in range(1, 21):
        nome = f"nuvem_2026-10-{dia:02d}.db" + ("" if dia <= 10 else fazer_backup.EXTENSAO)
        (tmp_path / nome).write_bytes(b"x")
    fazer_backup.apagar_antigos(tmp_path)
    restam = sorted(p.name for p in tmp_path.iterdir())
    assert len(restam) == 14 and restam[0] == "nuvem_2026-10-07.db" and restam[-1].endswith(".cripto")


def test_nuvem_avisa_quando_fica_dias_sem_backup(cliente, monkeypatch):
    monkeypatch.setattr(alertas.config, "ALERTAS_LIGADOS", True)
    with sessao() as db:
        gravar_config(db, "backup_ultimo", {"em": (agora() - timedelta(days=4)).isoformat(timespec="seconds")})
        assert "backup" in alertas.problemas_agora(db)
        gravar_config(db, "backup_ultimo", {"em": (agora() - timedelta(days=2)).isoformat(timespec="seconds")})
        assert "backup" not in alertas.problemas_agora(db)  # fim de semana sem backup não avisa
        gravar_config(db, "backup_ultimo", "")
