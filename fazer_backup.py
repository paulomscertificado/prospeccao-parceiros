"""Cópia de segurança do banco da NUVEM (Supabase), criptografada, neste computador e fora dele.

O Supabase grátis não tem backup. Este script copia tudo (leads, histórico, campanhas, parceiros, vendas,
usuários, configurações), menos a base da Receita (que se importa de novo dos .zip), e grava a cópia
CRIPTOGRAFADA (AES-256, compactada) em dados/backups/nuvem_AAAA-MM-DD.db.cripto. Guarda os últimos 14 dias.

Auditoria de 11/11/2026 (P0.5): antes eram 14 cópias abertas no mesmo computador. Agora:
- a senha fica em dados/senha_backup.txt (criada na primeira vez). GUARDE UMA CÓPIA DELA FORA DO COMPUTADOR:
  sem ela, nenhuma cópia abre;
- cada cópia é aberta e conferida logo depois de feita (dá para restaurar);
- uma cópia vai para fora do computador: a pasta BACKUP_PASTA_FORA do .env ou, se o Google Drive para computador
  estiver instalado, "G:\\Meu Drive\\Backups Prospeccao MS" (o Google Drive sobe sozinho para a nuvem);
- o sistema da nuvem fica sabendo do último backup e avisa por e-mail se ficar mais de 3 dias sem.

Uso: dois cliques em fazer_backup.bat. O agendador do Windows (dados/chamar_cron.ps1) também roda sozinho,
1 vez por dia, com --automatico (sem perguntas). Para voltar uma cópia: restaurar_backup.bat.
"""

import os
import secrets
import shutil
import sqlite3
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import config
from enviar_para_nuvem import copiar, endereco_postgres

PASTA = config.PASTA_DADOS / "backups"
ARQUIVO_SUPABASE = config.PASTA_DADOS / "supabase.txt"
ARQUIVO_SENHA = config.PASTA_DADOS / "senha_backup.txt"
TENTATIVA = PASTA / "ultima_tentativa.txt"
FICAM = 14  # dias guardados (aqui e fora do computador)
# base: grande e reimportável; artes: imagens de poucos dias; conversas do WhatsApp: são cópia das do WhatsApp Leads
# (que tem o próprio backup) e eram 3/4 do tráfego do backup no Supabase grátis (14/11/2026). Ao restaurar, o
# WhatsApp Leads manda de novo o que faltar (restaurar_backup._reabrir_conversas).
FORA_DO_BACKUP = {"base_receita", "artes_aviso", "mensagens_whatsapp"}
EXTENSAO = ".cripto"
CABECALHO = b"MS-BACKUP-1\n"
NOME_PASTA_FORA = "Backups Prospeccao MS"


class SenhaErrada(Exception):
    pass


# ---------------------------------------------------------------- Banco da nuvem

def endereco_da_nuvem() -> str:
    try:
        for linha in ARQUIVO_SUPABASE.read_text(encoding="utf-8-sig").splitlines():
            if linha.startswith("DATABASE_URL="):
                return endereco_postgres(linha.split("=", 1)[1])
    except OSError:
        pass
    return ""


def motor_da_nuvem(endereco: str):
    return create_engine(endereco, pool_pre_ping=True, connect_args={"prepare_threshold": None})


# ---------------------------------------------------------------- Criptografia

def senha_do_backup(criar: bool = True) -> str:
    """A senha das cópias (dados/senha_backup.txt). Na primeira vez cria uma senha forte."""
    try:
        for linha in ARQUIVO_SENHA.read_text(encoding="utf-8-sig").splitlines():
            if linha.strip() and not linha.lstrip().startswith("#"):
                return linha.strip()
    except OSError:
        pass
    if not criar:
        return ""
    senha = secrets.token_urlsafe(24)
    ARQUIVO_SENHA.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_SENHA.write_text(
        f"{senha}\n\n"
        "# Esta é a senha das cópias de segurança (backups) do sistema de Prospecção da MS.\n"
        "# GUARDE UMA CÓPIA DELA FORA DESTE COMPUTADOR (gerenciador de senhas, cofre ou papel guardado).\n"
        "# Sem ela, nenhuma cópia abre. Não mande esta senha por e-mail nem WhatsApp.\n", encoding="utf-8")
    return senha


def _chave(senha: str, sal: bytes) -> bytes:
    return Scrypt(salt=sal, length=32, n=2 ** 15, r=8, p=1).derive(senha.encode("utf-8"))


def criptografar(origem: Path, destino: Path, senha: str) -> None:
    """Compacta e criptografa (AES-256-GCM, chave derivada da senha com scrypt)."""
    sal, nonce = os.urandom(16), os.urandom(12)
    cifrado = AESGCM(_chave(senha, sal)).encrypt(nonce, zlib.compress(origem.read_bytes(), 6), CABECALHO)
    parcial = destino.with_name(destino.name + ".parcial")
    parcial.write_bytes(CABECALHO + sal + nonce + cifrado)
    parcial.replace(destino)


def descriptografar(origem: Path, destino: Path, senha: str) -> None:
    bruto = origem.read_bytes()
    if not bruto.startswith(CABECALHO):
        raise ValueError(f"{origem.name} não é uma cópia de segurança criptografada da Prospecção.")
    inicio = len(CABECALHO)
    sal, nonce, cifrado = bruto[inicio:inicio + 16], bruto[inicio + 16:inicio + 28], bruto[inicio + 28:]
    try:
        dados = AESGCM(_chave(senha, sal)).decrypt(nonce, cifrado, CABECALHO)
    except InvalidTag:
        raise SenhaErrada("A senha não abre esta cópia (senha errada ou arquivo estragado).") from None
    destino.write_bytes(zlib.decompress(dados))


def conferir(arquivo_db: Path) -> dict:
    """Abre a cópia (só leitura) e confere: arquivo íntegro e quantos leads e usuários tem."""
    con = sqlite3.connect(f"file:{arquivo_db.as_posix()}?mode=ro", uri=True)
    try:
        ok = con.execute("pragma integrity_check").fetchone()[0] == "ok"
        leads = con.execute("select count(*) from leads").fetchone()[0]
        usuarios = con.execute("select count(*) from usuarios").fetchone()[0]
    finally:
        con.close()
    return {"ok": ok and usuarios > 0, "leads": leads, "usuarios": usuarios}


# ---------------------------------------------------------------- Onde as cópias ficam

def pasta_fora_do_pc() -> Path | None:
    """A pasta fora do computador: BACKUP_PASTA_FORA no .env ou o Google Drive para computador ("Meu Drive"),
    se estiver instalado. None = só neste computador."""
    escolhida = os.environ.get("BACKUP_PASTA_FORA", "").strip().strip('"')
    if escolhida:
        return Path(escolhida)
    for letra in "GHIJKLMNOPQRSTUVWXYZ":
        for nome in ("Meu Drive", "My Drive"):
            drive = Path(f"{letra}:/{nome}")
            if drive.is_dir():
                return drive / NOME_PASTA_FORA
    return None


def copias(pasta: Path) -> list[Path]:
    """As cópias da pasta (criptografadas e as antigas abertas), da mais nova para a mais antiga."""
    if not pasta.is_dir():
        return []
    achadas = list(pasta.glob("nuvem_*.db")) + list(pasta.glob(f"nuvem_*.db{EXTENSAO}"))
    return sorted(achadas, key=lambda a: (a.name[6:16], a.suffix == EXTENSAO), reverse=True)


def apagar_antigos(pasta: Path = PASTA) -> None:
    """Fica com as cópias dos últimos FICAM dias (as abertas antigas saem junto, com o tempo)."""
    por_dia: dict[str, list[Path]] = {}
    for arquivo in copias(pasta):
        por_dia.setdefault(arquivo.name[6:16], []).append(arquivo)
    for dia in sorted(por_dia)[:-FICAM]:
        for arquivo in por_dia[dia]:
            arquivo.unlink(missing_ok=True)


def anotar_na_nuvem(endereco: str, info: dict) -> None:
    """Conta ao sistema da nuvem que o backup foi feito (ele avisa por e-mail se ficar dias sem)."""
    from app.banco import gravar_config

    motor = motor_da_nuvem(endereco)
    try:
        with Session(motor) as s:
            gravar_config(s, "backup_ultimo", info)
            s.commit()
    finally:
        motor.dispose()


# ---------------------------------------------------------------- Fazer

def fazer(avisar=print) -> dict:
    """Faz a cópia de hoje (criptografada e conferida), põe uma cópia fora do computador e devolve o resumo."""
    endereco = endereco_da_nuvem()
    if not endereco:
        raise RuntimeError(f"Não encontrei o endereço do banco da nuvem em {ARQUIVO_SUPABASE}.")
    PASTA.mkdir(parents=True, exist_ok=True)
    TENTATIVA.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    senha = senha_do_backup()
    dia = f"{datetime.now():%Y-%m-%d}"
    aberta = PASTA / f"nuvem_{dia}.db.parcial"
    conferindo = PASTA / f"conferindo_{dia}.db"
    final = PASTA / f"nuvem_{dia}.db{EXTENSAO}"
    aberta.unlink(missing_ok=True)
    destino = create_engine(f"sqlite:///{aberta.as_posix()}")
    try:
        copiar(motor_da_nuvem(endereco), destino, avisar=avisar, pular=FORA_DO_BACKUP)
    finally:
        destino.dispose()
    try:
        criptografar(aberta, final, senha)
        descriptografar(final, conferindo, senha)  # a cópia abre? (teste de restauração de todo dia)
        resultado = conferir(conferindo)
    finally:
        aberta.unlink(missing_ok=True)  # nada fica aberto no computador
        conferindo.unlink(missing_ok=True)
    if not resultado["ok"]:
        raise RuntimeError("A cópia foi feita, mas não passou na conferência. Avise quem cuida do sistema.")
    apagar_antigos(PASTA)
    fora, erro_fora = pasta_fora_do_pc(), ""
    if fora is not None:
        try:
            fora.mkdir(parents=True, exist_ok=True)
            shutil.copy2(final, fora / final.name)
            apagar_antigos(fora)
        except OSError as erro:
            erro_fora, fora = str(erro)[:200], None
    info = {"em": datetime.now().isoformat(timespec="seconds"), "tamanho_mb": round(final.stat().st_size / 1e6, 1),
            "leads": resultado["leads"], "conferido": True, "fora_do_pc": str(fora) if fora else "",
            "erro_fora": erro_fora}
    try:
        anotar_na_nuvem(endereco, info)
    except Exception as erro:  # noqa: BLE001 - o backup já está feito; só não avisou a nuvem
        info["erro_nuvem"] = str(erro).splitlines()[0][:200]
    return {**info, "arquivo": str(final)}


def main() -> int:
    automatico = "--automatico" in sys.argv
    if not automatico:
        print("Cópia de segurança do banco da nuvem (criptografada, sem a base da Receita)\n")
    inicio = time.time()
    try:
        r = fazer(avisar=(lambda _texto: None) if automatico else print)
    except Exception as erro:  # noqa: BLE001
        print(f"Não deu certo: {str(erro).splitlines()[0][:300]}")
        print("Confira a internet. Se continuar, avise quem cuida do sistema.")
        return 1
    print(f"Pronto em {(time.time() - inicio) / 60:.1f} min: {r['arquivo']} ({r['tamanho_mb']} MB, "
          f"{r['leads']} leads, conferida).")
    if r["fora_do_pc"]:
        print(f"Cópia fora do computador: {r['fora_do_pc']}")
    else:
        print("ATENÇÃO: ainda não há cópia fora deste computador. Instale o Google Drive para computador "
              "(entrando com o e-mail da MS) e a próxima cópia vai sozinha para lá.")
    print(f"A senha das cópias está em {ARQUIVO_SENHA}: guarde uma cópia dela fora do computador.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
