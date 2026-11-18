#!/usr/bin/env bash
# Prepara o servidor Hostinger (Ubuntu 24.04) para o sistema da MS: segurança, PostgreSQL 17 (a mesma versão do
# Supabase), Caddy (o site com cadeado, certificado renovado sozinho) e Google Chrome (artes da Renovação).
# Roda NO SERVIDOR, como root, uma vez. Pode rodar de novo sem estragar nada.
# Roteiro completo: docs/migracao-hostinger.md. Plano: doc "Plano Hostinger" (opção B, 17/11/2026).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# servidor recém-criado: o Ubuntu costuma estar se atualizando sozinho nos primeiros minutos (espera até 10 min)
APT="apt-get -o DPkg::Lock::Timeout=600"
CHAVE_DO_CLAUDE="ms-whatsapp-servidor"   # comentário da chave pública colada na Hostinger

echo "== 1/8 Ubuntu atualizado e fuso de Brasília"
$APT update -qq
$APT -y -qq -o Dpkg::Options::=--force-confold upgrade
$APT install -y -qq ca-certificates curl gnupg ufw fail2ban unattended-upgrades python3-venv python3-pip \
    rsync sqlite3 openssl python3-systemd debian-keyring debian-archive-keyring apt-transport-https
timedatectl set-timezone America/Sao_Paulo

echo "== 2/8 PostgreSQL 17"
. /etc/os-release
install -d /usr/share/postgresql-common/pgdg
curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list

echo "== 3/8 Caddy (site com cadeado)"
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --batch --yes --dearmor \
    -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list

echo "== 4/8 Google Chrome (desenha as artes da Renovação)"
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --batch --yes --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list

$APT update -qq
# ffmpeg: o WhatsApp Leads (neonize) usa para áudio, vídeo e miniaturas (faltou na 1ª instalação, 17/11/2026)
$APT install -y -qq postgresql-17 postgresql-client-17 caddy google-chrome-stable fonts-liberation fonts-dejavu-core ffmpeg

echo "== 5/8 Banco de dados (só o próprio servidor acessa)"
install -d -m 755 /etc/prospeccao
id prospeccao >/dev/null 2>&1 || useradd --system --home-dir /opt/prospeccao --shell /usr/sbin/nologin prospeccao
id wleads >/dev/null 2>&1 || useradd --system --home-dir /opt/whatsapp-leads --shell /usr/sbin/nologin wleads
chgrp prospeccao /etc/prospeccao && chmod 750 /etc/prospeccao
if [ ! -s /etc/prospeccao/senha_postgres ]; then
    (umask 077; openssl rand -hex 24 > /etc/prospeccao/senha_postgres)
fi
SENHA=$(cat /etc/prospeccao/senha_postgres)
cat > /etc/postgresql/17/main/conf.d/ms.conf <<'EOF'
# Sistema da MS (servidor KVM 2: 8 GB de memória). Fuso UTC como no Supabase (as datas são gravadas pelo sistema).
listen_addresses = 'localhost'
max_connections = 60
shared_buffers = 1GB
effective_cache_size = 4GB
work_mem = 16MB
maintenance_work_mem = 256MB
timezone = 'UTC'
log_timezone = 'UTC'
EOF
systemctl restart postgresql
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='prospeccao'" | grep -q 1; then
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE ROLE prospeccao LOGIN PASSWORD '${SENHA}'"
else
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER ROLE prospeccao PASSWORD '${SENHA}'" >/dev/null
fi
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='prospeccao'" | grep -q 1 \
    || sudo -u postgres createdb -O prospeccao prospeccao

echo "== 6/8 Firewall: entram só o site (80/443) e o acesso com chave (SSH)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "== 7/8 Entrada só com chave, bloqueio de tentativas e atualizações de segurança automáticas"
if grep -q "$CHAVE_DO_CLAUDE" /root/.ssh/authorized_keys 2>/dev/null; then
    cat > /etc/ssh/sshd_config.d/10-ms.conf <<'EOF'
# Entrada só com chave (a senha de root continua valendo no console do painel da Hostinger)
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
    sshd -t && (systemctl restart ssh || systemctl restart ssh.service)
else
    echo "ATENÇÃO: a chave $CHAVE_DO_CLAUDE não está em /root/.ssh/authorized_keys: a entrada por senha continua ligada."
fi
# Ubuntu 24.04 sem /var/log/auth.log: o fail2ban lê as tentativas de entrada pelo journal
cat > /etc/fail2ban/jail.d/ms.local <<'EOF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
bantime = 1h
EOF
systemctl enable fail2ban >/dev/null
systemctl restart fail2ban
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
install -d /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=500M\n' > /etc/systemd/journald.conf.d/ms.conf
systemctl restart systemd-journald

echo "== 8/8 Memória de reserva (2 GB de swap)"
if ! swapon --show | grep -q .; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo
echo "Pronto. PostgreSQL $(sudo -u postgres psql -tAc 'SHOW server_version'), $(caddy version | cut -d' ' -f1), $(google-chrome-stable --version)"
echo "Próximo passo: servidor/pc/enviar_codigo.sh (no computador da MS) e instalar_sistema.sh (aqui)."
