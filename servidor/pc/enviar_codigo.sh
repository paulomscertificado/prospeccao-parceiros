#!/usr/bin/env bash
# Manda o código da Prospecção (a versão do git, a mesma publicada) e do WhatsApp Leads para o servidor, sem os dados.
# Também serve para publicar uma versão nova depois da virada (em seguida: instalar_sistema.sh no servidor).
# Uso (Git Bash, na pasta prospeccao-parceiros): bash servidor/pc/enviar_codigo.sh <IP do servidor>
set -euo pipefail
IP=${1:?Informe o IP do servidor}
OPCOES=(-i "$HOME/.ssh/ms_servidor" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
RAIZ=$(cd "$(dirname "$0")/../.." && pwd)
WL=$(cd "$RAIZ/../whatsapp-leads" && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git -C "$RAIZ" archive --format=tar -o "$TMP/prospeccao.tar" HEAD
tar -C "$WL" --exclude=./.venv --exclude=./dados --exclude=./testes --exclude='__pycache__' --exclude='*.pyc' \
    -cf "$TMP/whatsapp-leads.tar" .
scp "${OPCOES[@]}" "$TMP/prospeccao.tar" "$TMP/whatsapp-leads.tar" "root@$IP:/root/"
ssh "${OPCOES[@]}" "root@$IP" 'bash -s' <<'REMOTO'
set -euo pipefail
command -v rsync >/dev/null || { apt-get update -qq && apt-get install -y -qq rsync; }
for nome in prospeccao whatsapp-leads; do
    rm -rf "/root/novo-$nome" && mkdir -p "/root/novo-$nome"
    tar -xf "/root/$nome.tar" -C "/root/novo-$nome"
    # arquivos feitos no Windows: sem o \r no fim das linhas (o bash e o systemd do Linux não aceitam)
    find "/root/novo-$nome" -type f \( -name '*.sh' -o -name '*.service' -o -name '*.timer' -o -name 'Caddyfile*' \) \
        -exec sed -i 's/\r$//' {} +
    mkdir -p "/opt/$nome"
    rsync -a --delete --exclude /dados --exclude /.venv "/root/novo-$nome/" "/opt/$nome/"
    rm -rf "/root/novo-$nome" "/root/$nome.tar"
done
chmod +x /opt/prospeccao/servidor/*.sh /opt/whatsapp-leads/servidor/*.sh 2>/dev/null || true
echo "Código no servidor: /opt/prospeccao e /opt/whatsapp-leads (dados e bibliotecas ficaram como estavam)."
REMOTO
