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
Agente de IA do lead: assinatura "*Nome:*" no começo (`ASSINATURA_DE_AGENTE`) ou 4+ mensagens em 10 min também contam como robô. A resposta automática da SDR respeita o limite diário do número por onde sai.

## Quando a IA não classifica (correções de risco, out/2026)

Valem para mensagens que chegam sozinhas (WhatsApp e e-mail). Uma resposta registrada à mão por alguém da equipe
continua sendo classificada.
- **Parceiro ou lead com alguém da equipe** (`sdr.com_humano`: assumido, Reunião, Negociação, Parceiro; ou com
  registro em `parceiros`): `_mensagem_para_o_humano` só registra e avisa quem cuida (1 aviso a cada 2 h por lead;
  pedido para parar avisa sempre). Não classifica, não responde, não volta a etapa e não marca opt-out sozinha
  ("cancelar a indicação do João" não vira opt-out). `rotinas.responder_automaticamente` também recusa esses leads.
- **Só mídia** (`[áudio]`, `[imagem]`, `[documento]`... sem legenda, `SO_MIDIA`): `_so_midia` para a sequência, não
  responde e cria uma oportunidade morna "Ouvir o áudio no WhatsApp e responder".
- Uma resposta quente nunca volta a etapa do lead (só vai para Interessado se ele estiver antes disso).

## Limite de WhatsApp por número

O limite diário (`limite_diario_whatsapp`, 40) e o por hora valem para **cada número**, porque é o número que pode ser
bloqueado; o WhatsApp Leads conta do mesmo jeito. `mensagens.limite_do_numero(db, conexao)` é conferido em
`sdr.enviar_whatsapp_conectado` depois de escolher o número, e na resposta automática. A fila automática pula para o
próximo lead quando um número chega ao limite. Minha fila mostra o contador do número da pessoa; Envios, o do número
que mais enviou.

## Empresa representada por usuário (nov/2026)

`app/marca.py`. Campos em `usuarios`: `empresa_nome`, `empresa_site`, `empresa_descricao` (vazio = `marca.PADRAO`,
a MS). Tela: Minha conta (`POST /minha-conta/empresa`). (`empresa_validacao`, `empresa_preco_a1/a3` existem no banco
mas não são usados: a Maria pediu para tirar.)

- `marca.aplicar(texto, usuario)` troca nos textos dos modelos "MS Certificação Digital"/"MS Certificados", o site,
  "Autoridade de Registro ICP-Brasil", tira "presencial em Recife ou por videoconferência"/"em Recife" e troca "a/da/com a MS" (com "do/no/
  pelo" para nomes masculinos como "Grupo ..."). Chamado em `cadencias.aplicar` (tarefas das campanhas),
  `mensagens.montar`, `sdr.gerar_mensagens`, `sdr.enviar_whatsapp_conectado`, `campanhas._enviar_email_da_tarefa`
  (na hora do envio, com o responsável pelo lead) e no e-mail de teste.
- A IA SDR escreve como SDR da empresa do usuário. Empresas novas: placeholder `{minha_empresa}` e assinatura
  `marca.assinatura`; as mensagens de venda não têm preço nem local de validação.
- `campanhas._trocar_assinatura` não depende mais do nome da MS.
- Correção (caso "Grupo Certy - Teste 02"): a troca de artigo ignora maiúscula ("A MS faz" → "O Grupo Certy faz",
  com concordância a/o, da/do, na/no, pela/pelo, com a/com o, à/ao, para a/para o); "Parceria/equipe/time MS" também
  troca, mas "MS" dentro do nome do lead não. A apresentação curta perde o ponto final (o modelo já põe) e tem até
  80 letras. O nome do lead nas mensagens passa por `util.nome_para_mensagem` (tira o CNPJ/CPF que a Receita põe no
  nome do MEI). O modelo de e-mail diz "1. Vocês indicam o cliente;" / "3. Vocês são remunerados por cada
  certificado emitido;" (`modelos_segmento.TROCAS_ANTIGAS` corrige os modelos salvos e `marca.aplicar` as tarefas
  já montadas, na hora do envio).
- Testes: `testes/test_marca.py`.

## Empresas novas – venda para empresas recém-abertas (nov/2026)

`app/empresas_novas.py`, tela `app/rotas/empresas_novas.py` + `empresas_novas.html` (menu "Empresas novas",
permissão `campanhas.ver`; configurar/buscar com `campanhas.gerenciar`).

- API paga da CNPJá (`CNPJA_API_KEY`, salva pela tela via `arquivo_env`): `GET https://api.cnpja.com/office` com
  `founded.gte`, `founded.lte`, `address.state.in`, `status.id.in=2`, `limit=1000`, paginação por `token`
  (até 5 páginas); `GET /credit` para o saldo. 1 crédito a cada 10 registros.
- `Campanha.tipo` (`parceiros` | `empresas_novas`). A campanha diária é criada com `status="gerando"` e o trabalho
  "campanha" começa na fase `novas` (`etapa_importar`): cadastra os leads em lotes (duplicado só pelo CNPJ),
  escreve as mensagens (`textos_do_lead`, modelos editáveis em config `novas_mensagens`) e segue para `_montar`
  com a cadência "Venda – Empresas novas (D1, D3, D7)" (ângulos `venda_*`).
- `rotinas.rodada`: a cada 15 min chama `rodada_diaria` (uma vez por dia depois de `novas_hora`; busca de
  `novas_ultima_data`+1 até hoje, no máximo 7 dias; erro da API tenta de novo na próxima volta).
- Edição de mensagens na campanha de venda usa `sdr.texto_sem_spam` (preço permitido) em vez de `texto_seguro`.
  `rotinas.responder_automaticamente` não responde leads de venda (`empresas_novas.e_lead_de_venda`).
- Sem filtro de atividade (pedido da Maria: venda para qualquer empresa nova). Telefones pelo `type` da CNPJá
  (LANDLINE = fixo, MOBILE = celular).
- Cada busca fica em `buscas_cnpja` + `buscas_cnpja_empresas` (`registrar_busca`), com `motivo_fora`: repetida,
  MEI (opção), já numa lista importada (`novas_excluir_listas`, tabela `bases_empresas`) ou lead já trabalhado.
  A campanha sai da lista guardada (`criar_campanha_da_busca`, sem gastar crédito). Tela
  `/empresas-novas/busca/{id}`; teste `/empresas-novas/testar` (`limit=10`, 1 página = 1 crédito, sem campanha).
- Testes: `testes/test_empresas_novas.py` (API simulada).

## Empresas novas sem repetição (nov/2026)

- Teste (`testar`): um dia de abertura por vez (`dia_do_teste`: o mais recente entre 1 e 10 dias atrás ainda não
  testado). Antes era sempre "últimos 7 dias" + `limit=10`, e a CNPJá devolvia as mesmas 10, na mesma ordem.
- Rotina diária: janela `novas_ultima_data`+1 até hoje − `ATRASO_DIAS` (2), no máximo 7 dias; grava o fim da janela em
  `novas_ultima_data` (janelas nunca se sobrepõem; a Receita publica com atraso, então o dia de hoje vinha incompleto).
- `registrar_busca` marca "já veio na busca de..." quem estava apto numa busca anterior que virou campanha.
- `buscar_e_criar` pede `limit` = 2 × `novas_maximo_dia` (só paga o que cabe na campanha).

## Horários dos toques nunca no passado (nov/2026)

`cadencias.hora_natural(db, dia)`: para hoje, só horários a partir de agora + 15 min (`FOLGA_MINUTOS`); `None` se o
horário de envio de hoje acabou. `cadencias.dia_e_hora_futuros` acha o próximo dia/horário livre (respeita
`pular_fim_de_semana`). `cadencias.aplicar` usa isso nos toques de campanha; `campanhas.aprovar` chama
`_sem_horario_no_passado` (campanha aprovada depois do horário marcado: o toque que já passou ganha horário novo e os
seguintes da mesma empresa nunca ficam antes dele). Testes: `testes/test_horarios_futuros.py`.

## Intervalo dos envios automáticos (nov/2026)

`campanhas.processar_fila` (e-mail) e `processar_fila_whatsapp`: um envio automático por rodada e por canal; depois
de cada envio `_anotar_envio` sorteia o próximo horário liberado (`INTERVALO_AUTOMATICO_SEG` = 150 a 210 s, config
`proximo_envio_automatico:<canal>`). Com a rodada a cada minuto, cada envio sai 3 ou 4 minutos depois do anterior.
E-mail recusado pelo destinatário também conta (o servidor foi chamado). Testes desligam com `ESPACAR_ENVIOS=0`
(conftest); a regra tem teste próprio em `testes/test_intervalo_envios.py`.
Chave da CNPJá: Configurações > Integrações (`/configuracoes/cnpja`, `/configuracoes/cnpja/saldo`); saiu da tela
Empresas novas, que virou um painel em 4 passos (estados por caixinha, `name="ufs"` repetido).

## Reserva do lead por usuário (nov/2026)

`app/reservas.py`. Campos em `leads`: `reservado_por_id`, `reservado_em`, `reservado_ate`.

- `campanhas._montar` reserva cada empresa para o dono da campanha (`reservar`, 60 dias).
- `campanhas._buscar_candidatos` pula empresa com reserva ativa de outro usuário (`de_outro`).
  `_leads_em_outras_campanhas` agora só barra empresa com toque pendente/rascunho em campanha em andamento
  (antes barrava para sempre qualquer empresa que já esteve em campanha).
- `leads_servico.mudar_status` chama `renovar_por_status` (os 60 dias recomeçam).
- Rotina de hora em hora (`rotinas.rodada`): `preencher_reservas_antigas` (uma vez, flag `reservas_preenchidas`)
  e `liberar_vencidas` (adia 1 dia se ainda há campanha em andamento com toque pendente).
- `liberar`: cancela toques de prospecção pendentes/rascunho, tira o vendedor se era o dono da reserva e volta o
  status para Novo se a empresa nunca respondeu (Novo/Pesquisando/Abordagem criada/Contatado/Aguardando resposta
  ou Perdido por "Sem resposta"), sem mexer em opt-out.
- Ficha do lead: selo + `POST /leads/{id}/liberar` (dono da reserva ou quem vê todos os leads).
- Testes: `testes/test_reservas.py`.

## Quem assina e envia a campanha (nov/2026)

- `campanhas._mensagens` gera os textos com o **dono da campanha** (`camp.usuario_id`), não com o vendedor da ficha.
- `campanhas._montar`: empresa que entra na campanha passa para o dono se `_livre_para_campanha` (sem
  `humano_id`, `contatado_em` e `respondeu_em`); a troca vai para o histórico. Assim `conexoes.responsavel` (que
  olha `lead.vendedor_id`) envia pelo WhatsApp/e-mail do dono.
- Campanhas antigas: `responsaveis_diferentes` mostra o aviso na campanha e `assumir_empresas`
  (`POST /campanhas/{id}/assumir-empresas`) passa as empresas livres para o dono e troca a assinatura nos toques
  rascunho/pendentes (`_trocar_assinatura`: só "\n\n<Nome>\nMS Certificação Digital" e "Sou <Nome>, da/e").
- Testes: `testes/test_responsavel_campanha.py`.

## E-mails que não existem (nov/2026)

`app/email_validacao.py`. Campos novos em `leads`: `email_invalido`, `email_motivo`, `email_verificado_em`,
`email_conferido` (endereço a que a marca se refere; editar o e-mail limpa a marca).

- **Antes do envio** (`utilizavel`, chamado em `campanhas._buscar_candidatos` e `_enviar_email_da_tarefa`):
  formato + MX via dns.google (NXDOMAIN, MX nulo "0 ." ou sem MX/A = inválido; erro de rede = não barra);
  reconfere a cada 30 dias; cache por domínio no processo. `tem_canal` ignora e-mail inválido.
- **Recusa do SMTP** (`ErroDestinatario`) também marca o lead.
- **Devoluções** (`email_imap.ler_devolucoes` + `rotinas._ler_devolucoes`, a cada 5 min junto com as respostas):
  identifica DSN (multipart/report, mailer-daemon/postmaster + assunto), extrai `Final-Recipient`/`X-Failed-Recipients`
  ou o e-mail citado no texto e o Message-ID original; só devolução permanente (5.x.x ou texto "não encontrado",
  "user unknown"...) marca. 1ª leitura por caixa: 60 dias (`devolucoes_lidas:<conta>` em config).
- `marcar_invalido` cancela os toques de e-mail pendentes/rascunho e grava no histórico.
- Quadro **E-mails que não existem** na campanha (`campanhas.emails_invalidos`) com correção em linha
  (`POST /campanhas/{id}/corrigir-email`, `campanhas.corrigir_email`): valida o endereço novo (formato + DNS),
  limpa a marca, reativa os toques de e-mail cancelados por e-mail inválido (empurra as datas atrasadas para hoje,
  mantendo o intervalo; em campanha aguardando aprovação voltam como rascunho) e, se o e-mail tinha sido
  devolvido, cria um toque de reenvio hoje com a última mensagem enviada.
- Botão **Conferir e-mails** na campanha (`POST /campanhas/{id}/conferir-emails`, `campanhas.conferir_emails`).
- Testes: `testes/test_emails_inexistentes.py`; a variável `CONFERIR_DOMINIO_EMAIL=0` desliga o DNS nos testes.
- Correção (nov/2026): a devolução do Gmail vem com `In-Reply-To` do nosso e-mail e era lida como RESPOSTA do lead
  (status "Respondeu", oportunidade e resposta automática "Obrigado pelo retorno!" para o endereço inexistente, que
  gerava outra devolução). Agora `email_imap.ler_respostas` pula o que `parece_devolucao`, `rotinas._ler_caixa` pula
  texto de devolução (`email_validacao.texto_de_devolucao`), `responder_automaticamente` nunca responde e-mail
  inválido e `ler_respostas_por_email` lê as devoluções ANTES das respostas.

## CNPJ inativo

Se a BrasilAPI disser que o CNPJ não está ativo (baixada, inapta, suspensa), `leads_servico.cnpj_inativo` registra no
histórico e, se o lead ainda não conversou, marca Perdido (motivo "CNPJ inativo") e ele sai da campanha.

**Restaurantes e lanchonetes** (CNAE 5611-2/01 e 5611-2/03): segmento novo; na base da Receita só entram os da Região
Metropolitana do Recife (importação própria, para não estourar o espaço do banco gratuito).

## Listas importadas (bases separadas da Receita, nov/2026)

`app/bases_importadas.py`. Tabelas `bases_dados` (a lista: nome, origem, total, estados) e `bases_empresas` (as
empresas, com as MESMAS colunas da `base_receita`, para reaproveitar `base_receita.buscar/contar` com
`modelo=EmpresaBase, filtro=base_id == id`). Identificação nas telas e em `campanhas.base`: `"receita"` ou
`"lista:<id>"`.

- Importação: `importar(db, nome, arquivo)` lê a exportação .xlsx da CNPJá (abas Estabelecimentos e Sócios; o
  cabeçalho é a linha que começa com "CNPJ"). Só situação "Ativa". Responsável = sócio pessoa física com o cargo mais
  indicado (`base_receita.CARGOS_RESPONSAVEL`); CPF e faixa etária não são guardados. Segmento pelas regras das
  categorias; sem segmento = `outros`. Mesmo nome = troca as empresas da lista.
- Telas: Configurações > Integrações > Listas (`/configuracoes/listas/importar`, `/{id}/apagar`, `/receita`);
  na nuvem só passam arquivos até 4 MB (limite da Vercel): para os maiores, `importar_lista.bat` (grava direto no
  Supabase pelo `dados/supabase.txt`; `--local` grava no banco deste computador).
- Escolha da base: Nova campanha (`base`, "Todas as cidades do estado" = `cidade` vazia, só para lista),
  `/api/contagem?base=`, e "Encontrar novos parceiros" (cada lista vira uma fonte `lista:<id>`).
- `receita_oculta` (config) esconde a base da Receita das telas (`bases_importadas.opcoes`/`escolher`).
- Testes: `testes/test_bases_importadas.py`.
