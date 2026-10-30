"""Cópia de segurança do banco da NUVEM (Supabase) para este computador.

O Supabase grátis não tem backup. Este script copia tudo (leads, histórico, campanhas, parceiros, vendas,
usuários, configurações), menos a base da Receita (que se importa de novo dos .zip), para
dados/backups/nuvem_AAAA-MM-DD.db. Guarda os últimos 14 dias.

Uso: dois cliques em fazer_backup.bat. O agendador do Windows (dados/chamar_cron.ps1) também roda sozinho,
1 vez por dia, com --automatico (sem perguntas). Para voltar uma cópia: restaurar_backup.bat.
"""

import sys
import time
from datetime import datetime

from sqlalchemy import create_engine

from app import config
from enviar_para_nuvem import copiar, endereco_postgres

PASTA = config.PASTA_DADOS / "backups"
ARQUIVO_SUPABASE = config.PASTA_DADOS / "supabase.txt"
TENTATIVA = PASTA / "ultima_tentativa.txt"
FICAM = 14  # dias guardados
FORA_DO_BACKUP = {"base_receita"}  # grande e reimportável dos .zip da Receita


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


def apagar_antigos() -> None:
    for antigo in sorted(PASTA.glob("nuvem_*.db"))[:-FICAM]:
        antigo.unlink(missing_ok=True)


def fazer(avisar=print) -> str:
    """Faz a cópia de hoje e devolve o caminho do arquivo."""
    endereco = endereco_da_nuvem()
    if not endereco:
        raise RuntimeError(f"Não encontrei o endereço do banco da nuvem em {ARQUIVO_SUPABASE}.")
    PASTA.mkdir(parents=True, exist_ok=True)
    TENTATIVA.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    final = PASTA / f"nuvem_{datetime.now():%Y-%m-%d}.db"
    parcial = PASTA / (final.name + ".parcial")
    parcial.unlink(missing_ok=True)
    destino = create_engine(f"sqlite:///{parcial.as_posix()}")
    try:
        copiar(motor_da_nuvem(endereco), destino, avisar=avisar, pular=FORA_DO_BACKUP)
    finally:
        destino.dispose()
    parcial.replace(final)  # só vira o arquivo do dia quando a cópia terminou inteira
    apagar_antigos()
    return str(final)


def main() -> int:
    automatico = "--automatico" in sys.argv
    if not automatico:
        print("Cópia de segurança do banco da nuvem (sem a base da Receita)\n")
    inicio = time.time()
    try:
        arquivo = fazer(avisar=(lambda _texto: None) if automatico else print)
    except Exception as erro:  # noqa: BLE001
        print(f"Não deu certo: {str(erro).splitlines()[0][:300]}")
        print("Confira a internet. Se continuar, avise quem cuida do sistema.")
        return 1
    print(f"Pronto em {(time.time() - inicio) / 60:.1f} min: {arquivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
