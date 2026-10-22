"""Entrada do sistema na Vercel: todos os endereços caem aqui (ver vercel.json)."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Na nuvem o registro vai para a tela de Logs da Vercel (não há arquivo dados/sistema.log).
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(name)s: %(message)s")
for nome in ("httpx", "httpcore"):
    logging.getLogger(nome).setLevel(logging.WARNING)

from app.main import app  # noqa: E402,F401
