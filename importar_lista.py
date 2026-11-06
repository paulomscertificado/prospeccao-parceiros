"""Importa uma lista de empresas exportada da CNPJá (.xlsx) direto no banco da NUVEM (Supabase).

A tela Configurações > Integrações > Listas também importa, mas pela internet só passam arquivos de até 4 MB
(limite da Vercel). Para listas grandes, use este programa no computador da MS.

Uso: dois cliques em importar_lista.bat (ou arraste o arquivo .xlsx em cima dele).
     python importar_lista.py "C:\\caminho\\arquivo.xlsx" "nome da lista" [--local]
--local: importa no banco deste computador (dados/banco.db) em vez da nuvem.
"""

import sys
import time
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app import bases_importadas, config, modelos  # noqa: F401  (registra as tabelas)
from app.banco import Base


def perguntar(texto: str, padrao: str = "") -> str:
    resposta = input(f"{texto}{f' [{padrao}]' if padrao else ''}: ").strip().strip('"')
    return resposta or padrao


def main() -> int:
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    local = "--local" in sys.argv
    print("=" * 60)
    print(" Importar lista de empresas da CNPJá")
    print("=" * 60)
    caminho = argumentos[0] if argumentos else perguntar("Arraste aqui o arquivo .xlsx da CNPJá e aperte Enter")
    arquivo = Path(caminho.strip().strip('"'))
    if not arquivo.is_file() or arquivo.suffix.lower() != ".xlsx":
        print(f"\nNão achei o arquivo .xlsx: {arquivo}\nConfira o caminho e tente de novo.")
        return 1
    nome = argumentos[1] if len(argumentos) > 1 else perguntar("Nome da lista", "contabilidades e adm cond PE & MG")

    if local:
        from app.banco import motor
        destino, onde = motor, "neste computador"
    else:
        from fazer_backup import endereco_da_nuvem, motor_da_nuvem

        endereco = endereco_da_nuvem()
        if not endereco:
            print("\nNão encontrei o endereço do banco da nuvem (dados/supabase.txt). Nada foi feito.")
            return 1
        destino, onde = motor_da_nuvem(endereco), "na nuvem"
    Base.metadata.create_all(destino, tables=[bases_importadas.BaseDados.__table__,
                                              bases_importadas.EmpresaBase.__table__])
    print(f"\nLendo {arquivo.name} (pode levar 1 a 2 minutos)...")
    inicio = time.monotonic()
    with sessionmaker(bind=destino)() as db:
        try:
            resumo = bases_importadas.importar(db, nome, str(arquivo), arquivo.name)
            db.commit()
        except bases_importadas.ErroImportacao as erro:
            print(f"\n{erro}")
            return 1
    print(f"\nPronto ({time.monotonic() - inicio:.0f} s). Lista \"{resumo['nome']}\" {onde}:")
    print(f"  {resumo['importadas']} empresas ativas importadas")
    if resumo["inativas"]:
        print(f"  {resumo['inativas']} inativas/suspensas ficaram de fora")
    if resumo["repetidas"]:
        print(f"  {resumo['repetidas']} repetidas ignoradas")
    print("\nAgora ela aparece para escolher em Nova campanha e em Encontrar novos parceiros.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
