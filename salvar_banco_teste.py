"""Guarda o endereço do banco de TESTE em dados/supabase_teste.txt.

O banco de teste é um projeto grátis no Supabase, separado do sistema de verdade. Nele entra uma cópia dos dados
(copiar_para_teste.bat) para ensaiar mudanças grandes antes de fazer na nuvem (white label: docs/white-label.md).
O endereço leva a senha do banco: ele fica só neste computador (nunca no chat nem no GitHub).
Uso: dois cliques em salvar_banco_teste.bat; colar o endereço (Supabase > Connect > Method: Session pooler ou
Transaction pooler; o "Direct connection" não funciona em rede comum) e digitar a senha do banco de teste.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

PASTA = Path(__file__).resolve().parent / "dados"
ARQUIVO = PASTA / "supabase_teste.txt"
NUVEM = PASTA / "supabase.txt"
MARCA_DA_SENHA = "[YOUR-PASSWORD]"


def endereco_do_arquivo(arquivo: Path) -> str:
    """A linha DATABASE_URL= do arquivo (vazio se não houver)."""
    try:
        for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
            if linha.startswith("DATABASE_URL="):
                return linha.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def mesmo_banco(a: str, b: str) -> bool:
    """Os dois endereços levam ao mesmo banco? (servidor, porta, usuário e nome; a senha não conta)"""
    if not a or not b:
        return False
    x, y = urlsplit(a.replace("+psycopg", "")), urlsplit(b.replace("+psycopg", ""))
    return ((x.hostname, x.port, x.username, x.path.strip("/")) ==
            (y.hostname, y.port, y.username, y.path.strip("/")))


def e_conexao_direta(endereco: str) -> bool:
    """O "Direct connection" do Supabase (db.<projeto>.supabase.co) só funciona em rede IPv6 no plano grátis: a
    maioria dos computadores não entra. O certo é o pooler (servidor ...pooler.supabase.com)."""
    servidor = urlsplit(endereco.strip().strip('"').strip("'").replace("[YOUR-PASSWORD]", "x")).hostname or ""
    return servidor.startswith("db.") and servidor.endswith(".supabase.co")


def montar(endereco: str, senha: str) -> str:
    """Põe a senha no lugar de [YOUR-PASSWORD] (com os caracteres especiais escapados)."""
    endereco = endereco.strip().strip('"').strip("'")
    return endereco.replace(MARCA_DA_SENHA, quote(senha, safe="")) if MARCA_DA_SENHA in endereco else endereco


def conecta(endereco: str) -> str:
    """Testa a entrada no banco. Devolve "" se deu certo, ou o motivo (sem mostrar a senha)."""
    from sqlalchemy import create_engine, text

    url = "postgresql+psycopg://" + endereco.split("://", 1)[1]
    motor = create_engine(url, connect_args={"prepare_threshold": None, "connect_timeout": 15})
    try:
        with motor.connect() as con:
            con.execute(text("SELECT 1"))
        return ""
    except Exception as erro:  # noqa: BLE001 - qualquer falha vira uma mensagem simples
        texto = str(erro).lower()
        if "password" in texto or "authentication" in texto:
            return "a senha não confere"
        return "o endereço não respondeu (confira se copiou o do Session pooler ou do Transaction pooler)"
    finally:
        motor.dispose()


def main() -> int:
    print("Banco de TESTE (projeto grátis no Supabase, separado do sistema de verdade)\n")
    endereco = input("Cole o endereço (começa com postgresql://) e aperte Enter:\n> ").strip()
    if not endereco.startswith(("postgres://", "postgresql://")):
        print("\nIsso não parece o endereço do banco. No Supabase: Connect > Method: Session pooler (ou Transaction "
              "pooler) > copiar. Nada foi feito.")
        return 1
    if e_conexao_direta(endereco):
        print("\nEsse é o endereço do \"Direct connection\" (db....supabase.co), que não funciona daqui. Na janela do "
              "Connect, troque o Method para \"Session pooler\" e copie de novo (o certo tem pooler.supabase.com). "
              "Nada foi feito.")
        return 1
    senha = ""
    if MARCA_DA_SENHA in endereco:
        senha = getpass.getpass("\nDigite a senha do banco de teste (a que você criou no Supabase; não aparece na tela): ")
    endereco = montar(endereco, senha)
    if mesmo_banco(endereco, endereco_do_arquivo(NUVEM)):
        print("\nEsse é o banco do sistema de verdade! O de teste precisa ser outro projeto. Nada foi feito.")
        return 1
    print("\nConferindo a entrada no banco de teste...")
    motivo = conecta(endereco)
    if motivo:
        print(f"Não consegui entrar: {motivo}. Nada foi guardado.")
        return 1
    PASTA.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text("# Banco de TESTE (Supabase gratis). NAO compartilhar.\n"
                       f"DATABASE_URL={endereco}\n", encoding="utf-8")
    print(f"Pronto: banco de teste guardado em {ARQUIVO}. Pode avisar no chat que terminou.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
