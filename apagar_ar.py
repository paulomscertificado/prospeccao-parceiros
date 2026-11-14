"""Apaga UMA AR inteira e todos os dados dela (white label, Fase 6; LGPD: quando a AR sai da plataforma).

Só funciona depois de exportar os dados dela HOJE (exportar_ar.py) e de digitar o apelido da AR e SIM. Não toca nas
outras ARs nem no que é da plataforma. A AR MS (dona da plataforma) nunca é apagada por aqui.

Uso: python apagar_ar.py <apelido da AR> [--nuvem]   (sem --nuvem: o banco de TESTE)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import exportar_ar

PROTEGIDAS = {"ms"}


def main(args: list[str], perguntar=input) -> int:
    slug = next((a for a in args if not a.startswith("--")), "").strip().lower()
    if not slug:
        print(__doc__)
        return 1
    if slug in PROTEGIDAS:
        print("A AR MS é a dona da plataforma e não é apagada por aqui. Nada foi feito.")
        return 1
    if not exportar_ar.arquivo_de(slug).exists():
        print(f"Antes de apagar, exporte os dados dela hoje: python exportar_ar.py {slug}"
              + (" --nuvem" if "--nuvem" in args else "") + ". Nada foi feito.")
        return 1
    url = exportar_ar._banco(args)
    if not url:
        return 1
    os.environ["DATABASE_URL"] = url
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sqlalchemy import func, select

    from app import ars
    from app.banco import motor, sessao
    from app.modelos import Tenant
    from app.seguranca import registrar_log

    with motor.connect() as con:
        ar = con.execute(select(Tenant.id, Tenant.nome).where(Tenant.slug == slug)).first()
        if ar is None:
            print(f"Não existe AR com o apelido {slug}. Nada foi feito.")
            return 1
        quantas = {t.name: con.execute(select(func.count()).select_from(t).where(t.c.tenant_id == ar.id)).scalar()
                   for t in ars._tabelas_da_ar()}
    print(f"\nA AR {ar.nome} tem:")
    for tabela, n in quantas.items():
        if n:
            print(f"  {tabela:<24} {n:,}".replace(",", "."))
    print(f"\nTUDO isso será apagado para sempre (a cópia exportada fica em {exportar_ar.arquivo_de(slug)}).")
    if perguntar(f"Para continuar, digite o apelido da AR ({slug}): ").strip().lower() != slug:
        print("Nada foi feito.")
        return 0
    if perguntar("Tem certeza? Não dá para desfazer. Digite SIM: ").strip() != "SIM":
        print("Nada foi feito.")
        return 0
    with motor.begin() as con:
        contagem = ars.apagar(con, ar.id)
    with sessao() as db:
        registrar_log(db, None, "apagou_ar", "tenant", ar.id,
                      f"{ar.nome} ({slug}) apagada pelo apagar_ar.py (LGPD): {sum(contagem.values())} linhas; "
                      f"exportação em {exportar_ar.arquivo_de(slug).name}")
    print(f"\nAR {ar.nome} apagada: {sum(contagem.values()):,} linhas.".replace(",", "."))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
