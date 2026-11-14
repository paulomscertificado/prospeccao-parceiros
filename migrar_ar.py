"""White label, Fase 1: põe a AR (a marca) em cada linha do banco (regras em app/ars.py, plano em docs/white-label.md).

Primeiro no banco de TESTE: dados/supabase_teste.txt (salvar_banco_teste.bat) com uma cópia dos dados de verdade
(copiar_para_teste.bat). Só depois do ensaio aprovado, no banco da nuvem.

Uso (ou dois cliques em migrar_ar.bat, que faz o ensaio):
  python migrar_ar.py ensaio            simula no banco de teste e desfaz; mostra quantas linhas iriam para cada AR
  python migrar_ar.py aplicar           grava no banco de teste e confere
  python migrar_ar.py conferir          só confere: linhas sem AR e ligações cruzando ARs
  python migrar_ar.py aplicar --nuvem   grava no banco da NUVEM (pede para digitar SIM)
Opções: --master=ms|grupo-certy   AR dos leads e campanhas do Admin Master (padrão: ms)
        --sem-dono=ms|grupo-certy AR dos leads sem vendedor (padrão: ms)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PASTA_DADOS = Path(os.environ.get("PP_PASTA_DADOS") or Path(__file__).resolve().parent / "dados")
ARQUIVOS = {"teste": PASTA_DADOS / "supabase_teste.txt", "nuvem": PASTA_DADOS / "supabase.txt"}
SLUGS = ("ms", "grupo-certy")

from salvar_banco_teste import mesmo_banco  # noqa: E402  (mesmo projeto do Supabase por qualquer porta)


def endereco(arquivo: Path) -> str:
    """O endereço do banco guardado no arquivo (linha DATABASE_URL=...), pronto para o SQLAlchemy."""
    try:
        linhas = arquivo.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    for linha in linhas:
        linha = linha.strip()
        if linha.startswith("DATABASE_URL="):
            linha = linha.split("=", 1)[1].strip().strip('"').strip("'")
        for prefixo in ("postgres://", "postgresql://", "postgresql+psycopg://"):
            if linha.startswith(prefixo):
                return "postgresql+psycopg://" + linha[len(prefixo):]
    return ""


def opcoes(args: list[str]) -> tuple[str, str, dict]:
    acao = next((a for a in args if not a.startswith("--")), "ensaio")
    alvo = "nuvem" if "--nuvem" in args else "teste"
    decisoes = {}
    for a in args:
        for opcao, chave in (("--master=", "do_master"), ("--sem-dono=", "sem_dono")):
            if a.startswith(opcao):
                decisoes[chave] = a.split("=", 1)[1].strip()
    return acao, alvo, decisoes


def _mostrar(contagem: dict) -> None:
    for tabela, partes in contagem.items():
        if any(partes.values()):
            print(f"  {tabela:<24}" + " · ".join(f"{ar} {n:,}".replace(",", ".") for ar, n in sorted(partes.items())))


def _mostrar_conferencia(r: dict) -> None:
    if r["ok"]:
        print("\nConferência: OK. Nenhuma linha sem AR e nenhuma ligação cruzando ARs.")
        return
    print("\nConferência: precisa de atenção.")
    for tabela, n in r["sem_ar"].items():
        print(f"  {n} linha(s) sem AR em {tabela}")
    for ligacao, n in r["cruzadas"].items():
        print(f"  {n} ligação(ões) cruzando ARs: {ligacao}")


def main(args: list[str]) -> int:
    acao, alvo, decisoes = opcoes(args)
    if acao not in ("ensaio", "aplicar", "conferir"):
        print(__doc__)
        return 1
    if any(v not in SLUGS for v in decisoes.values()):
        print(f"AR desconhecida. Use uma destas: {', '.join(SLUGS)}. Nada foi feito.")
        return 1
    url = endereco(ARQUIVOS[alvo])
    if not url:
        print(f"Não achei o endereço do banco em {ARQUIVOS[alvo]}."
              + (" Rode antes o salvar_banco_teste.bat." if alvo == "teste" else "") + " Nada foi feito.")
        return 1
    if alvo == "teste" and mesmo_banco(url, endereco(ARQUIVOS["nuvem"])):
        print("O banco de TESTE é o mesmo da nuvem. Crie um projeto separado no Supabase. Nada foi feito.")
        return 1
    if alvo == "nuvem" and acao == "ensaio":
        print("O ensaio é só no banco de teste (python migrar_ar.py ensaio). Nada foi feito.")
        return 1
    if alvo == "nuvem" and acao == "aplicar":
        print("ATENÇÃO: isto grava a AR em todas as linhas do banco da NUVEM (o sistema de verdade).\n"
              "As telas não mudam nesta fase. Faça um backup antes (fazer_backup.bat).")
        if input("Para continuar, digite SIM: ").strip() != "SIM":
            print("Nada foi feito.")
            return 0

    os.environ["DATABASE_URL"] = url
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sqlalchemy import inspect

    from app import ars
    from app.banco import agora, criar_tabelas, gravar_config, motor, proteger_tabelas, sessao

    print(f"Banco: {'TESTE' if alvo == 'teste' else 'NUVEM'} · ação: {acao} · "
          f"decisões: {json.dumps({**ars.PADRAO, **decisoes})}\n")
    inicio = time.time()
    if alvo == "teste":
        criar_tabelas()      # o mesmo que a publicação da Fase 1 faz: tabela das ARs e a coluna tenant_id
        proteger_tabelas()
    elif not inspect(motor).has_table("tenants"):
        print("A nuvem ainda não tem a tabela das ARs: publique a versão da Fase 1 antes. Nada foi feito.")
        return 1
    with motor.connect() as con:
        if acao == "ensaio":
            ars.preencher(con, decisoes, gravar=False)
            print("Se aplicar, as linhas ficam assim (AR · quantidade):")
            _mostrar(ars.contagem(con))
            resultado = ars.conferir(con)
            con.rollback()
            print("\n(Ensaio: nada foi gravado.)")
        elif acao == "aplicar":
            ars.preencher(con, decisoes, gravar=True, limpar=True)
            con.commit()
            print("Linhas por AR:")
            _mostrar(ars.contagem(con))
            resultado = ars.conferir(con)
        else:
            _mostrar(ars.contagem(con))
            resultado = ars.conferir(con)
    _mostrar_conferencia(resultado)
    if acao == "aplicar" and resultado["ok"]:
        with sessao() as db:  # liga o preenchimento de hora em hora das linhas novas (rotinas._rotina_hora)
            gravar_config(db, ars.LIGADO, json.dumps({**ars.PADRAO, **decisoes,
                                                      "desde": agora().isoformat(timespec="seconds")}))
        print("Preenchimento de hora em hora das linhas novas: ligado.")
    print(f"\nTempo: {(time.time() - inicio) / 60:.1f} min")
    return 0 if resultado["ok"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
