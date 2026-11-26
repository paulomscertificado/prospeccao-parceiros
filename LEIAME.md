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
O sistema está em **https://sistema.mscertificados.com.br** (desde 18/11/2026, no servidor próprio). É só abrir esse endereço
no navegador, de qualquer lugar: não precisa do `iniciar.bat`. O passo a passo da publicação está em
[`docs/deploy-vercel.md`](docs/deploy-vercel.md) (dois cliques em **`enviar_para_nuvem.bat`** levam seus dados).
- **WhatsApp:** o computador com o **WhatsApp Leads** precisa ficar **ligado e aberto**. Ele é ligado ao site
  uma vez só, pelo `ligar_nuvem.bat` da pasta `whatsapp-leads`.
- Campanhas e buscas começam em **até 1 minuto** depois do clique (a tela mostra "Na fila").
- Menu **Conversas**: todas as conversas do número conectado (lista à esquerda, conversa à direita), com
  busca por nome ou telefone. Escreva e aperte **Enter** para responder. **+ Nova mensagem** manda para qualquer
  celular (digite com DDD). Sai na hora pelo número da MS; quem pediu SAIR não recebe.
  O celular aparece sempre com o 9 na frente, mesmo quando o WhatsApp entrega o número antigo sem ele; a busca
  acha o contato digitando o número com ou sem o 9.
  A tela se atualiza sozinha enquanto está aberta: mensagem nova aparece em até uns 15 segundos. Para gastar pouco
  do banco da nuvem, ela só baixa a conversa de novo quando algo mudou (mensagem nova, status, mensagem lida).
  Para trocar o nome de um contato, abra a conversa e clique em **✏️ Editar nome** (o nome muda também no
  WhatsApp Leads).
  O **número vermelho** ao lado de **Conversas** no menu é quantas mensagens recebidas ainda não foram lidas nos
  números que você vê. Elas ficam lidas quando alguém abre a conversa nessa tela ou responde pelo celular do número
  (ou pela tela Conversas). Resposta automática (da IA ou da campanha) não conta como lida.
  Acima da lista, **Não lidas** mostra só as conversas com mensagem nova (**Tudo** volta a mostrar todas).
  O mesmo contato pode ter uma conversa em cada número (por exemplo, a 1ª mensagem saiu pelo número principal e a
  resposta chegou pelo WhatsApp de um vendedor). O **Ver conversa** das Oportunidades abre pelo número em que a
  conversa está (o da mensagem mais recente), e a conversa avisa no alto quando o contato também tem conversa por
  outro número que você vê: clique no nome do número para abrir a conversa de lá.
  Nas mensagens que saíram, como no WhatsApp: **✓** saiu, **✓✓** o contato recebeu, **✓✓ azul** o contato leu.
  Clique numa mensagem que saiu para ver os **Dados da mensagem**: a hora em que foi **Entregue** e em que foi
  **Lida** ("-" enquanto não aconteceu; quem desligou a confirmação de leitura no WhatsApp nunca aparece como lida). O
  mesmo vale na tela **API Oficial**. As mensagens de antes de 23/11/2026 não têm essas horas.
  **Apagar para todos**, como no WhatsApp: clique na mensagem que saiu e, nos **Dados da mensagem**, em
  **🗑️ Apagar para todos** (confirme). Ela some do WhatsApp do contato (lá aparece "Esta mensagem foi apagada"), mas
  **para nós ela continua aparecendo**: o aviso **🚫 Você apagou esta mensagem** em vermelho em cima e o texto em
  itálico embaixo; nos Dados da mensagem aparecem quando e quem apagou. Quando o **contato** apaga uma mensagem que ele
  mandou, ela também fica, com o aviso **🚫 Essa mensagem foi apagada pelo contato** (desde 24/11/2026). No celular do
  número, o próprio WhatsApp mostra só "Você apagou esta mensagem" (lá não dá para mudar). Leva alguns segundos (o
  pedido vai ao computador do WhatsApp). Como no WhatsApp, só dá para apagar **até 2 dias depois do envio** e só as mensagens que saíram (não as que o contato mandou). O número precisa
  estar conectado pelo QR code: em modo teste a mensagem não sai de verdade, então não há o que apagar. A tela
  **API Oficial** (número oficial) não tem esse botão.
  **Fotos e áudios:** a foto (e a figurinha) aparece dentro da mensagem, como no WhatsApp; clique nela para abrir
  inteira numa aba nova. O áudio aparece com o botão ▶ para ouvir ali mesmo (também os que a equipe manda pelo
  celular do número). Vale para as mensagens que chegaram depois de 24/11/2026: as de antes continuam só com o
  "📷 Imagem" / "🎤 Áudio". A foto ou o áudio pode levar alguns segundos a mais que o texto para aparecer. Vídeo e
  documento continuam só com o nome (abra no celular do número), e a foto ou o áudio de **visualização única** também:
  como no WhatsApp Web, ela só abre no celular.
  **Enviar arquivo (📎):** clique no clipe ao lado da caixa de texto e escolha o arquivo (PDF, foto JPG/PNG, Word,
  Excel, PowerPoint, texto, XML, ZIP, áudio ou vídeo MP4; até 15 MB). O que você escrever vai como legenda (pode
  ficar em branco). A foto chega ao cliente como foto; o resto, como documento, com o nome do arquivo. Para desistir,
  clique no ✕ ao lado do nome. Na conversa, o arquivo enviado aparece com o 📄 e o nome: clique para abrir (PDF) ou
  baixar (Word, planilha...). Vale também na **+ Nova mensagem** e segue as regras do envio de texto (o número que você
  usa, quem pediu SAIR não recebe).
  **Apagar conversa** (desde 25/11/2026; toda a equipe, em todas as marcas, cada pessoa nas conversas dos números que
  vê; para tirar de alguém: Configurações > Papéis e permissões, "Apagar conversas inteiras"): abra a conversa e clique
  em **🗑️ Apagar conversa**, no alto (confirme). As
  mensagens daquele contato **por aquele número**, com as fotos, os áudios e os arquivos, saem do sistema para toda a
  equipe. **No WhatsApp do contato e no celular do número nada muda.** O contato, o nome que você deu a ele, a ficha do
  lead e o pedido de SAIR continuam, e a ficha do lead ganha a anotação de que a conversa foi apagada. A mensagem que
  ainda está saindo continua na conversa, e uma mensagem nova do contato abre a conversa de novo. A conversa do mesmo
  contato por outro número não muda. **Não dá para desfazer.** A tela **API Oficial** não tem esse botão.
- **Avisos como no WhatsApp:** com o sistema aberto no navegador (pode estar em outra aba), quando chega mensagem nas
  Conversas, no número oficial (API Oficial) ou uma resposta de campanha:
  - toca um **som**;
  - os **números vermelhos do menu** mudam sozinhos, sem recarregar a página;
  - o **título da aba** mostra quantas novidades há, por exemplo "(3) Leads";
  - com os avisos na tela ligados, aparece um **aviso no canto da tela do computador** quando o sistema está em outra
    aba ou minimizado. Clicar no aviso abre a conversa ou a oportunidade.

  No rodapé do menu ficam dois botões: **🔊 Som ligado** (clique para desligar ou ligar de novo; ao ligar, ele toca o
  som) e **🔔 Ativar avisos na tela** (clique e escolha **Permitir** na pergunta do navegador). Se aparecer "Avisos
  bloqueados no navegador", libere no cadeado ao lado do endereço do site > Notificações > Permitir. O navegador só
  deixa tocar som depois de um clique na página. A conversa que está aberta na tela não avisa, como no WhatsApp.
  As conversas antigas (até 1 ano) chegam quando o celular é conectado pelo QR code. Para puxar de novo: menu
  WhatsApp > Desligar este número > Conectar com QR code.
- **WhatsApp** (em **Configurações > Comunicação**; quem não vê as Configurações, como os vendedores, acha no menu
  lateral): a mesma tela do WhatsApp Leads, dentro do site. Mostra se o celular está conectado e
  tem os botões **Conectar com QR code**, **Usar modo teste**, **Pausar**, **Desligar** e as **regras de envio**.
  O QR code aparece ali mesmo, para ler com o celular. Os botões levam alguns segundos, porque quem faz a
  conexão é o computador da MS (que precisa estar ligado com o WhatsApp Leads aberto).

## 3. O dia a dia

| Quero... | Onde |
|---|---|
| Encontrar escritórios numa cidade | **Prospecção**: escreva "Quero encontrar 100 escritórios contábeis em Recife" e clique em Buscar |
| Ver e filtrar meus leads | **Leads** (lista) ou **Leads > Pipeline** (Kanban: arraste os cards) |
| Saber com quem falar hoje | **Dashboard**, quadro **Quem precisa de mim hoje** (respostas quentes com prazo, tarefas e leads esfriando) |
| Mandar a mensagem | Na Agenda ou na ficha do lead: **Copiar mensagem** ou **Abrir no WhatsApp** |
| Registrar que o lead respondeu | Botão **Respondeu** na Agenda (cole a resposta: o sistema sugere o que responder) |
| Qualificar e gerar abordagem | Ficha do lead: **Qualificar lead**, **Gerar abordagem com IA**, **Qual é o próximo melhor passo?** |
| Transformar em parceiro | Ficha do lead: **Converter em parceiro** (ou arraste para a coluna "Parceiro") |
| Registrar uma venda | **Vendas** (a comissão e o vencimento são calculados sozinhos) |
| Ver quem vai vencer | **Vencimentos** (alertas 90, 60, 30, 15 e 7 dias antes viram tarefas na Agenda) |
| Pagar comissões | **Comissões**: marque e clique em "Marcar como pagas" |

**Vendas, Vencimentos, Comissões e a Agenda ficam ocultos** no menu e no Dashboard (a Agenda: Configurações > Geral >
Menu > "Mostrar a Agenda de prospecção"). Para mostrar de novo: Configurações > Geral > Menu > ligue
"Mostrar Vendas, Vencimentos e Comissões" > Salvar alterações.
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
- Há **limites** de mensagens (por hora e, se ligado, por dia) e um **intervalo mínimo** entre mensagens para o mesmo
  lead (Configurações). No WhatsApp, os limites valem para **cada número** conectado. **Desde 17/11/2026 (decisão da
  Maria, que aceitou o risco de bloqueio) o WhatsApp não tem limite por dia: só 15 por hora por número**, com as
  pausas entre uma mensagem e outra; no WhatsApp Leads o limite diário ficou em 300 (Regras de envio).
- **Proteção dos números de WhatsApp contra bloqueio:** o teto de **contatos frios por número por dia** (era 20;
  mensagem para quem nunca conversou com a MS) está **desligado desde 17/11/2026** (Configurações > Geral, 0 = sem
  teto; para religar, ponha o número de volta). Quem já conversou ou autorizou não entra nessa conta. Continua valendo:
  se **3 pessoas pedirem para sair no mesmo dia**, os contatos frios
  daquele número param até o dia seguinte (e chega um aviso por e-mail). **Resposta automática de robô** ("recebemos
  sua mensagem...") **não conta** como conversa: não libera envio automático. Os dois números se ajustam em
  Configurações > Geral.
- Áudio, foto ou documento sem texto não recebem resposta automática: viram uma oportunidade para alguém ouvir/ver.
- Depois que alguém da equipe assume o lead, e nas mensagens de parceiros, a IA não responde nem muda a etapa:
  só avisa quem cuida.
- Se a pessoa pedir para sair, clique em **Pediu para sair / Registrar opt-out**: ela nunca mais entra em campanha.
  Quem responde **SAIR no WhatsApp** sai das campanhas de **todas as marcas** (o WhatsApp Leads bloqueia o número
  para todos); o descadastro pelo link do e-mail vale para a marca que mandou.
- Cada lead guarda **de onde veio** (fonte) e a **base legal**. Pedido de exclusão: ficha do lead → **Excluir dados (LGPD)**.
- O sistema **não inventa dados**: se a fonte não traz telefone ou e-mail, o lead fica sem.
- **Cópia das conversas do WhatsApp (tela Conversas):** guarda todas as conversas dos números conectados, por um
  **prazo de guarda** (Configurações > Geral > Avisos e LGPD > "Guardar a cópia das conversas do WhatsApp por"; só o
  admin master muda). As mais antigas saem da cópia sozinhas, de hora em hora; as originais continuam nos celulares e no
  WhatsApp Leads.
- O **registro de atividades** (Configurações > Logs) mostra o **módulo** e, nas mudanças de configurações, score,
  cadastro de pessoas, marca e módulos, o **antes e depois** (ex.: limite_diario_whatsapp: 40 → 35). E-mails e telefones
  aparecem mascarados (ex.: ma***@empresa.com.br, (81) *****-8888) e ninguém apaga o que está nele.

## 4. IA SDR (prospecção de parceiros)

**Tela Nova campanha (4 passos):** 1) **Onde?** (base, estado e cidade); 2) **Que tipo de empresa?** Cada tipo mostra
quantas empresas há na cidade e por que pode ser um bom parceiro ("⭐ Mais indicado" = quem mais precisa de certificado
para os próprios clientes). Os tipos sem nenhuma empresa na cidade ficam escondidos (botão **Mostrar**), e o quadro do
topo soma as empresas dos tipos escolhidos. 3) **Quantas empresas?** 4) **Como a IA vai abordar?**, com o tom e o
ritmo dos contatos:

| Tom | Quando usar |
|---|---|
| Consultivo e cordial | O padrão: apresenta a MS, explica a parceria e faz uma pergunta |
| Pergunta curta | Começa só com uma pergunta fácil de responder (o que mais abre conversa no WhatsApp) |
| Conversa de parceiro | Fala como colega de mercado, os dois lados ganham (contadores, consultorias) |
| Foco nos clientes deles | Começa pelo problema do cliente deles (certificado vencido travando tudo) |
| Empresa da região | Mostra que a MS é Autoridade de Registro, com validação presencial ou por vídeo |
| Direto e objetivo | Mensagens curtas, a proposta em uma frase |
| Leve e informal | Próximo e descontraído (coworkings, restaurantes, negócios menores) |
| Formal e institucional | Linguagem de carta (associações, franqueadoras, administradoras grandes) |

| Ritmo (cadência) | Toques |
|---|---|
| IA SDR – 4 toques (padrão) | Dia 1 apresentação, dia 3 praticidade, dia 7 receita, dia 12 encerramento |
| Curta e segura – 2 toques | Dia 1 e dia 6. A mais segura para WhatsApp frio (menos chance de bloqueio) |
| Leve – 3 toques | Dia 1, dia 5 (praticidade) e dia 12 (encerramento) |
| Pergunta primeiro – 3 toques | Dia 1 só uma pergunta, dia 4 explica a parceria, dia 10 encerra |
| Relacionamento – 5 toques em 30 dias | Dia 1, 4, 10 (dica útil), 18 e 30. Para quem decide devagar |
| Convite por e-mail – 3 e-mails | Só e-mail, sem WhatsApp frio: convida para conversar. Quem chamar no WhatsApp vira conversa |

**Visual das campanhas (e-mail em HTML e imagem no WhatsApp):** em **Campanhas > 🎨 Visuais** você cadastra cada
visual: o **HTML do e-mail** (cole o código; escreva `{{mensagem}}` onde entra o texto do toque, e use `{{nome}}`,
`{{empresa}}`, `{{cidade}}`, `{{vendedor}}` e `{{descadastro}}` se quiser), a **imagem do WhatsApp** (PNG ou JPG, até
1 MB) e as **imagens que o HTML usa** (cada uma ganha um endereço para colar no HTML). A tela mostra a prévia do e-mail
e do WhatsApp e manda um e-mail de teste para você.
- Na **Nova campanha (IA SDR)** (passo 4) e na configuração das **Empresas novas** (passo 5), **Como enviar a
  campanha** tem 4 botões: **WhatsApp e e-mail com HTML**, **WhatsApp apenas com HTML**, **E-mail apenas com HTML** e
  **Apenas mensagens de texto**. Com HTML, escolha o **Modelo de HTML deste envio** (uma das suas artes ou, só para o
  e-mail, o **E-mail com a marca**, feito pelo sistema com o logo e a cor) e os toques: **do 2º toque em diante**
  (recomendado: o 1º contato frio responde melhor só com texto) ou **em todos**. A tela avisa se o modelo ainda não tem a
  imagem do WhatsApp ou o HTML do e-mail. A Nova campanha vem com a escolha da sua última campanha.
- Empresa sem o nome do responsável: o "Olá, {{nome}}!" da arte vira "Olá!".
- **Regra do HTML:** o 1º toque vai em texto e, do 2º em diante, vai **só o HTML**. Com uma arte que é o e-mail
  inteiro (sem `{{mensagem}}`, como a "Escritorios contabeis"), o texto do toque não vai: a cópia em texto que segue
  escondida dentro do e-mail (para o filtro de spam e para quem não abre HTML) é a da própria arte.
- Na campanha, a área **Mensagens** mostra em cada e-mail se ele vai **só texto** ou **🎨 HTML**; abra **Ver o e-mail em
  HTML** para ver como ele chega para a empresa (com os dados dela).
- O **e-mail** sai com o HTML e também com a versão em texto (exigência dos filtros de spam).
- No **WhatsApp** vai a imagem com o texto do toque embaixo, **só para quem já conversou com a MS**. Para contato frio
  sai só o texto, para proteger o número contra bloqueio.
- O botão **Testar** da campanha manda o e-mail com o visual e o WhatsApp com a imagem para você mesmo. Com o
  visual **do 2º toque em diante**, o 1º contato chega **só em texto**: para ver a arte no teste, escolha **Todos os 4
  toques** em "Quais toques" (a tela avisa e tem um botão para isso; depois do envio ela diz quantos foram com o HTML).

**E-mail com a marca (padrão):** sem um visual escolhido, a IA SDR e as Empresas novas podem mandar **do 2º e-mail em
diante** um e-mail em HTML leve, feito sozinho com o **logo e a cor da marca** (Configurações > Marca): uma faixa com o
logo em cima, o texto de sempre com a assinatura de quem envia e o "Não quer mais receber?" discreto embaixo. O **1º
e-mail** para cada empresa continua **só em texto** (no primeiro contato, e-mail "desenhado" cai mais no spam ou na aba
Promoções). Veja a prévia em **Campanhas > 🎨 Visuais**. É um **módulo**: o admin master libera **por marca** em
**Painel master > Módulos de cada AR** ("E-mail em HTML com a marca"); marca nova começa desligada. Vale também para as
campanhas em andamento (os e-mails que ainda não saíram). A Renovação continua com a arte do aviso.
Com o módulo liberado para a marca, a **Nova campanha** (parte Visual) e a configuração das **Empresas novas** (passo 5)
mostram o botão **✉️ E-mail em HTML com a marca**, que já vem marcado: desmarque para aquela campanha (ou para as
campanhas diárias das Empresas novas) mandar todos os e-mails só em texto. A página da campanha mostra "visual: e-mail
com a marca" quando ela usa.

**Pergunta final (vai no fim do 1º contato):** 14 perguntas prontas em 5 tipos (descobrir como fazem hoje,
convidar para conversar, achar a pessoa certa, mandar informação, resposta de uma palavra), **Automática** (a mais
natural para cada empresa), **Variar** (cada empresa recebe uma pergunta de um tipo diferente, para descobrir qual
traz mais resposta) ou **Escrever a minha**. A pergunta escolhida vale em todos os tons. A pergunta escrita à mão não
pode ter valores, porcentagem, desconto, exclusividade nem frase de propaganda.

O tom muda as mensagens de verdade, mesmo sem a IA ligada: cada tom tem os próprios textos. Para o convite por e-mail
levar o botão do WhatsApp, cadastre o número da empresa em **Configurações > Geral > WhatsApp > "WhatsApp dos convites
por e-mail"** (sem ele, o convite pede para responder o e-mail).

A IA **encontra, pesquisa, qualifica, faz o primeiro contato e entrega o interessado para você**. Ela não negocia
preço nem comissão e não fecha parceria.

1. **Campanhas > Criar campanha**: escreva o que procura (ex.: "Quero parceiros entre contadores, administradoras e
   empresas de software em São Paulo"). Se faltar a região ou o segmento, a tela pergunta.
2. A IA monta a campanha: acha as empresas, pesquisa o site de cada uma, calcula o potencial, escolhe as melhores e
   escreve uma mensagem **diferente para cada empresa**, nos toques da cadência escolhida (padrão: dia 1, 3, 7 e 12).
   **Deu erro ao montar?** (por exemplo, a cidade não tem empresas na base ou na lista escolhida.) A campanha mostra o
   motivo e o botão **Corrigir e montar de novo** (na lista de campanhas, **Corrigir**). A tela abre com tudo o que
   foi escolhido: troque a cidade, o estado, a base ou os tipos de empresa e clique em **Montar a campanha de novo**.
   É a mesma campanha, não cria outra (desde 24/11/2026). Dica: no passo 1 a tela mostra quantas empresas a base tem
   na cidade; uma lista importada só tem as empresas dos estados dela.
3. Você confere e clica em **APROVAR CAMPANHA** (ou edita/cancela). Nada sai antes disso.
4. **Aprovou, entrou na fila.** Os e-mails e os WhatsApps saem sozinhos, cada um no seu horário, também para quem
   nunca conversou com a MS (desde 12/11/2026). O WhatsApp sai pelo celular conectado, uma mensagem a cada 8 a 12 minutos
   em cada número (Configurações > Geral; desde 17/11/2026; números diferentes mandam ao mesmo tempo desde 23/11/2026),
   só no horário de envio, com o limite por hora (sem limite por dia e sem teto de contatos frios desde 17/11/2026) e
   pausa com 3 pedidos de SAIR. Ao aprovar, cada WhatsApp entra numa **vaga do número** (veja abaixo) e o que fica de
   um dia para o outro vai sozinho para a próxima vaga, sem acumular atrasados. O toque seguinte
   da mesma empresa espera o anterior sair (o "último contato" nunca chega antes da apresentação). A fila nunca manda
   dois WhatsApps, nem dois e-mails, para a mesma empresa em menos de 20 horas, mesmo com o intervalo mínimo em 0 nas
   Configurações (o e-mail desde 17/11/2026): o segundo fica para o dia seguinte. O envio manual segue as Configurações.
   LinkedIn: sempre com um clique.
   **Desligar numa campanha (só o administrador):** na tela da campanha, o cartão **WhatsApp sai sozinho depois da
   aprovação** tem o botão **Desligar**. Desligado, o WhatsApp só sai sozinho para quem já conversou com a MS
   (respondeu pelo WhatsApp ou tem marcado na ficha "Autorizou receber mensagens da MS pelo WhatsApp"); para os
   demais, a campanha e a Minha fila mostram o botão para enviar com um clique. Para as campanhas novas voltarem ao
   clique, desligue em **Configurações > Geral > WhatsApp** a chave "Campanha nova já vem com o WhatsApp automático
   ligado".
   Toda empresa da campanha ganha a mensagem de WhatsApp. Se o campo **WhatsApp** da empresa estiver em branco, a
   mensagem fica pronta e **não sai**: cadastre o número na ficha da empresa e ela fica liberada.
   **Vagas de WhatsApp de cada número (desde 23/11/2026):** cada número manda uns **6 WhatsApps por hora** (um a cada
   8 a 12 minutos), no horário de envio da marca e fora do almoço: uns 64 num dia inteiro das 07:30 às 20:00. Várias
   campanhas no mesmo número dividem essas vagas. Por isso:
   - na **Nova campanha** (passo 3), no **Buscar agora** das Empresas novas e na **aprovação** aparece o quadro
     **Vagas de WhatsApp no número**, com quantas vagas livres há hoje e nos próximos dias (vermelho = dia cheio) e,
     na aprovação, até quando cabem os primeiros toques da campanha;
   - ao **aprovar**, o WhatsApp fica no horário marcado se aquela hora ainda tem vaga no número; se não tem, vai para
     a hora mais vazia do dia ou para o próximo dia com vaga, e os toques seguintes da empresa (e o e-mail do mesmo
     toque) andam junto, mantendo o espaço da cadência. O aviso da aprovação diz de que dia a que dia saem os
     primeiros WhatsApps;
   - **de hora em hora**, o WhatsApp que ficou de um dia anterior (o número caiu, o computador ficou desligado) e o
     que está numa hora já lotada do número vão para a próxima vaga. Quem já começou a conversa fica com a vaga; anda
     o primeiro toque de quem ainda não recebeu nada. Ficam como estão a Renovação (tem prazo), os avisos pela API
     oficial e as campanhas com o WhatsApp automático desligado (essas esperam o seu clique);
   - na fila, **cada número tem a sua vez**: o intervalo de 8 a 12 minutos vale para o mesmo número, e números
     diferentes mandam ao mesmo tempo. Quando a fila aperta, a conversa que já começou (o toque seguinte) sai antes do
     primeiro toque de uma empresa nova.
   **Vagas de e-mail (desde 25/11/2026):** o mesmo para os e-mails. A fila manda um e-mail por vez, a cada 3 a 4
   minutos: cabem uns **17 por hora** e, pelo limite de Configurações > Geral > E-mail, **80 por dia**. Esses limites
   são da **marca**: as campanhas de todas as contas de e-mail da marca dividem as vagas (todas usam o mesmo domínio e
   dividem a mesma reputação). Só de segunda a sexta, no horário de envio, fora do almoço e dos feriados de quem envia.
   - ao lado do quadro de WhatsApp aparece o quadro **Vagas de e-mail**, com a conta por onde os seus e-mails saem e
     quantas vagas livres há hoje e nos próximos dias. Hoje já descontando os e-mails que saíram (o limite é do dia).
     Sem conta de e-mail, o quadro avisa: os e-mails esperam até você cadastrar a sua em **Contas de e-mail** (ou
     alguém compartilhar uma com você);
   - ao **aprovar**, cada e-mail fica no horário marcado se a hora e o dia ainda têm vaga; se não, vai para a hora mais
     vazia ou para o próximo dia com vaga. Ele nunca passa na frente do WhatsApp do mesmo toque, e dois e-mails para a
     mesma empresa ficam a pelo menos 20 horas um do outro. O aviso da aprovação diz de que dia a que dia saem os
     primeiros e-mails;
   - **de hora em hora**, o e-mail que ficou de um dia anterior e o que está numa hora ou num dia já lotado vão para a
     próxima vaga. Ficam como estão a Renovação (tem prazo), os e-mails de quem ainda não tem conta de e-mail e o
     e-mail atrasado das Empresas novas cuja empresa ainda tem WhatsApp para sair: esse sai logo, sem esperar o
     WhatsApp.
   **Quanto cabe por dia (desde 25/11/2026):** no alto da tela **Campanhas** aparece quantas empresas novas cabem por
   dia no envio automático, somando todas as campanhas da marca. Com a cadência padrão de 4 toques, cada empresa recebe
   4 WhatsApps e 4 e-mails, então cabem por dia as vagas do dia divididas por 4. Exemplo: um número de verdade
   (64 WhatsApps por dia) e o e-mail da marca (80 por dia) dão 64 ÷ 4 = 16 e 80 ÷ 4 = 20; vale o menor: **16 empresas
   novas por dia**, 80 por semana. Clique em **Ver a conta** para ver:
   - os números e as contas de e-mail que contam e quem dispara por cada um (número em modo teste ou desconectado não
     conta; cada número de verdade a mais soma mais empresas por dia);
   - a mesma conta com cadências de 2, 3 e 5 toques;
   - quantas campanhas precisam estar em andamento para usar tudo: não há limite de campanhas, mas cada uma manda até
     60 mensagens por dia (WhatsApp e e-mail somados);
   - quanto já está marcado nos próximos 10 dias de envio;
   - num aviso amarelo, quem ainda não tem número de WhatsApp de verdade ou conta de e-mail (os envios dessas pessoas
     esperam).
   O quadro só aparece nas marcas com conta de e-mail cadastrada, para quem cria campanhas. O Admin Master vê o de
   cada marca.
   Empresa com WhatsApp **e** e-mail recebe os dois em cada toque (nas Empresas novas, só o WhatsApp).
5. Quando alguém responde com interesse, a automação para e a resposta aparece em **Oportunidades** (🔥), com o
   resumo, para a equipe toda. Quem estiver livre responde o cliente, clica em **Marcar como atendido** e segue com a
   negociação (veja **Oportunidades** abaixo).
6. Veja em **Inteligência** qual segmento, canal e mensagem funcionam melhor.

**E-mail:** as campanhas saem do e-mail @mscertificados.com.br configurado em **Configurações > E-mail**
(e-mail + senha de app do Google + "Enviar e-mail de teste").

**Resposta de robô:** quando quem responde é um robô da empresa (ex.: "Recebemos sua mensagem, aguarde um
momento", menu "digite 1", aviso de ausência), a IA SDR **não responde**, **não cria oportunidade** e a sequência
continua normalmente. Desde 17/11/2026 o sistema reconhece também "X agradece sua mensagem. Não estamos disponíveis
no momento", menus de departamento ("1 - Fiscal, 2 - Pessoal..."), "em breve você será atendido", "você foi removido
do menu por inatividade", pesquisa de satisfação e "este canal é exclusivo para documentos". Uma recusa educada ("Agradecemos
o contato, mas não temos interesse") continua valendo como recusa, e várias mensagens curtas seguidas de uma pessoa
("Sim", "Bom dia", "Vamos agendar") não viram robô. O nome do atendente em negrito no começo ("*Gabi:* Boa tarde!")
e um "Em que posso ajudar?" sozinho também não contam como robô: na dúvida, a resposta aparece como oportunidade. Além disso, a SDR responde no máximo 1 vez por dia para o mesmo contato, para nunca entrar
numa conversa sem fim. Se o mesmo lead mandar várias mensagens, tudo fica na mesma oportunidade.

**Minha fila (menu):** mostra os seus disparos num lugar só, em 4 abas. Clicar no **nome da empresa** (ou no nome da
campanha logo abaixo) abre a **campanha** daquele envio, já nas mensagens daquela empresa (em destaque); o mesmo vale
na tela **Envios** e na **Agenda**. Quem não pode abrir aquela campanha vai para a ficha do lead. As abas:
- **Próximos envios:** o que ainda vai sair, separado por dia (Atrasados, Hoje, Amanhã, os próximos dias) e na ordem
  em que vai sair. Cada envio mostra a situação em destaque (ex.: "Aguardando seu clique", "WhatsApp em branco",
  "Programado") e o botão certo: **Enviar** ou **Cadastrar WhatsApp**/**Cadastrar e-mail**, quando falta o contato.
  Ao lado de **Programado** e de **Fora do horário** aparece **quando o envio sai sozinho** (ex.: "sai amanhã às
  08:41"): o horário marcado, ou quando completam 20 horas do último WhatsApp (ou e-mail) para a empresa, sempre dentro
  do horário de envio, em dia útil (a Renovação também respeita o horário e os feriados dela). A fila manda um por vez
  em cada número, com alguns minutos entre um e outro: quando muitos ficam livres na mesma hora, alguns saem depois. Envio que espera o
  seu clique não mostra horário.
  **Quantos saem por hora:** logo acima da lista, um quadro por dia (Hoje, Amanhã e os próximos) mostra, hora a hora,
  quantos WhatsApps e quantos e-mails vão sair, pelo horário previsto de cada envio, e o total do dia. Ele segue os
  filtros da tela (pessoa, canal, campanha, período). O que não tem hora para sair (espera o seu clique ou um ajuste,
  como o WhatsApp em branco) aparece embaixo, separado. A fila manda um por vez em cada número, com pausas: numa hora
  cheia, parte sai na hora seguinte (as campanhas aprovadas desde 23/11/2026 já entram nas vagas do número).
  Para achar um envio, use os filtros: **Quando** (todos, hoje e atrasados, atrasados, hoje, amanhã, próximos dias),
  **Situação**, a **campanha** e a **busca pelo nome da empresa**. Cada filtro mostra quantos envios há nele;
  **Limpar filtros** volta a mostrar tudo.
  **Cancelar:** o botão vermelho **Cancelar** de cada envio tira só aquele envio da fila (ele não sai mais; os outros
  toques da empresa continuam). Com um filtro escolhido aparece também **Cancelar os N envios mostrados**, para
  cancelar de uma vez, por exemplo, todos os atrasados de uma campanha. O sistema pede confirmação antes.
- **Na fila do WhatsApp:** o que está saindo agora, um por vez;
- **Histórico (7 dias):** o que saiu ou falhou, com o erro de quem não saiu;
- **Registro dos disparos:** disparos e testes.

Os números do topo também são atalhos: clique em **Atrasados** para ver só os atrasados, em **Para sair hoje** para
ver os de hoje e os atrasados. Admin e gestor podem ver a fila de outra pessoa ou da equipe toda.

**Oportunidades (menu 🔥):** os leads que responderam. O número vermelho ao lado de **Oportunidades** no menu é
quantas oportunidades **novas** esperam atendimento na sua marca (as mesmas da aba **Novas**); os avisos do sininho
ficam em **Avisos (N)**, no rodapé do menu. **A equipe toda vê todas as respostas**: ninguém precisa
"assumir" o lead, quem estiver livre atende o cliente na hora. Quando chega uma resposta nova, **todos da equipe
recebem o aviso no sininho** (o aviso por e-mail continua indo só para o responsável pelo lead). Quando alguém atende
ou descarta, o aviso some do sininho de todos. São 4 abas:
- **Novas:** esperam alguém da equipe responder. Ficam separadas por dia (Hoje, Ontem, o dia da semana) e, em cada
  dia, as **quentes vêm primeiro**. Cada cartão mostra há quanto tempo o lead está **esperando** e até quando
  responder: o **prazo é de 2 horas úteis** (horário de envio, de segunda a sexta; uma resposta das 17h30 tem prazo até
  10h do dia útil seguinte). Passou do prazo, fica vermelho. Mostra também a campanha e quem é o dono dela, o canal
  (e por qual número a mensagem saiu), o contato do cliente, o que enviamos, o que o lead respondeu e o que a IA
  entendeu. Botões: **Marcar como atendido** (depois de responder o cliente: a resposta sai da lista e a automação do
  lead para; o responsável pelo lead continua o mesmo), **Iniciar WhatsApp**, **Ver conversa** (abre a conversa em
  Conversas, pelo número em que ela está) e **Descartar**: para descartar é preciso **escolher o motivo** (sem interesse, já renovou, já tem
  parceiro, resposta de robô, pessoa errada...). O motivo aparece na aba Descartadas e ensina o que ajustar nas
  campanhas.
  **Já renovou:** quando o cliente da Renovação diz que já renovou, descarte com esse motivo: o certificado dele vira
  **Renovado** na tela Renovação e os avisos que faltavam não saem mais. Se o contato tiver mais de um certificado
  ativo, o sistema avisa para marcar na tela Renovação qual foi renovado.
- **Atendidas:** quem atendeu, quando e quanto tempo depois da resposta.
- **Descartadas:** o que foi descartado. Descartou sem querer? O botão **Voltar para Novas** desfaz.
- **Todas as respostas** (só administrador e gestor): tudo o que os leads responderam, inclusive "sem interesse",
  "pediu para sair" e respostas de robô.

Para achar uma oportunidade, use os filtros: **Quando** (tudo, hoje, ontem, últimos 7 ou 30 dias, mais de 30 dias),
**Tipo** (quentes ou para analisar), **Resposta** (na aba Todas as respostas), **Canal** e a **busca pelo nome da
empresa**. Cada filtro mostra quantas há nele. Com um filtro escolhido aparece **Descartar as N mostradas**, para
descartar de uma vez, por exemplo, todas as "para analisar" de ontem (o sistema pede confirmação; dá para voltar com
elas pela aba Descartadas). Os números do topo mostram quantas esperam, quantas são quentes, quantas passaram do
prazo de 2 horas úteis e o tempo típico até alguém atender. Todos da equipe veem todas as oportunidades; o nome da
empresa só abre a ficha do lead para quem pode ver aquele lead.

**Quem precisa de mim hoje (topo do Dashboard):** a lista de trabalho de cada pessoa, para nenhum interessado ser
esquecido:
- **Respostas quentes** esperando atendimento (de toda a equipe), com o prazo de 2 horas úteis ("responder até
  10:30" ou "fora do prazo há 3 h") e o botão **Marcar como atendido** ali mesmo;
- **Respostas para analisar** (mornas): decidir se insiste ou descarta, com o motivo;
- **Suas tarefas** de hoje e as atrasadas (reuniões, ligações, follow-ups; os toques das campanhas ficam na Minha fila);
- **Leads esfriando:** os seus, em conversa (respondeu, interessado, assumido, reunião, negociação), sem nada
  acontecer há 7 dias ou mais e sem nada agendado. Abra e agende o próximo passo;
- **Parceiros sem venda** há muito tempo.
Quando está tudo em dia, o quadro diz "Tudo em dia".

**Lead perdido precisa de motivo:** para marcar um lead como **Perdido** (na ficha, na mudança em lote ou arrastando no
Pipeline) é obrigatório escolher o motivo da perda.

**Disparar campanha (qualquer pessoa da equipe):** na página da campanha ativa, **🚀 Disparar campanha** tem os
botões **Disparar campanha WhatsApp** e **Disparar campanha e-mail**. Eles mandam na hora o toque de hoje de cada
empresa pelo canal escolhido, um por vez, com horário, limites, controle de frequência e opt-out. Quando alguma
não sai, o aviso diz o motivo de cada uma (ex.: "recebeu mensagem há pouco (controle de frequência) (2)"), e o mesmo
fica registrado em **Fila de envios**.

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
- **Celular:** a Receita e a CNPJá guardam o celular sem o 9 da frente (ex.: (81) 9888-7777). O sistema coloca o 9
  ((81) 99888-7777) e, na campanha com WhatsApp, usa esse número como o WhatsApp da empresa. Na campanha com
  WhatsApp, as empresas com celular vêm primeiro: as que só têm telefone fixo só entram se faltar empresa com celular.
  Celular informado à Receita nem sempre tem WhatsApp: se a mensagem não chegar, confira o número.
- **Empresa que já estava cadastrada:** a campanha usa o mesmo cadastro (não duplica). Se a empresa veio de outra
  busca (ex.: a base da Receita), ela passa a mostrar a lista em **Origem do lead** e ganha da lista o que faltava
  (celular, e-mail, endereço...). O que já estava preenchido não muda, e o histórico da empresa conta o que mudou.
  Empresa cadastrada à mão ou por indicação continua com a origem dela.

### Empresa que cada usuário representa

Cada usuário pode trabalhar por uma empresa diferente (ex.: MS Certificação Digital, Grupo Certy Certificados).
Em **Minha conta > Empresa que eu represento**, cada pessoa preenche: nome da empresa, site e apresentação curta.
A partir daí, as campanhas, mensagens de WhatsApp, e-mails e a assinatura dessa pessoa falam em nome da empresa
dela (nas campanhas de parceria e na área Empresas novas). Para outra empresa, as mensagens não falam de onde é a
validação (o "presencial em Recife" é da MS).
Quem deixa em branco fala pela **marca da sua empresa** no sistema (Configurações > Marca). Mensagens já enviadas
não mudam; as que ainda vão sair são corrigidas na hora do envio.

### Feriados da cidade de cada pessoa

Nos feriados de quem envia, as campanhas dessa pessoa **não enviam nada** (WhatsApp, e-mail e avisos da Renovação) e a
agenda dela **não oferece horários de reunião**. Valem:
- os **feriados nacionais**, automáticos (com Carnaval, Sexta-feira Santa e Corpus Christi);
- os do **estado** e da **cidade** onde a pessoa trabalha. Os de **todo o Brasil já vêm prontos**: todos os estados e
  os 5.570 municípios (3.838 têm feriado próprio na base, montada com dados públicos de 2024 a 2026).

Como deixar pronto:
1. Cada pessoa informa a **cidade e a UF** em **Minha conta > Onde eu trabalho** (ou o administrador, em
   Configurações > Usuários > Editar). O sistema confere o nome na lista do IBGE e avisa se não achar ("Você quis
   dizer...?").
2. Pronto: os feriados da cidade e do estado dela já valem. Em **Configurações > Feriados** dá para consultar os
   feriados de qualquer cidade e ver, em cada quadro, os que vêm da base.
3. Se faltar ou sobrar algum, acerte no quadro da cidade (uma data por linha): `16/07 Nossa Senhora do Carmo`
   acrescenta (todo ano), `20/11/2026 Ponto facultativo` acrescenta só naquele ano e `-16/07` tira um feriado da base.
   Um feriado nacional não sai. Ao salvar, os toques já marcados para um feriado **mudam sozinhos para o próximo dia de
   envio** de quem envia (e o sistema confere de novo de hora em hora e na hora de enviar).

Cada marca tem os seus acertos. Quem está sem cidade no cadastro segue os feriados do **estado e da cidade da marca**
(Configurações > Marca > "Estado (UF) da marca" e "Cidade da marca"); se a marca também não tiver, só os nacionais (e os
do estado, se a pessoa tiver a UF). A base tem os anos 2024 a 2026: o feriado que caiu no mesmo dia nesses anos vale todo ano; o que mudou de
dia (decreto de um ano só) vale só em 2026. Feriado municipal novo ou mudado por decreto: acrescente no quadro.

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
**aguardando aprovação**. Depois de aprovada, **tudo sai sozinho, sem clique**: o e-mail e o WhatsApp entram na fila
e saem cada um no seu horário, um por vez, com as pausas e os limites do número (WhatsApp: 1 a cada 8 a 12 minutos,
6 por hora por número, sem limite por dia desde 17/11/2026, só no horário de envio; quem pede SAIR não recebe mais). Ao aprovar,
cada WhatsApp entra numa vaga do número de quem envia, e o que fica de um dia para o outro vai sozinho para a próxima
vaga (veja "Vagas de WhatsApp de cada número"). São 3 toques: dia 1 (boas-vindas + oferta do e-CNPJ), dia 3 (lembrete)
e dia 7 (último contato). As mensagens podem ser editadas na própria tela. A IA não responde sozinha esses
leads: as respostas vão para **Oportunidades** e o time conversa.

- **Buscar agora:** escolha as datas de abertura (até 7 dias), escolha **quantas empresas buscar** (10, 20, 30, 40,
  50 ou 100; cada 10 gastam 1 crédito) e clique em **Buscar e montar campanha**. A campanha leva **todas** as
  empresas que vierem e puderem entrar: nada pago fica sem uso. O **Máximo de empresas por campanha diária**
  (passo 2) vale só para a busca automática, que pede à CNPJá o dobro desse número e usa esse número.
- **Muitas empresas de uma vez:** o WhatsApp sai no ritmo do número (uns 6 por hora; o teto de contatos frios por
  dia está desligado desde 17/11/2026). Com 50 ou 100 empresas, leva algumas horas ou dias. O quadro **Vagas de
  WhatsApp no número de quem envia**, embaixo do Buscar agora, mostra quantas vagas livres há hoje e nos próximos dias;
  ao aprovar, o que não cabe vai para o próximo dia com vaga, sem ficar atrasado.
- **Custo:** cada 10 empresas encontradas gastam 1 crédito (a busca por faixas de capital pode gastar alguns a
  mais). Em PE abrem cerca de 380 empresas por dia
  (≈ 1.100 créditos por mês).
- Os celulares que a Receita guarda sem o 9 ganham o 9 na frente (é um palpite: confira antes de enviar).
- Empresas com o mesmo telefone/e-mail (do contador) **não** são juntadas: só o CNPJ conta como repetido.
- Opção para deixar de fora **empresário individual** (inclui os MEIs, que muitas vezes não precisam de e-CNPJ).
- **WhatsApp primeiro, e-mail depois:** empresa com celular recebe os 3 toques **por WhatsApp**, que saem sozinhos
  depois da aprovação (o botão **Enviar** da **Minha fila** ou da campanha só adianta). Se ela também tem e-mail,
  cada toque ganha a versão por **e-mail**, marcada para umas 2 horas depois do WhatsApp (ou o dia seguinte, se não
  couber no horário). O e-mail só sai **depois** que o WhatsApp da empresa saiu; se ela responder no WhatsApp antes,
  o e-mail não sai. Se o WhatsApp travar (atrasado mais de 2 dias, esperando clique, ou sem número), o e-mail sai
  assim mesmo. E o e-mail que ficou **atrasado** (era de um dia que já passou) sai sem esperar o WhatsApp: assim a
  fila de e-mail não fica presa quando o WhatsApp está no limite do dia. Quem não tem celular recebe só por e-mail. Para não mandar e-mail nenhum, desmarque o canal
  **E-mail** no passo 4. As campanhas de **parceiros** da IA SDR também saem sozinhas desde 12/11/2026 (o
  administrador pode desligar em cada campanha).
- **Buscar de novo não gasta à toa:** toda empresa que já veio entra numa lista de exclusão guardada na própria
  CNPJá. Buscando o mesmo dia de novo, a CNPJá só traz (e só cobra) as empresas que ainda não vieram.
- **Atividade:** a busca pega empresas novas de **qualquer atividade** (toda empresa nova pode precisar do e-CNPJ).
- **Maior capital social primeiro:** a busca (no **Buscar agora** e na automática) traz primeiro as empresas de
  **maior capital social**: pede à CNPJá as de R$ 1 milhão ou mais, depois as de R$ 500 mil a R$ 1 milhão, e assim
  por diante, até completar a quantidade. A campanha também começa por elas (entre as que têm celular ou e-mail), e o
  capital aparece na lista das empresas encontradas e nas observações do lead. O botão **Testar** continua pegando
  10 empresas quaisquer daquele dia (1 crédito).
- **Lista de exclusão:** com a opção marcada, quem já está em alguma **lista importada** (Configurações >
  Integrações > Listas) fica de fora. Também ficam de fora: repetidas, leads já em atendimento e quem pediu para sair.
- **Ver as empresas encontradas:** no quadro **"Empresas encontradas na CNPJá"**, clique na busca. A lista mostra
  razão social, CNPJ, **capital social** (do maior para o menor), cidade, data de abertura, **telefone fixo**, **celular**, **e-mails**, atividade e quem ficou
  de fora (e por quê), com o link da campanha.
- **Testar a API:** o botão **Testar (10 empresas · 1 crédito)** busca até 10 empresas abertas **num dia** e só
  mostra a lista. Cada teste olha um dia diferente (ontem, anteontem...), para não vir sempre a mesma lista. Se estiver certa, clique em **Montar a campanha com estas empresas** (não gasta crédito).

### Renovação (aviso de vencimento do certificado para os clientes)

Menu **Renovação**. O sistema avisa os clientes da MS antes de o certificado digital vencer: **30, 15, 5 e 1 dia
antes**, pelo WhatsApp e pelo e-mail. Os clientes vêm do **Relatório de renovação** que vocês exportam do sistema da
certificadora.

**Cada marca tem a sua Renovação** (desde 24/11/2026): a planilha, os clientes, as campanhas e todas as configurações
(dono, número, dias dos avisos, horários, feriados, canais, arte e textos) são só da marca. O que uma marca muda não
muda nas outras. A campanha automática do dia, por enquanto, roda só para a MS.

**Passo a passo:**
1. **Teste primeiro** (quadro **1. Testar os avisos**, ver abaixo): mande os avisos para o seu WhatsApp e confira.
2. Exporte o **Relatório de renovação** (Excel) no sistema da certificadora. Em **Renovação**, no quadro
   **2. Importar a planilha de renovação**, escolha o arquivo e clique em **Importar planilha**. Pode importar de novo sempre que sair um relatório novo: quem já estava é atualizado, sem
   duplicar.
3. No quadro **3. Montar campanha agora**, escolha quantos contatos (10 a 100; vão os que vencem primeiro) e clique
   em **Montar campanha**. Em alguns minutos a campanha fica **aguardando aprovação**.
4. A campanha que espera aprovação aparece no **topo da tela Renovação**, com o botão verde **APROVAR CAMPANHA**
   (também no quadro **Campanhas de renovação** e na página da campanha). Para conferir as mensagens antes, clique em
   **Ver os avisos**. Depois de aprovar, você volta para a tela Renovação.
   Depois de aprovada, tudo sai sozinho. As campanhas de renovação não aparecem na lista da IA SDR.
5. No quadro **4**, escolha o **dono** (ele assina e os e-mails saem pela conta dele) e o **Número de WhatsApp dos
   disparos** (só o administrador escolhe; fica gravado em cada campanha e dá para trocar na página da campanha).
   **Número em "MODO TESTE" só simula o envio: a mensagem não chega.** No automático, o sistema usa o número de quem
   assina e nunca um em modo teste quando há um de verdade conectado. Se quiser, ligue a **campanha automática**:
   todo dia, no horário escolhido, o sistema monta a campanha com quem chegou a 30 dias do vencimento (ela também
   espera a aprovação). Clique em **Salvar configuração**.

**Dias, horário e início (quadro 4):** em **Avisar quantos dias antes de vencer** você escreve os 4 dias dos avisos
(padrão 30, 15, 5, 1; no piloto de 13/11/2026: **12, 6, 3, 1**). **Avisos a partir das** e **até as** limitam o
horário (hoje: das 10:00 às 18:00). **Começar em** é o dia em que a campanha automática começa a montar sozinha (no
piloto: 01/01/2027). Valem para as campanhas montadas depois de salvar.

**Só em dia comercial:** os avisos da Renovação só saem **de segunda a sexta, das 10:00 às 18:00** (o horário do quadro
4). Fora disso eles esperam e saem no próximo horário permitido; o WhatsApp para às 17:50, para chegar ao cliente antes
das 18:00. O botão **Disparar** e o **Enviar** da Minha fila também só funcionam nesse horário. Quem vence no
**sábado ou no domingo** recebe o **último aviso na sexta** antes (nunca no fim de semana nem depois do vencimento).

**Feriados:** nos feriados também não sai aviso. Os nacionais já estão incluídos (e também Carnaval, Sexta-feira Santa
e Corpus Christi). Os da cidade ou do estado você escreve em **Outros feriados** (quadro 4): `08/12` vale todo ano e
`08/12/2026` só naquele ano. O aviso que cairia num feriado sai no dia útil antes. Ao salvar um feriado novo, os avisos
já marcados para ele mudam de dia sozinhos (se não couber em outro dia antes do vencimento, aquele aviso é cancelado).

**Piloto de 13/11/2026 a 01/01/2027:** a campanha **"Renovação – piloto"** leva todos os clientes da planilha que vencem
até 31/12, com os avisos já marcados (12, 6, 3 e 1 dia antes, a partir das 10h, WhatsApp com a arte pelo número do
Paulo Lucas, e-mail ~2 h depois). A partir de 01/01/2027 a campanha automática do dia assume (importe o relatório de
renovação novo antes, para entrarem os clientes de janeiro).

**Como funciona:**
- Entra quem vence até o dia do 1º aviso (ex.: **próximos 12 dias**). Quem já venceu **não recebe aviso**.
- **Dois vencimentos distantes no mesmo contato** (ex.: um certificado vence em 20/11 e outro em 18/12): cada um ganha
  os próprios avisos, na mesma campanha.
- Todas as mensagens terminam com **"Se você já renovou, pode desconsiderar esta mensagem."** (a equipe também avisa
  e o sistema só sabe quem renovou se alguém marcar **Renovado** na lista).
- **Uma mensagem por contato:** se o mesmo WhatsApp aparece em vários certificados (ex.: um grupo de empresas com o
  mesmo telefone), ele recebe **uma** mensagem em cada aviso, com a lista dos certificados (até 5; com mais, um
  resumo: "57 certificados digitais que você acompanha vencem entre..."). Nunca uma mensagem por certificado.
- **Datas:** 30, 15, 5 e 1 dia antes do vencimento. Quem entra mais tarde começa pelo aviso que combina com os
  **dias que faltam** (ex.: com 12, 6, 3 e 1 dia, quem vence amanhã recebe só o **Último aviso**, nunca o 1º; faltando
  2 ou 3 dias, o **Faltam poucos dias**). Esse primeiro aviso se apresenta como o 1º ("Olá, Paula! Aqui é Thamires,
  da Grupo Certy. Último aviso: ...", com a marca de quem montou a campanha) e traz a frase do SAIR; depois vêm só os
  seguintes que ainda cabem (nunca em dias seguidos). Aviso que atrasou (número desconectado, fila parada) também sai com o texto dos dias que faltam no
  dia em que sai, e os avisos repetidos são cancelados sozinhos. Aviso que cairia no sábado ou no domingo vem para a sexta antes;
  quem vence no fim de semana tem o último aviso na sexta (se preciso, o aviso anterior vem um dia antes para caber).
- **WhatsApp primeiro, e-mail depois:** igual às Empresas novas (o e-mail de cada aviso sai umas 2 horas depois do
  WhatsApp). Quem não tem celular na planilha recebe só por e-mail. Sem WhatsApp e sem e-mail na planilha, não recebe
  aviso (aparece no filtro **Sem WhatsApp e e-mail**): o contato vem só da planilha.
- **Teto por dia (quando ligado):** com o teto de contatos frios ligado em Configurações > Geral (era 20; desligado
  desde 17/11/2026, e aí os avisos ficam nos dias certos e saem no ritmo de 15 por hora), a campanha espalha os avisos: no máximo 20 WhatsApps de renovação por dia, quem vence antes recebe antes, todo mundo recebe o
  1º aviso e os lembretes entram nas vagas que sobram. Com 100 clientes, os primeiros avisos levam uma semana.
- **Renovação antes das Empresas novas:** as duas usam o mesmo número e o mesmo limite. No mesmo dia, a renovação sai
  primeiro (tem prazo). Nos dias cheios de renovação, as Empresas novas esperam.
- **Os mesmos cuidados com o WhatsApp:** uma mensagem a cada 8 a 12 minutos, limite por hora, só no horário de
  envio, e quem responde SAIR não recebe mais.
- **Quando o cliente responde:** os avisos seguintes param e a resposta vai para **Oportunidades** e **Quem precisa de
  mim hoje**. A IA não responde esses clientes: quem conversa é a equipe. Se ele disser que já renovou, descarte a
  resposta com o motivo **Já renovou**: o certificado vira Renovado sozinho.
- **Pelo número oficial (API da Meta):** dá para mandar os avisos pelo número oficial da empresa, com os botões Quero
  renovar, Já renovei e Parar avisos (veja **API oficial do WhatsApp (Meta)**). Ligue no quadro 4.
- **E-mail em HTML com a marca:** com o módulo liberado para a marca, o quadro 4 mostra o botão **✉️ E-mail em HTML com
  a marca** (vem marcado). Os e-mails dos avisos que vão **sem a arte** (quem tem vários certificados, ou quando a arte
  não fica pronta) saem com o logo e a cor da marca, em **todos** os avisos (quem recebe é cliente, não contato frio).
  Com a arte, continua indo a arte. Desmarcar vale também para as campanhas em andamento.
- **Arte do aviso:** cada aviso vai com a **arte do site** (mscertificados.com.br/interno/aviso-vencimento)
  preenchida com os dados do cliente: e-CNPJ ou e-CPF, A1 ou A3, razão social ou nome, CNPJ ou CPF, a data de
  vencimento e quantos dias faltam. No WhatsApp a arte vai como imagem e o texto como legenda, **para todos os
  clientes**, também quem nunca conversou com a MS (decisão da Maria em 12/11/2026, ciente do risco maior de bloqueio
  do número). O e-mail do mesmo aviso leva a mesma arte. Quem tem vários certificados recebe a lista no texto, sem a
  arte. Quem desenha a arte é o **computador do WhatsApp Leads**, que precisa do **Google Chrome instalado** e de
  internet. Se a arte falhar, o aviso sai só com o texto e a tela Renovação avisa. Mudou a arte no site? Em até 6
  horas os avisos já saem com a arte nova. Para desligar: quadro 4, opção **Arte do aviso junto**.
- **Arte de cada marca (campo "Endereço da arte do aviso", quadro 4):** cada marca tem a sua página da arte, com o
  logo e as cores dela (uma cópia da ferramenta de aviso do site da MS, com os mesmos campos). Quem coloca ou troca o
  endereço é o **administrador master**: entre na marca (Painel master > **Entrar na AR**), abra a Renovação e escreva
  o endereço (começando com https://) no quadro 4; ao salvar, o sistema abre a página e confere se ela tem o desenho da
  arte. Pode ser o endereço da página do site onde a ferramenta aparece, também em site feito no **Wix**: o sistema
  acha a ferramenta dentro da página e guarda o endereço dela. Nas artes das outras marcas, o "FALTAM N DIAS" vai
  numa etiqueta branca no alto, ao lado de "AVISO DE VENCIMENTO".
- **Cada marca com o seu dono e o seu número:** o **dono das campanhas de renovação** e o **número dos disparos**
  são de cada marca. Salvar o quadro 4 dentro de uma marca não muda os da outra. O resto do quadro 4 (campanha do
  dia, dias dos avisos, horários, feriados e canais) ainda vale para todas: a tela das outras marcas avisa isso. Fora
  das marcas, o administrador master mexe na Renovação da MS. Em branco: a MS volta para a arte do site da MS, e as outras marcas mandam os avisos só com o texto. O teste
  do quadro 1 já usa a arte da marca em que você está.
- **Testar antes (quadro 1, "Testar os avisos"):** como o teste da IA SDR. Escolha também **por qual número** o teste
  sai (número em modo teste: a tela avisa que não chega de verdade). Escolha um cliente da planilha (ou o
  cliente fictício), o canal (WhatsApp ou e-mail), digite o **seu** WhatsApp ou e-mail, escolha os avisos (só o 1º, um
  deles ou os 4) e deixe marcado **Mandar a arte junto** para receber a arte do site com os dados do cliente. Chega
  com "[TESTE]" no começo, assinado por quem assina as campanhas de renovação e pelo WhatsApp/e-mail dele. Nenhum
  cliente recebe nada e nenhuma campanha muda. A arte do teste de e-mail vem da arte que o computador desenhou no teste
  de WhatsApp do mesmo cliente: mande primeiro o teste no WhatsApp e, 1 minuto depois, o de e-mail.
- **Achar um cliente:** no quadro **Certificados da planilha**, digite no campo de pesquisa (ao lado do título) uma
  parte do nome do cliente ou do responsável, o CNPJ/CPF, o telefone ou o e-mail e clique em **Buscar**. A busca olha
  **todas as abas** (inclusive renovados, cancelados e vencidos), não liga para acento nem para maiúsculas e aceita o
  número com ou sem pontos e traços. Os botões da linha funcionam ali mesmo, e **Limpar a busca** volta para a aba.
- **Renovou?** Na lista de certificados, clique em **Renovado** (ou **Não vai renovar**): os avisos que ainda não
  saíram param (WhatsApp e e-mail). **Reabrir** desfaz. Vale também para o certificado que **já venceu** (o cliente
  que renova depois do vencimento): na aba **Vencidos**, os botões **Renovado** e **Não vai renovar** aparecem na
  linha e ele passa para a aba **Renovados e não vão renovar**.
- **Parar os avisos de um cliente** sem dizer se renovou: botão vermelho **Cancelar avisos** na linha dele. Os avisos
  que ainda não saíram param e ele vai para a aba **Avisos cancelados** (**Reabrir** desfaz).
- **Cancelar a campanha inteira:** botão **Cancelar campanha**, no aviso do topo (campanha esperando aprovação) ou no
  quadro **Campanhas de renovação**. Nenhum aviso dela que ainda não saiu vai sair.
- A data de nascimento que vem no relatório **não é guardada**.

### Intervalo entre os envios automáticos

Nas campanhas automáticas (depois da aprovação), os **e-mails** e as **mensagens de WhatsApp** que saem sozinhos
saem **um de cada vez**, sorteando o tempo a cada envio (nunca todos no mesmo horário): **e-mail, 3 a 4 minutos**
entre um e outro; **WhatsApp, 8 a 12 minutos em cada número** (desde 17/11/2026, quando o WhatsApp restringiu um número
por "envio de spam" depois de 66 mensagens no dia; muda em **Configurações > Geral**). Desde 23/11/2026 o intervalo do
WhatsApp é de cada número: dois números diferentes mandam ao mesmo tempo, e o mesmo número nunca manda dois em menos
de 8 minutos. E-mail e WhatsApp têm cada um o seu intervalo. Os envios feitos por clique de uma pessoa não esperam a fila da Prospecção, mas o WhatsApp Leads também
espera de 3 a 6 minutos entre uma mensagem e outra de cada número (Configurações do WhatsApp Leads).
Com mais de uma marca, a vez **reveza**: o próximo envio é da marca que mandou há mais tempo, e uma marca que chegou ao
limite dela espera sozinha, sem segurar as outras.

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

**Número em MODO TESTE:** no WhatsApp Leads, o modo teste só **simula** o envio: a mensagem não chega. Por isso a
escolha automática do número (campanhas da IA SDR, Empresas novas e Renovação) **nunca usa um número em modo teste
quando há um número de verdade conectado** (QR code), e no sistema de verdade **nunca usa um número em modo teste**:
sem número de verdade conectado, a mensagem **espera na fila** e a pessoa recebe o aviso para conectar o WhatsApp
(desde 17/11/2026, quando 45 mensagens "saíram" simuladas depois que um número caiu). Nas listas de números ele aparece
como **"MODO TESTE (não chega de verdade)"**, e a página da campanha mostra um aviso vermelho se o número escolhido para ela estiver em modo teste.
(Em 11 e 12/11/2026, 14 mensagens de campanha saíram por números em modo teste e não chegaram.)

### E-mails que não existem

Muitos e-mails da base da Receita estão desatualizados. O sistema tira esses endereços das campanhas sozinho:

- **Antes de enviar**, confere se o domínio do e-mail existe e recebe e-mails (ex.: `jaci@jacicontabilpe.com.br`,
  cujo domínio não existe). Esse e-mail nem sai.
- **Depois de enviar**, a cada 5 minutos lê as mensagens de devolução que chegam na caixa ("Endereço não
  encontrado", "Undeliverable", "Mail delivery failed"). O e-mail daquele lead é marcado como **não existe**.
  Na primeira vez, ele também lê as devoluções dos últimos 60 dias que já estão na caixa.
- Lead marcado: os próximos e-mails da campanha para ele são cancelados, e a ficha mostra o selo vermelho
  **"não existe"** ao lado do e-mail. Se você corrigir o endereço em **Editar**, ele volta a receber.
- Recusa temporária (caixa cheia, servidor da empresa fora do ar) **não** tira o e-mail enquanto o servidor de envio
  ainda está tentando (no Gmail, o aviso "Delivery Status Notification (**Delay**)"). Quando ele **desiste** depois de
  alguns dias ("Delivery Status Notification (**Failure)**"), o e-mail não foi entregue: o lead é marcado ("caixa de
  entrada cheia há dias" ou "o servidor do e-mail não recebe mensagens") e os próximos e-mails para ele são cancelados.
  Recusa por limite de envio ou reputação de quem envia não tira o e-mail (o endereço existe).
- Na página da campanha, o botão **Conferir e-mails** faz a conferência de todos de uma vez.
- **Corrigir e reenviar:** na página da campanha aparece o quadro **"E-mails que não existem"**, com as empresas
  marcadas, o motivo e botões para pesquisar no site, no Google e no Instagram. Digite o e-mail certo e clique em
  **Salvar e reenviar** (ou **Salvar**). A empresa volta para o cronograma: os envios parados voltam, com as datas
  empurradas para hoje em diante (o intervalo entre eles continua igual), e o e-mail que tinha voltado é reenviado
  hoje para o endereço novo. Se o endereço novo também não existir, o sistema avisa e não salva.

Obs.: a conferência do domínio não descobre se uma caixa específica existe (ex.: `fulano@hotmail.com`). Isso
só se sabe quando a devolução chega, e aí o sistema tira o e-mail sozinho.

### Consulta Assertiva (telefones, e-mails e sócios por CNPJ, CPF, telefone, e-mail ou nome)

A **Assertiva** encontra telefones (avisando se têm WhatsApp e se estão no cadastro "não perturbe"), e-mails,
endereços e sócios. **Cada marca usa as próprias credenciais e paga as próprias consultas.**

1. **Credenciais (o administrador, uma vez):** em **Configurações > Integrações**, quadro **Assertiva**, cole o
   **Client ID** e o **Client Secret** (portal da Assertiva > Integração > Credenciais), escolha a **finalidade** das
   consultas (para prospecção, "Legítimo interesse") e clique em **Salvar credenciais**. Depois, **Testar as
   credenciais** (não gasta consulta). As credenciais ficam guardadas criptografadas e nunca aparecem na tela. O
   Admin Master configura cada marca depois de "Entrar na AR".
2. **Consultar:** no menu **Consulta Assertiva**, escolha CNPJ, CPF, telefone ou e-mail e digite; ou busque por
   **nome** (com estado e cidade, se quiser). Na ficha do lead com CNPJ, use **Buscar contatos na Assertiva**.
3. **No lead:** no resultado aberto pela ficha, cada telefone, e-mail e sócio tem um botão (**Usar como WhatsApp**,
   **Usar como telefone**, **Usar como e-mail**, **Usar como responsável**). Só entra o que veio da Assertiva, e o
   valor de antes fica no histórico do lead.

**Custos:** cada consulta é cobrada pela Assertiva. A mesma consulta feita pela marca nos últimos **30 dias** aparece
de novo **sem cobrar**; "Consultar de novo" cobra outra. Os resultados ficam guardados 30 dias e depois são apagados
(LGPD). Quem pode consultar: administrador e gestor (o administrador libera para outros em Papéis e permissões,
"Consultar na Assertiva"). Telefone com o selo **não perturbe**: evite usar para prospecção.

### API oficial do WhatsApp (Meta)

O número oficial da empresa na Meta (Plataforma do WhatsApp Business) não tem o risco de bloqueio do QR code, mas a
Meta cobra por mensagem e a primeira mensagem para cada contato precisa ser um **modelo aprovado** por ela. Hoje o
sistema guarda as chaves, testa a conexão, manda uma mensagem de teste e recebe as respostas, o SAIR e a situação das
mensagens (entregue, lida). As campanhas continuam saindo pelos números do QR code até os modelos ficarem prontos.

Como ligar (o administrador da AR; o Admin Master, dentro da AR):
1. **Meta for Developers** (developers.facebook.com/apps) > **Criar app** > caso de uso **Conectar-se com clientes
   pelo WhatsApp** > escolha o portfólio da empresa > **Começar a usar a API** > **Criar uma conta do WhatsApp
   Business**. Não precisa usar o número de teste: o sistema liga o app à conta do WhatsApp sozinho quando você
   salvar o token.
2. **Número**: na mesma tela, **Adicionar número de telefone** (nome de exibição, um número que não esteja em nenhum
   WhatsApp, código por SMS ou ligação). Cadastre também a **forma de pagamento** (Gerenciador do WhatsApp >
   Faturamento): sem ela nenhuma mensagem sai, nem o teste.
3. **Publique o app**: Configurações do app > Básico (ícone, Política de Privacidade do site, categoria) >
   **Publicar**. Sem isso as respostas dos clientes não chegam ao sistema.
4. **Configurações do negócio** > Usuários > **Usuários do sistema** > Adicionar (Admin) > atribua o app e a conta de
   mensagens do número (Contas > Contas de mensagens; controle total) > **Gerar token** (validade "Nunca", permissões `whatsapp_business_messaging`,
   `whatsapp_business_management` e `business_management`). **Não mande o token para ninguém**: ele vai só na tela do
   sistema.
5. No sistema: **Configurações > WhatsApp > API oficial da Meta**. Preencha a Identificação do número de telefone
   (Gerenciador do WhatsApp > Números de telefone > clique no número), o token e
   a chave secreta do app (Meta for Developers > seu app > Configurações do app > Básico) e clique em
   **Salvar e testar**. O ID da conta de mensagens pode ficar em branco: o sistema descobre pelo token (se não achar, a tela diz o que
   fazer). O
   token e a chave ficam guardados protegidos e não aparecem mais na tela; para trocar, cole de novo.
6. **Ativar o número** (número novo): no quadro **Ativar o número na Meta**, digite duas vezes uma senha de 6 números
   e clique em **Ativar o número**. A Meta só aceita esse passo pelo sistema. **Anote a senha num lugar seguro**: o
   sistema não guarda, e a Meta pede essa senha para mudar o número de lugar ou apagá-lo. A Meta aceita até 10
   tentativas a cada 3 dias. Enquanto o número não estiver ativado, a tela avisa e os avisos da Renovação não saem por
   ele.
7. **Webhook**: no Meta for Developers > seu app > WhatsApp > Configuração, cole a **URL de retorno** e o **token de
   verificação** que aparecem na tela do sistema e assine o campo **messages**.
8. **Enviar teste**: mande antes um "oi" do seu celular para o número oficial (a Meta só deixa mandar texto livre
   para quem escreveu nas últimas 24 horas). Depois digite o seu celular e clique em **Enviar teste**: chega uma
   mensagem de teste em texto simples, de graça. O modelo de exemplo "hello_world" da Meta não serve: ele só sai dos
   números de teste dela.

**Foto do perfil do número oficial:** o número oficial não abre no celular, então a foto muda pelo sistema. Em
**Configurações > WhatsApp > API oficial da Meta**, no quadro **Foto do perfil no WhatsApp**, escolha a imagem (JPG ou
PNG, até 5 MB) e clique em **Trocar a foto**. O sistema usa o quadrado do meio da imagem e o WhatsApp mostra a foto num
círculo: deixe o logo no centro, longe dos cantos. A foto que está valendo aparece ao lado do botão; para os clientes,
a nova aparece em alguns minutos.

Quem responder ao número oficial: a resposta aparece no lead (para os próximos toques e avisa a equipe) e quem
mandar SAIR deixa de receber mensagens. Por enquanto, responda pelo app WhatsApp Business do celular.

**Avisos da Renovação pelo número oficial:**
1. Em **Configurações > WhatsApp > API oficial da Meta**, clique em **Enviar os modelos para a Meta aprovar**. São
   dois: o aviso com a arte e o aviso só com o texto, com os botões **Quero renovar**, **Já renovei** e **Parar
   avisos**. A Meta costuma responder em minutos (às vezes em até 24 horas); o sistema confere sozinho de hora em hora.
2. Aprovado, use **Enviar um aviso de exemplo** para ver como chega no seu celular.
3. Na tela **Renovação**, quadro 4, ligue **Enviar o WhatsApp dos avisos pela API oficial da Meta** e salve. Vale também
   para as campanhas de renovação em andamento. Para voltar ao número do QR code, é só desligar.

**Onde ver as respostas: menu API Oficial.** O número oficial não abre em celular (ele fica ligado direto na Meta).
Tudo o que ele manda e tudo o que chega nele aparece no menu **API Oficial**, separado das Conversas: a lista das
conversas (a mais recente primeiro, com as mensagens novas em destaque) e, ao clicar, a conversa com os avisos que
saíram (com ✓ enviada, ✓✓ entregue e ✓✓ lida, ou o motivo de não ter sido entregue) e tudo o que o cliente escreveu ou
tocou nos botões, inclusive de quem não é cliente cadastrado. O aviso que foi com a arte mostra a **imagem** em cima do
texto, como no WhatsApp: dá para conferir se saiu certa (nome, certificado, vencimento). Clique na imagem para vê-la
inteira numa aba nova. A imagem fica guardada o mesmo tempo da conversa (12 meses).
As **fotos e figurinhas que os clientes mandam** para o número oficial também aparecem na conversa, com a legenda: o
sistema baixa cada uma da Meta em até 1 minuto ("Imagem: aparece aqui em instantes" enquanto isso). A Meta guarda a
foto só 7 dias; se ela não entregar, a mensagem avisa "a Meta não entregou". Áudio, vídeo e documento ainda não
aparecem aqui (fale com o cliente pelo seu WhatsApp). O número vermelho ao lado de **API Oficial** é quantas
mensagens novas chegaram (some quando alguém abre a conversa). Para responder, fale com o cliente pelo seu WhatsApp ou
por telefone (responder pelo número oficial, de dentro do sistema, é o próximo passo). O item só aparece na marca que
tem a API oficial configurada.

**Quem vê as conversas do número oficial:** ele não precisa ser compartilhado, porque é da empresa, não de uma pessoa.
Todos da equipe da marca com a permissão "Ver as conversas da API oficial do WhatsApp" veem as conversas no menu
**API Oficial** (essa permissão vem ligada em todos os papéis). Em **Configurações > WhatsApp**, o quadro **Número
oficial (API da Meta)** mostra o número e a lista de quem vê. Para tirar alguém: **Configurações > Exceções por
pessoa**.

Como fica: os mesmos dias e horários de sempre, a arte do aviso em cima (quem tem vários certificados recebe a lista
no texto) e sem o limite de 20 por dia do QR code (a Meta cobra por mensagem). Quando o cliente toca em um botão:
**Quero renovar** vira uma oportunidade quente para a equipe; **Já renovei** marca o certificado como Renovado (com
vários certificados, a equipe confere qual); **Parar avisos** funciona como o SAIR. A arte é desenhada no computador do
WhatsApp Leads; se ele estiver desligado, o aviso sai só com o texto.

**Calendário para quem quer renovar.** Na tela **Renovação**, quadro 4, ligue **Calendário para quem tocar em "Quero
renovar"** e escolha a **Agenda de quem atende**. Quem tocar em "Quero renovar" recebe na hora, pelo número oficial, o
botão **Escolher o horário**: abre um calendário com os próximos 15 dias (só os dias com horário livre) e a lista de
horários. Ao confirmar:
- o horário vira uma **reunião na Agenda** de quem atende (nunca duas no mesmo horário; se alguém pegou o horário
  antes, o sistema marca o livre mais perto e avisa o cliente);
- o cliente recebe: "Combinado! Nossa equipe vai falar com você na quarta, 25/11, às 10:00 para fazer a sua
  renovação.";
- a equipe recebe o aviso no sininho, e a conversa aparece na tela **API Oficial**.
Os horários livres saem do expediente da pessoa (Configurações > Usuários) e das reuniões que já estão na Agenda dela.
No expediente, um dia com horário diferente vai separado por ponto e vírgula, por exemplo
`seg-qui 08:00-18:00; sex 08:00-17:30` (segunda a quinta das 8h às 18h, sexta das 8h às 17h30).
Para testar no seu celular: mande um "oi" do seu WhatsApp para o número oficial e, em **Configurações > WhatsApp**,
use **Testar o calendário** (a confirmação do teste vem com "[TESTE]" e não marca reunião). A Meta só deixa mandar o
calendário até 24 horas depois do toque do cliente.

## 5. Perfis de acesso

| Perfil | Vê |
|---|---|
| Administrador | Tudo, inclusive Configurações, usuários, todos os números de WhatsApp e as regras de envio |
| Gestor | O que é dele e o de **quem está abaixo** (funcionários e vendedores), com os indicadores; aprova as campanhas dessas pessoas e configura a Renovação e as Empresas novas (não altera configurações) |
| Funcionário MS | Quase toda a plataforma (prospecção, campanhas, IA, cadências, templates, categorias, conversas); **vê** o que é dele e o dos vendedores, mas só **mexe** no que é dele e no que for compartilhado com ele; não mexe em Configurações |
| Vendedor | Só os próprios leads, campanhas, tarefas e vendas |
| Parceiro | Só o portal: própria carteira, indicações, vendas e comissão |

**Quem está acima vê o que é de quem está abaixo** (pedido de 17/11/2026): Administrador > Gestor > Funcionário >
Vendedor. Colegas do mesmo nível não veem o que é um do outro, e quem está abaixo não vê o que é de quem está acima.
Nas telas com o filtro "de quem" (Campanhas, Minha fila, Leads, Pipeline, Agenda e Dashboard), quem está acima escolhe
uma das pessoas abaixo ou "todos". As **Oportunidades** continuam abertas para a equipe toda (16/11/2026). As telas
**Renovação** e **Empresas novas** (planilha da certificadora e busca paga na CNPJá) são só de quem as configura
(administrador e gestor).

Crie usuários em **Configurações > Usuários** (o perfil padrão é Funcionário MS).

**Admin master:** quem criou o sistema (na MS, o **Paulo Marinho**) aparece com o selo **admin master**. Só ele cria ou
promove administradores e dá permissões de administração. O cadastro, a senha e o código do celular dele só ele muda; os
dos outros administradores, só ele também. Ninguém muda o próprio papel, a própria equipe nem as próprias permissões.

**Cada marca (AR) vê só o que é dela.** O sistema separa as marcas: hoje a **AR MS Certificados** e o **Grupo Certy**.
Quem é de uma marca vê e mexe só nos leads, campanhas, tarefas, conversas, números de WhatsApp, e-mails, certificados
e relatórios da própria marca, mesmo sendo administrador. A marca de cada pessoa vem da empresa que ela representa
(Minha conta). O admin master vê todas as marcas. Os modelos de mensagem, as cadências e as categorias continuam
iguais para todas.

**Configurações de cada marca:** em **Configurações > Geral** (organizada em grupos: Horário de envio, WhatsApp,
E-mail, Campanhas e IA SDR, Parceria, Acompanhamento, Menu e Avisos e LGPD; chaves de liga/desliga, relógio nos
horários e um botão "Salvar alterações" sempre à vista), o administrador de uma marca muda só as configurações da
própria marca (horários e limites de envio, textos da parceria, regras da IA SDR, prazos). Os campos marcados como
**"da plataforma"** (proteção dos números de WhatsApp, avisos de problema, módulos, banco, Renovação, Empresas novas)
só o admin master muda; o que ele muda vale para as marcas que não têm valor próprio.

**Painel master** (link "Painel master", só para o admin master): mostra as marcas com os números de cada uma; **Entrar
na AR** pede o motivo (fica registrado) e, até clicar em **Sair da AR** (na faixa amarela do topo) ou por até
**2 horas** (depois volta sozinho para a plataforma; para continuar, entre de novo), mostra só aquela marca, como o
administrador dela vê; **Nova AR** (escreva o nome da empresa: o apelido, que vira o endereço dela, é preenchido
sozinho, sem acento nem espaço; depois de criar, entre na AR e coloque a marca em Configurações > Marca);
**Suspender** (as pessoas da marca não entram até reativar); e os
**módulos de cada marca**. O administrador de uma marca não muda os papéis do sistema, os modelos de mensagem, as
cadências e as categorias que valem para todas: ele cria os da própria marca (pode copiar de um da plataforma).
O que o admin master faz dentro de uma marca aparece no histórico dela (Configurações > Logs), marcado como dele.

**A marca de cada empresa nas telas e nas mensagens.** O endereço é um só para todas as marcas. A tela de entrada é
neutra (sem o nome de nenhuma marca); depois de entrar, cada pessoa vê o **nome, o logo, as cores e a fonte da própria
marca**, e as mensagens dela saem em nome da marca. Quem muda: o administrador da marca, em **Configurações > Marca**
(nome nas mensagens, nome curto nas telas, "a" ou "o" antes do nome, apresentação curta, site, domínio do e-mail da
equipe, estado e cidade da marca, cor principal, cor dos detalhes, cor do fundo, fonte e logo). O **estado e a cidade
da marca** puxam os feriados de quem ainda não informou a própria cidade; ao salvar, os toques que caíam num feriado
dela mudam de dia. O logo vai no menu colorido: de preferência a
versão branca, em PNG com fundo transparente, até 300 KB. Se o logo veio num fundo branco ou cinza (JPG) e aparece
como um retângulo no menu, marque **"Tirar o fundo liso do logo"** e salve (com o arquivo novo ou, sem arquivo, para o
logo de agora): o fundo some e o logo fica direto na cor do menu. Logo escuro ou colorido pode sumir no menu sem o fundo:
confira em "Como fica" e, se não gostar, envie o arquivo de novo sem marcar. Logo comprido (como o do Grupo Certy) fica
sozinho no alto do menu, na largura dele. Botões e títulos usam a cor principal um pouco mais escura
quando a original não dá leitura com letra branca. Depois de salvar, as outras pessoas veem a mudança em até 5 minutos.
O admin master muda o **nome neutro da plataforma** (tela de entrada) em Configurações > Marca, fora das marcas.
O e-mail de cada pessoa precisa ser do **domínio da marca** dela (Configurações > Marca); o e-mail principal, as
chaves (CNPJá), a base da Receita e as listas importadas são da plataforma: só o admin master muda.
A arte do aviso de vencimento (Renovação) é a do site da MS: só a AR MS manda; as outras marcas mandam só o texto.

**Dados de uma marca (LGPD):** para entregar os dados a uma marca, dois cliques em **exportar_ar.bat** (pede o
apelido da marca e uma senha; o arquivo fechado fica em `dados\exportacoes`; mande a senha por outro caminho). Para
apagar uma marca que saiu da plataforma, **apagar_ar.bat**, que só funciona depois de exportar no mesmo dia e pede para
digitar o apelido e SIM. A AR MS nunca é apagada por ele.

### Configurações organizadas por assunto

Em **Configurações**, um menu à esquerda separa tudo por assunto (no celular, é uma faixa que rola para o lado):
**Empresa** (Geral, Marca, Score dos leads), **Pessoas e acesso** (Usuários, Papéis e permissões, Exceções por pessoa,
Equipes e, para o admin master, Módulos), **Comunicação** (Contas de e-mail, Domínio do e-mail e WhatsApp), **Dados e IA** (Integrações, LGPD e dados,
Categorias de parceiros, Base de conhecimento da IA) e **Segurança** (Registro de atividades).

**Usuários separados por marca:** cada marca tem o seu quadro com as pessoas dela (nome e e-mail, papel, equipe,
situação). **Editar** abre os campos da pessoa logo abaixo da linha; **+ Nova pessoa** cria a pessoa já na marca do
quadro (equipe, parceiro e papel precisam ser da mesma marca). A busca no topo acha a pessoa pelo nome ou e-mail. O
admin master vê todas as marcas (e a plataforma); o administrador de uma marca vê só a dele.

### Permissões (Configurações > Pessoas e acesso, só o administrador)

Cada perfil acima é um **papel**. Em **Configurações > Papéis e permissões** (e nos itens ao lado dele) você pode:

1. **Papéis:** ver e mudar o que cada papel pode fazer. As permissões ficam em grupos que abrem e fecham (Painel,
   Leads, IA SDR...), cada um mostrando quantas estão liberadas. Em cada item escolha **Não**, **Só os próprios** (só
   o que é da pessoa), **Só a equipe**, **Eu e quem está abaixo** (o que é da pessoa e o de quem tem papel abaixo do
   dela) ou **Tudo**. Clique em **Salvar permissões do papel**. O Administrador tem sempre tudo.
2. **Novo papel:** clique em **+ Novo papel**, dê um nome (ex.: "Vendedor sênior"), escolha de qual papel copiar e
   ajuste. Depois escolha esse papel para a pessoa em Configurações > Usuários.
3. **Exceções por pessoa:** escolha uma pessoa (a lista separa as marcas) para dar uma exceção só para ela:
   - **PERMITIR** libera algo que o papel não dá (ex.: cobrir as férias de alguém, até uma data);
   - **NEGAR** tira algo do papel (ex.: não exportar planilhas). O NEGAR sempre vence.
   Ao lado aparece o **acesso real** da pessoa: o que ela consegue fazer agora e por quê.
4. **Equipes:** crie equipes (ex.: "Unidade Recife") e escolha a equipe de cada pessoa em Configurações > Usuários.
   Serve para o alcance "Só a equipe" (ex.: um líder que vê os leads do time dele).
5. **Módulos:** ligue ou desligue partes inteiras (Vendas, Agenda, IA SDR, Prospecção, Consulta Assertiva, Conversas,
   IA Comercial, Portal). Desligado some do menu **e fica bloqueado para todos**. Para ligar ou desligar só numa marca,
   o admin master usa **Painel master > Módulos de cada AR** (as outras marcas não mudam). O módulo **E-mail em HTML
   com a marca** não tem menu: ligado, o 2º e-mail em diante das campanhas sai em HTML com a marca; desligado, sai só
   em texto.

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

**Regra da MS: cada usuário tem o seu disparo** (pedido da Maria em 13/11/2026). Os disparos de uma pessoa nunca
saem pelo WhatsApp ou pelo e-mail de outra pessoa: o **e-mail** sai só pelo do cadastro dela (**Contas de e-mail**); o
**WhatsApp**, pelo número dela ou por um que outra pessoa **compartilhou** com ela. Ser administrador não muda isso.
Sem e-mail ou número, os disparos dela esperam e ela recebe um aviso para cadastrar.

**Cada pessoa com o seu WhatsApp:** em **WhatsApp > Meu WhatsApp** (Configurações > Comunicação, ou o menu lateral para
quem não vê as Configurações), cada um conecta o próprio número pelo
QR code. A IA SDR manda os WhatsApps dos leads de cada pessoa pelo número dela (ou por um compartilhado com ela);
sem número, as mensagens esperam e a pessoa recebe um aviso para conectar. Em **Conversas**, cada um vê só as conversas do
próprio número e dos números compartilhados com ele. O número oficial da API da Meta aparece na mesma tela, no quadro
**Número oficial (API da Meta)**, e não precisa ser compartilhado (ver "Quem vê as conversas do número oficial").
**Compartilhar um número:** no cartão do número, **Compartilhar este número** → "Toda a equipe" ou escolha as
pessoas. O dono do número, o administrador e o gestor escolhem com quem compartilhar; só o dono e o administrador
conectam, pausam ou desligam. Quem não é o dono não pode se incluir, não pode liberar para toda a equipe e não mexe no
número (ou no e-mail) de um administrador: isso só o dono ou o admin master.

**Cada pessoa com o seu e-mail:** em **Contas de e-mail** (Configurações > Comunicação, ou o item **E-mail** do menu
lateral para quem não vê as Configurações), cada um pode cadastrar o próprio e-mail @mscertificados.com.br
(com a senha de app do Google, 16 letras) e clicar em **Enviar e-mail de teste**. Os e-mails das campanhas dos leads
de cada pessoa saem pelo e-mail dela, e as respostas chegam na caixa dela (a IA SDR lê todas as caixas marcadas).
Sem e-mail próprio cadastrado, os e-mails dos leads dela saem por um **e-mail que compartilharam com ela** (o dono
da conta, o administrador ou o gestor escolhe com quem compartilhar, no cartão da conta) e as respostas chegam nessa
caixa. Sem nenhum dos dois, os e-mails **esperam** e ela recebe um aviso para cadastrar. O **e-mail principal da MS**
nunca é usado para os disparos de outras pessoas, mesmo compartilhado (ele é do cadastro do administrador dono dele). Os limites de envio por hora e por dia continuam
valendo para a MS inteira.

**Gestor com o domínio da própria empresa:** o gestor (e o administrador) pode cadastrar um e-mail de outro domínio,
por exemplo joao@contabiljoao.com.br. Em **Contas de e-mail**:
1. Em **Onde fica este e-mail?**, escolha **Google Workspace** ou **Outro provedor** (Microsoft 365, Hostinger,
   Locaweb, servidor próprio...).
2. Outro provedor: copie do painel do provedor o **servidor de envio (SMTP)** e a porta (quase sempre 587 ou 465) e
   o **servidor de leitura (IMAP)** (porta 993). Digite a senha do e-mail. A tela traz os dados do Microsoft 365 e
   da Hostinger como exemplo.
3. Clique em **Salvar** e depois em **Enviar e-mail de teste**.
4. Logo abaixo aparece **"O domínio ... está pronto para não cair no spam?"**, com SPF, DKIM e DMARC. O que estiver
   "Falta configurar" traz o passo a passo; quem cuida do domínio faz isso em poucos minutos.

Gmail, Hotmail e Yahoo pessoais não são aceitos (caem no spam e a conta pode ser bloqueada). Outras pessoas só podem
usar outro domínio se o administrador der a permissão **"Enviar pelo próprio domínio"** em Configurações > Exceções por pessoa; tirando a
permissão, a conta para de enviar na hora.

## 6. Problemas comuns

| Mensagem / situação | O que fazer |
|---|---|
| "O Python não foi encontrado" | Instale o Python marcando "Add Python to PATH" e rode `instalar.bat` de novo |
| "O sistema ainda não foi instalado" | Rode `instalar.bat` |
| Esqueci a senha | Outro administrador cria uma senha nova em Configurações > Usuários, ou rode `redefinir_senha.bat` |
| "Código errado" no login | O código muda a cada 30 segundos: digite o que o app mostra agora. Se sempre der errado, acerte a hora automática do celular |
| Perdi o celular do código | Use um código de recuperação ou peça ao administrador para clicar em "zerar" em Configurações > Usuários |
| "Entrada travada por segurança" | Depois de 5 tentativas erradas seguidas (senha ou código do celular), a entrada fica travada por 15 minutos; a mensagem diz a partir de que horas tentar de novo. A cada erro a tela avisa quantas tentativas restam. Se a pessoa não lembrar a senha, o administrador cria uma nova (Configurações > Usuários; a de um administrador, só o Admin Master). O contato do suporte que aparece na mensagem fica em Configurações > Marca (Admin Master, fora das empresas) |
| "O formulário expirou" | Recarregue a página (F5) e repita |
| Lead da base sem responsável | A Receita não tem sócio-administrador pessoa física para essa empresa: preencha à mão |
| A busca acha poucos escritórios | Importe a **base da Receita Federal** (Configurações > Integrações) |
| O Google recusa mesmo com a senha de app certa | Depois de várias tentativas erradas o Google bloqueia por alguns minutos: espere e teste de novo. Para conferir a senha a partir deste computador: dois cliques em `testar_email_daqui.bat` |
| "Connection unexpectedly closed" ao testar o e-mail | É senha errada: o Google fecha a conexão em vez de avisar. Use a **senha de app** de 16 letras (não a senha normal) |
| "O Google recusou a senha" | Use a **senha de app** (16 letras) da conta de envio, não a senha normal (Configurações > E-mail mostra o passo a passo) |
| E-mails caindo no spam | Configurações > E-mail mostra o que falta no DNS (DKIM e DMARC); comece com poucos e-mails por dia |
| Ver se o e-mail/WhatsApp já foi para o lead | Menu **Envios**, em abas: **Enviados** (tudo o que saiu, separado por dia, com a situação: na fila, enviada, não saiu, respondeu; e os testes da campanha, marcados com 🧪, que vão só para quem testou) e **Próximos envios** (o que ainda vai sair, com o motivo: a hora mostrada é a programada; "atrasado" + "Aguardando seu clique" quer dizer que ainda não saiu). Filtros por período, situação, canal, campanha e nome da empresa; o número **Aguardando seu clique** no topo mostra o que precisa de um clique hoje. Na campanha: **Andamento por empresa**. Na ficha do lead: **Envios para este lead** |
| Arquivar ou excluir uma campanha | Na lista de campanhas (ou dentro da campanha): **Arquivar** tira da lista (veja em "Arquivadas"); **Excluir** apaga a campanha e cancela o que estava programado. As empresas continuam em Leads. Cada pessoa vê e mexe só nas próprias campanhas (administrador e gestor veem todas) |
| Onde envio os WhatsApps da campanha? | Dentro da campanha aprovada, em **WhatsApp de hoje**: um botão por mensagem, sai pelo seu número |
| Como testo uma campanha antes de aprovar? | Na campanha, cartão **Testar antes de aprovar**: escolha a campanha e o canal (WhatsApp ou e-mail); as mensagens chegam no SEU e-mail/WhatsApp com "[TESTE]". Nenhum lead recebe nada e não conta nos limites |
| Testei e o e-mail chegou só em texto. O HTML não funciona? | Funciona: o **1º e-mail** sai só em texto (com a arte "do 2º toque em diante" e com o e-mail com a marca). No teste, escolha **Todos os 4 toques**: o 1º chega em texto e os outros com a arte. A tela do teste avisa isso. Se a campanha foi criada com o **Visual** em "Só texto (sem visual)", nenhum e-mail leva a arte (só o e-mail com a marca, se estiver ligado) |
| A campanha tem empresas sem WhatsApp. O que faço? | Empresas que só têm telefone fixo entram na campanha também. No cartão **Pesquisar WhatsApp** da campanha, clique em Google/Instagram, ache o número e salve: as mensagens passam a ir para ele |
| A campanha tem mensagem de WhatsApp e de e-mail? | Sim. Cada toque tem os dois modelos lado a lado. Se achar o e-mail (ou o WhatsApp) da empresa, clique em **Enviar este toque por e-mail/WhatsApp** |
| Onde vejo os modelos de cada segmento? | Em **Cadências > Templates de mensagem**, escolha o segmento. São 15 por segmento (8 de WhatsApp e 7 de e-mail); dá para editar. No lead, aparecem os do segmento dele |
| Dá para pesquisar empresas por CNAE? | Sim. Em **Prospecção**, abra **Pesquisar por CNAE**, marque (ex.: 6319-4/00) ou digite os códigos. Ao lado aparece quantas empresas há na base |
| Campanhas repetindo as mesmas empresas | Não acontece mais: cada campanha pula as empresas que já estão em outra campanha ativa (ou já contatadas) e busca mais fundo na base. Cancelar uma campanha libera as empresas dela |
| Campanha com "erro" ao montar | Leia o motivo na campanha e clique em **Corrigir e montar de novo**: a tela abre com tudo o que foi escolhido; troque o que precisar e clique em **Montar a campanha de novo** (é a mesma campanha, não cria outra). Região sem empresas: confira cidade/bairro e estado (bairro funciona, ex.: "Boa Viagem" / PE) e a base (uma lista importada só tem as empresas dos estados dela). Uma empresa com site quebrado não para mais a campanha: ela segue com os dados da Receita |
| A campanha não manda e-mails sozinha | Configure o SMTP no `.env` e confira em Configurações se "fila envia e-mails sozinha" = 1; o envio só acontece em dias úteis, no horário configurado |
| "APROVAÇÃO NECESSÁRIA" não some | Clique em APROVAR CAMPANHA (qualquer pessoa da equipe pode aprovar) |
| Nenhum horário para reunião | Confira o expediente da pessoa em Configurações > Usuários (nos feriados da cidade dela não há horários) |
| Um toque mudou de dia sozinho | Caía num feriado de quem envia (nacional ou da cidade, em Configurações > Feriados): foi para o próximo dia de envio |
| "Os servidores do OpenStreetMap estão ocupados" | Tente de novo em alguns minutos ou use a base da Receita |
| "O limite diário... foi atingido" | Continue amanhã ou aumente o limite em Configurações |
| "Já houve uma mensagem para este lead há menos de 20 horas" | Controle de frequência: contate amanhã |
| "Este número já fez 20 contatos frios hoje" | Proteção contra bloqueio: o resto sai amanhã (ou por outro número). O teto fica em Configurações > Geral |
| "Este número está com os contatos frios pausados até amanhã" | 3 pessoas pediram para sair hoje: revise o texto e a lista da campanha. Amanhã volta sozinho |
| "Aguardando: o toque anterior desta empresa ainda não saiu" | O toque anterior da empresa está parado (atrasado mais de 2 dias ou sem WhatsApp). Envie o anterior na Minha fila ou cancele-o: os próximos voltam a sair sozinhos |
| "Nenhum cliente para avisar agora" (Renovação) | Ninguém com certificado vencendo nos próximos 30 dias fora de campanha. Importe o relatório de renovação mais recente |
| "Não achei a coluna Vencimento na planilha" | O arquivo não é o Relatório de renovação. Exporte de novo no sistema da certificadora e importe o .xlsx |
| "Avisos saíram sem a arte" (Renovação) | O computador do WhatsApp Leads não conseguiu desenhar a arte. Confira se o **Google Chrome** está instalado nele e se a internet está funcionando |
| Cliente da Renovação "Sem WhatsApp e sem e-mail" | A planilha não tem celular nem e-mail dele. Corrija o cadastro no sistema da certificadora e importe o relatório de novo |
| "Sai sozinho depois do WhatsApp desta empresa" | Empresas novas: o e-mail espera o WhatsApp da mesma empresa sair primeiro (o WhatsApp tem prioridade). Não precisa fazer nada |
| E-mail "[Prospecção MS] ⚠️ ..." | Aviso automático de problema: o próprio e-mail diz o que fazer. Quando resolver, chega o "✅ Resolvido" |
| (site na internet) "O computador com o WhatsApp Leads está desligado" | Ligue o computador e abra o `iniciar.bat` do WhatsApp Leads; em até 1 minuto volta |
| (site na internet) Campanha ou busca parada em "Na fila" | Espere 1 minuto. Se continuar, avise o suporte: o agendador da Vercel (Cron Jobs) pode estar desligado |
| A IA não escreve as mensagens | Sem a chave da IA, o sistema usa os templates. Veja `docs/configuracao.md` |

**Seus dados ficam na pasta `dados/`. Não apague essa pasta.** Faça cópia dela de vez em quando (backup).

**Cópia de segurança do sistema na internet:** todo dia, a partir do meio-dia, este computador guarda sozinho uma
cópia do banco da nuvem em `dados\backups` (ficam os últimos 14 dias). Desde novembro/2026 a cópia sai
**criptografada** (ninguém abre sem a senha) e é **aberta e conferida** logo depois de feita.
- **A senha das cópias** fica no arquivo `dados\senha_backup.txt` (criado sozinho no primeiro backup).
  **Guarde uma cópia dessa senha fora do computador** (gerenciador de senhas, cofre ou papel guardado): sem ela,
  nenhuma cópia abre. Não mande essa senha por e-mail nem WhatsApp.
- **Cópia fora do computador:** instale o **Google Drive para computador** (entrando com o e-mail da MS). A partir
  daí cada backup também vai sozinho para `Meu Drive\Backup Sistema MS\Prospeccao` (configurado em 11/2026). Se o computador quebrar, as cópias
  estão lá.
- O sistema da nuvem fica sabendo de cada backup e manda um e-mail de aviso se ficar mais de 3 dias e meio sem.

Para fazer uma cópia na hora: dois cliques em `fazer_backup.bat`. Só em emergência (dados apagados por engano):
`restaurar_backup.bat` volta uma cópia (deste computador ou do Google Drive). Ele apaga o que está hoje no sistema
e pede para digitar SIM. Num computador novo, ele pede a senha das cópias.

**Avisos por e-mail quando algo para:** o sistema da nuvem confere tudo a cada 5 minutos e manda um e-mail para os
administradores quando: o computador do WhatsApp Leads para de responder (mais de 15 minutos), um número de WhatsApp
em uso fica desconectado (mais de 15 minutos), os e-mails da fila não saem, uma rotina dá erro 3 vezes seguidas, o
banco chega a 80% do tamanho, o backup fica dias sem ser feito ou o agendador fica parado (o aviso chega quando ele
volta). Também confere o **servidor de licenças do Assinador MS** (desde 26/11/2026): se ele não responder em duas
conferências seguidas (uns 10 minutos), o aviso vai só para a MS (o Admin Master e os administradores da AR MS), nunca
para as outras marcas. Enquanto ele estiver fora, quem já entrou no Assinador continua assinando por até 72 horas, mas
ninguém consegue entrar na conta nem renovar a licença. Quando a nuvem passar a chamar o sistema a cada minuto (plano Pro da Vercel), também avisa se ela ficar mais
de 10 minutos sem chamar: aí o computador da MS cobre como reserva. Quem está fazendo as filas andarem aparece em
**Configurações > Integrações**, na linha "Relógio das filas". Vem um lembrete a cada 12 horas enquanto o problema durar e outro e-mail quando volta ao normal. O aviso
também aparece no sino. Quem recebe: os administradores, ou a lista em **Configurações > Geral > Avisos e
LGPD > "Quem recebe os avisos de problema"**. Para testar: **Configurações > Integrações > Mandar e-mail de teste do aviso**.

Testes automáticos: dois cliques em `testar.bat` (não mexe nos seus dados).

Documentação técnica: pasta [`docs/`](docs/README.md).
