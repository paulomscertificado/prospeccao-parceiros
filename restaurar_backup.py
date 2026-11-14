"""Volta uma cópia de segurança para o banco da NUVEM.

Só para emergência (dados apagados por engano, banco corrompido). APAGA o que está na nuvem hoje e coloca a
cópia no lugar. A base da Receita fica como está (ela não vai no backup).
Aceita as cópias criptografadas (nuvem_AAAA-MM-DD.db.cripto, desde 11/2026) e as antigas abertas (.db), deste
computador (dados/backups) e da pasta fora do computador (Google Drive). A senha vem de dados/senha_backup.txt;
num computador novo, o script pede para digitar a senha guardada.
Uso: dois cliques em restaurar_backup.bat. Pergunta qual cópia usar e pede para digitar SIM.
"""

import getpass
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from enviar_para_nuvem import copiar, esvaziar
from fazer_backup import (EXTENSAO, FORA_DO_BACKUP, PASTA, SenhaErrada, copias, descriptografar,
                          endereco_da_nuvem, motor_da_nuvem, pasta_fora_do_pc, senha_do_backup)


def restaurar(arquivo: Path, destino, avisar=print, senha: str = "") -> dict[str, int]:
    """Coloca a cópia no banco `destino` (apaga o que havia nele, menos a base da Receita)."""
    aberta = arquivo
    temporaria = None
    if arquivo.name.endswith(EXTENSAO):
        temporaria = PASTA / f"restaurando_{arquivo.name.removesuffix(EXTENSAO)}"
        PASTA.mkdir(parents=True, exist_ok=True)
        descriptografar(arquivo, temporaria, senha or senha_do_backup(criar=False))
        aberta = temporaria
    origem = create_engine(f"sqlite:///{aberta.as_posix()}")
    try:
        esvaziar(destino, pular=FORA_DO_BACKUP)
        contagem = copiar(origem, destino, avisar=avisar, pular=FORA_DO_BACKUP)
        _reabrir_conversas(destino)
        return contagem
    finally:
        origem.dispose()
        if temporaria is not None:
            temporaria.unlink(missing_ok=True)


def _reabrir_conversas(destino) -> None:
    """As conversas do WhatsApp não vão no backup (são cópia das do WhatsApp Leads, que tem o próprio). Se o banco
    restaurado tem menos conversas do que a configuração diz já ter recebido, o marcador volta para a maior que ficou
    e o WhatsApp Leads manda de novo o que falta (as repetidas são ignoradas: api._guardar_conversas)."""
    with destino.begin() as d:
        if not inspect(destino).has_table("mensagens_whatsapp"):
            return
        maior = d.execute(text("SELECT COALESCE(MAX(id_wl), 0) FROM mensagens_whatsapp")).scalar() or 0
        atual = d.execute(text("SELECT valor FROM configuracoes WHERE chave = 'wl_conv_ultimo_id'")).scalar()
        if atual is not None and str(atual).strip().isdigit() and int(atual) > maior:
            d.execute(text("UPDATE configuracoes SET valor = :v WHERE chave = 'wl_conv_ultimo_id'"), {"v": str(maior)})


def main() -> int:
    print("Voltar uma cópia de segurança para o banco da nuvem\n")
    fora = pasta_fora_do_pc()
    lista = [(c, "neste computador") for c in copias(PASTA)]
    lista += [(c, "fora do computador") for c in copias(fora)] if fora else []
    if not lista:
        print(f"Nenhuma cópia encontrada em {PASTA}" + (f" nem em {fora}" if fora else "") + ". Nada foi feito.")
        return 1
    for n, (c, onde) in enumerate(lista, start=1):
        tipo = "criptografada" if c.name.endswith(EXTENSAO) else "aberta (antiga)"
        print(f"  {n}) {c.name[6:16]}  {c.stat().st_size / 1_000_000:.1f} MB  {tipo}, {onde}")
    escolha = input("\nNúmero da cópia (Enter = a primeira da lista): ").strip() or "1"
    if not escolha.isdigit() or not 1 <= int(escolha) <= len(lista):
        print("Número inválido. Nada foi feito.")
        return 1
    arquivo = lista[int(escolha) - 1][0]
    senha = ""
    if arquivo.name.endswith(EXTENSAO):
        senha = senha_do_backup(criar=False) or getpass.getpass("Digite a senha das cópias (não aparece na tela): ")
    endereco = endereco_da_nuvem()
    if not endereco:
        print("Não encontrei o endereço do banco da nuvem (dados/supabase.txt). Nada foi feito.")
        return 1
    print(f"\nATENÇÃO: tudo o que está hoje no sistema da nuvem (menos a base da Receita) será APAGADO e trocado "
          f"pela cópia de {arquivo.name[6:16]}. O que foi feito depois dessa data se perde.")
    if input("Para continuar, digite SIM: ").strip() != "SIM":
        print("Nada foi feito.")
        return 0
    inicio = time.time()
    try:
        contagem = restaurar(arquivo, motor_da_nuvem(endereco), senha=senha)
    except SenhaErrada as erro:
        print(f"{erro} Nada foi feito.")
        return 1
    print(f"\nPronto em {(time.time() - inicio) / 60:.1f} min: {contagem.get('leads', 0)} leads, "
          f"{contagem.get('usuarios', 0)} usuários.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
