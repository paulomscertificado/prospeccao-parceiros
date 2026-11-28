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
`whatsapp-leads/dados/token_integracao.txt`). O status aparece no pontinho colorido ao lado de "WhatsApp" (Configurações > Comunicação, ou o grupo Operação
do menu para quem não vê as Configurações).
- **Enviar pelo WhatsApp conectado** (Agenda e ficha do lead): a mensagem entra na fila do WhatsApp Leads e
  sai com as pausas, o horário e o limite diário configurados lá. Sempre **um clique por mensagem**.
- **Respostas** dos parceiros chegam sozinhas em até 1 minuto → IA SDR classifica → oportunidade.
- **Resposta automática da SDR** ("vou passar para o time comercial") sai pelo mesmo número, na frente da fila.
- **SAIR** no WhatsApp bloqueia o contato nos dois sistemas.
- Em outro servidor: `WHATSAPP_LEADS_URL` e `WHATSAPP_LEADS_TOKEN` no `.env`.
- **Sistema na nuvem (Vercel):** a nuvem não alcança este computador, então a ligação é invertida: o WhatsApp
  Leads busca as mensagens no site a cada 1 min de dia e 5 min à noite (`ligar_nuvem.bat` + `WHATSAPP_PONTE_TOKEN`).
  Ver `deploy-vercel.md`.

Por que o primeiro contato não é disparado sozinho pelo WhatsApp: a conexão por QR code não é oficial, e
mensagens automáticas para quem não conhece o número violam as regras do WhatsApp e podem bloquear o número.
Para automação total, use a API oficial (abaixo) com contatos que autorizaram (opt-in).


**Sem configurar nada (recomendado para começar):** botões **Copiar mensagem** e **Abrir no WhatsApp**
(abre o WhatsApp Web/aplicativo com o texto pronto; o vendedor revisa e envia). O sistema registra o envio,
respeita opt-out, limite diário e intervalo mínimo.

**API oficial (WhatsApp Cloud API, da Meta):** desde 16/11/2026, cada AR configura o próprio número na tela
**Configurações > WhatsApp > API oficial da Meta** (chaves guardadas criptografadas no banco, teste de conexão,
mensagem de teste e webhook): ver [whatsapp-oficial.md](whatsapp-oficial.md). A forma antiga abaixo (variáveis no
`.env`, um número só) continua valendo para o botão **Enviar pela API** da ficha do lead.
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
- Conta de envio de um lead (`para_enviar`): a do cadastro do responsável; sem conta própria, uma que compartilharam
  com ele (`compartilhadas_para_disparo`: ligada, da mesma AR, primeiro as compartilhadas com a pessoa pelo nome, depois
  as de toda a equipe; pedido da Maria em 18/11/2026, como no WhatsApp). Continua valendo a regra de 13/11/2026 ("cada
  usuário tem seu disparo, nunca misture os disparos de um usuário com outro"): ninguém dispara pelo e-mail de outra
  pessoa sem que ela (ou o administrador/gestor) compartilhe. A principal conta só como do cadastro do dono dela
  (`garantir_principal` dá o primeiro administrador como dono quando falta): compartilhada, ela não vale para os
  disparos de outras pessoas. Conta própria pausada: o toque espera (não troca para a compartilhada). Sem conta: o toque
  espera e a pessoa recebe um aviso por dia.
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
  ainda tem a permissão (NEGAR em Configurações > Exceções por pessoa bloqueia na hora).
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
da reunião. Dias com horário diferente vão separados por ponto e vírgula (23/11/2026, o horário da MS no calendário da
Renovação: `seg-qui 08:00-18:00; sex 08:00-17:30`; `agenda_horarios.faixas_por_dia`; um pedaço errado deixa o
expediente inválido). Os horários oferecidos = expediente − reuniões já marcadas − feriados da pessoa. Integração com
Google Calendar: prevista. Testes: `testes/test_expediente.py`.

### Feriados de cada pessoa (Configurações > Feriados; pedido da Maria em 18/11/2026)
`app/feriados.py`. Cada pessoa tem **cidade e UF** (`Usuario.cidade`/`uf`; Configurações > Usuários ou Minha conta >
"Onde eu trabalho"; `conferir_cidade` grava o nome como o IBGE escreve e avisa com o mais parecido quando não acha). Os
feriados dela = os nacionais (`util.feriados_nacionais`, com Carnaval, Sexta-feira Santa e Corpus Christi) + os do
estado e da cidade da **base de todo o Brasil** (`app/feriados_brasil.json`, ~450 KB: 23 UFs com feriado e os 5.570
municípios, 3.838 com feriado; chaves "PE" e "PE/RECIFE" = `chave_do_local`; montada em 18/11/2026 com os JSON públicos
de github.com/joaopbini/feriados-brasil, licença MIT em `app/feriados_brasil_LICENSE.txt`: data repetida em 2 ou mais
dos anos 2024-2026 = todo ano, só em 2026 = só em 2026, nacionais de fora) + os acertos da marca em Configurações >
Feriados (chave da AR `feriados_locais`, em `banco.CHAVES_DA_AR`: JSON `{"PE": "...", "PE/RECIFE": "..."}`, uma data por
linha, `16/07 Nome` todo ano, `20/11/2026 Nome` só naquele ano e `-16/07` tira da base; um nacional nunca sai;
`ler_lista`). `da_pessoa(db, pessoa)` junta tudo (cache por sessão). Sem UF no cadastro, a pessoa segue o estado e a cidade **da marca**
(`MarcaAR.uf`/`cidade`, Configurações > Marca; `local_da_pessoa`; pedido da Maria em 19/11/2026, "é para puxar
os feriados"); a tela Feriados mostra o quadro dela como "padrão da marca" e salvar a marca remarca os toques de
quem está sem cidade (`admin.salvar_marca` → `_remarcar_feriados`). Para atualizar a base (quando o repositório
ganhar 2027): baixar os JSON de `dados/feriados/{estadual,municipal}/json/<ano>.json` e
`dados/localizacao/municipios/municipios.json` e montar de novo com a mesma regra.
Onde vale:
- **Montagem das campanhas** (todas, não só a Renovação, que já pulava os nacionais): `campanhas._feriados(db, camp)`
  = feriados de quem é a campanha → `cadencias.aplicar(feriados=)` e a aprovação (`_sem_horario_no_passado`; aprovada
  depois, a data empurrada também pula o feriado). Renovação: `renovacao.dias_sem_envio(db, pessoa)` (os "Outros
  feriados" dela + os da pessoa) na montagem, na aprovação e em `remarcar_feriados` (por dono de campanha).
- **Toques já marcados**: `feriados.remarcar(db)` (rotina de hora em hora; também ao salvar os feriados ou a cidade de
  alguém) passa o toque em aberto que cai num feriado de quem envia (`conexoes.responsavel`) para o próximo dia de envio
  dela, sem ficar antes do toque anterior da mesma empresa. Olha só os dias que são feriado para alguém da equipe
  (`_dias_que_podem_ser_feriado`), até 120 dias à frente. A Renovação usa `renovacao.remarcar_feriados`.
- **Tela** (Configurações > Feriados): consulta de qualquer cidade (`painel(db, uf, cidade)`), um quadro por estado e
  cidade da equipe com os feriados da base e os acertos da marca, e os nacionais dos próximos 12 meses.
- **Filas** (e-mail, WhatsApp e API oficial), na hora de enviar: `feriados.adiar_se_feriado(db, t)` adia o toque de
  hoje se hoje é feriado de quem envia (aviso de renovação que só caberia depois do vencimento sai assim mesmo).
- **Reuniões**: `agenda_horarios.horarios_livres` não oferece horário nos feriados da pessoa.
Testes: `testes/test_feriados.py`.

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
