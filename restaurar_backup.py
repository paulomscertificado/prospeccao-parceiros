"""Volta uma cópia de segurança (dados/backups/nuvem_AAAA-MM-DD.db) para o banco da NUVEM.

Só para emergência (dados apagados por engano, banco corrompido). APAGA o que está na nuvem hoje e coloca a
cópia no lugar. A base da Receita fica como está (ela não vai no backup).
Uso: dois cliques em restaurar_backup.bat. Pergunta qual cópia usar e pede para digitar SIM.
"""

import sys
import time
from pathlib import Path

from sqlalchemy import create_engine

from enviar_para_nuvem import copiar, esvaziar
from fazer_backup import FORA_DO_BACKUP, PASTA, endereco_da_nuvem, motor_da_nuvem


def restaurar(arquivo: Path, destino, avisar=print) -> dict[str, int]:
    origem = create_engine(f"sqlite:///{arquivo.as_posix()}")
    try:
        esvaziar(destino, pular=FORA_DO_BACKUP)
        return copiar(origem, destino, avisar=avisar, pular=FORA_DO_BACKUP)
    finally:
        origem.dispose()


def main() -> int:
    print("Voltar uma cópia de segurança para o banco da nuvem\n")
    copias = sorted(PASTA.glob("nuvem_*.db"), reverse=True)
    if not copias:
        print(f"Nenhuma cópia encontrada em {PASTA}. Nada foi feito.")
        return 1
    for n, c in enumerate(copias, start=1):
        print(f"  {n}) {c.stem.replace('nuvem_', '')}  ({c.stat().st_size / 1_000_000:.1f} MB)")
    escolha = input("\nNúmero da cópia (Enter = a mais recente): ").strip() or "1"
    if not escolha.isdigit() or not 1 <= int(escolha) <= len(copias):
        print("Número inválido. Nada foi feito.")
        return 1
    arquivo = copias[int(escolha) - 1]
    endereco = endereco_da_nuvem()
    if not endereco:
        print("Não encontrei o endereço do banco da nuvem (dados/supabase.txt). Nada foi feito.")
        return 1
    print(f"\nATENÇÃO: tudo o que está hoje no sistema da nuvem (menos a base da Receita) será APAGADO e trocado "
          f"pela cópia de {arquivo.stem.replace('nuvem_', '')}. O que foi feito depois dessa data se perde.")
    if input("Para continuar, digite SIM: ").strip() != "SIM":
        print("Nada foi feito.")
        return 0
    inicio = time.time()
    contagem = restaurar(arquivo, motor_da_nuvem(endereco))
    print(f"\nPronto em {(time.time() - inicio) / 60:.1f} min: {contagem.get('leads', 0)} leads, "
          f"{contagem.get('usuarios', 0)} usuários.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
