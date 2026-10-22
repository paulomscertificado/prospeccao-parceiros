"""Importa a base de CNPJs da Receita Federal (empresas ativas das categorias de parceiros).

Uso: python importar_receita.py "PASTA"   (ou dois cliques em importar_receita.bat)
"""

import sys
import time

from app.banco import criar_tabelas
from app.base_receita import ErroBase, importar_pasta


def main():
    criar_tabelas()
    pasta = sys.argv[1] if len(sys.argv) > 1 else input("Cole o caminho da pasta com os arquivos .zip da Receita: ")
    print("Importando... leva uns 3 a 5 minutos. Não feche esta janela.")
    inicio = time.time()
    try:
        total = importar_pasta(pasta)
    except ErroBase as erro:
        print(f"Não deu certo: {erro}")
        return 1
    print(f"Pronto! {total} empresas ativas guardadas (todas as categorias) ({(time.time() - inicio) / 60:.1f} min).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
