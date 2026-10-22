"""Liga o sistema de Prospecção de Parceiros e abre o navegador.

Uso: python iniciar.py   (ou dois cliques em iniciar.bat)
"""

import logging
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler

from app import config

ENDERECO_NO_NAVEGADOR = f"http://localhost:{config.PORTA}"


def porta_ocupada() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", config.PORTA)) == 0


def preparar_registro():
    arquivo = RotatingFileHandler(config.ARQUIVO_LOG, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    arquivo.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
    tela.setLevel(logging.INFO)
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(arquivo)
    raiz.addHandler(tela)
    for nome in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(nome).setLevel(logging.WARNING)


def abrir_navegador_quando_pronto():
    for _ in range(60):
        if porta_ocupada():
            webbrowser.open(ENDERECO_NO_NAVEGADOR)
            return
        time.sleep(0.5)


def main():
    print("=" * 60)
    print(" Prospecção de Parceiros - MS Certificação Digital")
    print("=" * 60)
    if porta_ocupada():
        print("O sistema já está aberto. Abrindo o navegador...")
        webbrowser.open(ENDERECO_NO_NAVEGADOR)
        return 0
    try:
        import uvicorn
        from app.main import app
    except ImportError as erro:
        print(f"Falta instalar uma parte do sistema ({erro.name}).")
        print("Dê dois cliques no 'instalar.bat' e tente de novo.")
        return 1

    preparar_registro()
    print(f"Endereço do sistema: {ENDERECO_NO_NAVEGADOR}")
    print("Deixe esta janela aberta enquanto usa o sistema.")
    print("Para desligar, feche esta janela (ou aperte Ctrl+C).")
    print("-" * 60)
    threading.Thread(target=abrir_navegador_quando_pronto, daemon=True).start()
    uvicorn.run(app, host=config.HOST, port=config.PORTA, log_level="warning", log_config=None,
                proxy_headers=config.PRODUCAO, forwarded_allow_ips="*" if config.PRODUCAO else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
