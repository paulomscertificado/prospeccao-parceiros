"""Põe no banco de TESTE (dados/supabase_teste.txt) a cópia de segurança mais nova do sistema da nuvem.

Apaga o que houver no banco de teste e copia tudo (menos a base da Receita, as artes e as filas, que não vão no
backup). Nunca mexe no banco da nuvem: recusa se o endereço de teste for o mesmo. Serve para ensaiar mudanças grandes
com os dados de verdade (white label, Fase 1: docs/white-label.md).
Uso: dois cliques em copiar_para_teste.bat (depois do salvar_banco_teste.bat).
"""
from __future__ import annotations

import sys
import time

from enviar_para_nuvem import endereco_postgres
from fazer_backup import PASTA, SenhaErrada, copias, endereco_da_nuvem, motor_da_nuvem, senha_do_backup
from restaurar_backup import restaurar
from salvar_banco_teste import ARQUIVO, endereco_do_arquivo, mesmo_banco


def main() -> int:
    teste = endereco_postgres(endereco_do_arquivo(ARQUIVO))
    if not teste:
        print("Não achei o banco de teste (dados/supabase_teste.txt). Rode antes o salvar_banco_teste.bat.")
        return 1
    if mesmo_banco(teste, endereco_da_nuvem()):
        print("O banco de teste é o mesmo do sistema de verdade. Nada foi feito.")
        return 1
    lista = copias(PASTA)
    if not lista:
        print(f"Nenhuma cópia de segurança em {PASTA}. Rode antes o fazer_backup.bat. Nada foi feito.")
        return 1
    arquivo = lista[0]
    print(f"Copiando a cópia de {arquivo.name[6:16]} para o banco de TESTE (o sistema de verdade não é tocado)...")
    inicio = time.time()
    try:
        contagem = restaurar(arquivo, motor_da_nuvem(teste), senha=senha_do_backup(criar=False))
    except SenhaErrada as erro:
        print(f"{erro} Nada foi feito.")
        return 1
    print(f"\nPronto em {(time.time() - inicio) / 60:.1f} min: {contagem.get('leads', 0)} leads, "
          f"{contagem.get('usuarios', 0)} usuários, {contagem.get('mensagens_whatsapp', 0)} mensagens de WhatsApp.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
