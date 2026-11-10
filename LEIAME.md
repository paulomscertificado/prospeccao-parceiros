# Prospecção de Parceiros – MS Certificação Digital

Sistema para encontrar escritórios de contabilidade, transformá-los em **parceiros** que indicam
clientes e acompanhar vendas, comissões e renovações de certificados.

```
ENCONTRAR → QUALIFICAR → PERSONALIZAR → CONTATAR → ACOMPANHAR → CONVERTER → MANTER → RENOVAR
```

## 1. Instalar (uma vez só)

1. Tenha o Python instalado (com a opção **"Add Python to PATH"** marcada).
2. Dê dois cliques em **`instalar.bat`** e espere aparecer "Tudo pronto!".

## 2. Abrir o sistema

1. Dê dois cliques em **`iniciar.bat`**. O navegador abre em `http://localhost:8001`.
2. **Deixe a janela preta aberta** enquanto usa o sistema. Para desligar, feche essa janela.
3. No primeiro acesso, crie a conta de **administrador** (seu nome, e-mail e senha).

Quer conhecer o sistema com dados de exemplo? Depois de criar o administrador, dê dois cliques em
**`popular_demo.bat`**. Ele cria leads, parceiros e vendas **fictícios**. Para apagar tudo depois:
Configurações > LGPD e dados > **Apagar dados de demonstração**.

### Sistema na internet (Vercel)
Quando o sistema estiver publicado (ex.: `https://prospeccao-parceiros.vercel.app`), é só abrir esse endereço
no navegador, de qualquer lugar: não precisa do `iniciar.bat`. O passo a passo da publicação está em
[`docs/deploy-vercel.md`](docs/deploy-vercel.md) (dois cliques em **`enviar_para_nuvem.bat`** levam seus dados).
- **WhatsApp:** o computador com o **WhatsApp Leads** precisa ficar **ligado e aberto**. Ele é ligado ao site
  uma vez só, pelo `ligar_nuvem.bat` da pasta `whatsapp-leads`.
- Campanhas e buscas começam em **até 1 minuto** depois do clique (a tela mostra "Na fila").
- Menu **Conversas**: todas as conversas do número conectado (lista à esquerda, conversa à direita), com
  busca por nome ou telefone. Escreva e aperte **Enter** para responder. **+ Nova mensagem** manda para qualquer
  celular (digite com DDD). Sai na hora pelo número da MS; quem pediu SAIR não recebe.
  Para trocar o nome de um contato, abra a conversa e clique em **✏️ Editar nome** (o nome muda também no
  WhatsApp Leads).
  As conversas antigas (até 1 ano) chegam quando o celular é conectado pelo QR code. Para puxar de novo: menu
  WhatsApp > Desligar este número > Conectar com QR code.
- Menu **WhatsApp**: a mesma tela do WhatsApp Leads, dentro do site. Mostra se o celular está conectado e
  tem os botões **Conectar com QR code**, **Usar modo teste**, **Pausar**, **Desligar** e as **regras de envio**.
  O QR code aparece ali mesmo, para ler com o celular. Os botões levam alguns segundos, porque quem faz a
  conexão é o computador da MS (que precisa estar ligado com o WhatsApp Leads aberto).

## 3. O dia a dia

| Quero... | Onde |
|---|---|
| Encontrar escritórios numa cidade | **Prospecção**: escreva "Quero encontrar 100 escritórios contábeis em Recife" e clique em Buscar |
| Ver e filtrar meus leads | **Leads** (lista) ou **Leads > Pipeline** (Kanban: arraste os cards) |
| Saber com quem falar hoje | **Agenda**: "Hoje você possui X follow-ups pendentes" |
| Mandar a mensagem | Na Agenda ou na ficha do lead: **Copiar mensagem** ou **Abrir no WhatsApp** |
| Registrar que o lead respondeu | Botão **Respondeu** na Agenda (cole a resposta: o sistema sugere o que responder) |
| Qualificar e gerar abordagem | Ficha do lead: **Qualificar lead**, **Gerar abordagem com IA**, **Qual é o próximo melhor passo?** |
| Transformar em parceiro | Ficha do lead: **Converter em parceiro** (ou arraste para a coluna "Parceiro") |
| Registrar uma venda | **Vendas** (a comissão e o vencimento são calculados sozinhos) |
| Ver quem vai vencer | **Vencimentos** (alertas 90, 60, 30, 15 e 7 dias antes viram tarefas na Agenda) |
| Pagar comissões | **Comissões**: marque e clique em "Marcar como pagas" |

**Vendas, Vencimentos, Comissões e a Agenda ficam ocultos** no menu e no Dashboard (a Agenda: Configurações > Geral >
"Mostrar a Agenda de prospecção" = 1). Para mostrar de novo: Configurações >
Geral > "Mostrar Vendas, Vencimentos e Comissões" = 1 > Salvar.
| Relatórios e exportação | **Relatórios** (PDF, Excel, CSV) |
| Perguntar sobre o negócio | **IA Comercial** (perguntas prontas funcionam mesmo sem IA) |

### Como criar uma campanha
1. **Prospecção** → busque a cidade (ou **Leads** → filtre os leads).
2. Marque os escritórios (os melhores já vêm primeiro e marcados).
3. Escolha a **cadência** (ex.: Dia 1 WhatsApp, Dia 2 ligação, Dia 4 WhatsApp, Dia 6 e-mail, Dia 8 LinkedIn,
   Dia 10 última tentativa) e a data de início → **Iniciar campanha**.
4. Todo dia, abra a **Agenda** e faça as tarefas. Quando o lead responde, as próximas tentativas param sozinhas.

### Regras importantes (anti-spam e LGPD)
- O sistema **nunca dispara mensagens sozinho**. Cada mensagem é enviada por uma pessoa.
- Há **limite diário** de mensagens e um **intervalo mínimo** entre mensagens para o mesmo lead (Configurações).
  No WhatsApp, o limite (40 por dia) vale para **cada número** conectado.
- Áudio, foto ou documento sem texto não recebem resposta automática: viram uma oportunidade para alguém ouvir/ver.
- Depois que alguém da equipe assume o lead, e nas mensagens de parceiros, a IA não responde nem muda a etapa:
  só avisa quem cuida.
- Se a pessoa pedir para sair, clique em **Pediu para sair / Registrar opt-out**: ela nunca mais entra em campanha.
- Cada lead guarda **de onde veio** (fonte) e a **base legal**. Pedido de exclusão: ficha do lead → **Excluir dados (LGPD)**.
- O sistema **não inventa dados**: se a fonte não traz telefone ou e-mail, o lead fica sem.

## 4. IA SDR (prospecção de parceiros)

A IA **encontra, pesquisa, qualifica, faz o primeiro contato e entrega o interessado para você**. Ela não negocia
preço nem comissão e não fecha parceria.

1. **Campanhas > Criar campanha**: escreva o que procura (ex.: "Quero parceiros entre contadores, administradoras e
   empresas de software em São Paulo"). Se faltar a região ou o segmento, a tela pergunta.
2. A IA monta a campanha: acha as empresas, pesquisa o site de cada uma, calcula o potencial, escolhe as melhores e
   escreve uma mensagem **diferente para cada empresa**, em 4 toques (dia 1, 3, 7 e 12).
3. Você confere e clica em **APROVAR CAMPANHA** (ou edita/cancela). Nada sai antes disso.
4. E-mails saem sozinhos (com limites). WhatsApp: com o celular conectado, sai **sozinho para quem já conversou com
   a MS** (respondeu pelo WhatsApp ou tem marcado na ficha "Autorizou receber mensagens da MS pelo WhatsApp"); para
   os demais, a Agenda mostra o botão para enviar com um clique. LinkedIn: sempre com um clique.
5. Quando alguém responde com interesse, a automação para e aparece em **Oportunidades** (🔥) com o resumo.
   Clique em **Assumir lead**, ligue, marque a reunião e siga com a negociação.
6. Veja em **Inteligência** qual segmento, canal e mensagem funcionam melhor.

**E-mail:** as campanhas saem do e-mail @mscertificados.com.br configurado em **Configurações > E-mail**
(e-mail + senha de app do Google + "Enviar e-mail de teste").

**Resposta de robô:** quando quem responde é um robô da empresa (ex.: "Recebemos sua mensagem, aguarde um
momento", menu "digite 1", aviso de ausência), a IA SDR **não responde**, **não cria oportunidade** e a sequência
continua normalmente. Além disso, a SDR responde no máximo 1 vez por dia para o mesmo contato, para nunca entrar
numa conversa sem fim. Se o mesmo lead mandar várias mensagens, tudo fica na mesma oportunidade.

**Minha fila (menu):** mostra os seus disparos num lugar só:
- o que está na fila do WhatsApp agora;
- o que ainda vai sair, com o motivo (ex.: "Aguardando seu clique", "Aguardando o horário de envio", "Sem WhatsApp");
- o histórico dos últimos 7 dias, com o erro de quem não saiu;
- o registro dos disparos e testes.

Admin e gestor podem ver a fila de outra pessoa ou da equipe toda.

**Disparar campanha (qualquer pessoa da equipe):** na página da campanha ativa, **🚀 Disparar campanha** tem os
botões **Disparar campanha WhatsApp** e **Disparar campanha e-mail**. Eles mandam na hora o toque de hoje de cada
empresa pelo canal escolhido, um por vez, com horário, limites, controle de frequência e opt-out.

**Número que dispara (só administrador):** no passo 4 da campanha (ou depois, na página da campanha), o
administrador escolhe **"WhatsApp que vai disparar"**. Em "Automático", cada mensagem sai pelo número do responsável
pelo lead. Escolhendo um número, todas as mensagens de WhatsApp da campanha saem por ele (se ele estiver
desconectado, as mensagens esperam e o sistema avisa).

**WhatsApp:** deixe o **WhatsApp Leads** aberto e conectado. Na Agenda e na ficha do lead aparece o botão
**Enviar pelo WhatsApp conectado** (sai pelo seu número, com as pausas e o limite do WhatsApp Leads), e as
respostas dos parceiros chegam sozinhas na IA SDR. O rodapé do menu mostra se o WhatsApp está conectado.

Configure as categorias em Configurações > **Categorias de parceiros** e o que a IA pode responder em
**Base de conhecimento**. Detalhes técnicos: [`docs/ia-sdr.md`](docs/ia-sdr.md).

### Escolher a base de dados (Receita ou lista da CNPJá)

Além da base da Receita, o sistema guarda **listas de empresas** exportadas da CNPJá (arquivo .xlsx), cada uma
separada da Receita. Exemplo: "contabilidades e adm cond PE & MG".

- **Escolher:** em **Nova campanha**, passo 2 ("Onde?"), escolha a **Base de dados**. Com uma lista, dá para pegar
  **Todas as cidades do estado**. Em **Encontrar novos parceiros**, marque a lista em "Fontes de dados".
- **Segmentos:** o sistema separa as empresas da lista pela atividade (contabilidade, administradora de condomínio...).
  As que não se encaixam em nenhum segmento aparecem em **"Da lista, sem segmento definido"**.
- **Importar ou atualizar uma lista:** Configurações > Integrações > **Listas de empresas**: dê o nome e escolha o
  arquivo. Mesmo nome = a lista é atualizada. Só entram empresas **ativas**.
  Arquivo com mais de 4 MB (como a lista de 24 MB): no computador da MS, arraste o arquivo em cima do
  **`importar_lista.bat`** e confirme o nome.
- **Esconder a base da Receita:** no mesmo lugar, botão "Esconder a base da Receita". Os usuários passam a ver só as
  listas. Nada é apagado e dá para mostrar de novo.

### Empresa que cada usuário representa

Cada usuário pode trabalhar por uma empresa diferente (ex.: MS Certificação Digital, Grupo Certy Certificados).
Em **Minha conta > Empresa que eu represento**, cada pessoa preenche: nome da empresa, site e apresentação curta.
A partir daí, as campanhas, mensagens de WhatsApp, e-mails e a assinatura dessa pessoa falam em nome da empresa
dela (nas campanhas de parceria e na área Empresas novas). Para outra empresa, as mensagens não falam de onde é a
validação (o "presencial em Recife" é da MS).
Quem deixa em branco fala pela MS Certificação Digital. Mensagens já enviadas não mudam; as que ainda vão sair
são corrigidas na hora do envio.

### Empresas novas (venda de certificado para empresas recém-abertas)

Menu **Empresas novas**. Todo dia o sistema busca as empresas que acabaram de abrir e monta uma campanha de
**venda** do certificado digital para elas.

**Configurar (uma vez):**
1. Crie uma conta em **cnpja.com**, assine um plano (ex.: R$ 39,99/mês, 2.500 créditos) e copie a **Chave de API**.
2. Em **Configurações > Integrações > CNPJá**: cole a chave, clique em **Salvar chave** e depois em **Testar a chave**
   (mostra o saldo e não gasta crédito).
3. Em **Empresas novas**, siga os 4 passos do painel: **1.** ligue a busca automática e escolha o horário;
   **2.** marque os **estados**; **3.** escolha quem fica de fora (listas importadas, MEI); **4.** escolha o **dono**
   das campanhas diárias (ele assina e envia pelo e-mail/WhatsApp dele) e os **canais**. Clique em **Salvar configuração**.

**Todo dia:** no horário escolhido, o sistema busca as empresas **ativas** abertas desde a última busca (continua
do dia seguinte ao último já buscado, até 2 dias atrás, porque a Receita publica as empresas novas com alguns dias de
atraso; nenhum dia é buscado duas vezes e empresa que já entrou em campanha nunca entra de novo), cadastra
como leads (origem "Empresas novas (CNPJá)") e monta a campanha **"Empresas novas dd/mm – PE"**, que fica
**aguardando aprovação**. Depois de aprovada: o e-mail sai sozinho pela fila (horário e limites) e o WhatsApp
aparece para o time enviar com 1 clique. São 3 toques: dia 1 (boas-vindas + oferta do e-CNPJ), dia 3 (lembrete)
e dia 7 (último contato). As mensagens podem ser editadas na própria tela. A IA não responde sozinha esses
leads: as respostas vão para **Oportunidades** e o time conversa.

- **Buscar agora:** escolha as datas de abertura (até 7 dias) e clique em **Buscar agora e montar campanha**.
- **Custo:** cada 10 empresas encontradas gastam 1 crédito. Em PE abrem cerca de 380 empresas por dia
  (≈ 1.100 créditos por mês).
- Os celulares que a Receita guarda sem o 9 ganham o 9 na frente (é um palpite: confira antes de enviar).
- Empresas com o mesmo telefone/e-mail (do contador) **não** são juntadas: só o CNPJ conta como repetido.
- Opção para deixar de fora **empresário individual** (inclui os MEIs, que muitas vezes não precisam de e-CNPJ).
- **E-mail e WhatsApp:** cada toque sai pelos dois canais que a empresa tiver, em horários diferentes. O e-mail sai
  sozinho; o WhatsApp (contato frio) o time envia com 1 clique em **Minha fila** ou na campanha.
- **Atividade:** a busca pega empresas novas de **qualquer atividade** (toda empresa nova pode precisar do e-CNPJ).
- **Lista de exclusão:** com a opção marcada, quem já está em alguma **lista importada** (Configurações >
  Integrações > Listas) fica de fora. Também ficam de fora: repetidas, leads já em atendimento e quem pediu para sair.
- **Ver as empresas encontradas:** no quadro **"Empresas encontradas na CNPJá"**, clique na busca. A lista mostra
  razão social, CNPJ, cidade, data de abertura, **telefone fixo**, **celular**, **e-mails**, atividade e quem ficou
  de fora (e por quê), com o link da campanha.
- **Testar a API:** o botão **Testar (10 empresas · 1 crédito)** busca até 10 empresas abertas **num dia** e só
  mostra a lista. Cada teste olha um dia diferente (ontem, anteontem...), para não vir sempre a mesma lista. Se estiver certa, clique em **Montar a campanha com estas empresas** (não gasta crédito).

### Intervalo entre os envios automáticos

Nas campanhas automáticas (depois da aprovação), os **e-mails** e as **mensagens de WhatsApp** que saem sozinhos
saem **um de cada vez**, com **3 a 4 minutos** entre um e outro, sorteados a cada envio (nunca todos no mesmo
horário). E-mail e WhatsApp têm cada um o seu intervalo. Os envios feitos por clique de uma pessoa não esperam.

### Empresa reservada (travada) com quem fez a campanha

- Quando uma empresa entra na campanha de alguém, ela fica **reservada** para essa pessoa: a campanha de **outro
  usuário não pega essa empresa**. A ficha do lead mostra o selo **"🔒 Reservada para Fulano até dd/mm/aaaa"**.
- A reserva vale **60 dias** e **recomeça a contar a cada mudança de status** do lead (Contatado, Respondeu,
  Interessado, Reunião...).
- **Passados 60 dias sem nenhuma mudança de status**, a empresa volta **sozinha** para a base (a conferência roda
  de hora em hora). Se ainda houver campanha mandando mensagens para ela, espera a campanha acabar.
- **Liberar antes:** na ficha do lead, botão **"Liberar para a base"** (quem está com a empresa, ou o
  administrador/gestor). Os envios de campanha pendentes para ela são cancelados.
- Ao voltar para a base, a empresa sai do nome da pessoa. Se ela **nunca respondeu** (Contatado, Aguardando
  resposta ou Perdido por "Sem resposta"), o status volta para **Novo** e outra pessoa pode fazer campanha. Quem
  respondeu, pediu para sair (opt-out) ou disse que não tem interesse **não** volta a ser procurado.
- As empresas que já estavam em campanhas antes desta regra ficaram reservadas para quem criou a campanha mais
  recente delas, contando os 60 dias a partir da criação da campanha.

### Quem assina e envia a campanha

Quem **cria a campanha** assina as mensagens ("Sou Paulo, da MS..." e a assinatura do e-mail) e é por **o WhatsApp
e o e-mail dessa pessoa** que elas saem. Uma empresa que já estava com outro vendedor na ficha, mas com quem
ninguém conversou ainda, passa para quem criou a campanha (fica anotado no histórico do lead). Se o outro vendedor
já conversou com ela, ela continua com ele.

Campanhas montadas antes desta regra podem mostrar o aviso **"⚠️ X empresas desta campanha estão com outro
responsável"**. Clique em **"Passar para ... e corrigir as assinaturas"**: as empresas passam para quem criou a
campanha e o nome na assinatura das mensagens que ainda vão sair é trocado.

### E-mails que não existem

Muitos e-mails da base da Receita estão desatualizados. O sistema tira esses endereços das campanhas sozinho:

- **Antes de enviar**, confere se o domínio do e-mail existe e recebe e-mails (ex.: `jaci@jacicontabilpe.com.br`,
  cujo domínio não existe). Esse e-mail nem sai.
- **Depois de enviar**, a cada 5 minutos lê as mensagens de devolução que chegam na caixa ("Endereço não
  encontrado", "Undeliverable", "Mail delivery failed"). O e-mail daquele lead é marcado como **não existe**.
  Na primeira vez, ele também lê as devoluções dos últimos 60 dias que já estão na caixa.
- Lead marcado: os próximos e-mails da campanha para ele são cancelados, e a ficha mostra o selo vermelho
  **"não existe"** ao lado do e-mail. Se você corrigir o endereço em **Editar**, ele volta a receber.
- "Caixa cheia" e outras recusas temporárias **não** tiram o e-mail.
- Na página da campanha, o botão **Conferir e-mails** faz a conferência de todos de uma vez.
- **Corrigir e reenviar:** na página da campanha aparece o quadro **"E-mails que não existem"**, com as empresas
  marcadas, o motivo e botões para pesquisar no site, no Google e no Instagram. Digite o e-mail certo e clique em
  **Salvar e reenviar** (ou **Salvar**). A empresa volta para o cronograma: os envios parados voltam, com as datas
  empurradas para hoje em diante (o intervalo entre eles continua igual), e o e-mail que tinha voltado é reenviado
  hoje para o endereço novo. Se o endereço novo também não existir, o sistema avisa e não salva.

Obs.: a conferência do domínio não descobre se uma caixa específica existe (ex.: `fulano@hotmail.com`). Isso
só se sabe quando a devolução chega, e aí o sistema tira o e-mail sozinho.

## 5. Perfis de acesso

| Perfil | Vê |
|---|---|
| Administrador | Tudo, inclusive Configurações, usuários, todos os números de WhatsApp e as regras de envio |
| Gestor | Toda a equipe e os indicadores; aprova campanhas (não altera configurações) |
| Funcionário MS | Quase toda a plataforma (prospecção, campanhas, IA, cadências, templates, categorias, conversas), mas **só os próprios dados** e o que for compartilhado com ele; não aprova campanhas nem mexe em Configurações |
| Vendedor | Só os próprios leads, tarefas e vendas |
| Parceiro | Só o portal: própria carteira, indicações, vendas e comissão |

Crie usuários em **Configurações > Usuários** (o perfil padrão é Funcionário MS).

### Permissões (menu Permissões, só o administrador)

Cada perfil acima é um **papel**. No menu **Permissões** você pode:

1. **Papéis:** ver e mudar o que cada papel pode fazer. Em cada item escolha **Não**, **Só os próprios** (só o que é
   da pessoa), **Só a equipe** ou **Tudo**. Clique em **Salvar permissões do papel**. O Administrador tem sempre tudo.
2. **Novo papel:** clique em **+ Novo papel**, dê um nome (ex.: "Vendedor sênior"), escolha de qual papel copiar e
   ajuste. Depois escolha esse papel para a pessoa em Configurações > Usuários.
3. **Exceções e acesso real:** escolha uma pessoa para dar uma exceção só para ela:
   - **PERMITIR** libera algo que o papel não dá (ex.: cobrir as férias de alguém, até uma data);
   - **NEGAR** tira algo do papel (ex.: não exportar planilhas). O NEGAR sempre vence.
   Ao lado aparece o **acesso real** da pessoa: o que ela consegue fazer agora e por quê.
4. **Equipes:** crie equipes (ex.: "Unidade Recife") e escolha a equipe de cada pessoa em Configurações > Usuários.
   Serve para o alcance "Só a equipe" (ex.: um líder que vê os leads do time dele).
5. **Módulos:** ligue ou desligue partes inteiras (Vendas, Agenda, IA SDR, Prospecção, Conversas, IA Comercial,
   Portal). Desligado some do menu **e fica bloqueado para todos**.

Se alguém tentar abrir um lead, parceiro, cliente ou venda de outra pessoa trocando o número no endereço, o sistema
responde "Página não encontrada". Toda mudança de permissão fica no **Registro de atividades**. Quem receber poder de
administrar (usuários, configurações ou permissões) passa a entrar também com o código do celular.

**Verificação em 2 etapas (administrador e gestor):** além da senha, o sistema pede um código de 6 números do
celular.
1. Instale no celular o app **Google Authenticator** ou **Microsoft Authenticator** (grátis).
2. No primeiro login depois da senha, o sistema mostra um QR code: no app, toque em **+** > **Ler código QR** e
   aponte para a tela. Digite o código de 6 números que aparecer.
3. Guarde os **8 códigos de recuperação** que aparecem em seguida (papel ou print fora do celular). Cada um serve
   para entrar uma vez se você perder o celular.
4. Nos próximos logins: senha + o código que o app mostra na hora. Marque "Não pedir o código neste computador por
   30 dias" no computador do trabalho.

**Perdeu ou trocou de celular?** Use um código de recuperação, ou peça ao administrador para clicar em **zerar** na
sua linha em Configurações > Usuários: no próximo login você lê um QR code novo. Se o próprio administrador ficar sem
acesso: `redefinir_senha.bat` (escolha "sistema na internet") cria uma senha nova e desliga o código do celular.

**Cada pessoa com o seu WhatsApp:** no menu **WhatsApp > Meu WhatsApp**, cada um conecta o próprio número pelo
QR code. A IA SDR manda os WhatsApps dos leads de cada pessoa pelo número dela; sem número conectado, as
mensagens esperam e a pessoa recebe um aviso para conectar. Em **Conversas**, cada um vê só as conversas do
próprio número e dos números compartilhados com ele.
**Compartilhar um número:** no cartão do número, **Compartilhar este número** → "Toda a equipe" ou escolha as
pessoas. O dono do número, o administrador e o gestor escolhem com quem compartilhar; só o dono e o administrador
conectam, pausam ou desligam.

**Cada pessoa com o seu e-mail:** no menu **E-mail**, cada um pode cadastrar o próprio e-mail @mscertificados.com.br
(com a senha de app do Google, 16 letras) e clicar em **Enviar e-mail de teste**. Os e-mails das campanhas dos leads
de cada pessoa saem pelo e-mail dela, e as respostas chegam na caixa dela (a IA SDR lê todas as caixas marcadas).
Sem e-mail próprio, sai por uma conta compartilhada com a pessoa; por último, pelo **e-mail principal da MS**, que
começa liberado para toda a equipe. O dono da conta, o administrador e o gestor escolhem com quem compartilhar cada
conta (inclusive o principal) em **Compartilhar esta conta**. Os limites de envio por hora e por dia continuam
valendo para a MS inteira.

**Gestor com o domínio da própria empresa:** o gestor (e o administrador) pode cadastrar um e-mail de outro domínio,
por exemplo joao@contabiljoao.com.br. No menu **E-mail**:
1. Em **Onde fica este e-mail?**, escolha **Google Workspace** ou **Outro provedor** (Microsoft 365, Hostinger,
   Locaweb, servidor próprio...).
2. Outro provedor: copie do painel do provedor o **servidor de envio (SMTP)** e a porta (quase sempre 587 ou 465) e
   o **servidor de leitura (IMAP)** (porta 993). Digite a senha do e-mail. A tela traz os dados do Microsoft 365 e
   da Hostinger como exemplo.
3. Clique em **Salvar** e depois em **Enviar e-mail de teste**.
4. Logo abaixo aparece **"O domínio ... está pronto para não cair no spam?"**, com SPF, DKIM e DMARC. O que estiver
   "Falta configurar" traz o passo a passo; quem cuida do domínio faz isso em poucos minutos.

Gmail, Hotmail e Yahoo pessoais não são aceitos (caem no spam e a conta pode ser bloqueada). Outras pessoas só podem
usar outro domínio se o administrador der a permissão **"Enviar pelo próprio domínio"** na tela Permissões; tirando a
permissão, a conta para de enviar na hora.

## 6. Problemas comuns

| Mensagem / situação | O que fazer |
|---|---|
| "O Python não foi encontrado" | Instale o Python marcando "Add Python to PATH" e rode `instalar.bat` de novo |
| "O sistema ainda não foi instalado" | Rode `instalar.bat` |
| Esqueci a senha | Outro administrador cria uma senha nova em Configurações > Usuários, ou rode `redefinir_senha.bat` |
| "Código errado" no login | O código muda a cada 30 segundos: digite o que o app mostra agora. Se sempre der errado, acerte a hora automática do celular |
| Perdi o celular do código | Use um código de recuperação ou peça ao administrador para clicar em "zerar" em Configurações > Usuários |
| "Muitas tentativas erradas" | Espere 15 minutos e tente de novo |
| "O formulário expirou" | Recarregue a página (F5) e repita |
| Lead da base sem responsável | A Receita não tem sócio-administrador pessoa física para essa empresa: preencha à mão |
| A busca acha poucos escritórios | Importe a **base da Receita Federal** (Configurações > Integrações) |
| O Google recusa mesmo com a senha de app certa | Depois de várias tentativas erradas o Google bloqueia por alguns minutos: espere e teste de novo. Para conferir a senha a partir deste computador: dois cliques em `testar_email_daqui.bat` |
| "Connection unexpectedly closed" ao testar o e-mail | É senha errada: o Google fecha a conexão em vez de avisar. Use a **senha de app** de 16 letras (não a senha normal) |
| "O Google recusou a senha" | Use a **senha de app** (16 letras) da conta de envio, não a senha normal (Configurações > E-mail mostra o passo a passo) |
| E-mails caindo no spam | Configurações > E-mail mostra o que falta no DNS (DKIM e DMARC); comece com poucos e-mails por dia |
| Ver se o e-mail/WhatsApp já foi para o lead | Menu **Envios**: tudo o que saiu, para quem, quando e a situação (na fila, enviada, não saiu, respondeu), os próximos envios e como funcionam os disparos. Na campanha: **Andamento por empresa**. Na ficha do lead: **Envios para este lead** |
| Arquivar ou excluir uma campanha | Na lista de campanhas (ou dentro da campanha): **Arquivar** tira da lista (veja em "Arquivadas"); **Excluir** apaga a campanha e cancela o que estava programado. As empresas continuam em Leads. Cada pessoa vê e mexe só nas próprias campanhas (administrador e gestor veem todas) |
| Onde envio os WhatsApps da campanha? | Dentro da campanha aprovada, em **WhatsApp de hoje**: um botão por mensagem, sai pelo seu número |
| Como testo uma campanha antes de aprovar? | Na campanha, cartão **Testar antes de aprovar**: escolha a campanha e o canal (WhatsApp ou e-mail); as mensagens chegam no SEU e-mail/WhatsApp com "[TESTE]". Nenhum lead recebe nada e não conta nos limites |
| A campanha tem empresas sem WhatsApp. O que faço? | Empresas que só têm telefone fixo entram na campanha também. No cartão **Pesquisar WhatsApp** da campanha, clique em Google/Instagram, ache o número e salve: as mensagens passam a ir para ele |
| A campanha tem mensagem de WhatsApp e de e-mail? | Sim. Cada toque tem os dois modelos lado a lado. Se achar o e-mail (ou o WhatsApp) da empresa, clique em **Enviar este toque por e-mail/WhatsApp** |
| Onde vejo os modelos de cada segmento? | Em **Cadências > Templates de mensagem**, escolha o segmento. São 15 por segmento (8 de WhatsApp e 7 de e-mail); dá para editar. No lead, aparecem os do segmento dele |
| Dá para pesquisar empresas por CNAE? | Sim. Em **Prospecção**, abra **Pesquisar por CNAE**, marque (ex.: 6319-4/00) ou digite os códigos. Ao lado aparece quantas empresas há na base |
| Campanhas repetindo as mesmas empresas | Não acontece mais: cada campanha pula as empresas que já estão em outra campanha ativa (ou já contatadas) e busca mais fundo na base. Cancelar uma campanha libera as empresas dela |
| Campanha com "erro" ao montar | Leia o motivo na campanha. Região sem empresas: confira cidade/bairro e estado (bairro funciona, ex.: "Boa Viagem" / PE). Uma empresa com site quebrado não para mais a campanha: ela segue com os dados da Receita |
| A campanha não manda e-mails sozinha | Configure o SMTP no `.env` e confira em Configurações se "fila envia e-mails sozinha" = 1; o envio só acontece em dias úteis, no horário configurado |
| "APROVAÇÃO NECESSÁRIA" não some | Clique em APROVAR CAMPANHA (qualquer pessoa da equipe pode aprovar) |
| Nenhum horário para reunião | Confira o expediente da pessoa em Configurações > Usuários |
| "Os servidores do OpenStreetMap estão ocupados" | Tente de novo em alguns minutos ou use a base da Receita |
| "O limite diário... foi atingido" | Continue amanhã ou aumente o limite em Configurações |
| "Já houve uma mensagem para este lead há menos de 20 horas" | Controle de frequência: contate amanhã |
| (site na internet) "O computador com o WhatsApp Leads está desligado" | Ligue o computador e abra o `iniciar.bat` do WhatsApp Leads; em até 1 minuto volta |
| (site na internet) Campanha ou busca parada em "Na fila" | Espere 1 minuto. Se continuar, avise o suporte: o agendador da Vercel (Cron Jobs) pode estar desligado |
| A IA não escreve as mensagens | Sem a chave da IA, o sistema usa os templates. Veja `docs/configuracao.md` |

**Seus dados ficam na pasta `dados/`. Não apague essa pasta.** Faça cópia dela de vez em quando (backup).

**Cópia de segurança do sistema na internet:** todo dia, a partir do meio-dia, este computador guarda sozinho uma
cópia do banco da nuvem em `dadosackups` (ficam os últimos 14 dias). Para fazer uma na hora: dois cliques em
`fazer_backup.bat`. Só em emergência (dados apagados por engano): `restaurar_backup.bat` volta uma cópia. Ele
apaga o que está hoje no sistema e pede para digitar SIM.

Testes automáticos: dois cliques em `testar.bat` (não mexe nos seus dados).

Documentação técnica: pasta [`docs/`](docs/README.md).
