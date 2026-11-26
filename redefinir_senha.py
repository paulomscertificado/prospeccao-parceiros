"""Cria uma senha nova para um usuário (quando ninguém consegue entrar) e desliga o código do celular dele
(verificação em 2 etapas), que é configurado de novo no próximo login. A senha nova é provisória: no próximo login,
depois do código do celular, a pessoa troca por uma senha só dela (pedido da Maria em 26/11/2026).

Uso: python redefinir_senha.py   (ou dois cliques em redefinir_senha.bat)
Pergunta onde: 1 = o sistema na internet ou 2 = a cópia deste computador. No 1, entra no servidor com o mesmo acesso
das cópias de segurança (SERVIDOR_IP de dados/agendador.txt e a chave ~/.ssh/ms_servidor, servidor/pc/baixar_copias.py)
e roda lá o servidor/redefinir_senha.sh: as perguntas vêm de lá e a senha muda no banco do sistema no ar. Até 26/11/2026
o 1 usava o dados/supabase.txt, o banco ANTIGO de antes da mudança para o servidor (17/11), e nada mudava no sistema.
O que o servidor/redefinir_senha.sh roda lá, como o usuário do sistema:
    python redefinir_senha.py --aqui --configuracoes /etc/prospeccao/ambiente [--conferir]
"""

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
NO_SERVIDOR = "bash /opt/prospeccao/servidor/redefinir_senha.sh"


def ler_configuracoes(arquivo: str | Path) -> dict[str, str]:
    """As configurações do site no servidor (/etc/prospeccao/ambiente, o EnvironmentFile do systemd): as linhas que o
    preparar_migracao.py e o instalar_sistema.sh gravam (CHAVE=valor sem aspas, com aspas simples ou duplas), sem
    trocar $NOME por nada, como o systemd. Arquivo que não existe ou não abre = erro, e não um banco vazio."""
    from io import StringIO

    from dotenv import dotenv_values

    texto = Path(arquivo).read_text(encoding="utf-8-sig")
    return {chave: valor for chave, valor in dotenv_values(stream=StringIO(texto), interpolate=False).items()
            if valor is not None}


def escolher_onde() -> str:
    resposta = input("Onde? 1 = sistema na internet (padrão), 2 = cópia deste computador: ").strip() or "1"
    return "servidor" if resposta == "1" else "aqui"


def no_servidor() -> int:
    """Opção 1: entra no servidor e roda lá a troca (servidor/redefinir_senha.sh); as respostas são digitadas aqui."""
    if str(RAIZ / "servidor" / "pc") not in sys.path:
        sys.path.insert(0, str(RAIZ / "servidor" / "pc"))
    import baixar_copias as acesso  # o mesmo acesso das cópias de segurança: SERVIDOR_IP + chave ~/.ssh/ms_servidor

    ip = acesso.ip_do_servidor()
    if not ip or not acesso.CHAVE.is_file():
        falta = "o SERVIDOR_IP no arquivo dados/agendador.txt" if not ip else f"a chave do servidor ({acesso.CHAVE})"
        print(f"Este computador não tem o acesso ao servidor do sistema: falta {falta}. Nada foi mudado.")
        print("Use o computador da MS que baixa as cópias de segurança do sistema, ou peça ajuda ao suporte.")
        return 1
    print(f"Entrando no servidor do sistema ({ip}). As perguntas a seguir vêm de lá.", flush=True)
    resultado = subprocess.run([acesso.programa("ssh"), "-t", *acesso.opcoes(), f"root@{ip}", NO_SERVIDOR])
    if resultado.returncode == 255:  # o ssh não entrou (internet, endereço ou chave)
        print("Não consegui entrar no servidor. Confira a internet deste computador e tente de novo. Nada foi mudado.")
    return resultado.returncode


def main(argumentos: list[str] | None = None) -> int:
    opcoes = argparse.ArgumentParser(description="Cria uma senha nova (provisória) para um usuário do sistema.")
    opcoes.add_argument("--aqui", action="store_true", help="no banco de onde está rodando, sem perguntar onde")
    opcoes.add_argument("--configuracoes", help="arquivo com as configurações do site (/etc/prospeccao/ambiente)")
    opcoes.add_argument("--conferir", action="store_true", help="só confere se o banco abre; não muda nada")
    args = opcoes.parse_args(argumentos)
    if args.configuracoes:  # antes de abrir o banco: o sistema lê as configurações quando é carregado
        try:
            valores = ler_configuracoes(args.configuracoes)
        except OSError as erro:
            print(f"Não consegui ler as configurações do sistema ({erro}). Nada foi mudado.")
            return 1
        if not valores.get("DATABASE_URL"):
            print(f"Não achei o banco do sistema (DATABASE_URL) em {args.configuracoes}. Nada foi mudado.")
            return 1
        os.environ.update(valores)
    if not args.aqui and escolher_onde() == "servidor":
        return no_servidor()
    from sqlalchemy import select

    from app import config, dois_fatores
    from app.banco import criar_tabelas, motor, preparar_banco_na_nuvem, sessao
    from app.modelos import Usuario
    from app.seguranca import problema_na_senha, registrar_log, resumir_senha

    if args.conferir:
        with motor.connect() as con:
            con.exec_driver_sql("SELECT 1")
        print("O banco do sistema respondeu. Nada foi mudado.")
        return 0
    if config.NA_NUVEM:
        preparar_banco_na_nuvem()  # no servidor: as tabelas já existem; só prepara se a versão mudou, como o site
    else:
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
        usuario.senha_provisoria = True  # no próximo login a pessoa troca por uma senha só dela
        dois_fatores.zerar(usuario)  # também derruba as sessões abertas
        usuario.ativo = True
        registrar_log(db, None, "redefiniu_senha", "usuario", usuario.id,
                      f"{usuario.email} pelo redefinir_senha; senha provisória: troca no próximo login")
        print(f"Pronto! Senha de {usuario.nome} trocada e código do celular desligado.")
        if usuario.perfil in dois_fatores.PERFIS_OBRIGADOS:
            print("No próximo login, o sistema mostra um QR code para ler de novo com o app do celular.")
        print("Depois de entrar, o sistema pede para a pessoa trocar esta senha por uma senha só dela.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
