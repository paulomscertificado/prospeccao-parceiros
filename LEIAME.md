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
  O celular aparece sempre com o 9 na frente, mesmo quando o WhatsApp entrega o número antigo sem ele; a busca
  acha o contato digitando o número com ou sem o 9.
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
| Saber com quem falar hoje | **Dashboard**, quadro **Quem precisa de mim hoje** (respostas quentes com prazo, tarefas e leads esfriando) |
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
- **Proteção dos números de WhatsApp contra bloqueio:** cada número faz no máximo **20 contatos frios por dia**
  (mensagem para quem nunca conversou com a MS; vale também para o botão Disparar e para as Empresas novas). Quem já
  conversou ou autorizou não entra nessa conta. Se **3 pessoas pedirem para sair no mesmo dia**, os contatos frios
  daquele número param até o dia seguinte (e chega um aviso por e-mail). **Resposta automática de robô** ("recebemos
  sua mensagem...") **não conta** como conversa: não libera envio automático. Os dois números se ajustam em
  Configurações > Geral.
- Áudio, foto ou documento sem texto não recebem resposta automática: viram uma oportunidade para alguém ouvir/ver.
- Depois que alguém da equipe assume o lead, e nas mensagens de parceiros, a IA não responde nem muda a etapa:
  só avisa quem cuida.
- Se a pessoa pedir para sair, clique em **Pediu para sair / Registrar opt-out**: ela nunca mais entra em campanha.
- Cada lead guarda **de onde veio** (fonte) e a **base legal**. Pedido de exclusão: ficha do lead → **Excluir dados (LGPD)**.
- O sistema **não inventa dados**: se a fonte não traz telefone ou e-mail, o lead fica sem.

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
- Na **Nova campanha (IA SDR)** e na configuração das **Empresas novas** (passo 5) escolha o visual, os canais (e-mail,
  WhatsApp) e os toques: **do 2º toque em diante** (recomendado: o 1º contato frio responde melhor só com texto) ou
  **em todos**.
- O **e-mail** sai com o HTML e também com a versão em texto (exigência dos filtros de spam).
- No **WhatsApp** vai a imagem com o texto do toque embaixo, **só para quem já conversou com a MS**. Para contato frio
  sai só o texto, para proteger o número contra bloqueio.
- O botão **Testar** da campanha manda o e-mail com o visual e o WhatsApp com a imagem para você mesmo.

**Pergunta final (vai no fim do 1º contato):** 14 perguntas prontas em 5 tipos (descobrir como fazem hoje,
convidar para conversar, achar a pessoa certa, mandar informação, resposta de uma palavra), **Automática** (a mais
natural para cada empresa), **Variar** (cada empresa recebe uma pergunta de um tipo diferente, para descobrir qual
traz mais resposta) ou **Escrever a minha**. A pergunta escolhida vale em todos os tons. A pergunta escrita à mão não
pode ter valores, porcentagem, desconto, exclusividade nem frase de propaganda.

O tom muda as mensagens de verdade, mesmo sem a IA ligada: cada tom tem os próprios textos. Para o convite por e-mail
levar o botão do WhatsApp, cadastre o número da MS em **Configurações > Geral > "WhatsApp da MS para os convites por
e-mail"** (sem ele, o convite pede para responder o e-mail).

A IA **encontra, pesquisa, qualifica, faz o primeiro contato e entrega o interessado para você**. Ela não negocia
preço nem comissão e não fecha parceria.

1. **Campanhas > Criar campanha**: escreva o que procura (ex.: "Quero parceiros entre contadores, administradoras e
   empresas de software em São Paulo"). Se faltar a região ou o segmento, a tela pergunta.
2. A IA monta a campanha: acha as empresas, pesquisa o site de cada uma, calcula o potencial, escolhe as melhores e
   escreve uma mensagem **diferente para cada empresa**, nos toques da cadência escolhida (padrão: dia 1, 3, 7 e 12).
3. Você confere e clica em **APROVAR CAMPANHA** (ou edita/cancela). Nada sai antes disso.
4. **Aprovou, entrou na fila.** Os e-mails e os WhatsApps saem sozinhos, cada um no seu horário, também para quem
   nunca conversou com a MS (desde 12/11/2026). O WhatsApp sai pelo celular conectado, uma mensagem a cada 3 minutos,
   só no horário de envio, com os limites por hora e por dia, até 20 contatos frios por número por dia e pausa com 3
   pedidos de SAIR. Toque atrasado mais de 2 dias espera o clique, para não sair tudo de uma vez, e o toque seguinte
   da mesma empresa espera o anterior sair (o "último contato" nunca chega antes da apresentação). A fila nunca manda
   dois WhatsApps para a mesma empresa em menos de 20 horas, mesmo com o intervalo mínimo em 0 nas Configurações.
   LinkedIn: sempre com um clique.
   **Desligar numa campanha (só o administrador):** na tela da campanha, o cartão **WhatsApp sai sozinho depois da
   aprovação** tem o botão **Desligar**. Desligado, o WhatsApp só sai sozinho para quem já conversou com a MS
   (respondeu pelo WhatsApp ou tem marcado na ficha "Autorizou receber mensagens da MS pelo WhatsApp"); para os
   demais, a campanha e a Minha fila mostram o botão para enviar com um clique. Para as campanhas novas voltarem ao
   clique, mude em **Configurações > Geral** "campanha nova já vem com o WhatsApp automático ligado" para 0.
   Toda empresa da campanha ganha a mensagem de WhatsApp. Se o campo **WhatsApp** da empresa estiver em branco, a
   mensagem fica pronta e **não sai**: cadastre o número na ficha da empresa e ela fica liberada.
   Empresa com WhatsApp **e** e-mail recebe os dois em cada toque (nas Empresas novas, só o WhatsApp).
5. Quando alguém responde com interesse, a automação para e aparece em **Oportunidades** (🔥) com o resumo.
   Clique em **Assumir lead**, ligue, marque a reunião e siga com a negociação (veja **Oportunidades** abaixo).
6. Veja em **Inteligência** qual segmento, canal e mensagem funcionam melhor.

**E-mail:** as campanhas saem do e-mail @mscertificados.com.br configurado em **Configurações > E-mail**
(e-mail + senha de app do Google + "Enviar e-mail de teste").

**Resposta de robô:** quando quem responde é um robô da empresa (ex.: "Recebemos sua mensagem, aguarde um
momento", menu "digite 1", aviso de ausência), a IA SDR **não responde**, **não cria oportunidade** e a sequência
continua normalmente. Além disso, a SDR responde no máximo 1 vez por dia para o mesmo contato, para nunca entrar
numa conversa sem fim. Se o mesmo lead mandar várias mensagens, tudo fica na mesma oportunidade.

**Minha fila (menu):** mostra os seus disparos num lugar só, em 4 abas:
- **Próximos envios:** o que ainda vai sair, separado por dia (Atrasados, Hoje, Amanhã, os próximos dias) e na ordem
  em que vai sair. Cada envio mostra a situação em destaque (ex.: "Aguardando seu clique", "WhatsApp em branco",
  "Programado") e o botão certo: **Enviar** ou **Cadastrar WhatsApp**/**Cadastrar e-mail**, quando falta o contato.
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

**Oportunidades (menu 🔥):** os leads que responderam, em 4 abas:
- **Novas:** esperam alguém assumir. Ficam separadas por dia (Hoje, Ontem, o dia da semana) e, em cada dia, as
  **quentes vêm primeiro**. Cada cartão mostra há quanto tempo o lead está **esperando** e até quando assumir: o
  **prazo é de 2 horas úteis** (horário de envio, de segunda a sexta; uma resposta das 17h30 tem prazo até 10h do dia
  útil seguinte). Passou do prazo, fica vermelho. Mostra também a campanha, o canal, o que enviamos, o que o lead
  respondeu e o que a IA entendeu. Botões: **Assumir lead**, **Iniciar WhatsApp**, **Ver conversa** (abre a conversa
  em Conversas) e **Descartar**: para descartar é preciso **escolher o motivo** (sem interesse, já tem parceiro,
  resposta de robô, pessoa errada...). O motivo aparece na aba Descartadas e ensina o que ajustar nas campanhas.
- **Assumidas:** quem assumiu, quando e quanto tempo depois da resposta.
- **Descartadas:** o que foi descartado. Descartou sem querer? O botão **Voltar para Novas** desfaz.
- **Todas as respostas** (só administrador e gestor): tudo o que os leads responderam, inclusive "sem interesse",
  "pediu para sair" e respostas de robô.

Para achar uma oportunidade, use os filtros: **Quando** (tudo, hoje, ontem, últimos 7 ou 30 dias, mais de 30 dias),
**Tipo** (quentes ou para analisar), **Resposta** (na aba Todas as respostas), **Canal** e a **busca pelo nome da
empresa**. Cada filtro mostra quantas há nele. Com um filtro escolhido aparece **Descartar as N mostradas**, para
descartar de uma vez, por exemplo, todas as "para analisar" de ontem (o sistema pede confirmação; dá para voltar com
elas pela aba Descartadas). Os números do topo mostram quantas esperam, quantas são quentes, quantas passaram do
prazo de 2 horas úteis e o tempo típico até alguém atender. Cada pessoa vê as oportunidades dos leads dela (administrador e
gestor veem todas, conforme as permissões).

**Quem precisa de mim hoje (topo do Dashboard):** a lista de trabalho de cada pessoa, para nenhum interessado ser
esquecido:
- **Respostas quentes** esperando alguém assumir, com o prazo de 2 horas úteis ("assumir até 10:30" ou "fora do
  prazo há 3 h") e o botão **Assumir** ali mesmo;
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
**aguardando aprovação**. Depois de aprovada, **tudo sai sozinho, sem clique**: o e-mail e o WhatsApp entram na fila
e saem cada um no seu horário, um por vez, com as pausas e os limites do número (no máximo 1 a cada 3 minutos,
15 por hora, 40 por dia por número, só no horário de envio; quem pede SAIR não recebe mais). Toque atrasado mais
de 2 dias não sai sozinho (espera um clique em **Minha fila**), para não sair tudo de uma vez. São 3 toques: dia 1 (boas-vindas + oferta do e-CNPJ), dia 3 (lembrete)
e dia 7 (último contato). As mensagens podem ser editadas na própria tela. A IA não responde sozinha esses
leads: as respostas vão para **Oportunidades** e o time conversa.

- **Buscar agora:** escolha as datas de abertura (até 7 dias), escolha **quantas empresas buscar** (10, 20, 30, 40,
  50 ou 100; cada 10 gastam 1 crédito) e clique em **Buscar e montar campanha**. A campanha leva **todas** as
  empresas que vierem e puderem entrar: nada pago fica sem uso. O **Máximo de empresas por campanha diária**
  (passo 2) vale só para a busca automática, que pede à CNPJá o dobro desse número e usa esse número.
- **Muitas empresas de uma vez:** o WhatsApp sai no ritmo seguro do número (no máximo 20 contatos frios por número
  por dia, contando os lembretes). Com 50 ou 100 empresas, leva vários dias, e o toque atrasado mais de 2 dias
  espera um clique em **Minha fila**.
- **Custo:** cada 10 empresas encontradas gastam 1 crédito. Em PE abrem cerca de 380 empresas por dia
  (≈ 1.100 créditos por mês).
- Os celulares que a Receita guarda sem o 9 ganham o 9 na frente (é um palpite: confira antes de enviar).
- Empresas com o mesmo telefone/e-mail (do contador) **não** são juntadas: só o CNPJ conta como repetido.
- Opção para deixar de fora **empresário individual** (inclui os MEIs, que muitas vezes não precisam de e-CNPJ).
- **WhatsApp primeiro, e-mail depois:** empresa com celular recebe os 3 toques **por WhatsApp**, que saem sozinhos
  depois da aprovação (o botão **Enviar** da **Minha fila** ou da campanha só adianta). Se ela também tem e-mail,
  cada toque ganha a versão por **e-mail**, marcada para umas 2 horas depois do WhatsApp (ou o dia seguinte, se não
  couber no horário). O e-mail só sai **depois** que o WhatsApp da empresa saiu; se ela responder no WhatsApp antes,
  o e-mail não sai. Se o WhatsApp travar (atrasado mais de 2 dias, esperando clique, ou sem número), o e-mail sai
  assim mesmo. Quem não tem celular recebe só por e-mail. Para não mandar e-mail nenhum, desmarque o canal
  **E-mail** no passo 4. As campanhas de **parceiros** da IA SDR também saem sozinhas desde 12/11/2026 (o
  administrador pode desligar em cada campanha).
- **Buscar de novo não gasta à toa:** toda empresa que já veio entra numa lista de exclusão guardada na própria
  CNPJá. Buscando o mesmo dia de novo, a CNPJá só traz (e só cobra) as empresas que ainda não vieram.
- **Atividade:** a busca pega empresas novas de **qualquer atividade** (toda empresa nova pode precisar do e-CNPJ).
- **Lista de exclusão:** com a opção marcada, quem já está em alguma **lista importada** (Configurações >
  Integrações > Listas) fica de fora. Também ficam de fora: repetidas, leads já em atendimento e quem pediu para sair.
- **Ver as empresas encontradas:** no quadro **"Empresas encontradas na CNPJá"**, clique na busca. A lista mostra
  razão social, CNPJ, cidade, data de abertura, **telefone fixo**, **celular**, **e-mails**, atividade e quem ficou
  de fora (e por quê), com o link da campanha.
- **Testar a API:** o botão **Testar (10 empresas · 1 crédito)** busca até 10 empresas abertas **num dia** e só
  mostra a lista. Cada teste olha um dia diferente (ontem, anteontem...), para não vir sempre a mesma lista. Se estiver certa, clique em **Montar a campanha com estas empresas** (não gasta crédito).

### Renovação (aviso de vencimento do certificado para os clientes)

Menu **Renovação**. O sistema avisa os clientes da MS antes de o certificado digital vencer: **30, 15, 5 e 1 dia
antes**, pelo WhatsApp e pelo e-mail. Os clientes vêm do **Relatório de renovação** que vocês exportam do sistema da
certificadora.

**Passo a passo:**
1. **Teste primeiro** (quadro **1. Testar os avisos**, ver abaixo): mande os avisos para o seu WhatsApp e confira.
2. Exporte o **Relatório de renovação** (Excel) no sistema da certificadora. Em **Renovação**, no quadro
   **2. Importar a planilha de renovação**, escolha o arquivo e clique em **Importar planilha**. Pode importar de novo sempre que sair um relatório novo: quem já estava é atualizado, sem
   duplicar.
3. No quadro **3. Montar campanha agora**, escolha quantos contatos (10 a 100; vão os que vencem primeiro) e clique
   em **Montar campanha**. Em alguns minutos a campanha fica **aguardando aprovação**.
4. Abra a campanha, confira as mensagens e **aprove**. Depois de aprovada, tudo sai sozinho.
5. No quadro **4**, escolha o **dono** (ele assina e os e-mails saem pela conta dele) e o **Número de WhatsApp dos
   disparos** (só o administrador escolhe; fica gravado em cada campanha e dá para trocar na página da campanha).
   **Número em "MODO TESTE" só simula o envio: a mensagem não chega.** No automático, o sistema usa o número de quem
   assina e nunca um em modo teste quando há um de verdade conectado. Se quiser, ligue a **campanha automática**:
   todo dia, no horário escolhido, o sistema monta a campanha com quem chegou a 30 dias do vencimento (ela também
   espera a aprovação). Clique em **Salvar configuração**.

**Dias, horário e início (quadro 4):** em **Avisar quantos dias antes de vencer** você escreve os 4 dias dos avisos
(padrão 30, 15, 5, 1; no piloto de 13/11/2026: **12, 6, 3, 1**). **Avisos a partir das** limita o horário (ex.: 10:00).
**Começar em** é o dia em que a campanha automática começa a montar sozinha (no piloto: 01/01/2027). Valem para as
campanhas montadas depois de salvar.

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
- **Datas:** 30, 15, 5 e 1 dia antes do vencimento. Quem entra mais tarde recebe o 1º aviso na hora e só os
  seguintes que ainda cabem (nunca em dias seguidos). Aviso que cairia no sábado ou no domingo vem para a sexta antes.
- **WhatsApp primeiro, e-mail depois:** igual às Empresas novas (o e-mail de cada aviso sai umas 2 horas depois do
  WhatsApp). Quem não tem celular na planilha recebe só por e-mail. Sem WhatsApp e sem e-mail na planilha, não recebe
  aviso (aparece no filtro **Sem WhatsApp e e-mail**): o contato vem só da planilha.
- **No máximo 20 por dia:** o número só faz 20 contatos frios por dia (Configurações > Geral). Por isso a campanha
  espalha os avisos: no máximo 20 WhatsApps de renovação por dia, quem vence antes recebe antes, todo mundo recebe o
  1º aviso e os lembretes entram nas vagas que sobram. Com 100 clientes, os primeiros avisos levam uma semana.
- **Renovação antes das Empresas novas:** as duas usam o mesmo número e o mesmo limite. No mesmo dia, a renovação sai
  primeiro (tem prazo). Nos dias cheios de renovação, as Empresas novas esperam.
- **Os mesmos cuidados com o WhatsApp:** uma mensagem a cada 3 minutos, limites por hora e por dia, só no horário de
  envio, e quem responde SAIR não recebe mais.
- **Quando o cliente responde:** os avisos seguintes param e a resposta vai para **Oportunidades** e **Quem precisa de
  mim hoje**. A IA não responde esses clientes: quem conversa é a equipe.
- **Arte do aviso:** cada aviso vai com a **arte do site** (mscertificados.com.br/interno/aviso-vencimento)
  preenchida com os dados do cliente: e-CNPJ ou e-CPF, A1 ou A3, razão social ou nome, CNPJ ou CPF, a data de
  vencimento e quantos dias faltam. No WhatsApp a arte vai como imagem e o texto como legenda, **para todos os
  clientes**, também quem nunca conversou com a MS (decisão da Maria em 12/11/2026, ciente do risco maior de bloqueio
  do número). O e-mail do mesmo aviso leva a mesma arte. Quem tem vários certificados recebe a lista no texto, sem a
  arte. Quem desenha a arte é o **computador do WhatsApp Leads**, que precisa do **Google Chrome instalado** e de
  internet. Se a arte falhar, o aviso sai só com o texto e a tela Renovação avisa. Mudou a arte no site? Em até 6
  horas os avisos já saem com a arte nova. Para desligar: quadro 3, opção **Arte do aviso junto**.
- **Testar antes (quadro 1, "Testar os avisos"):** como o teste da IA SDR. Escolha também **por qual número** o teste
  sai (número em modo teste: a tela avisa que não chega de verdade). Escolha um cliente da planilha (ou o
  cliente fictício), o canal (WhatsApp ou e-mail), digite o **seu** WhatsApp ou e-mail, escolha os avisos (só o 1º, um
  deles ou os 4) e deixe marcado **Mandar a arte junto** para receber a arte do site com os dados do cliente. Chega
  com "[TESTE]" no começo, assinado por quem assina as campanhas de renovação e pelo WhatsApp/e-mail dele. Nenhum
  cliente recebe nada e nenhuma campanha muda. A arte do teste de e-mail vem da arte que o computador desenhou no teste
  de WhatsApp do mesmo cliente: mande primeiro o teste no WhatsApp e, 1 minuto depois, o de e-mail.
- **Renovou?** Na lista de certificados, clique em **Renovado** (ou **Não vai renovar**): os avisos que ainda não
  saíram param. **Reabrir** desfaz.
- A data de nascimento que vem no relatório **não é guardada**.

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

**Número em MODO TESTE:** no WhatsApp Leads, o modo teste só **simula** o envio: a mensagem não chega. Por isso a
escolha automática do número (campanhas da IA SDR, Empresas novas e Renovação) **nunca usa um número em modo teste
quando há um número de verdade conectado** (QR code). Nas listas de números ele aparece como **"MODO TESTE (não chega
de verdade)"**, e a página da campanha mostra um aviso vermelho se o número escolhido para ela estiver em modo teste.
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
| Ver se o e-mail/WhatsApp já foi para o lead | Menu **Envios**, em abas: **Enviados** (tudo o que saiu, separado por dia, com a situação: na fila, enviada, não saiu, respondeu; e os testes da campanha, marcados com 🧪, que vão só para quem testou) e **Próximos envios** (o que ainda vai sair, com o motivo: a hora mostrada é a programada; "atrasado" + "Aguardando seu clique" quer dizer que ainda não saiu). Filtros por período, situação, canal, campanha e nome da empresa; o número **Aguardando seu clique** no topo mostra o que precisa de um clique hoje. Na campanha: **Andamento por empresa**. Na ficha do lead: **Envios para este lead** |
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
volta). Vem um lembrete a cada 12 horas enquanto o problema durar e outro e-mail quando volta ao normal. O aviso
também aparece no sino. Quem recebe: os administradores, ou a lista em **Configurações > Geral > "Avisos de
problema · e-mails que recebem"**. Para testar: **Configurações > Integrações > Mandar e-mail de teste do aviso**.

Testes automáticos: dois cliques em `testar.bat` (não mexe nos seus dados).

Documentação técnica: pasta [`docs/`](docs/README.md).
