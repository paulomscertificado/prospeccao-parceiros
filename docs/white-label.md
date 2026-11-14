# White label: várias ARs (marcas) na mesma plataforma

Plano completo (diagnóstico, arquitetura, regras de acesso, fluxo de navegação e as 7 fases com portão): documento
"Plataforma White Label – Diagnóstico e Arquitetura" (https://claude.ai/artifact/5hJjyDGvMam8aEADVQpNKq).
O dono da plataforma e Admin Master é o Paulo Marinho (`Usuario.master`).

| Fase | O quê | Portão (só segue quando) | Situação |
|---|---|---|---|
| 0 | Vercel Pro, Supabase Pro, relógio das filas na nuvem, ambiente de teste | 7 dias seguidos sem a reserva do computador | Código do relógio publicado (`app/relogio.py`); planos esperando o cartão |
| 1 | A AR entra nos dados (`tenants` + `tenant_id`) | nenhuma linha sem AR, contagens iguais, nenhuma ligação cruzando ARs | **Concluída em 14/11/2026**: ensaio no banco de teste e aplicação na nuvem com a conferência OK (leads: 1.387 na AR MS, 111 no Grupo Certy); linhas novas de hora em hora |
| 2 | Isolamento obrigatório (filtro, porteiro com AR, RLS, testes nas 178 rotas) | nenhuma rota abre registro de outra AR | **Parte 1 (isolamento dos dados) no ar desde 14/11/2026**; parte 2 (configurações por AR) pronta e ensaiada; RLS, `NOT NULL` e índices adiados (ver abaixo) |
| 3 | Permissões por AR e painel /master | admin de uma AR não alcança outra nem o /master | — |
| 4 | WhatsApp, e-mail e filas por AR | uma AR parada não atrasa as outras | — |
| 5 | Marca (white label) | nenhuma tela ou mensagem mostra a MS em outra AR | — |
| 6 | Auditoria, LGPD e planos | exportar e apagar uma AR de teste sem tocar nas outras | — |

Os planos pagos são obrigatórios antes da Fase 3 (a primeira AR nova): o Hobby da Vercel não permite uso comercial
e o banco grátis tem 500 MB.

## Fase 1: a AR entra nos dados

**Banco.** Tabela nova `tenants` (slug, nome, CNPJ, situação, plano) e a coluna `tenant_id` (modelos.`DaAR`) em
36 das 41 tabelas. Ficam sem coluna: `base_receita`, `bases_dados` e `bases_empresas` (listas da CNPJá: da
plataforma, todas as ARs usam — decisão de 13/11/2026), `categorias` e `travas`. A coluna nasce vazia e sem índice
(a publicação a cria com `banco.migrar_colunas`); índices, `NOT NULL` e chaves compostas ficam para a Fase 2.

**ARs de hoje.** `ms` (AR MS Certificados) e `grupo-certy` (Grupo Certy), criadas por `ars.garantir_ars`.
A AR de cada pessoa vem da empresa representada (`empresa_nome` com "Certy" ou e-mail `@grupocerty`): Grupo Certy;
senão, MS. O Admin Master fica sem AR (é da plataforma).

**Regras** (`app/ars.py`, só preenchem o que está vazio):

| Tabela | AR |
|---|---|
| leads | a do vendedor; do Admin Master → decisão `do_master`; sem vendedor → decisão `sem_dono` |
| historico, oportunidades | a do lead |
| campanhas | Renovação → MS (planilha da MS); senão a de quem criou (Master → `do_master`) |
| tarefas, mensagens | a do lead; senão a da campanha (ou certificado, cliente, pessoa) |
| certificados | a da campanha ou do lead; senão MS |
| conexoes_whatsapp, contas_email | a do dono; a principal → MS |
| mensagens_whatsapp, ponte_whatsapp | a do número por onde passou (`conexao`); número desconhecido → MS |
| contatos_whatsapp | a da última conversa com o telefone |
| buscas, buscas_cnpja (+ empresas), visuais (+ arquivos), artes_aviso, comandos, trabalhos | a do dono ou da campanha/busca de origem |
| equipes | a dos membros; papéis criados na tela → MS; os 5 papéis do sistema ficam vazios (modelo) |
| notificacoes, logs, excecoes_permissao | a da pessoa; as do Admin Master ficam vazias |
| base_conhecimento, produtos | MS |
| templates, cadencias, passos_cadencia, configuracoes | vazias = da plataforma (a cópia por AR é da Fase 2) |

Decididas em 14/11/2026 (`ars.PADRAO`): os leads e as campanhas do Admin Master vão para a AR MS, e os leads sem dono
também. Para outra escolha numa AR futura: `--master=` e `--sem-dono=` no `migrar_ar.py`.

**Conferência** (`ars.conferir`, o portão): nenhuma linha sem AR nas tabelas obrigatórias (vazio só onde é
permitido: Admin Master, papel do sistema) e nenhuma ligação cruzando ARs (`ars.LIGACOES`: histórico → lead, tarefa →
campanha, campanha → quem criou...). Uma ligação cruzada aponta dado a corrigir à mão antes da Fase 2.

**Como rodar** (sempre primeiro no teste):
1. Banco de teste: projeto grátis no Supabase; `salvar_banco_teste.bat` guarda o endereço em
   `dados/supabase_teste.txt` (recusa se for o mesmo da nuvem); `copiar_para_teste.bat` põe nele a última cópia de
   segurança (com o esquema de hoje, sem `tenant_id`).
2. `python migrar_ar.py ensaio`: cria a tabela e as colunas no teste (como a publicação faria), simula, mostra as
   contagens por AR e a conferência, e desfaz.
3. `python migrar_ar.py aplicar`: grava no teste, em lotes de 5.000 (com `VACUUM` nas tabelas grandes), confere e
   liga o preenchimento de hora em hora (configuração `ar_preenchimento`).
4. Com o ensaio aprovado e as decisões respondidas: publicar a versão da Fase 1 (cria a coluna vazia na nuvem; nada
   muda para quem usa), fazer um backup e rodar `python migrar_ar.py aplicar --nuvem` (pede SIM).
5. Daí em diante, `rotinas._rotina_hora` chama `ars.preencher_novos`: as linhas criadas desde a última hora ganham
   a AR pelas mesmas regras. Até a Fase 2 ninguém lê o `tenant_id`.

Plano de volta: a coluna fica e nenhum dado se perde; para desligar o preenchimento, apagar `ar_preenchimento`.
Testes: `testes/test_ars.py` (banco SQLite próprio com pessoas da MS, do Grupo Certy e o Admin Master).

## Fase 2, parte 1: cada AR vê e grava só o que é dela

**Onde** (`app/isolamento.py`): `seguranca.usuario_logado` chama `isolamento.ligar(db, usuario)` e a sessão do banco
da tela passa a ter a AR da pessoa (`db.info["ar"]`). Admin Master: sem AR (vê a plataforma toda até a Fase 3 trazer o
"Entrar numa AR"). Pessoa sem AR que não é o Admin Master: AR -1, não vê nada (na dúvida, fecha).

**Filtro automático** (evento `do_orm_execute` + `with_loader_criteria`): toda consulta do ORM dessa sessão — listas,
`db.get`, relações e update/delete do ORM — só alcança a AR da pessoa. `templates`, `cadencias`, `passos_cadencia`,
`papeis`, `permissoes_papel` e `usuarios`: a AR da pessoa OU a plataforma (vazio). `configuracoes` fica sem filtro
(chave única no sistema todo até a parte 2). Sessões sem AR (rotinas, cron, ponte do WhatsApp, scripts) veem tudo:
trabalham para todas as ARs. O que existe uma vez só e é da plataforma (número e e-mail principais) é procurado com
`.execution_options(sem_filtro_de_ar=True)`, senão a tela de outra AR tentaria criar de novo.

**AR nas linhas novas** (evento `before_flush`): a da sessão; sem ela, a do registro "pai" (lead, campanha, cliente...)
ou do dono (Admin Master como dono → AR MS); conversas e mensagens da ponte, a do número (`conexao`); sem nada, AR MS.
Pessoa nova: a da tela de quem criou ou, pelo sistema, a da empresa representada. Notificações e registros de ação: a
da pessoa (as do Admin Master ficam vazias). A rotina de hora em hora (`ars.preencher_novos`) segue de rede de segurança.

**Testes** (`testes/test_isolamento.py`): uma administradora do Grupo Certy percorre todas as rotas GET (com e sem os
ids de tudo da AR MS) sem ver nada da MS; as rotas POST com ids da MS não mudam nada; a AR MS não abre lead do Grupo
Certy (404) e o Admin Master abre os dois. Ensaio no Postgres do banco de teste (14/11/2026): Admin Master 1.276 leads,
AR MS 1.165, Grupo Certy 111, sem AR 0; alteração do Grupo Certy num lead da MS: 0 linhas.

**Falta (parte 2 e Fase 3):** configurações por AR (`configuracoes` com AR na chave); RLS no Postgres (usuário do banco
que não ignora a regra); `tenant_id` obrigatório e índices começando por ele; chaves únicas por AR
(`contatos_whatsapp.telefone`, `equipes.nome`, `papeis.codigo`); papéis, cadências, modelos e categorias da plataforma
hoje podem ser editados por administrador de qualquer AR (Fase 3: cópia por AR); "Entrar numa AR" do Admin Master.

## Fase 2, parte 2: configurações de cada AR

**Onde:** tabela `configuracoes_ar` (`modelos.ConfiguracaoAR`, chave = AR + configuração) e `banco.CHAVES_DA_AR` (envio,
horários, limites de volume, textos e regras da IA SDR, score, dias, retenção, base da Receita escondida). Sem valor
próprio, a AR usa o da plataforma (`configuracoes`). As outras chaves são da plataforma e só o Admin Master muda
(proteção dos números, alertas, módulos, banco, Renovação e Empresas novas até as decisões da planilha e da CNPJá por AR).

**Leitura e gravação** (`banco.ler_config`/`gravar_config`): numa tela de pessoa de uma AR, as chaves da AR leem e
gravam o valor dela (os valores próprios da AR são lidos uma vez por sessão, `_valores_da_ar`); o Admin Master muda o
padrão da plataforma. Rotinas escolhem a AR do registro com `banco.usar_config_da_ar(db, ar)`: filas de e-mail e
WhatsApp (por tarefa: envio ligado e horário da AR), respostas do WhatsApp e do e-mail (pela AR do lead). A fila só
para de vez se nenhuma AR quiser o envio (`banco.algum_valor`) ou estiver no horário
(`mensagens.dentro_do_horario_de_alguma_ar`). Tela Configurações > Geral: pessoa de AR vê "sua AR" e os campos da
plataforma travados; o POST ignora as chaves da plataforma de quem não é o Admin Master.

**Nome de contato do WhatsApp** (`contatos_whatsapp`, chave = telefone): se o telefone já tem nome de outra AR, a
tela não grava nem manda renomear no WhatsApp Leads (que é o mesmo computador para as ARs) e avisa (409).

**Testes:** `testes/test_config_ar.py`. Ensaio no Postgres de teste (14/11/2026): tabela criada pela preparação do
banco; o Grupo Certy gravou 09:45 e só ele viu; AR MS e Admin Master seguiram com o padrão.

**Adiados, com o motivo:**
- RLS no Postgres: as buscas da plataforma que precisam passar por cima do filtro (`sem_filtro_de_ar`: número e e-mail
  principais, nome de contato) seriam barradas no banco, e o pooler de transação exige marcar a AR a cada transação.
  Hoje não há SQL direto nas telas; a barreira é o filtro do ORM + a varredura de todas as rotas. Rever quando houver
  usuário de banco por AR ou integração externa.
- `tenant_id` obrigatório (`NOT NULL`): um backup de antes de 14/11/2026 (sem a coluna) não voltaria mais. A AR já é
  garantida no `before_flush`, conferida pelo `migrar_ar.py conferir` e preenchida de hora em hora.
- Índices começando pela AR: com o volume de hoje as consultas filtradas já usam os índices que existem.
- Chaves únicas por AR (`contatos_whatsapp.telefone`, `equipes.nome`, `papeis.codigo`): junto com a Fase 3.
