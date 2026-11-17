#!/usr/bin/env bash
# Copia o banco do Supabase (inteiro: todas as tabelas do schema public, inclusive as conversas do WhatsApp) para o
# PostgreSQL deste servidor e confere a quantidade de linhas tabela por tabela. Só LÊ o Supabase.
# Roda NO SERVIDOR, como root. Apaga e refaz o banco DESTE servidor a cada vez (serve para ensaiar e para a virada).
# Uso: bash /opt/prospeccao/servidor/migrar_banco.sh /root/migracao/supabase_sessao.url
#   O arquivo tem uma linha: o endereço do Supabase no modo "Session pooler" (porta 5432), postgresql://...
#   (feito pelo servidor/pc/preparar_migracao.py e enviado pelo servidor/pc/enviar_configuracao.sh).
set -euo pipefail
ARQUIVO_ORIGEM=${1:?Informe o arquivo com o endereço do Supabase}
# Depois da virada este servidor é o sistema de verdade: copiar de novo APAGARIA o que foi feito aqui desde então
if systemctl is-enabled --quiet prospeccao-relogio.timer 2>/dev/null || systemctl is-enabled --quiet whatsapp-leads.service 2>/dev/null; then
    echo "O relógio ou o WhatsApp Leads já estão ligados neste servidor: ele já é o sistema em uso."
    echo "Copiar o Supabase de novo apagaria os dados daqui. Nada foi feito."
    exit 1
fi
ORIGEM=$(head -n1 "$ARQUIVO_ORIGEM" | tr -d '\r\n')
SENHA=$(cat /etc/prospeccao/senha_postgres)
DESTINO="postgresql://prospeccao:${SENHA}@127.0.0.1:5432/prospeccao"
PASTA=/root/migracao
install -d -m 700 "$PASTA"
DUMP="$PASTA/supabase_$(date +%Y%m%d_%H%M%S).dump"
inicio=$(date +%s)

echo "== 1/5 Lendo o Supabase (só leitura; uns minutos)"
pg_dump --format=custom --no-owner --no-privileges --no-publications --no-subscriptions --no-security-labels \
    --schema=public --dbname="$ORIGEM" --file="$DUMP"
echo "   cópia: $(du -h "$DUMP" | cut -f1)"

echo "== 2/5 Parando o site deste servidor e refazendo o banco vazio"
systemctl stop prospeccao.service 2>/dev/null || true
sudo -u postgres psql -v ON_ERROR_STOP=1 -q -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='prospeccao' AND pid <> pg_backend_pid()" >/dev/null
sudo -u postgres dropdb --if-exists prospeccao
sudo -u postgres createdb -O prospeccao prospeccao

echo "== 3/5 Gravando a cópia no banco deste servidor"
# O schema public já existe no banco novo: tira da lista a criação e o comentário dele (senão o pg_restore para)
pg_restore --list "$DUMP" | grep -v -E ' SCHEMA - public |COMMENT - SCHEMA public' > "$PASTA/lista.txt"
pg_restore --no-owner --no-privileges --exit-on-error --use-list="$PASTA/lista.txt" --dbname="$DESTINO" "$DUMP"
sudo -u postgres psql -d prospeccao -q -c "ANALYZE"

echo "== 4/5 Conferindo as linhas de cada tabela (Supabase x servidor)"
/opt/prospeccao/.venv/bin/python /opt/prospeccao/servidor/conferir_contagens.py "$ORIGEM" "$DESTINO"

echo "== 5/5 Ligando o site deste servidor (o relógio continua como estava)"
systemctl start prospeccao.service
for _ in $(seq 1 30); do
    curl -fsS -o /dev/null http://127.0.0.1:8001/login && break
    sleep 2
done
curl -fsS -o /dev/null -w "   site respondendo: %{http_code}\n" http://127.0.0.1:8001/login \
    || { echo "   O site não respondeu: journalctl -u prospeccao -n 50"; exit 1; }
# Guarda só as 3 cópias mais novas (têm dados de clientes; ficam só para o root)
ls -1t "$PASTA"/supabase_*.dump | tail -n +4 | xargs -r rm -f
echo "Pronto em $(( ($(date +%s) - inicio) / 60 )) min."
