"""Confere se dois bancos PostgreSQL têm as mesmas tabelas com a mesma quantidade de linhas (schema public).

Usado na migração para o servidor da Hostinger (servidor/migrar_banco.sh): origem = Supabase, destino = o banco do
servidor. Não mostra endereços nem dados, só nomes de tabelas e contagens. Sai com código 1 se algo não bater.
Uso: python conferir_contagens.py <endereço de origem> <endereço de destino>   (postgresql://...)
"""
from __future__ import annotations

import sys

import psycopg


def contagens(endereco: str) -> dict[str, int]:
    with psycopg.connect(endereco, prepare_threshold=None, connect_timeout=30) as con:
        tabelas = [linha[0] for linha in con.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")]
        return {t: con.execute(f'SELECT count(*) FROM public."{t}"').fetchone()[0] for t in tabelas}


def comparar(origem: dict[str, int], destino: dict[str, int]) -> list[str]:
    """As diferenças, em português (lista vazia = tudo igual)."""
    problemas = []
    for tabela in sorted(set(origem) | set(destino)):
        if tabela not in destino:
            problemas.append(f"{tabela}: falta no destino")
        elif tabela not in origem:
            problemas.append(f"{tabela}: só existe no destino")
        elif origem[tabela] != destino[tabela]:
            problemas.append(f"{tabela}: origem {origem[tabela]} x destino {destino[tabela]}")
    return problemas


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    origem, destino = contagens(sys.argv[1]), contagens(sys.argv[2])
    problemas = comparar(origem, destino)
    total = sum(origem.values())
    if problemas:
        print(f"ATENÇÃO: {len(problemas)} tabela(s) diferentes:")
        for linha in problemas:
            print("  -", linha)
        return 1
    maiores = sorted(origem.items(), key=lambda item: -item[1])[:5]
    print(f"   {len(origem)} tabelas iguais, {total} linhas no total. Maiores: "
          + ", ".join(f"{t} {n}" for t, n in maiores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
