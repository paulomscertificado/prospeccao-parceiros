"""Testa o e-mail de envio (o mesmo salvo no site) a partir DESTE computador.

Uso: dois cliques em testar_email_daqui.bat. Serve para descobrir se o Google recusa a senha em qualquer lugar
ou só quando o acesso vem do servidor da nuvem (que fica fora do Brasil). Não mostra a senha nem manda e-mail.
"""

import json
import re
import smtplib
import ssl
import sys
from pathlib import Path

from cryptography.fernet import Fernet

PASTA = Path(__file__).resolve().parent / "dados"


def main() -> int:
    import psycopg

    try:
        texto = (PASTA / "supabase.txt").read_text(encoding="utf-8-sig")
        url = re.search(r"^DATABASE_URL=(.+)$", texto, re.M).group(1).strip().replace("postgresql+psycopg://", "postgresql://")
        chave = (PASTA / "chave_criptografia.txt").read_text(encoding="utf-8").strip()
    except (OSError, AttributeError):
        print("Não achei os dados do banco da nuvem neste computador (dados\\supabase.txt).")
        return 1
    with psycopg.connect(url, prepare_threshold=None, connect_timeout=20) as c:
        linha = c.execute("select valor from configuracoes where chave = 'env_criptografado'").fetchone()
    if not linha:
        print("O e-mail ainda não foi salvo no site (Configurações > E-mail).")
        return 1
    cfg = json.loads(Fernet(chave.encode()).decrypt(linha[0].encode()))
    host, porta = cfg.get("SMTP_HOST", ""), int(cfg.get("SMTP_PORTA") or 587)
    usuario, senha = cfg.get("SMTP_USUARIO", ""), cfg.get("SMTP_SENHA", "")
    print(f"Testando a entrada de {usuario} em {host}:{porta} a partir deste computador...")
    print(f"Senha salva: {len(senha)} caracteres, {'só letras' if senha.isalpha() else 'COM números/símbolos'} "
          f"(a senha de app do Google tem 16 letras).")
    import base64

    try:
        with smtplib.SMTP(host, porta, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            print("Formas de entrada aceitas pelo servidor:", s.esmtp_features.get("auth", "(nenhuma)"))
            # Entrada passo a passo para mostrar a resposta EXATA do Google (sem mostrar a senha)
            credencial = base64.b64encode(f"\0{usuario}\0{senha}".encode()).decode()
            codigo, resposta = s.docmd("AUTH", "PLAIN " + credencial)
            texto = resposta.decode(errors="ignore")
            if codigo == 235:
                print("\nFUNCIONOU AQUI: a senha está certa.")
                return 0
            print(f"\nRECUSADO AQUI TAMBÉM. Resposta do Google: {codigo} {texto[:300]}")
            if codigo == 534:
                print("-> O Google pede para entrar pelo navegador antes (bloqueio de segurança da conta).")
            elif codigo == 535:
                print("-> O Google diz que usuário/senha não conferem para esta conta.")
            return 2
    except smtplib.SMTPServerDisconnected:
        print("\nRECUSADO AQUI TAMBÉM: o Google fechou a conexão logo depois da senha, sem dar motivo.")
        print("-> Costuma ser bloqueio temporário por muitas tentativas erradas, ou o acesso por senha de app")
        print("   desligado pelo administrador do Google Workspace.")
        return 2
    except (smtplib.SMTPException, OSError) as erro:
        print(f"\nNão consegui falar com o servidor ({erro}). Confira a internet.")
        return 3
    print("\nFUNCIONOU AQUI: a senha está certa. O Google está bloqueando só o acesso vindo do servidor da nuvem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
