"""Exporta os dados de UMA AR para um arquivo criptografado (white label, Fase 6; LGPD: a AR é a controladora dos dados
dela e pode pedir a cópia, por exemplo ao sair da plataforma). Nada é apagado aqui (para isso, depois: apagar_ar.py).

Uso: python exportar_ar.py <apelido da AR> [--nuvem]   (sem --nuvem: o banco de TESTE)
O arquivo sai em dados/exportacoes/ar_<apelido>_<AAAA-MM-DD>.db.cripto, fechado com a senha digitada (entregue a senha
à AR por outro caminho, nunca junto do arquivo). Dentro: um banco SQLite só com as linhas da AR.
"""
from __future__ import annotations

import getpass
import os
import sys
import time
from datetime import date
from pathlib import Path

import migrar_ar

PASTA = migrar_ar.PASTA_DADOS / "exportacoes"


def arquivo_de(slug: str, dia: date | None = None) -> Path:
    return PASTA / f"ar_{slug}_{(dia or date.today()).isoformat()}.db.cripto"


def _banco(args: list[str]) -> str:
    """Endereço do banco escolhido (teste ou nuvem), nunca confundindo um com o outro. Vazio = não dá."""
    alvo = "nuvem" if "--nuvem" in args else "teste"
    url = migrar_ar.endereco(migrar_ar.ARQUIVOS[alvo])
    if not url:
        print(f"Não achei o endereço do banco em {migrar_ar.ARQUIVOS[alvo]}. Nada foi feito.")
        return ""
    if alvo == "teste" and migrar_ar.mesmo_banco(url, migrar_ar.endereco(migrar_ar.ARQUIVOS["nuvem"])):
        print("O banco de TESTE é o mesmo da nuvem. Nada foi feito.")
        return ""
    return url


def main(args: list[str], senha: str = "") -> int:
    slug = next((a for a in args if not a.startswith("--")), "").strip().lower()
    if not slug:
        print(__doc__)
        return 1
    url = _banco(args)
    if not url:
        return 1
    os.environ["DATABASE_URL"] = url
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sqlalchemy import create_engine, select

    from app import ars
    from app.banco import motor
    from app.modelos import Tenant
    from fazer_backup import criptografar

    with motor.connect() as con:
        ar = con.execute(select(Tenant.id, Tenant.nome).where(Tenant.slug == slug)).first()
    if ar is None:
        print(f"Não existe AR com o apelido {slug}. Nada foi feito.")
        return 1
    if not senha:
        senha = getpass.getpass(f"Senha para fechar o arquivo da {ar.nome} (mínimo 10 caracteres; não aparece): ")
        if getpass.getpass("Digite a senha de novo: ") != senha:
            print("As senhas não conferem. Nada foi feito.")
            return 1
    if len(senha) < 10:
        print("A senha precisa ter pelo menos 10 caracteres. Nada foi feito.")
        return 1
    PASTA.mkdir(parents=True, exist_ok=True)
    aberto = PASTA / f"exportando_{slug}.db"
    aberto.unlink(missing_ok=True)
    inicio = time.time()
    destino = create_engine(f"sqlite:///{aberto.as_posix()}")
    try:
        contagem = ars.exportar(motor, ar.id, destino)
    finally:
        destino.dispose()
    final = arquivo_de(slug)
    try:
        criptografar(aberto, final, senha)
    finally:
        aberto.unlink(missing_ok=True)  # nada fica aberto no computador
    print(f"\nDados da {ar.nome} exportados em {(time.time() - inicio) / 60:.1f} min: {final}")
    for tabela, n in contagem.items():
        if n:
            print(f"  {tabela:<24} {n:,}".replace(",", "."))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
