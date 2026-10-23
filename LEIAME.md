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

**Vendas, Vencimentos e Comissões ficam ocultos** no menu e no Dashboard. Para mostrar de novo: Configurações >
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

**WhatsApp:** deixe o **WhatsApp Leads** aberto e conectado. Na Agenda e na ficha do lead aparece o botão
**Enviar pelo WhatsApp conectado** (sai pelo seu número, com as pausas e o limite do WhatsApp Leads), e as
respostas dos parceiros chegam sozinhas na IA SDR. O rodapé do menu mostra se o WhatsApp está conectado.

Configure as categorias em Configurações > **Categorias de parceiros** e o que a IA pode responder em
**Base de conhecimento**. Detalhes técnicos: [`docs/ia-sdr.md`](docs/ia-sdr.md).

## 5. Perfis de acesso

| Perfil | Vê |
|---|---|
| Administrador | Tudo, inclusive Configurações e usuários |
| Gestor | Toda a equipe e os indicadores (não altera configurações) |
| Vendedor | Só os próprios leads, tarefas e vendas |
| Parceiro | Só o portal: própria carteira, indicações, vendas e comissão |

Crie usuários em **Configurações > Usuários**.

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
| "O Google recusou a senha" | Use a **senha de app** (16 letras) da conta de envio, não a senha normal (Configurações > E-mail mostra o passo a passo) |
| E-mails caindo no spam | Configurações > E-mail mostra o que falta no DNS (DKIM e DMARC); comece com poucos e-mails por dia |
| A campanha não manda e-mails sozinha | Configure o SMTP no `.env` e confira em Configurações se "fila envia e-mails sozinha" = 1; o envio só acontece em dias úteis, no horário configurado |
| "APROVAÇÃO NECESSÁRIA" não some | Só administrador ou gestor aprovam campanhas |
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
