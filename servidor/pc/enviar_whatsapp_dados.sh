#!/usr/bin/env bash
# VIRADA: leva os dados do WhatsApp Leads deste computador (banco, sessões dos números, mídias) para o servidor.
# Só com o WhatsApp Leads deste computador DESLIGADO: o mesmo número nunca pode ficar ligado em dois lugares.
# Não liga o WhatsApp Leads do servidor (passo seguinte do roteiro: systemctl enable --now whatsapp-leads).
# Uso (Git Bash, na pasta prospeccao-parceiros): bash servidor/pc/enviar_whatsapp_dados.sh <IP do servidor>
set -euo pipefail
IP=${1:?Informe o IP do servidor}
OPCOES=(-i "$HOME/.ssh/ms_servidor" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
RAIZ=$(cd "$(dirname "$0")/../.." && pwd)
WL=$(cd "$RAIZ/../whatsapp-leads" && pwd)
if curl -s -o /dev/null --max-time 3 http://127.0.0.1:8000/; then
    echo "O WhatsApp Leads deste computador ainda está ligado (porta 8000). Desligue antes. Nada foi feito."
    exit 1
fi
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
tar -C "$WL/dados" --exclude=./backups --exclude='./sistema.log*' --exclude=./saida_escondido.txt \
    --exclude=./erros_escondido.txt --exclude=./sistema.trava -cf "$TMP/wl-dados.tar" .
echo "Enviando $(du -h "$TMP/wl-dados.tar" | cut -f1) de dados do WhatsApp Leads..."
scp "${OPCOES[@]}" "$TMP/wl-dados.tar" "root@$IP:/root/"
ssh "${OPCOES[@]}" "root@$IP" 'bash -s' <<'REMOTO'
set -euo pipefail
systemctl stop whatsapp-leads.service 2>/dev/null || true
D=/opt/whatsapp-leads/dados
SENHA=""
[ -s $D/senha_backup.txt ] && SENHA=$(cat $D/senha_backup.txt)
[ -d $D ] && mv $D "/root/wl-dados-antes-$(date +%Y%m%d%H%M%S)"
install -d -m 700 $D
tar -xf /root/wl-dados.tar -C $D && rm -f /root/wl-dados.tar
[ -n "$SENHA" ] && printf '%s\n' "$SENHA" > $D/senha_backup.txt
chown -R wleads:wleads $D
chmod 700 $D
echo "Dados do WhatsApp Leads no servidor: $(du -sh $D | cut -f1). O WhatsApp Leads do servidor continua desligado."
REMOTO
