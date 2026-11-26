#!/usr/bin/env bash
# Senha nova (provisória) para um usuário do sistema no ar, com o código do celular desligado: roda o redefinir_senha.py
# com o banco e as configurações do site (/etc/prospeccao/ambiente), como o usuário do sistema (prospeccao).
# Roda NO SERVIDOR, como root. Quem chama: o redefinir_senha.bat do computador da MS (opção 1, por ssh -t) ou, à mão:
#   bash /opt/prospeccao/servidor/redefinir_senha.sh             faz as perguntas (precisa de um terminal)
#   bash /opt/prospeccao/servidor/redefinir_senha.sh --conferir  só confere se o banco abre; não muda nada
set -euo pipefail
P=/opt/prospeccao
if [ "${1:-}" != "--conferir" ] && [ ! -t 0 ]; then
    echo "O programa faz perguntas: entre no servidor com um terminal (ssh -t). Nada foi mudado."
    exit 1
fi
cd "$P"
exec runuser -u prospeccao -- env PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 \
    "$P/.venv/bin/python" "$P/redefinir_senha.py" --aqui --configuracoes /etc/prospeccao/ambiente "$@"
