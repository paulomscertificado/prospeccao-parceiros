# Publicar na Vercel (sistema na nuvem)

Endereço: o domínio gratuito da Vercel (`https://<projeto>.vercel.app`, escolha da Maria; domínio próprio é opcional). O sistema roda na Vercel, os dados ficam num
**PostgreSQL** (Neon, pelo Marketplace da Vercel) e o **WhatsApp continua no computador da MS** (WhatsApp Leads).

## O que muda na nuvem (e por quê)

| Neste computador | Na Vercel | Onde está no código |
|---|---|---|
| Banco `dados/banco.db` (SQLite) | PostgreSQL (`DATABASE_URL`) | `config.py`, `banco.py` (`preparar_banco_na_nuvem`) |
| Chaves geradas em `dados/` | `SECRET_KEY` e `CHAVE_CRIPTOGRAFIA` obrigatórias nas variáveis | `config.py` (`FaltaConfiguracao`) |
| Relógio interno a cada 60 s | **Vercel Cron** chama `/api/cron` a cada minuto, com `CRON_SECRET` | `vercel.json`, `rotas/api.py`, `rotinas.rodada(None)` |
| Linhas de execução em segundo plano | **Trabalhos em etapas** retomáveis (campanha, busca, personalização) | `trabalhos.py` |
| Tela de e-mail grava no `.env` | Grava no banco, **criptografado**; todas as cópias releem a cada 30 s | `arquivo_env.py` |
| Prospecção chama o WhatsApp Leads | **Ponte invertida**: o WhatsApp Leads chama a nuvem a cada 30 s | `integracoes/whatsapp_leads.py`, `rotas/api.py`, `whatsapp-leads/app/ponte_nuvem.py` |
| Importar base pela tela | Base copiada do computador por `enviar_para_nuvem.bat` | `enviar_para_nuvem.py` |
| Log em `dados/sistema.log` | Logs da Vercel (Project > Logs) | `api/index.py` |
| Fuso do Windows | Horário de Brasília fixo (UTC-3) | `config.py` (`FUSO_HORARIO`) |

O modo nuvem liga sozinho quando a variável `VERCEL` existe (a Vercel cria) ou com `MODO_NUVEM=1`.

### Limites da Vercel considerados
- **Cron por minuto só no plano Pro.** No Hobby (grátis) a Vercel só aceita cron 1 vez por dia e o deploy
  **falha** com `* * * * *` ([documentação](https://vercel.com/docs/cron-jobs/usage-and-pricing)). No Hobby:
  apague o bloco `"crons"` do `vercel.json` e use um agendador externo gratuito (ex.: cron-job.org) chamando
  `GET https://SEU-SITE/api/cron` a cada minuto com o cabeçalho `Authorization: Bearer <CRON_SECRET>`.
  Atenção: os termos da Vercel reservam o Hobby para uso não comercial.
- **Duração**: `maxDuration` de 300 s (`vercel.json`), aceito no Hobby e no Pro
  ([limites](https://vercel.com/docs/functions/limitations)). Cada chamada do agendador trabalha até
  `SEGUNDOS_POR_RODADA` (240 s) e para; o resto continua no minuto seguinte.
- **Disco**: apagado a toda hora, só `/tmp` aceita gravação. Nada importante é gravado em arquivo.
- **Preset "Other"**: a Vercel reconhece o FastAPI no `requirements.txt` e sugere o preset *FastAPI*; com ele a
  pasta `api/` deixa de virar função e o build **falha** (`The pattern "api/index.py" defined in functions doesn't
  match any Serverless Functions`) ([documentação](https://vercel.com/docs/functions/runtimes/python/api-directory)).
  O `"framework": null` do `vercel.json` força o *Other* (`api/index.py` + `rewrites`), seja qual for a escolha no painel.

### Trabalhos em etapas (`app/trabalhos.py`)
Tabela `trabalhos` (tipo, ref_id, status, estado em JSON). Cada tipo registra `etapa(ref_id, usuario_id, estado,
prazo) -> terminou?`. As etapas processam lotes (`em_lotes`) e param no prazo; o `estado` guarda o ponto exato.
A tabela `travas` impede que duas chamadas mexam no mesmo trabalho (e que duas rodadas enviem o mesmo e-mail);
uma trava vence sozinha se a Vercel cortar a chamada. Neste computador, o trabalho começa na hora numa linha de
execução e, se o sistema for fechado no meio, continua ao abrir de novo.

### Ponte com o WhatsApp Leads
1. A cada 30 s o WhatsApp Leads faz `POST /api/ponte/troca` (cabeçalho `x-token`) com o status do WhatsApp e
   recebe as mensagens esperando (`ponte_whatsapp`), que ficam marcadas "retirada" **antes** da resposta: se a
   conexão cair, a mensagem não sai duas vezes.
2. Coloca cada uma na fila de lá (mesmas pausas, horário, limite diário e lista de quem saiu).
3. `POST /api/ponte/retorno` com o id de cada mensagem lá e as novidades (respostas → IA SDR, status, opt-outs).

Sem sinal do computador por 3 minutos, a tela mostra "WhatsApp desligado" e o botão de envio avisa em vez de
deixar a mensagem esperando sem prazo. Senha: `WHATSAPP_PONTE_TOKEN` (Vercel) = token do `ligar_nuvem.bat`.

## Passo a passo

### 1. Contas (a Maria cria)
1. **GitHub**: repositório **privado** `prospeccao-parceiros`.
2. **Vercel**: conta entrando com o GitHub; plano **Pro** (por causa do cron por minuto).
3. **Banco**: no projeto da Vercel, *Storage* > *Create Database* > **Neon** (Postgres). A base da Receita
   ocupa uns 300 MB aqui e deve ficar entre 600 e 800 MB no Postgres (814 mil empresas, com índices):
   mais que o plano gratuito do Neon (0,5 GB). Escolha um plano pago pequeno.
   A Vercel cria a variável `DATABASE_URL` sozinha.

### 2. Código no GitHub
Enviar a pasta `prospeccao-parceiros` para o repositório. O `.gitignore` já deixa de fora `dados/`, `.env`
e `.venv/`. O `.vercelignore` deixa de fora também testes, documentação e os `.bat`.

### 3. Variáveis
Dois cliques em **`enviar_para_nuvem.bat`** → informe o endereço do site → abre-se
`dados/variaveis_para_vercel.txt` com tudo pronto: `AMBIENTE`, `URL_PUBLICA`, `SECRET_KEY`,
`CHAVE_CRIPTOGRAFIA` (a mesma daqui, para as chaves Pix dos parceiros continuarem legíveis), `CRON_SECRET`,
`WHATSAPP_PONTE_TOKEN` e as chaves que já estavam no `.env`. Cole em *Settings > Environment Variables*
e **apague o arquivo**.

### 4. Dados
No mesmo `enviar_para_nuvem.bat`, cole o endereço de conexão do Neon (*Storage* > banco > *.env.local* >
`DATABASE_URL`). Ele copia leads, histórico, usuários, campanhas, configurações e a base da Receita
(10 a 20 minutos). Rodar de novo pergunta antes de apagar o que estiver lá (digitar `SIM`).

### 5. Publicar
Na Vercel: *Add New > Project* > importar o repositório > *Deploy* (o *Framework Preset* fica *Other* pelo
`vercel.json`; se o painel mostrar *FastAPI*, troque para *Other*). Teste em `https://<projeto>.vercel.app`:
login com o mesmo e-mail e senha, painel, uma busca pequena.

### 6. Endereço do site
Usamos o endereço gratuito da Vercel (*Settings > Domains* mostra o `.vercel.app`). A variável `URL_PUBLICA`
precisa ser **exatamente** esse endereço (com https), senão o link de descadastro dos e-mails aponta para o lugar
errado: ao mudar, faça *Redeploy*. Domínio próprio (ex.: `parceiros.mscertificados.com.br`) é opcional: *Settings >
Domains* + registro CNAME no DNS, e trocar a `URL_PUBLICA`.
O **DKIM** e o **DMARC** do e-mail continuam precisando do DNS do mscertificados.com.br (ver `configuracao.md`, seção 5).

### 7. WhatsApp
No computador do WhatsApp Leads: dois cliques em **`ligar_nuvem.bat`** (pasta `whatsapp-leads`) → endereço do
site + `WHATSAPP_PONTE_TOKEN` → feche e abra o `iniciar.bat` dele. Em até 1 minuto o rodapé da Prospecção
mostra "WhatsApp conectado". **O computador precisa ficar ligado** com o WhatsApp Leads aberto.

### 8. E-mail
Configurações > E-mail na nuvem (fica guardado criptografado no banco) > *Enviar e-mail de teste*.

## Conferir se está tudo rodando
- Vercel > projeto > *Cron Jobs*: `/api/cron` a cada minuto, com respostas 200.
- *Logs*: mensagens "Fila: N e-mails enviados", "Prospecção ... respostas".
- Uma campanha nova sai de "Na fila" em até 1 minuto.

## Atualizar
Cada envio para o GitHub publica sozinho. Mudanças de tabelas são aplicadas no primeiro acesso (versão do
esquema guardada em `configuracoes.versao_esquema`).
