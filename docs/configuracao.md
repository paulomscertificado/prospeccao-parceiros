# Configuração das integrações

Todas as chaves ficam no arquivo **`.env`** (nunca no código, nunca no banco). Depois de editar o `.env`,
feche e abra o sistema. O estado de cada integração aparece em Configurações > **Integrações**.

## 3. Como configurar a IA (Claude)

1. Crie uma conta em <https://console.anthropic.com/>, coloque créditos e gere uma chave em **API Keys**.
2. No `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   IA_MODELO=claude-opus-5-5
   ```
   Modelos: `claude-opus-5-5` (melhor qualidade), `claude-sonnet-5-5` (equilíbrio), `claude-haiku-5-5` (mais barato).
3. Pronto: "Gerar abordagem com IA", "Qual é o próximo melhor passo?", análise de respostas (objeções),
   "Criar template com IA", personalização de campanhas e perguntas livres na IA Comercial passam a usar o Claude.

Sem chave, tudo continua funcionando com **regras próprias** (templates, score, objeções por palavras-chave).
A IA recebe só dados empresariais do lead (nome do escritório, cidade, site, especialidade, status, histórico);
telefones e e-mails não são enviados. O texto do programa de parceria usado pela IA é editado em Configurações > Geral.

## 4. Como configurar o WhatsApp

### WhatsApp conectado pelo WhatsApp Leads (recomendado neste computador)
Se o sistema **WhatsApp Leads** (pasta vizinha `whatsapp-leads`) estiver aberto e com o WhatsApp
conectado, a Prospecção usa esse número **sem configurar nada** (o token é lido de
`whatsapp-leads/dados/token_integracao.txt`). O status aparece no rodapé do menu ("WhatsApp conectado").
- **Enviar pelo WhatsApp conectado** (Agenda e ficha do lead): a mensagem entra na fila do WhatsApp Leads e
  sai com as pausas, o horário e o limite diário configurados lá. Sempre **um clique por mensagem**.
- **Respostas** dos parceiros chegam sozinhas em até 1 minuto → IA SDR classifica → oportunidade.
- **Resposta automática da SDR** ("vou passar para o time comercial") sai pelo mesmo número, na frente da fila.
- **SAIR** no WhatsApp bloqueia o contato nos dois sistemas.
- Em outro servidor: `WHATSAPP_LEADS_URL` e `WHATSAPP_LEADS_TOKEN` no `.env`.
- **Sistema na nuvem (Vercel):** a nuvem não alcança este computador, então a ligação é invertida: o WhatsApp
  Leads busca as mensagens no site a cada 30 s (`ligar_nuvem.bat` + `WHATSAPP_PONTE_TOKEN`). Ver `deploy-vercel.md`.

Por que o primeiro contato não é disparado sozinho pelo WhatsApp: a conexão por QR code não é oficial, e
mensagens automáticas para quem não conhece o número violam as regras do WhatsApp e podem bloquear o número.
Para automação total, use a API oficial (abaixo) com contatos que autorizaram (opt-in).


**Sem configurar nada (recomendado para começar):** botões **Copiar mensagem** e **Abrir no WhatsApp**
(abre o WhatsApp Web/aplicativo com o texto pronto; o vendedor revisa e envia). O sistema registra o envio,
respeita opt-out, limite diário e intervalo mínimo.

**API oficial (WhatsApp Cloud API, da Meta):**
1. Em <https://developers.facebook.com/> crie um app do tipo "Empresa" e adicione o produto **WhatsApp**.
2. Cadastre e verifique o número da empresa e a conta do WhatsApp Business.
3. Crie um **token permanente** (usuário do sistema no Gerenciador de Negócios, permissão `whatsapp_business_messaging`).
4. Crie e aprove **templates** no Gerenciador do WhatsApp. Para iniciar conversa, a Meta só aceita templates aprovados.
   Corpo com 3 variáveis: `{{1}}` nome, `{{2}}` empresa, `{{3}}` vendedor.
5. No sistema, em Cadências > Templates, preencha "Nome do template aprovado na Meta".
6. No `.env`:
   ```
   WHATSAPP_TOKEN=...
   WHATSAPP_PHONE_NUMBER_ID=...
   WHATSAPP_VERIFY_TOKEN=um-texto-que-voce-inventa
   WHATSAPP_APP_SECRET=chave-secreta-do-app
   ```
7. **Webhook** (respostas e "SAIR" automáticos): no painel da Meta, URL de callback
   `https://SEU-DOMINIO/api/webhooks/whatsapp`, token de verificação = `WHATSAPP_VERIFY_TOKEN`, assine o campo `messages`.
   Exige o sistema publicado com HTTPS (ver `deploy.md`). A assinatura `X-Hub-Signature-256` é conferida com o App Secret.

O botão **Enviar pela API** envia **uma** mensagem por clique. Não existe envio em massa.
Respeite a [política comercial do WhatsApp](https://business.whatsapp.com/policy): contate empresas com
quem faz sentido falar, ofereça saída e pare quando pedirem.

### Respostas por e-mail (IMAP) – IA SDR
Configurado na mesma tela (Configurações > E-mail, "A IA SDR lê as respostas desta caixa"). A cada 5 minutos o
sistema lê os e-mails dos **últimos 3 dias, lidos ou não**, em modo só leitura (nada fica marcado como lido). Entram
os que vêm de um lead cadastrado ou que respondem a um e-mail mandado pelo sistema (cabeçalhos In-Reply-To e
References: vale quando um colega do lead responde de outro endereço). Cada e-mail é tratado uma vez só (o
Message-ID fica guardado na mensagem recebida). A resposta automática sai no mesmo fio ("Re:" + In-Reply-To).
Na 1ª leitura depois desta mudança, o sistema começa do zero (`imap_ler_desde`) para não repetir respostas antigas.

### Um e-mail por pessoa (tela E-mail)
`app/contas_email.py` + tabela `contas_email` + `rotas/email_contas.py`. O principal da MS é uma linha com
`principal=1` cujos dados de acesso continuam em Configurações > E-mail (`SMTP_*`/`IMAP_*`); as outras contas guardam
endereço, login e senha de app criptografada (Google Workspace: smtp.gmail.com:587 e imap.gmail.com:993).
- Conta de envio de um lead (`para_enviar`): a do responsável (ligada) → uma compartilhada com ele → a principal, se
  liberada para ele (começa liberada para todos). Sem nenhuma: o toque espera e a pessoa recebe um aviso por dia.
- Compartilhar (`pode_compartilhar`): dono, administrador e gestor. Trocar senha, pausar, remover: dono e administrador.
- Respostas: `rotinas.ler_respostas_por_email` lê todas as caixas com leitura ligada (`para_ler`); conta nova só lê o
  que chegou depois de cadastrada. A resposta automática sai pela mesma conta.
- `Mensagem.conexao` guarda por onde saiu (`email:principal` ou `email:<id>`). Os limites de e-mail continuam da MS
  inteira (mesmo domínio, mesma reputação).

### Domínio e servidor próprios (permissão `email.outro_dominio`, padrão: admin e gestor)
- Tela E-mail > **Onde fica este e-mail?**: Google Workspace (smtp.gmail.com/imap.gmail.com, senha de app de 16
  letras) ou **Outro provedor** (SMTP + porta 465/587/25/2525 e IMAP SSL, senha livre). Porta 465 = SSL direto; as
  outras = STARTTLS. Leitura só por IMAP com SSL (993).
- Endereço fora de `EMAIL_DOMINIO` ou outro servidor exigem a permissão (o servidor confere, não só a tela). Domínio
  gratuito (`util.PROVEDORES_GRATUITOS`) é recusado; servidor tem de ser um nome público (nada de localhost, IP
  interno, `.local`).
- `ContaEmail.dominio_livre` marca a conta; `contas_email.dominio_liberado` confere **a cada envio** se o dono
  ainda tem a permissão (NEGAR na tela Permissões bloqueia na hora).
- A tela confere o DNS do domínio da conta (`dns_email.verificar`): reconhece Google e Microsoft 365 pelo MX (SPF com
  o include certo; DKIM `google` ou `selector1/2`) e, nos outros, procura o DKIM nos seletores mais comuns
  (`dns_email.SELETORES_DKIM`).
- Os limites por hora/dia continuam somados com os da MS (conservador para não queimar nenhum domínio).

### Fila de e-mail: endereço recusado x caixa com problema
- Endereço do lead inválido ou recusado pelo servidor (`email_smtp.ErroDestinatario`): só aquele toque é cancelado
  (o motivo fica na tarefa e no histórico) e a fila segue com os outros.
- Erro da caixa de envio (senha, servidor fora do ar): só aquela conta pausa 15 minutos
  (`fila_email_pausada_ate:email:<conta>`); as outras contas seguem. Na fila automática esse erro **não** vira
  "Não saiu" em Envios a cada tentativa: o toque continua esperando e sai sozinho quando a caixa voltar. Quem cuida
  da conta (responsável pelo lead e, na principal, quem tem `email.gerenciar_todas`) recebe **um aviso por dia**
  (`campanhas._avisar_caixa_com_erro`, marca `aviso_caixa_email:<conta>:<usuário>`). No envio por clique o erro
  continua aparecendo na hora e fica registrado.

### Regras do WhatsApp para a IA SDR
- Primeiro contato com quem **não autorizou** receber mensagens: a SDR prepara a mensagem e a pessoa envia com
  "Abrir no WhatsApp" (a política da Meta exige opt-in para mensagens iniciadas pela empresa pela API).
- Quando o lead responde, abre-se a janela de 24 h: o webhook classifica a resposta e, com
  `sdr_resposta_automatica = 1`, a SDR responde "vou passar para o time comercial" pela API.

- **Disparo automático pelo WhatsApp conectado** (`campanhas.processar_fila_whatsapp`, a cada minuto): com o
  celular conectado no WhatsApp Leads, os passos de WhatsApp das campanhas **aprovadas** saem sozinhos **só para
  quem já conversou com a MS**: marcou "Autorizou receber mensagens da MS pelo WhatsApp" na ficha
  (`consentimento`, com data) ou já mandou mensagem pelo WhatsApp (`campanhas.whatsapp_liberado`). Até 3 por
  minuto, dentro do horário de envio, com os limites daqui e as pausas/limite diário de lá. Celular desconectado:
  tudo espera. Desligar: Configurações > Geral > `enviar_whatsapp_automatico = 0`. Contato frio: sempre 1 clique.

### Agenda de reuniões
Cada usuário tem um **expediente** (Configurações > Usuários, ex.: `seg-sex 09:00-12:00,14:00-18:00`) e a duração
da reunião. Os horários oferecidos = expediente − reuniões já marcadas. Integração com Google Calendar: prevista.

## 5. Como configurar o e-mail (remetente @mscertificados.com.br)

As campanhas saem de um e-mail **do domínio da MS** (o sistema recusa outro domínio). O domínio
`mscertificados.com.br` está no **Google Workspace**.

1. No Google Admin, crie o e-mail das campanhas (sugestão: `parcerias@mscertificados.com.br`).
2. Entre nessa conta, ligue a **verificação em duas etapas** e crie uma **senha de app** em
   `myaccount.google.com/apppasswords` (16 letras).
3. No sistema: **Configurações > E-mail** → e-mail, nome que aparece, senha de app, "Google Workspace",
   marque "A IA SDR lê as respostas desta caixa" → **Salvar** → **Enviar e-mail de teste**.
4. No Gmail dessa conta, confira se o IMAP está ativado (Configurações > Encaminhamento e POP/IMAP).

A tela grava no `.env` (`SMTP_*` e `IMAP_*`) e já passa a usar, sem reiniciar. Na nuvem (Vercel) grava no banco,
criptografado com `CHAVE_CRIPTOGRAFIA`. O domínio exigido é
`EMAIL_DOMINIO` no `.env` (padrão `mscertificados.com.br`).

### Para não cair no spam (DNS do domínio)
A mesma tela confere o DNS (que fica na **Cloudflare**). Situação em 23/10/2026: **tudo configurado**.

| Registro | Situação |
|---|---|
| SPF | OK (`v=spf1 include:_spf.google.com ~all`) |
| DKIM | OK (`google._domainkey`, autenticação ativa no Google Admin) |
| DMARC | OK (`_dmarc`: `v=DMARC1; p=none; rua=mailto:contato@mscertificados.com.br`) — modo observar; depois de algumas semanas sem problemas, pode passar para `p=quarantine` |

Boas práticas: comece com poucos e-mails por dia (ex.: 20) e aumente aos poucos em Configurações
(limites diário, por hora e por domínio); o Google Workspace permite até 2.000 por dia por conta, mas
prospecção fria em volume alto prejudica a reputação do domínio.

### Descadastro
Todo e-mail sai com "responda SAIR" e o cabeçalho `List-Unsubscribe`. Com o sistema publicado na internet
(`URL_PUBLICA` com https), o rodapé ganha um **link de descadastro de 1 clique** e o Gmail/Outlook mostram o
botão "Cancelar inscrição" (exigência do Gmail para quem envia em volume).

Outros provedores: escolha "Outro servidor" e informe SMTP/porta/IMAP (Microsoft 365: `smtp.office365.com:587`
e `outlook.office365.com`; Hostinger: `smtp.hostinger.com:465` e `imap.hostinger.com`).

## 6. Como configurar as APIs externas (busca de escritórios)

### Base da Receita Federal (recomendada, gratuita)
É a fonte mais completa: todos os escritórios de contabilidade **ativos** do Brasil (atividades 6920-6/01 e
6920-6/02), com CNPJ, endereço, telefone e e-mail informados à Receita.
1. Abra <https://arquivos.receitafederal.gov.br> e entre em **Dados > Cadastros > CNPJ > (mês mais recente,
   ex.: 2026-10)**. A Receita publica um mês novo por volta do dia 15.
2. Baixe `Estabelecimentos0.zip` … `Estabelecimentos9.zip` (≈ 5,4 GB), `Municipios.zip` e, para razão social
   e porte, `Empresas0.zip` … `Empresas9.zip` (≈ 1,4 GB). Opcionais: `Socios0.zip` … `Socios9.zip` (≈ 0,7 GB) e
   `Simples.zip` (≈ 0,3 GB), que trazem o **responsável** (sócio-administrador) e o **regime** (MEI / Simples Nacional). O servidor da Receita às vezes fica lento ou bloqueia
   quem abre muitas conexões: baixe **um arquivo por vez**.
3. Coloque tudo numa pasta (na MS: `D:\Base de dados`).
4. Configurações > Integrações > **Importar base** (cole o caminho da pasta) — ou dois cliques em
   `importar_receita.bat`. Leva uns 3 minutos (base de out/2026: 121 mil escritórios em 2,6 min).
   Depois os .zip podem ser apagados.

Como a Receita não informa o site, a busca testa o domínio do e-mail do escritório (ex.: `fiscal@wcont.com.br` →
`www.wcont.com.br`) e só aceita o site se ele responder **e** o nome do domínio combinar com o nome do escritório
(ou a página mostrar o CNPJ). E-mails de Gmail, Hotmail, provedores etc. nunca viram site.
Dos sócios, o sistema guarda **só o nome e o cargo de uma pessoa** por empresa (sócio-administrador; na falta,
administrador, titular, empresário, sócio-gerente, presidente, diretor ou responsável, sempre pessoa física) e a
**quantidade** de sócios. CPF, idade e os demais sócios não são guardados (LGPD). O responsável vira o
"Responsável" do lead; o regime aparece na ficha ("Regime (Receita)"). Leads que já existiam são completados na
importação (só campos vazios; o regime é atualizado), com registro no histórico.
5. Atualize uma vez por mês. A busca passa a oferecer a fonte "Base da Receita Federal".

Obs.: desde julho/2026 os CNPJs novos podem ser **alfanuméricos**; o sistema já aceita esse formato.
O celular informado à Receita vai para as observações ("confirmar se é WhatsApp"): o sistema não supõe que é WhatsApp.

### Google Places (opcional, pago)
Boa cobertura e traz site e telefone atualizados.
1. <https://console.cloud.google.com/> → crie um projeto → ative **Places API (New)** → crie uma chave de API
   (restrinja à Places API).
2. `.env`: `GOOGLE_PLACES_API_KEY=...`
3. Cobrança por pedido conforme a tabela do Google; o sistema faz no máximo 3 páginas (60 lugares) por busca.
   Respeite os termos do Google sobre armazenamento de dados do Places.

### OpenStreetMap (gratuito, sem chave)
Já funciona. No Brasil poucos escritórios estão cadastrados no mapa, por isso serve como complemento.
`OSM_CONTATO` no `.env` identifica a MS para os servidores públicos (exigido pela política de uso).

### BrasilAPI (gratuito, sem chave)
Usada para completar um lead pelo CNPJ (sócios, endereço, atividade, situação cadastral): botão
"Buscar dados públicos" na ficha do lead e enriquecimento automático da busca.

### Outras APIs
Novas fontes entram em `app/prospeccao.py` como uma função `buscar_xxx(cidade, uf, raio_km, limite, tipo)`
que devolve uma lista de dicionários com os campos do lead + `fonte_url` + `origem`. A deduplicação e o
score são aplicados automaticamente.
