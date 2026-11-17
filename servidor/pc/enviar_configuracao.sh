#!/usr/bin/env bash
# Manda as configurações (dados/migracao, feitas pelo preparar_migracao.py) para o servidor, cada uma no seu lugar e
# legível só por quem precisa. Depois APAGA a pasta dados/migracao deste computador (tem senhas).
# Uso (Git Bash, na pasta prospeccao-parceiros): bash servidor/pc/enviar_configuracao.sh <IP do servidor>
set -euo pipefail
IP=${1:?Informe o IP do servidor}
OPCOES=(-i "$HOME/.ssh/ms_servidor" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
RAIZ=$(cd "$(dirname "$0")/../.." && pwd)
M="$RAIZ/dados/migracao"
for f in ambiente.base wl_ambiente supabase_sessao.url; do
    [ -s "$M/$f" ] || { echo "Falta $M/$f: rode antes o preparar_migracao.py. Nada foi feito."; exit 1; }
done
ssh "${OPCOES[@]}" "root@$IP" 'rm -rf /root/migracao-config && install -d -m 700 /root/migracao-config'
scp "${OPCOES[@]}" "$M"/* "root@$IP:/root/migracao-config/"
ssh "${OPCOES[@]}" "root@$IP" 'bash -s' <<'REMOTO'
set -euo pipefail
C=/root/migracao-config
if ! id prospeccao >/dev/null 2>&1 || ! id wleads >/dev/null 2>&1; then
    rm -rf $C; echo "Rode antes o instalar_servidor.sh. Nada foi feito."; exit 1
fi
install -d -m 750 -o root -g prospeccao /etc/prospeccao
install -m 640 -o root -g prospeccao $C/ambiente.base /etc/prospeccao/ambiente.base
install -d -m 750 -o root -g wleads /etc/whatsapp-leads
install -m 640 -o root -g wleads $C/wl_ambiente /etc/whatsapp-leads/ambiente
install -d -m 700 /root/migracao
install -m 600 $C/supabase_sessao.url /root/migracao/supabase_sessao.url
if [ -s $C/senha_backup.txt ]; then
    install -d -m 700 -o prospeccao -g prospeccao /opt/prospeccao/dados
    install -m 600 -o prospeccao -g prospeccao $C/senha_backup.txt /opt/prospeccao/dados/senha_backup.txt
    install -d -m 700 -o wleads -g wleads /opt/whatsapp-leads/dados
    install -m 600 -o wleads -g wleads $C/senha_backup.txt /opt/whatsapp-leads/dados/senha_backup.txt
fi
rm -rf $C
echo "Configurações no lugar: /etc/prospeccao/ambiente.base, /etc/whatsapp-leads/ambiente e a senha das cópias."
REMOTO
rm -rf "$M"
echo "A pasta dados/migracao deste computador foi apagada (tinha senhas)."
