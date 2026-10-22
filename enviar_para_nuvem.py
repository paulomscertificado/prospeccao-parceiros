"""Prepara a publicação na Vercel a partir DESTE computador.

Uso: dois cliques em enviar_para_nuvem.bat. Faz duas coisas:
1. Gera dados/variaveis_para_vercel.txt com as variáveis que vão no painel da Vercel
   (as chaves daqui, para as senhas criptografadas continuarem legíveis, e senhas novas do agendador e da ponte).
2. Copia o banco deste computador (leads, histórico, usuários, campanhas e a base da Receita já importada)
   para o banco PostgreSQL da nuvem, informado pelo endereço de conexão (Neon/Supabase).

Pode rodar de novo: pergunta antes de apagar o que já estiver no banco da nuvem.
"""

import secrets
import sys
import time

from sqlalchemy import create_engine, delete, func, insert, inspect, select, text, update

from app import base_receita, config, modelos  # noqa: F401  (registra todas as tabelas)
from app.banco import Base

ARQUIVO_VARIAVEIS = config.PASTA_DADOS / "variaveis_para_vercel.txt"
TABELAS_QUE_NAO_VAO = {"travas", "trabalhos", "ponte_whatsapp"}  # coisas de execução, não dados
COPIAR_DO_ENV = ["IA_MODELO", "ANTHROPIC_API_KEY", "GOOGLE_PLACES_API_KEY", "OSM_CONTATO", "EMAIL_DOMINIO",
                 "SMTP_HOST", "SMTP_PORTA", "SMTP_USUARIO", "SMTP_SENHA", "SMTP_REMETENTE", "SMTP_TLS",
                 "SMTP_RESPONDER_PARA", "IMAP_HOST", "IMAP_PORTA", "IMAP_USUARIO", "IMAP_SENHA",
                 "WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"]
LOTE = 2000


def endereco_postgres(texto: str) -> str:
    texto = texto.strip().strip('"').strip("'")
    for prefixo in ("postgres://", "postgresql://"):
        if texto.startswith(prefixo):
            return "postgresql+psycopg://" + texto[len(prefixo):]
    return texto


def gerar_variaveis(url_publica: str) -> None:
    import os

    linhas = [
        "# Cole no painel da Vercel: Settings > Environment Variables (pode colar tudo de uma vez).",
        "# APAGUE este arquivo depois de colar: ele tem senhas.",
        "AMBIENTE=producao",
        f"URL_PUBLICA={url_publica}",
        f"SECRET_KEY={config.SECRET_KEY}",
        f"CHAVE_CRIPTOGRAFIA={config.CHAVE_CRIPTOGRAFIA}",
        f"CRON_SECRET={secrets.token_urlsafe(32)}",
        f"WHATSAPP_PONTE_TOKEN={secrets.token_urlsafe(32)}",
        "# DATABASE_URL: o Neon/Supabase da Vercel já cria sozinho. Se não criar, cole o endereço de conexão aqui.",
    ]
    for chave in COPIAR_DO_ENV:
        valor = os.environ.get(chave, "")
        if valor:
            linhas.append(f"{chave}={valor}")
    ARQUIVO_VARIAVEIS.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _ciclos(tabelas) -> set[str]:
    """Tabelas que apontam umas para as outras (ex.: usuário ↔ parceiro): as ligações entram num 2º passo."""
    nomes = {t.name for t in tabelas}
    alcanca = {t.name: {fk.column.table.name for fk in t.foreign_keys} & nomes for t in tabelas}
    mudou = True
    while mudou:
        mudou = False
        for nome, destinos in alcanca.items():
            novos = set().union(*(alcanca[d] for d in destinos)) - destinos if destinos else set()
            if novos:
                destinos |= novos
                mudou = True
    return {nome for nome, destinos in alcanca.items() if nome in destinos}


def copiar(origem, destino, avisar=print) -> dict[str, int]:
    """Copia todas as tabelas de `origem` para `destino` (que precisa estar vazio). Devolve as contagens."""
    Base.metadata.create_all(destino)
    tabelas = [t for t in Base.metadata.sorted_tables if t.name not in TABELAS_QUE_NAO_VAO
               and inspect(origem).has_table(t.name)]
    em_ciclo = _ciclos(tabelas)
    depois: list[tuple] = []  # (tabela, coluna, [(id, valor)])
    contagem = {}
    colunas_origem = {t.name: {c["name"] for c in inspect(origem).get_columns(t.name)} for t in tabelas}
    for tabela in tabelas:
        adiar = [fk.parent for fk in tabela.foreign_keys
                 if tabela.name in em_ciclo and fk.column.table.name in em_ciclo and fk.parent.nullable]
        colunas = [c for c in tabela.columns if c.name in colunas_origem[tabela.name]]
        total = 0
        with origem.connect() as o:
            n = o.execute(select(func.count()).select_from(tabela)).scalar()
            avisar(f"  {tabela.name}: {n} linhas...")
            resultado = o.execution_options(stream_results=True).execute(select(*colunas))
            while lote := resultado.fetchmany(LOTE):
                linhas = [dict(l._mapping) for l in lote]
                for coluna in adiar:
                    valores = [(l["id"], l[coluna.name]) for l in linhas if l.get(coluna.name) is not None]
                    if valores:
                        depois.append((tabela, coluna, valores))
                    for l in linhas:
                        l[coluna.name] = None
                with destino.begin() as d:
                    d.execute(insert(tabela), linhas)
                total += len(linhas)
        contagem[tabela.name] = total
    with destino.begin() as d:
        for tabela, coluna, valores in depois:
            for id_, valor in valores:
                d.execute(update(tabela).where(tabela.c.id == id_).values({coluna.name: valor}))
        if destino.dialect.name == "postgresql":  # o próximo id continua depois do maior copiado
            for tabela in tabelas:
                if "id" in tabela.c and contagem.get(tabela.name):
                    d.execute(text(f"SELECT setval(pg_get_serial_sequence('{tabela.name}', 'id'), "
                                   f"(SELECT MAX(id) FROM {tabela.name}))"))
    return contagem


def esvaziar(destino) -> None:
    tabelas = [t for t in reversed(Base.metadata.sorted_tables) if inspect(destino).has_table(t.name)]
    with destino.begin() as d:
        if destino.dialect.name == "postgresql":
            d.execute(text("TRUNCATE " + ", ".join(t.name for t in tabelas) + " RESTART IDENTITY CASCADE"))
        else:
            for t in tabelas:
                d.execute(delete(t))


def main() -> int:
    print("Enviar a Prospecção de Parceiros para a nuvem (Vercel)\n")
    url_publica = input("Endereço do site (ex.: https://parceiros.mscertificados.com.br): ").strip().rstrip("/")
    if not url_publica.startswith("https://"):
        print("O endereço precisa começar com https://. Nada foi feito.")
        return 1
    gerar_variaveis(url_publica)
    print(f"\n1) Variáveis prontas em: {ARQUIVO_VARIAVEIS}")
    print("   Abra esse arquivo, copie tudo e cole no painel da Vercel. Depois apague o arquivo.\n")

    if config.DATABASE_URL.startswith("postgres"):
        print("Este computador já usa PostgreSQL: não há o que copiar.")
        return 0
    texto = input("2) Cole o endereço de conexão do banco da nuvem (começa com postgresql://), "
                  "ou deixe vazio para pular: ").strip()
    if not texto:
        print("Cópia pulada.")
        return 0
    try:
        destino = create_engine(endereco_postgres(texto), pool_pre_ping=True)
        with destino.connect() as d:
            d.execute(text("SELECT 1"))
    except Exception as erro:  # noqa: BLE001
        print(f"\nNão consegui conectar no banco da nuvem: {str(erro).splitlines()[0]}")
        print("Confira se copiou o endereço inteiro (com a senha). Nada foi copiado.")
        return 1
    if inspect(destino).has_table("usuarios"):
        with destino.connect() as d:
            ja_tem = d.execute(text("SELECT COUNT(*) FROM usuarios")).scalar()
        if ja_tem:
            resposta = input(f"\nO banco da nuvem já tem dados ({ja_tem} usuários). APAGAR tudo lá e copiar de novo? "
                             "(digite SIM): ").strip()
            if resposta != "SIM":
                print("Nada foi copiado.")
                return 0
            esvaziar(destino)
    origem = create_engine(config.DATABASE_URL)
    print("\nCopiando (a base da Receita é grande: pode levar uns 10 a 20 minutos; não feche esta janela)...")
    inicio = time.time()
    contagem = copiar(origem, destino)
    print(f"\nPronto em {(time.time() - inicio) / 60:.1f} min: {contagem.get('leads', 0)} leads, "
          f"{contagem.get('usuarios', 0)} usuários, {contagem.get('base_receita', 0)} empresas da Receita.")
    print("Na nuvem, entre com o mesmo e-mail e senha de sempre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
