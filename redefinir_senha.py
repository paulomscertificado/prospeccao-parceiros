"""Cria uma senha nova para um usuário (quando ninguém consegue entrar).

Uso: python redefinir_senha.py   (ou dois cliques em redefinir_senha.bat)
"""

import getpass
import sys

from sqlalchemy import select

from app.banco import criar_tabelas, sessao
from app.modelos import Usuario
from app.seguranca import problema_na_senha, resumir_senha


def main():
    criar_tabelas()
    with sessao() as db:
        usuarios = db.execute(select(Usuario).order_by(Usuario.id)).scalars().all()
        if not usuarios:
            print("Ainda não existe nenhum usuário. Abra o sistema e crie a conta de administrador.")
            return 0
        print("Usuários cadastrados:")
        for u in usuarios:
            print(f"  {u.id} - {u.nome} ({u.email}) - {u.perfil_nome}{'' if u.ativo else ' - DESATIVADO'}")
        escolha = input("Digite o número do usuário: ").strip()
        usuario = db.get(Usuario, int(escolha)) if escolha.isdigit() else None
        if not usuario:
            print("Número inválido.")
            return 1
        senha = getpass.getpass("Senha nova (não aparece enquanto digita): ")
        if problema := problema_na_senha(senha):
            print(problema)
            return 1
        if getpass.getpass("Repita a senha nova: ") != senha:
            print("As senhas não são iguais.")
            return 1
        usuario.senha_hash = resumir_senha(senha)
        usuario.versao_sessao += 1
        usuario.ativo = True
        print(f"Pronto! Senha de {usuario.nome} trocada. Já pode entrar no sistema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
