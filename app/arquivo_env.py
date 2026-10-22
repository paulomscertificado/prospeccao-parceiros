"""Grava configurações no arquivo .env (as senhas continuam fora do banco de dados).

Usado pela tela Configurações > E-mail: a pessoa preenche na tela, o sistema escreve no .env e
já passa a usar os valores novos (sem precisar fechar e abrir o sistema).

Na nuvem não há .env para escrever: os valores vão para o banco CRIPTOGRAFADOS (chave CHAVE_CRIPTOGRAFIA,
que fica só nas variáveis da Vercel) e cada cópia do sistema relê a cada 30 segundos.
"""

import json
import os
import re
import time

from . import config

ARQUIVO = config.PASTA_DO_SISTEMA / ".env"

# Chave do .env → (atributo em config, conversão)
CAMPOS = {
    "SMTP_HOST": ("SMTP_HOST", str), "SMTP_PORTA": ("SMTP_PORTA", int), "SMTP_USUARIO": ("SMTP_USUARIO", str),
    "SMTP_SENHA": ("SMTP_SENHA", str), "SMTP_REMETENTE": ("SMTP_REMETENTE", str),
    "SMTP_TLS": ("SMTP_TLS", lambda v: v == "1"), "SMTP_RESPONDER_PARA": ("SMTP_RESPONDER_PARA", str),
    "IMAP_HOST": ("IMAP_HOST", str), "IMAP_PORTA": ("IMAP_PORTA", int), "IMAP_USUARIO": ("IMAP_USUARIO", str),
    "IMAP_SENHA": ("IMAP_SENHA", str),
}


def _formatar(valor: str) -> str:
    valor = str(valor).replace("\n", " ").strip()
    if re.search(r"[\s#\"'<>]", valor):
        return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return valor


CHAVE_NO_BANCO = "env_criptografado"
_lido_em = {"quando": -1e9}


def gravar(valores: dict[str, str]) -> None:
    """Atualiza (ou acrescenta) as chaves no .env (na nuvem: no banco, criptografado) e aplica na hora."""
    if config.NA_NUVEM:
        _gravar_no_banco(valores)
    else:
        _gravar_no_arquivo(valores)
    _aplicar(valores)


def _gravar_no_banco(valores: dict[str, str]) -> None:
    from .banco import gravar_config, sessao
    from .seguranca import criptografar

    with sessao() as db:
        atuais = _ler_do_banco(db)
        atuais.update({k: str(v) for k, v in valores.items()})
        gravar_config(db, CHAVE_NO_BANCO, criptografar(json.dumps(atuais)))


def _ler_do_banco(db) -> dict:
    from .banco import ler_config
    from .seguranca import descriptografar

    texto = descriptografar(ler_config(db, CHAVE_NO_BANCO))
    try:
        return {k: v for k, v in json.loads(texto).items() if k in CAMPOS} if texto else {}
    except ValueError:
        return {}


def carregar_do_banco(forcar: bool = False) -> None:
    """Na nuvem: aplica o que foi salvo pela tela (vale para todas as cópias do sistema)."""
    if not config.NA_NUVEM or (not forcar and time.monotonic() - _lido_em["quando"] < 30):
        return
    from .banco import sessao

    with sessao() as db:
        valores = _ler_do_banco(db)
    _lido_em["quando"] = time.monotonic()
    _aplicar(valores)


def _gravar_no_arquivo(valores: dict[str, str]) -> None:
    linhas = ARQUIVO.read_text(encoding="utf-8").splitlines() if ARQUIVO.exists() else []
    pendentes = dict(valores)
    novas = []
    for linha in linhas:
        m = re.match(r"\s*([A-Z0-9_]+)\s*=", linha)
        if m and m.group(1) in pendentes:
            chave = m.group(1)
            novas.append(f"{chave}={_formatar(pendentes.pop(chave))}")
        else:
            novas.append(linha)
    if pendentes:
        novas.append("")
        novas.extend(f"{chave}={_formatar(valor)}" for chave, valor in pendentes.items())
    ARQUIVO.write_text("\n".join(novas) + "\n", encoding="utf-8")


def _aplicar(valores: dict[str, str]) -> None:
    for chave, valor in valores.items():
        os.environ[chave] = str(valor)
        if chave in CAMPOS:
            atributo, converter = CAMPOS[chave]
            try:
                setattr(config, atributo, converter(str(valor)))
            except ValueError:
                pass
