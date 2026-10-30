"""Cria uma senha nova para um usuário (quando ninguém consegue entrar) e desliga o código do celular dele
(verificação em 2 etapas), que é configurado de novo no próximo login.

Uso: python redefinir_senha.py   (ou dois cliques em redefinir_senha.bat)
Se existir dados/supabase.txt, pergunta se é no sistema da internet ou no deste computador.
"""

import getpass
import os
import sys
from pathlib import Path

ARQUIVO_SUPABASE = Path(__file__).resolve().parent / "dados" / "supabase.txt"


def escolher_banco() -> None:
    """Antes de abrir o banco: no sistema da internet, usa o endereço guardado em dados/supabase.txt."""
    if not ARQUIVO_SUPABASE.exists():
        return
    resposta = input("Onde? 1 = sistema na internet (padrão), 2 = este computador: ").strip() or "1"
    if resposta != "1":
        return
    for linha in ARQUIVO_SUPABASE.read_text(encoding="utf-8-sig").splitlines():
        if linha.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = linha.split("=", 1)[1].strip()
            return
    print("Não achei o endereço do banco em dados/supabase.txt. Usando o deste computador.")


def main():
    escolher_banco()
    from sqlalchemy import select

    from app import dois_fatores
    from app.banco import criar_tabelas, sessao
    from app.modelos import Usuario
    from app.seguranca import problema_na_senha, resumir_senha

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
        dois_fatores.zerar(usuario)  # também derruba as sessões abertas
        usuario.ativo = True
        print(f"Pronto! Senha de {usuario.nome} trocada e código do celular desligado.")
        if usuario.perfil in dois_fatores.PERFIS_OBRIGADOS:
            print("No próximo login, o sistema mostra um QR code para ler de novo com o app do celular.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
