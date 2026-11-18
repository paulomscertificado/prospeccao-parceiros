# Migração para o servidor da Hostinger (opção B): roteiro da noite

Decidido em 17/11/2026 (doc "Plano Hostinger – servidor próprio do sistema",
https://claude.ai/artifact/BV6pabhv1V2thY3Eh8Xyg4): o sistema inteiro (site, banco e WhatsApp Leads) sai da Vercel,
do Supabase e do computador da MS e vai para um Hostinger VPS KVM 2 no Brasil. A Maria pediu a migração na noite de
**17/11/2026, a partir das 22h**: as etapas 0 a 3 do plano numa noite só, com um ponto de decisão antes da virada. A
Vercel e o Supabase ficam intactos, de reserva, por 30 dias (etapa 4).

Tudo que roda está em `servidor/` (testes em `testes/test_servidor_hostinger.py`):

| Arquivo | Onde roda | O que faz |
| --- | --- | --- |
| `instalar_servidor.sh` | servidor (root), 1 vez | Ubuntu atualizado, PostgreSQL 17, Caddy, Google Chrome, firewall (22/80/443), entrada só com chave, fail2ban, atualizações automáticas, swap |
| `instalar_sistema.sh <endereço>` | servidor (root) | Instala/atualiza Prospecção e WhatsApp Leads, serviços, Caddy (cadeado). Não liga o relógio nem o WhatsApp Leads pela 1ª vez |
| `migrar_banco.sh <arquivo>` | servidor (root) | Copia o Supabase inteiro (pg_dump/pg_restore, só lê o Supabase) e confere as linhas tabela por tabela (`conferir_contagens.py`). Recusa se o servidor já for o sistema em uso |
| `modo_ensaio.sh ligar/desligar` | servidor (root) | Bloqueia a saída de e-mail (SMTP/IMAP) enquanto o oficial ainda é a Vercel |
| `prospeccao*.service/.timer`, `whatsapp-leads-copia.*`, `Caddyfile.modelo` | servidor | Site (uvicorn em 127.0.0.1:8001, `api.index:app`), relógio a cada minuto (`/api/cron`), cópias diárias 06:10 e 06:30 |
| `pc/preparar_migracao.py <endereço>` | computador da MS | Monta as configurações em `dados/migracao/` (tem senhas; só mostra nomes) |
| `pc/enviar_codigo.sh <IP>` | computador da MS (Git Bash) | Manda o código dos dois sistemas (sem dados). Também é o jeito de publicar depois da virada |
| `pc/enviar_configuracao.sh <IP>` | computador da MS (Git Bash) | Põe as configurações no servidor e apaga `dados/migracao` daqui |
| `pc/enviar_whatsapp_dados.sh <IP>` | computador da MS (Git Bash) | Na virada: leva banco, sessões e mídias do WhatsApp Leads (recusa se o daqui estiver ligado) |
| `pc/chamar_cron_servidor.ps1` | computador da MS | Nova versão do `dados/chamar_cron.ps1` depois da virada: não religa o WhatsApp Leads, baixa as cópias do servidor para o Drive, relógio só de reserva |
| `pc/baixar_copias.py` | computador da MS | Baixa as cópias do dia (Prospecção e WhatsApp Leads) e manda para o Google Drive |
| `vercel_redirecionar.json` | Vercel | `vercel.json` de depois da virada: o endereço antigo leva para o novo (links de descadastro dos e-mails já enviados continuam valendo) |

## Configurações (conferido em 17/11/2026)

As 12 configurações da Vercel estão marcadas como **sensíveis**: o `vercel env pull` devolve só "[SENSITIVE]". Por isso
o `preparar_migracao.py` monta tudo com o que está no computador da MS, conferido contra a nuvem no mesmo dia: a chave de
criptografia (`dados/chave_criptografia.txt`) abriu os valores criptografados do banco da nuvem e a chave de sessão
(`dados/chave_sessao.txt`) gerou um link de descadastro que o site aceitou. `CRON_SECRET` e `WHATSAPP_PONTE_TOKEN` vêm do
`dados/agendador.txt`; `IA_MODELO` e `OSM_CONTATO` do `.env`. E-mail (SMTP/IMAP) e a chave da CNPJá estão no próprio banco
(`env_criptografado`), então vão junto com a cópia. A chave da Anthropic do `.env` NÃO vai (a IA não está ligada na nuvem).

O banco do Supabase é PostgreSQL 17.11, 47 tabelas, 140 MB, sem funções, gatilhos, políticas ou tipos de extensões no
schema public: a cópia por `pg_dump`/`pg_restore` é exata (sequências inclusive). O `pg_dump` usa o modo "Session pooler"
(porta 5432 do mesmo endereço; o "Transaction pooler" da porta 6543 não serve para isso).

## O que a Maria faz (antes das 22h; quanto antes, melhor)

1. Contratar na Hostinger o **VPS KVM 2 por 24 meses**: local **Brasil**, sistema **Ubuntu 24.04** sem painel (o da MS veio com o **Ubuntu 26.04**, Python 3.14: funcionou igual). Criar a
   senha de root e guardar só com ela. Colar a chave SSH (está no doc do plano e em
   `whatsapp-leads/docs/servidor-nuvem-passo-a-passo.md`).
2. Mandar o **IP** e o **nome do servidor** (hostname, algo como `srv123456.hstgr.cloud`), que aparecem no painel do VPS.
3. Escolher o endereço: (1) o nome do servidor (recomendado para hoje: grátis, neutro, sem mexer em DNS); (2)
   `sistema.mscertificados.com.br` (precisa de um registro no DNS); (3) um domínio da plataforma.
4. Avisar a equipe: o sistema fica fora do ar das 22h às 23h30. Depois o endereço antigo leva para o novo, e todos entram
   de novo (senha e código).
5. Às 22h, estar com os celulares dos números do WhatsApp à mão (se algum pedir o QR code de novo).

## Ensaio (assim que o IP chegar; não mexe no sistema de hoje)

Na pasta `prospeccao-parceiros` deste computador (o código desta pasta já com a migração na `main`):

```bash
ssh -i ~/.ssh/ms_servidor -o StrictHostKeyChecking=accept-new root@IP "uname -a"                          # entra só com a chave
scp -i ~/.ssh/ms_servidor servidor/instalar_servidor.sh root@IP:/root/ && ssh -i ~/.ssh/ms_servidor root@IP "sed -i 's/\r$//' /root/instalar_servidor.sh && bash /root/instalar_servidor.sh"
.venv/Scripts/python.exe servidor/pc/preparar_migracao.py ENDERECO
bash servidor/pc/enviar_codigo.sh IP
bash servidor/pc/enviar_configuracao.sh IP
ssh -i ~/.ssh/ms_servidor root@IP "bash /opt/prospeccao/servidor/modo_ensaio.sh ligar && bash /opt/prospeccao/servidor/instalar_sistema.sh ENDERECO && bash /opt/prospeccao/servidor/migrar_banco.sh /root/migracao/supabase_sessao.url"
```

Servidor da MS (17/11/2026): **srv2170631.hstgr.cloud** (IP 187.53.121.102), o endereço escolhido pela Maria. Ensaio
feito na mesma noite: 47 tabelas iguais (226.098 linhas), cadeado e arte da Renovação funcionando.

Depois: `https://ENDERECO/login` abre com cadeado; a Maria pode entrar e **só olhar** (Dashboard, Leads, Renovação,
Conversas). Com o modo ensaio o servidor não manda nem lê e-mail, o relógio e o WhatsApp Leads do servidor estão
desligados, mas ações como "Buscar agora" (créditos da CNPJá) ainda gastariam de verdade: não clicar. Teste da arte:

```bash
sudo -u wleads bash -c 'set -a; . /etc/whatsapp-leads/ambiente; set +a; export HOME=/opt/whatsapp-leads/dados; cd /opt/whatsapp-leads && .venv/bin/python -c "from app import arte_aviso; print(len(arte_aviso.gerar({\"modelo\": \"cnpj\", \"tipo\": \"A1\", \"nome\": \"TESTE DA MIGRACAO\", \"doc\": \"\", \"data\": \"2026-12-31\"})), \"bytes de PNG\")"'
```

Se o Chrome reclamar de "sandbox": acrescentar `ARTE_CHROME_EXTRA=--no-sandbox` em `/etc/whatsapp-leads/ambiente`.

## A noite (22:00)

| Hora | Passo | Conferir |
| --- | --- | --- |
| 22:00 | **Congelar o de hoje.** No computador: guardar `dados/chamar_cron.ps1` como `dados/chamar_cron_vercel.ps1`, copiar `servidor/pc/chamar_cron_servidor.ps1` para `dados/chamar_cron.ps1`; em `dados/agendador.txt`: `SITE=https://ENDERECO` e `SERVIDOR_IP=IP`. Parar o WhatsApp Leads daqui (PowerShell abaixo) | Porta 8000 fechada; ele não volta sozinho (a tarefa nova não religa) |
| 22:05 | **Banco:** `ssh root@IP "bash /opt/prospeccao/servidor/migrar_banco.sh /root/migracao/supabase_sessao.url"` | "tabelas iguais" e site respondendo 200 |
| 22:15 | **WhatsApp Leads:** `bash servidor/pc/enviar_whatsapp_dados.sh IP`, depois `ssh root@IP "systemctl enable --now whatsapp-leads"` | `journalctl -u whatsapp-leads -n 50` sem erro; `dados/sistema.log` com a ponte em 200; tela WhatsApp do site novo com os números conectados (senão, QR code) |
| 22:30 | **Relógio e e-mail:** `ssh root@IP "bash /opt/prospeccao/servidor/modo_ensaio.sh desligar && systemctl enable --now prospeccao-relogio.timer"` | `journalctl -u prospeccao-relogio -n 5` sem falha |
| 22:40 | **Portão da virada** (lista abaixo) | Tudo marcado; senão, voltar (plano A) |
| 22:55 | **Endereço antigo leva para o novo:** na `main`, `vercel.json` = `servidor/vercel_redirecionar.json` com o endereço; commit e push | Vercel "Ready"; o endereço antigo responde 307 para o novo |
| 23:05 | **Cópias:** `.venv/Scripts/python.exe servidor/pc/baixar_copias.py` (depois da 1ª cópia do servidor; rodar `systemctl start prospeccao-copia whatsapp-leads-copia` no servidor para ter uma já) | Arquivos de hoje em `dados/backups`, `whatsapp-leads/dados/backups` e no Google Drive |
| 23:10 | Maria avisa a equipe | |

Parar o WhatsApp Leads deste computador (PowerShell):

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*whatsapp-leads*iniciar.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Portão da virada (todos):
- [ ] contagens iguais (passo 22:05);
- [ ] a Maria entra no site novo com senha e código;
- [ ] Dashboard, Leads, Renovação e Conversas abrem com os dados de hoje;
- [ ] tela WhatsApp: os números conectados;
- [ ] Renovação, área de teste: um aviso "[TESTE]" chega no WhatsApp e no e-mail de quem testa, com a arte;
- [ ] o relógio roda sem erro há pelo menos 5 minutos.

## Se der errado

- **Plano A, antes do passo 22:55** (a Vercel ainda atende): no servidor `systemctl disable --now prospeccao-relogio.timer
  whatsapp-leads`; no computador, voltar `dados/chamar_cron_vercel.ps1` para `dados/chamar_cron.ps1` e o `SITE` antigo em
  `dados/agendador.txt`. Em 1 minuto a tarefa religa o WhatsApp Leads daqui (os dados daqui foram copiados, não movidos).
  Mensagens trocadas pelo WhatsApp do servidor nesse meio tempo ficam só lá. O Supabase não foi tocado.
- **Plano B, depois do passo 22:55:** `git revert` do commit do `vercel.json` (push) e depois o plano A. Vale só na mesma
  noite: o que for gravado no servidor depois disso não está no Supabase.
- **WhatsApp Leads não funciona no servidor** (biblioteca, sessões): ele pode continuar NESTE computador falando com o
  site novo pela internet. Basta voltar a versão antiga da tarefa (religa o WhatsApp Leads daqui) com
  `prospeccao_nuvem.json` do WhatsApp Leads apontando para `https://ENDERECO`.

## Como foi a virada (17/11/2026)

Feita na mesma noite do ensaio, das 23:28 às 23:45, com o portão completo: cópia final igual (47 tabelas, 226.098
linhas), WhatsApp Leads no servidor (principal e Lucas Pinheiro em modo teste, Maria Eduarda conectado, Paulo Lucas
desconectado de propósito por causa da restrição do WhatsApp), relógio sem falha, e-mail conferido entrando no SMTP e
no IMAP sem enviar nada (o teste da Renovação não rodou: quem assina, o Paulo Lucas, não tem conta de e-mail, e a MS
estava sem número de verdade conectado), arte desenhada no servidor. Endereço antigo redirecionando (307) desde 23:45.
Ajustes da noite: Caddy não ligava (arquivo de registro criado pelo root; corrigido no `instalar_sistema.sh`), faltava
o ffmpeg (instalado; agora no `instalar_servidor.sh`) e o CRON_SECRET foi trocado no servidor e no `dados/agendador.txt`
porque apareceu na conversa ao listar processos (a linha do curl do relógio mostra o segredo: não listar com `ps`).

## Depois da virada

- **Publicar** uma versão nova: testes, commit e push (a Vercel só redireciona), depois `bash servidor/pc/enviar_codigo.sh
  IP` e `ssh root@IP "bash /opt/prospeccao/servidor/instalar_sistema.sh ENDERECO"`.
- Registros: `journalctl -u prospeccao`, `-u prospeccao-relogio`, `-u whatsapp-leads`; acessos em `/var/log/caddy/`.
- **Etapa 4 (30 dias depois, com o OK da Maria):** pausar o Supabase (guardar antes o último `/root/migracao/*.dump`) e
  manter a Vercel só redirecionando.
