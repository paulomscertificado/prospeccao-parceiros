#!/usr/bin/env bash
# Instala ou atualiza a Prospecção e o WhatsApp Leads no servidor. O código já foi enviado para /opt/prospeccao e
# /opt/whatsapp-leads (servidor/pc/enviar_codigo.sh) e as configurações para /etc (servidor/pc/enviar_configuracao.sh).
# Roda NO SERVIDOR, como root. Pode rodar de novo: é também o jeito de publicar uma versão nova.
# Uso: bash /opt/prospeccao/servidor/instalar_sistema.sh <endereço do sistema, ex.: srv123456.hstgr.cloud>
#
# Cuidado (ver docs/migracao-hostinger.md): este roteiro NÃO liga o relógio (filas e envios automáticos) e NÃO liga o
# WhatsApp Leads pela primeira vez. Os dois só ligam na virada, depois que o computador da MS parou os dele; senão
# o mesmo envio sairia duas vezes e o mesmo número do WhatsApp ficaria ligado em dois lugares.
set -euo pipefail
DOMINIO=${1:?Informe o endereço do sistema, ex.: srv123456.hstgr.cloud}
P=/opt/prospeccao
W=/opt/whatsapp-leads
S=$P/servidor

[ -s /etc/prospeccao/senha_postgres ] || { echo "Rode antes o instalar_servidor.sh."; exit 1; }
[ -s /etc/prospeccao/ambiente.base ] || { echo "Falta /etc/prospeccao/ambiente.base (servidor/pc/enviar_configuracao.sh)."; exit 1; }
[ -f $P/requirements.txt ] || { echo "Falta o código em $P (servidor/pc/enviar_codigo.sh)."; exit 1; }

echo "== 1/6 Configurações (as da Vercel + banco deste servidor + endereço)"
SENHA=$(cat /etc/prospeccao/senha_postgres)
{
    grep -v -E '^(DATABASE_URL|URL_PUBLICA|PP_PASTA_DADOS|MODO_NUVEM)=' /etc/prospeccao/ambiente.base
    echo "DATABASE_URL=postgresql://prospeccao:${SENHA}@127.0.0.1:5432/prospeccao"
    echo "URL_PUBLICA=https://${DOMINIO}"
    echo "PP_PASTA_DADOS=$P/dados"
    echo "MODO_NUVEM=1"
} > /etc/prospeccao/ambiente.novo
install -m 640 -o root -g prospeccao /etc/prospeccao/ambiente.novo /etc/prospeccao/ambiente
rm -f /etc/prospeccao/ambiente.novo
for chave in SECRET_KEY CHAVE_CRIPTOGRAFIA CRON_SECRET WHATSAPP_PONTE_TOKEN AMBIENTE; do
    grep -q "^${chave}=" /etc/prospeccao/ambiente || { echo "Falta ${chave} nas configurações. Nada foi ligado."; exit 1; }
done

echo "== 2/6 Bibliotecas da Prospecção"
[ -x $P/.venv/bin/python ] || python3 -m venv $P/.venv
$P/.venv/bin/pip install -q --upgrade pip
$P/.venv/bin/pip install -q -r $P/requirements.txt
install -d -m 700 -o prospeccao -g prospeccao $P/dados $P/dados/backups
[ -f $P/dados/senha_backup.txt ] && chown prospeccao:prospeccao $P/dados/senha_backup.txt && chmod 600 $P/dados/senha_backup.txt

echo "== 3/6 Bibliotecas do WhatsApp Leads"
if [ -f $W/requirements.txt ]; then
    [ -x $W/.venv/bin/python ] || python3 -m venv $W/.venv
    $W/.venv/bin/pip install -q --upgrade pip
    $W/.venv/bin/pip install -q -r $W/requirements.txt
    install -d -m 700 -o wleads -g wleads $W/dados
    chown -R wleads:wleads $W/dados
    [ -s /etc/whatsapp-leads/ambiente ] || echo "ATENÇÃO: falta /etc/whatsapp-leads/ambiente (servidor/pc/enviar_configuracao.sh)."
else
    echo "ATENÇÃO: o código do WhatsApp Leads não está em $W (servidor/pc/enviar_codigo.sh)."
fi

echo "== 4/6 Serviços (site, relógio, cópias de segurança)"
for u in prospeccao.service prospeccao-relogio.service prospeccao-relogio.timer prospeccao-copia.service \
         prospeccao-copia.timer whatsapp-leads-copia.service whatsapp-leads-copia.timer; do
    install -m 644 $S/$u /etc/systemd/system/$u
done
[ -f $W/servidor/whatsapp-leads.service ] && install -m 644 $W/servidor/whatsapp-leads.service /etc/systemd/system/whatsapp-leads.service
systemctl daemon-reload
systemctl enable prospeccao.service prospeccao-copia.timer whatsapp-leads-copia.timer >/dev/null
systemctl start prospeccao-copia.timer whatsapp-leads-copia.timer

echo "== 5/6 Site com cadeado (Caddy) em https://${DOMINIO}"
sed "s/__DOMINIO__/${DOMINIO}/g" $S/Caddyfile.modelo > /etc/caddy/Caddyfile
install -d -o caddy -g caddy /var/log/caddy
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
# o validate roda como root e cria o arquivo de registro como root: o Caddy (usuário caddy) não conseguia abrir
# e não ligava (17/11/2026, 1ª instalação)
chown -R caddy:caddy /var/log/caddy
systemctl reload caddy || systemctl restart caddy

echo "== 6/6 Ligando o que já pode ligar"
TABELAS=$(sudo -u postgres psql -d prospeccao -tAc "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
if [ "$TABELAS" -gt 0 ]; then
    systemctl restart prospeccao.service
    for _ in $(seq 1 30); do
        curl -fsS -o /dev/null http://127.0.0.1:8001/login && break
        sleep 2
    done
    curl -fsS -o /dev/null -w "Site respondendo: %{http_code}\n" http://127.0.0.1:8001/login || echo "O site não respondeu: journalctl -u prospeccao -n 50"
else
    echo "Banco ainda vazio: o site só liga depois da cópia do banco (servidor/migrar_banco.sh)."
fi
if systemctl is-enabled --quiet whatsapp-leads.service 2>/dev/null; then
    systemctl restart whatsapp-leads.service
    echo "WhatsApp Leads reiniciado (já estava ligado neste servidor)."
else
    echo "WhatsApp Leads instalado e DESLIGADO: só liga na virada (docs/migracao-hostinger.md)."
fi
if systemctl is-enabled --quiet prospeccao-relogio.timer 2>/dev/null; then
    echo "Relógio ligado (filas e envios automáticos rodando neste servidor)."
else
    echo "Relógio DESLIGADO: só liga na virada (systemctl enable --now prospeccao-relogio.timer)."
fi
echo "Pronto."
