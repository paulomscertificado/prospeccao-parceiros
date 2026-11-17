#!/usr/bin/env bash
# Modo ensaio do servidor: bloqueia a SAÍDA de e-mail (envio SMTP e leitura IMAP) enquanto o sistema de verdade ainda é
# o da Vercel. Assim, um clique de teste no site do servidor (que tem as mesmas senhas de e-mail) não manda nada em
# dobro nem lê a caixa de respostas antes da hora. O WhatsApp e o relógio do servidor ficam desligados à parte.
# Roda NO SERVIDOR, como root.   Uso: bash modo_ensaio.sh ligar | desligar | ver
set -euo pipefail
PORTAS=(25 465 587 993 995)
case "${1:-ver}" in
    ligar)
        for p in "${PORTAS[@]}"; do ufw deny out "$p/tcp" >/dev/null; done
        echo "Modo ensaio LIGADO: o servidor não manda nem lê e-mail."
        ;;
    desligar)
        for p in "${PORTAS[@]}"; do ufw --force delete deny out "$p/tcp" >/dev/null 2>&1 || true; done
        echo "Modo ensaio DESLIGADO: o servidor manda e lê e-mail normalmente."
        ;;
    ver)
        if ufw status | grep -q "587/tcp.*DENY OUT"; then echo "Modo ensaio: LIGADO"; else echo "Modo ensaio: desligado"; fi
        ;;
    *)
        echo "Uso: bash modo_ensaio.sh ligar | desligar | ver"; exit 2
        ;;
esac
