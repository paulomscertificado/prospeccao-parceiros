"""Prepara, NESTE computador, as configurações do servidor novo (Hostinger) a partir do que já existe aqui.

Por que daqui e não da Vercel: as configurações da Vercel estão marcadas como "sensíveis" e ela não devolve os valores
(o "vercel env pull" traz só "[SENSITIVE]"; conferido em 17/11/2026). As chaves que importam estão neste computador e
foram conferidas contra a nuvem no mesmo dia (a de criptografia abre os valores do banco; a de sessão gera links de
descadastro que o site aceita):
- SECRET_KEY = dados/chave_sessao.txt; CHAVE_CRIPTOGRAFIA = dados/chave_criptografia.txt;
- CRON_SECRET e WHATSAPP_PONTE_TOKEN = dados/agendador.txt (os que o computador usa hoje com a nuvem);
- IA_MODELO e OSM_CONTATO = o .env daqui (se tiver); e-mail, IMAP e CNPJá vêm do próprio banco (criptografados).
Também grava o endereço do Supabase no modo "Session pooler" (porta 5432; o pg_dump não funciona pelo "Transaction
pooler" da porta 6543), a configuração do WhatsApp Leads no servidor e a senha das cópias de segurança.

Grava tudo em dados/migracao/ (fora do git). TEM SENHAS: nunca mostrar, mandar por e-mail/WhatsApp ou colar em chat.
Este programa só mostra os NOMES. Uso, na pasta prospeccao-parceiros:
    .venv\\Scripts\\python.exe servidor\\pc\\preparar_migracao.py <endereço do sistema, ex.: srv123456.hstgr.cloud>
Roteiro: docs/migracao-hostinger.md.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

RAIZ = Path(os.environ.get("PROSPECCAO_RAIZ") or Path(__file__).resolve().parents[2])
DADOS = RAIZ / "dados"
SAIDA = DADOS / "migracao"
DO_ENV_LOCAL = ("IA_MODELO", "OSM_CONTATO")  # as outras chaves do .env daqui (IA, Google, Meta) não estão na nuvem
SEGURO_SEM_ASPAS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@%+=:,./-")


def endereco_sessao(texto: str) -> str:
    """O endereço do Supabase no modo sessão (porta 5432), no formato que o pg_dump entende (postgresql://)."""
    texto = texto.strip().strip('"').strip("'")
    partes = urlsplit(texto)
    if partes.scheme not in ("postgres", "postgresql", "postgresql+psycopg") or "@" not in partes.netloc:
        raise ValueError("o endereço do Supabase não parece um endereço PostgreSQL")
    credenciais, servidor = partes.netloc.rsplit("@", 1)
    host = servidor.rsplit(":", 1)[0] if ":" in servidor else servidor
    # Sem parâmetros de outros programas (ex.: pgbouncer=true do Prisma, que o pg_dump recusa); só o SSL obrigatório
    return urlunsplit(("postgresql", f"{credenciais}@{host}:5432", partes.path or "/postgres", "sslmode=require", ""))


def linha_de_ambiente(chave: str, valor: str) -> str:
    """Uma linha para o EnvironmentFile do systemd (sem expansão de nada)."""
    if valor and set(valor) <= SEGURO_SEM_ASPAS:
        return f"{chave}={valor}"
    if "'" not in valor and "\n" not in valor:
        return f"{chave}='{valor}'"
    escapado = valor.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'{chave}="{escapado}"'


def ler_chaves(arquivo: Path) -> dict[str, str]:
    """CHAVE=valor de um arquivo de configuração simples (ignora comentários)."""
    valores = {}
    if arquivo.is_file():
        for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, valor = linha.split("=", 1)
                valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def ler_arquivo(arquivo: Path) -> str:
    return arquivo.read_text(encoding="utf-8").strip() if arquivo.is_file() else ""


def configuracoes(dominio: str) -> tuple[dict[str, str], list[str]]:
    """(configurações do site no servidor, o que faltou)."""
    agendador = ler_chaves(DADOS / "agendador.txt")
    env_local = ler_chaves(RAIZ / ".env")
    valores = {
        "AMBIENTE": "producao",
        "SECRET_KEY": ler_arquivo(DADOS / "chave_sessao.txt"),
        "CHAVE_CRIPTOGRAFIA": ler_arquivo(DADOS / "chave_criptografia.txt"),
        "CRON_SECRET": agendador.get("CRON_SECRET", ""),
        "WHATSAPP_PONTE_TOKEN": agendador.get("WHATSAPP_PONTE_TOKEN", ""),
    }
    faltou = [chave for chave, valor in valores.items() if not valor]
    valores.update({chave: env_local[chave] for chave in DO_ENV_LOCAL if env_local.get(chave)})
    valores.update({"URL_PUBLICA": f"https://{dominio}", "MODO_NUVEM": "1"})
    return valores, faltou


def main() -> int:
    if len(sys.argv) != 2 or "." not in sys.argv[1]:
        print(__doc__)
        return 2
    dominio = sys.argv[1].strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    valores, faltou = configuracoes(dominio)
    if faltou:
        print(f"Faltam neste computador: {', '.join(faltou)}. Nada foi feito.")
        return 1
    supabase = DADOS / "supabase.txt"
    banco = ler_chaves(supabase).get("DATABASE_URL", "")
    if not banco:
        print(f"Não achei DATABASE_URL em {supabase}. Nada foi feito.")
        return 1
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / "supabase_sessao.url").write_text(endereco_sessao(banco) + "\n", encoding="utf-8", newline="\n")
    linhas = ["# Configurações do sistema no servidor (servidor/pc/preparar_migracao.py). TEM SENHAS."]
    linhas += [linha_de_ambiente(chave, valor) for chave, valor in valores.items()]
    (SAIDA / "ambiente.base").write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")
    (SAIDA / "wl_ambiente").write_text("\n".join([
        "# WhatsApp Leads no servidor: a ponte fala com o site do próprio servidor. TEM SENHA.",
        "PROSPECCAO_URL=http://127.0.0.1:8001",
        linha_de_ambiente("PROSPECCAO_TOKEN", valores["WHATSAPP_PONTE_TOKEN"]),
        "ARTE_NAVEGADOR=/usr/bin/google-chrome-stable",
    ]) + "\n", encoding="utf-8", newline="\n")
    senha = DADOS / "senha_backup.txt"
    if senha.is_file():
        shutil.copy2(senha, SAIDA / "senha_backup.txt")
    print(f"Pronto em {SAIDA}:")
    print(f"  ambiente.base: {', '.join(valores)}")
    print("  wl_ambiente: PROSPECCAO_URL, PROSPECCAO_TOKEN, ARTE_NAVEGADOR")
    print("  supabase_sessao.url: endereço do Supabase no modo sessão (porta 5432)")
    print("  senha_backup.txt: a mesma senha das cópias de hoje" if senha.is_file()
          else "  ATENÇÃO: sem dados/senha_backup.txt: as cópias do servidor vão criar uma senha nova")
    print("Próximo passo: bash servidor/pc/enviar_configuracao.sh <IP>  (Git Bash). Estes arquivos têm senhas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
