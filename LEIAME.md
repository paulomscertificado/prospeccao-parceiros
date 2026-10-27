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

**Número que dispara (só administrador):** no passo 4 da campanha (ou depois, na página da campanha), o
administrador escolhe **"WhatsApp que vai disparar"**. Em "Automático", cada mensagem sai pelo número do responsável
pelo lead. Escolhendo um número, todas as mensagens de WhatsApp da campanha saem por ele (se ele estiver
desconectado, as mensagens esperam e o sistema avisa).

**WhatsApp:** deixe o **WhatsApp Leads** aberto e conectado. Na Agenda e na ficha do lead aparece o botão
**Enviar pelo WhatsApp conectado** (sai pelo seu número, com as pausas e o limite do WhatsApp Leads), e as
respostas dos parceiros chegam sozinhas na IA SDR. O rodapé do menu mostra se o WhatsApp está conectado.

Configure as categorias em Configurações > **Categorias de parceiros** e o que a IA pode responder em
**Base de conhecimento**. Detalhes técnicos: [`docs/ia-sdr.md`](docs/ia-sdr.md).

## 5. Perfis de acesso

| Perfil | Vê |
|---|---|
| Administrador | Tudo, inclusive Configurações, usuários, todos os números de WhatsApp e as regras de envio |
| Gestor | Toda a equipe e os indicadores; aprova campanhas (não altera configurações) |
| Funcionário MS | Quase toda a plataforma (prospecção, campanhas, IA, cadências, templates, categorias, conversas), mas **só os próprios dados** e o que for compartilhado com ele; não aprova campanhas nem mexe em Configurações |
| Vendedor | Só os próprios leads, tarefas e vendas |
| Parceiro | Só o portal: própria carteira, indicações, vendas e comissão |

Crie usuários em **Configurações > Usuários** (o perfil padrão é Funcionário MS).

**Cada pessoa com o seu WhatsApp:** no menu **WhatsApp > Meu WhatsApp**, cada um conecta o próprio número pelo
QR code. A IA SDR manda os WhatsApps dos leads de cada pessoa pelo número dela; sem número conectado, as
mensagens esperam e a pessoa recebe um aviso para conectar. Em **Conversas**, cada um vê só as conversas do
próprio número e dos números compartilhados com ele.
**Compartilhar um número:** no cartão do número, **Compartilhar este número** → "Toda a equipe" ou escolha as
pessoas. Só o dono do número e o administrador compartilham, pausam ou desligam.

## 6. Problemas comuns

| Mensagem / situação | O que fazer |
|---|---|
| "O Python não foi encontrado" | Instale o Python marcando "Add Python to PATH" e rode `instalar.bat` de novo |
| "O sistema ainda não foi instalado" | Rode `instalar.bat` |
| Esqueci a senha | Outro administrador cria uma senha nova em Configurações > Usuários, ou rode `redefinir_senha.bat` |
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

Testes automáticos: dois cliques em `testar.bat` (não mexe nos seus dados).

Documentação técnica: pasta [`docs/`](docs/README.md).
