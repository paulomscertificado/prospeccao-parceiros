# 10. Como colocar o sistema em produção

Para a equipe acessar de qualquer lugar (e para o webhook do WhatsApp), publique num servidor com HTTPS.

## Opção recomendada: servidor Linux com Docker

Requisitos: um servidor (VPS) com Docker e Docker Compose, e um domínio (ex.: `parceiros.mscertificados.com.br`)
apontando para o IP do servidor.

1. Copie a pasta do projeto para o servidor (sem `.venv`, `dados` e `.env` do seu computador).
2. Crie o `.env` a partir do `.env.example` e preencha:
   ```
   AMBIENTE=producao
   URL_PUBLICA=https://parceiros.mscertificados.com.br
   SECRET_KEY=<gere: python -c "import secrets; print(secrets.token_hex(32))">
   CHAVE_CRIPTOGRAFIA=<gere: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
   POSTGRES_PASSWORD=<senha forte>
   ```
   **Guarde a CHAVE_CRIPTOGRAFIA num cofre de senhas:** sem ela as chaves Pix criptografadas não podem ser lidas.
3. Suba:
   ```bash
   docker compose up -d --build
   ```
   O sistema fica em `127.0.0.1:8001` do servidor, com PostgreSQL em volume próprio.
4. HTTPS com Caddy (certificado automático). Arquivo `/etc/caddy/Caddyfile`:
   ```
   parceiros.mscertificados.com.br {
       reverse_proxy 127.0.0.1:8001
   }
   ```
   `sudo systemctl reload caddy`. (Com Nginx: `proxy_pass http://127.0.0.1:8001;` + Certbot.)
5. Acesse o domínio e crie o administrador **imediatamente** (o primeiro acesso cria o admin).
6. Importe a base da Receita: copie os .zip para o servidor e rode
   `docker compose exec sistema python importar_receita.py /caminho/da/pasta` (monte a pasta como volume).

## Backup
- PostgreSQL: `docker compose exec banco pg_dump -U prospeccao prospeccao > backup_$(date +%F).sql` (agende diário).
- Guarde também o `.env` (com as chaves) em local seguro.

## Atualizar a versão
```bash
docker compose up -d --build
```
As tabelas novas são criadas sozinhas. Mudanças em colunas existentes exigem migração (Alembic).

## Outras opções
- **Render / Railway / Fly.io:** use o `Dockerfile`, crie um PostgreSQL gerenciado, defina as variáveis do `.env`
  no painel e um disco persistente em `/dados` (para logs).
- **Só na rede do escritório:** em um computador fixo, `.env` com `HOST=0.0.0.0` e acesse por `http://IP-DO-PC:8001`.
  Sem HTTPS, use apenas na rede interna.

## Checklist de segurança em produção
- [ ] `AMBIENTE=producao` (cookie só em HTTPS, HSTS ligado)
- [ ] `SECRET_KEY` e `CHAVE_CRIPTOGRAFIA` próprias e guardadas
- [ ] Porta 8001 não exposta para a internet (só via proxy HTTPS)
- [ ] Senhas fortes; desativar usuários que saírem da empresa
- [ ] Backup diário testado
- [ ] `WHATSAPP_APP_SECRET` preenchido se o webhook estiver ativo
