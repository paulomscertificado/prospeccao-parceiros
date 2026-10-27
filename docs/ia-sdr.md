# IA SDR – prospecção B2B de parceiros

> **Princípio:** a IA não é o vendedor. A IA é a SDR.
> Ela **encontra + chama a atenção + gera resposta + qualifica + entrega a oportunidade.**
> O time humano **conversa, entende, negocia, fecha e constrói o relacionamento.**

## 1. Arquitetura (módulos)

| Módulo | Arquivo | O que faz |
|---|---|---|
| Lead Discovery | `app/base_receita.py`, `app/prospeccao.py` | Base local da Receita com as empresas ativas das categorias (CNAE + palavras no nome); OSM e Google Places opcionais |
| Lead Enrichment | `app/pesquisa.py` | Lê até 6 páginas públicas do site, BrasilAPI (sócios), sinais por regras e **perfil do parceiro** (IA só com o texto lido) |
| Lead Scoring | `app/score.py` | 12 critérios configuráveis, score 0–100+, potencial e **fit** (Muito alto … Sem fit) |
| AI SDR | `app/sdr.py` | Canal, mensagens únicas (4 ângulos), classificação de respostas (15 classes), handoff, notificações |
| Campaign Manager | `app/campanhas.py` | Pedido em texto → campanha → **aprovação** → fila; fim de cadência ("Sem resposta") |
| Email | `app/integracoes/email_smtp.py`, `email_imap.py` | Envio pela fila (com limites) e leitura das respostas (IMAP) |
| WhatsApp conectado | `app/integracoes/whatsapp_leads.py` + `sdr.enviar_whatsapp_conectado` / `sincronizar_whatsapp_conectado` | Usa o número conectado no sistema WhatsApp Leads (fila com pausas, horário e limite; respostas e opt-out voltam sozinhos) |
| WhatsApp | `app/integracoes/whatsapp_cloud.py` | API oficial: templates aprovados, resposta dentro da janela de 24 h, webhook com assinatura |
| CRM | `app/config.py` (status), pipeline | Novo → Pesquisando → Abordagem criada → Contatado → Aguardando resposta → Respondeu → Interessado → Humano assumiu → Reunião → Negociação → Parceiro → Parceiro ativo / Perdido |
| Calendar | `app/agenda_horarios.py` | Horários livres = expediente do responsável − reuniões marcadas (nunca inventa horário) |
| Human Handoff | `Oportunidade`, `/oportunidades` | Tela "Novas oportunidades", botão **Assumir lead**, avisos |
| Analytics | `app/metricas.py` (`inteligencia`) | Painel "Inteligência de Prospecção", ranking de segmentos, sugestões |
| Knowledge Base | tabela `base_conhecimento`, `/conhecimento` | O que a SDR pode responder sozinha |
| Partner Management | módulo Parceiros (já existente) | Parceiros, vendas, comissão, vencimentos |
| Rotinas | `app/rotinas.py` | Fila (1 min), respostas por e-mail (5 min), vencimentos e fim de cadência (1 h) |

## 2. Fluxo de dados

```
"Quero novos parceiros" ──► IA pergunta: "Qual região?" / "Algum segmento específico?"
        │
        ▼
Base da Receita (categorias) ──► dedup (CNPJ, domínio, telefone, e-mail; respeita opt-out)
        │
        ▼
Pesquisa pública (site + BrasilAPI) ──► Perfil do parceiro ──► Score + fit ──► seleciona os melhores
        │
        ▼
Mensagens únicas (apresentação, praticidade, receita, encerramento) ──► tarefas em RASCUNHO
        │
        ▼
APROVAÇÃO NECESSÁRIA  [APROVAR] [EDITAR] [CANCELAR]
        │
        ▼
Seleção: cada campanha pega empresas DIFERENTES (`campanhas._leads_em_outras_campanhas`: pula leads de campanhas
não canceladas; `_buscar_candidatos` busca mais fundo na base, até `MAXIMO_BUSCA` por segmento)
Fila: e-mail automático (limites) · WhatsApp automático só p/ quem já conversou (resto com 1 clique) · LinkedIn com 1 clique
        │
        ▼
Resposta (webhook WhatsApp · IMAP · registro manual) ──► IA classifica (15 classes)
        ├─ Interesse ──► PARA a automação ──► 🔥 OPORTUNIDADE ──► aviso ao responsável ──► humano assume
        ├─ Objeção / já tem parceiro / não é o responsável ──► oportunidade "morna" para o humano decidir
        ├─ Sem interesse ──► Perdido (Sem interesse)
        └─ Opt-out ──► bloqueio permanente
Sem resposta após o último toque + N dias ──► Perdido (Sem resposta). Não insiste.
        │
        ▼
Resultado (reunião, parceiro, vendas) ──► Inteligência de Prospecção ──► próxima campanha
```

## 3. Integrações

| Integração | Uso | Obrigatória? |
|---|---|---|
| Base da Receita (dados abertos) | Encontrar empresas por categoria e cidade | Recomendada (gratuita) |
| BrasilAPI | Sócios e dados do CNPJ | Não (gratuita) |
| Sites das empresas | Perfil do parceiro | Não (leitura pública, 6 páginas no máximo) |
| Claude (Anthropic) | Perfil, mensagens, classificação, interpretação do pedido | Não (sem chave, regras) |
| SMTP / IMAP | Enviar e-mails pela fila / ler as respostas | Para envio automático |
| WhatsApp Cloud API | Templates, respostas dentro de 24 h, webhook | Não |
| LinkedIn | Sem API oficial de mensagens: só tarefa manual | — |
| Google Calendar | Previsto (hoje a agenda é a interna) | — |

## 4. Banco de dados (novo)

- `categorias`: código, nome, prioridade, aderência (0–25), recorrente, CNAEs, CNAEs com palavra, palavras-chave, motivo, estratégia, abertura e gancho da mensagem, ativa, sugerida pela IA.
- `oportunidades`: lead, temperatura (quente/morna), classificação, canal, mensagem enviada, resposta, resumo, objeções, interesse, próximo passo, status (nova/assumida/descartada), responsável.
- `notificacoes`: avisos por usuário (contador no menu).
- `base_conhecimento`: pergunta e resposta.
- `leads` (+): categoria, perfil (JSON), pesquisado_em, fit, motivo_potencial, programa_parceiros, possibilidade_indicacao, canal_preferido, classificacao_resposta, automacao_pausada, humano_id, assumido_em.
- `campanhas` (+): pedido, categorias, cidade, estado, quantidade, canais, objetivo, tom, CTA, status, etapa, aprovado_por, aprovado_em.
- `mensagens` (+): campanha, categoria, ângulo, respondida — base das métricas "qual mensagem/canal/abordagem funciona".
- `tarefas` (+): ângulo; status `rascunho` até a aprovação.
- `usuarios` (+): expediente e duração da reunião.
- `base_receita` (+): categoria.

A migração é automática ao abrir o sistema (colunas novas e status antigos → novos).

## 5. Estratégia de IA

- Saídas sempre em JSON com esquema fixo (classe dentro da lista, fit dentro da lista).
- **Não inventar:** a IA recebe só o texto lido no site e os dados cadastrados; números de clientes só ficam se o
  trecho citado aparecer literalmente no texto; nomes de responsáveis só se estiverem no site.
- **Não negociar:** o prompt proíbe preço, comissão em números, desconto, exclusividade, contrato e fechamento,
  e o sistema confere depois (`sdr.texto_seguro`). Se a IA sair da regra, a mensagem é trocada pela versão segura.
- Mensagem nunca genérica para todos: cada empresa recebe texto com os fatos dela; sem fatos, a abordagem
  genérica pede o responsável por parcerias (como definido pela MS).
- Opt-out é detectado por regras antes da IA (não depende dela).
- Sem chave de IA, tudo funciona com regras e modelos por categoria.

## 6. Segurança

Perfis e permissões (aprovação de campanha só administrador/gestor), CSRF, sessão com expiração, senhas com
hash, logs de auditoria (criar/aprovar/cancelar campanha, assumir lead), webhook com assinatura HMAC,
chaves só no `.env`, automação para imediatamente em "Assumir lead".

## 7. Conformidade

- **WhatsApp:** a política do WhatsApp Business exige opt-in para mensagens iniciadas pela empresa pela API.
  Por isso o primeiro contato por WhatsApp com quem não autorizou é **assistido** (a SDR prepara, a pessoa
  envia com um clique). A API oficial é usada para templates aprovados (contatos com opt-in) e para responder
  dentro da janela de 24 h aberta pela mensagem do lead.
- **E-mail:** contato B2B com base no legítimo interesse, com descadastro em todo e-mail (`List-Unsubscribe` +
  "responda SAIR"), limites por hora/dia/domínio e horário comercial.
- **LGPD:** origem e fonte de cada lead, base legal, opt-out com bloqueio permanente, exclusão, retenção,
  histórico de tratamento e logs. Só dados empresariais públicos.
- **Controle de frequência:** por contato (intervalo mínimo), por dia e por hora (canal), por campanha e por domínio.

## 8. MVP entregue

Tudo acima funcionando com: descoberta por categoria na base da Receita, pesquisa e perfil, score e fit,
mensagens únicas em 4 ângulos, campanhas com aprovação, fila de e-mail com limites, leitura de respostas
(IMAP e webhook), classificação em 15 classes, handoff com "Assumir lead", oportunidades, agenda com horários
reais, base de conhecimento, inteligência de prospecção com ranking e sugestões, categorias editáveis e
sugestões de novas categorias pela IA.

**Próximos passos sugeridos:** Google Calendar, templates de WhatsApp aprovados por categoria, teste A/B
automático de ângulos/CTAs, fila em Redis para volumes acima de milhares de envios por dia.

## Testar antes de aprovar

`campanhas.enviar_teste` (ação `/campanhas/{id}/testar`): a pessoa escolhe a campanha (`campanha_teste`, qualquer uma que ela pode ver, aguardando/ativa/pausada), o canal (`canal_teste` = whatsapp ou email) e o destino dela; vão os toques daquele canal de 1 a 5 empresas (só o primeiro ou todos), com "[TESTE]". A tela mostra quantas mensagens de cada canal a campanha tem (`mensagens_para_teste`). Não grava `Mensagem` nos leads, não conta nos limites, não muda a campanha; fica só no log (`testou_campanha`).

Canal: a IA não faz ligações. Com WhatsApp permitido, o celular informado à Receita vira o WhatsApp do lead (`celular_do_lead`). Empresas só com telefone fixo também entram (depois das que têm canal): a cadência cria passos de WhatsApp sem número, os ids vão para `Campanha.so_fixo` e a campanha mostra o cartão "Pesquisar WhatsApp" (links de busca + campo para salvar, ação `whatsapp-lead`). `cadencias.aplicar` nunca cria ligação/LinkedIn em campanha da IA, e `aprovar` cancela ligações de campanhas antigas.

Dois modelos: cada toque da campanha da IA guarda o texto de WhatsApp e o de e-mail (`Tarefa.mensagem_whatsapp`, `mensagem_email`, `assunto_email`); `mensagem`/`assunto` são os do canal escolhido. Na campanha os dois aparecem lado a lado e editáveis; a ação `trocar-canal` passa o toque para o outro canal.

## Modelos por segmento

`app/modelos_segmento.py`: 15 modelos por segmento (8 WhatsApp + 7 e-mail, cobrindo os 4 toques), 14 segmentos = 210 modelos, criados na partida por `garantir` (só os que faltam; editados não são sobrescritos). `Template.categoria`/`Template.angulo`. Aparecem no lead do segmento (antes dos gerais), em Cadências > Templates com filtro por segmento, e nas campanhas sem IA (`sdr._usar_modelos_do_segmento`, um modelo por toque escolhido pelo id da empresa).

Prospecção por CNAE: `Busca.cnaes` + `base_receita.buscar(cnaes=...)` filtra pela atividade principal no lugar da categoria. Lista pronta em `config.CNAES_BUSCA`; contagem guardada em `contagem_cnaes` (`atualizar_contagem_cnaes`, roda ao fim da importação).

## Resposta automática (robô) do lado do lead

`sdr.e_resposta_automatica` (frases em `FRASES_AUTOMATICAS`) ou 3+ mensagens recebidas em 2 minutos (`_rajada_de_mensagens`)
viram a classe `config.CLASSE_AUTOMATICA`: `processar_resposta` só registra (`_resposta_de_robo`), sem resposta da SDR,
sem oportunidade e sem cancelar a sequência. A IA também pode devolver essa classe. `rotinas.responder_automaticamente`
responde no máximo 1 vez a cada 24 h por lead. `criar_oportunidade` junta novas respostas na oportunidade "nova" do lead.
