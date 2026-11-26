"""Baixa do servidor (Hostinger) as cópias de segurança dos últimos dias, da Prospecção, do WhatsApp Leads e do banco
de licenças do Assinador MS (desde 26/11/2026), guarda neste computador e manda para o Google Drive, como era antes da
migração. Assim sempre existe uma cópia FORA do servidor.

As cópias são feitas no servidor todo dia às 06:10 e 06:30 (criptografadas, com a senha de dados/senha_backup.txt).
Chamado 1 vez por dia pelo chamar_cron.ps1 (versão do servidor). Uso manual, na pasta prospeccao-parceiros:
    .venv\\Scripts\\python.exe servidor\\pc\\baixar_copias.py
Precisa de SERVIDOR_IP em dados/agendador.txt e da chave ~/.ssh/ms_servidor.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
WL_DADOS = RAIZ.parent / "whatsapp-leads" / "dados"
LICENCAS_LOCAL = RAIZ.parent / "assinador-ms" / "dados" / "copias-licencas"
CHAVE = Path.home() / ".ssh" / "ms_servidor"
SISTEMAS = (  # (pasta no servidor, prefixo dos arquivos, pasta neste computador)
    ("/opt/prospeccao/dados/backups", "nuvem_", RAIZ / "dados" / "backups"),
    ("/opt/whatsapp-leads/dados/backups", "whatsapp_", WL_DADOS / "backups"),
    # API de licenças do Assinador MS (cópia a cada 6 h, mesma senha e mesmo formato; assinador-ms/api_licencas)
    ("/var/backups/assinador-licencas", "licencas_", LICENCAS_LOCAL),
)
FICAM = 14


def programa(nome: str) -> str:
    """ssh/scp do Git (aceita a chave como está no disco) ou o do Windows."""
    for pasta in (r"C:\Program Files\Git\usr\bin", r"C:\Windows\System32\OpenSSH"):
        caminho = Path(pasta) / f"{nome}.exe"
        if caminho.is_file():
            return str(caminho)
    return nome


def opcoes() -> list[str]:
    return ["-i", str(CHAVE), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=20"]


def ip_do_servidor() -> str:
    """SERVIDOR_IP de dados/agendador.txt ("" sem ele). O redefinir_senha.py também entra no servidor por aqui."""
    arquivo = RAIZ / "dados" / "agendador.txt"
    if not arquivo.is_file():
        return ""
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        if linha.startswith("SERVIDOR_IP="):
            return linha.split("=", 1)[1].strip()
    return ""


def pasta_do_drive_whatsapp() -> Path | None:
    """A mesma regra do whatsapp-leads/fazer_backup.py."""
    escolhida = os.environ.get("WL_BACKUP_PASTA_FORA", "").strip().strip('"')
    if escolhida:
        return Path(escolhida)
    for letra in "GHIJKLMNOPQRSTUVWXYZ":
        for nome in ("Meu Drive", "My Drive"):
            drive = Path(f"{letra}:/{nome}")
            if (drive / "Backup Sistema MS").is_dir():
                return drive / "Backup Sistema MS" / "WhatsApp Leads"
            if drive.is_dir():
                return drive / "Backups WhatsApp Leads MS"
    return None


def limpar(pasta: Path, prefixo: str) -> None:
    """Fica com as FICAM cópias mais novas daquele sistema."""
    for antiga in sorted(pasta.glob(f"{prefixo}*.cripto"), reverse=True)[FICAM:]:
        antiga.unlink(missing_ok=True)


def main() -> int:
    from fazer_backup import pasta_fora_do_pc  # Prospecção (lê BACKUP_PASTA_FORA do .env)

    ip = ip_do_servidor()
    if not ip:
        print("Falta SERVIDOR_IP em dados/agendador.txt. Nada foi feito.")
        return 1
    prospeccao_fora = pasta_fora_do_pc()
    fora = {"nuvem_": prospeccao_fora, "whatsapp_": pasta_do_drive_whatsapp(),
            "licencas_": prospeccao_fora.parent / "Assinador Licencas" if prospeccao_fora else None}
    baixadas, erros = [], []
    for remota, prefixo, local in SISTEMAS:
        r = subprocess.run([programa("ssh"), *opcoes(), f"root@{ip}", f"ls -1t {remota}/{prefixo}*.cripto 2>/dev/null | head -3"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode not in (0, 2) and r.stderr:
            erros.append(f"{prefixo}: {r.stderr.strip()[:200]}")
            continue
        local.mkdir(parents=True, exist_ok=True)
        for caminho in [l.strip() for l in r.stdout.splitlines() if l.strip()]:
            nome = caminho.rsplit("/", 1)[-1]
            destino = local / nome
            if not destino.is_file():
                b = subprocess.run([programa("scp"), *opcoes(), f"root@{ip}:{caminho}", str(destino)],
                                   capture_output=True, text=True, timeout=600)
                if b.returncode != 0:
                    erros.append(f"{nome}: {b.stderr.strip()[:200]}")
                    destino.unlink(missing_ok=True)
                    continue
                baixadas.append(nome)
            drive = fora[prefixo]
            if drive is not None:
                try:
                    drive.mkdir(parents=True, exist_ok=True)
                    if not (drive / nome).is_file():
                        shutil.copy2(destino, drive / nome)
                    limpar(drive, prefixo)
                except OSError as erro:
                    erros.append(f"Google Drive: {str(erro)[:200]}")
        limpar(local, prefixo)
    print(f"Baixadas: {', '.join(baixadas) or 'nenhuma nova'}.")
    for erro in erros:
        print("ERRO", erro)
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
