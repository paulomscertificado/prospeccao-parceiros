# White label: várias ARs (marcas) na mesma plataforma

Plano completo (diagnóstico, arquitetura, regras de acesso, fluxo de navegação e as 7 fases com portão): documento
"Plataforma White Label – Diagnóstico e Arquitetura" (https://claude.ai/artifact/5hJjyDGvMam8aEADVQpNKq).
O dono da plataforma e Admin Master é o Paulo Marinho (`Usuario.master`).

| Fase | O quê | Portão (só segue quando) | Situação |
|---|---|---|---|
| 0 | Vercel Pro, Supabase Pro, relógio das filas na nuvem, ambiente de teste | 7 dias seguidos sem a reserva do computador | Código do relógio publicado (`app/relogio.py`); planos esperando o cartão |
| 1 | A AR entra nos dados (`tenants` + `tenant_id`) | nenhuma linha sem AR, contagens iguais, nenhuma ligação cruzando ARs | Código pronto no ramo `fase1-ar`; falta o ensaio no banco de teste |
| 2 | Isolamento obrigatório (filtro, porteiro com AR, RLS, testes nas 178 rotas) | nenhuma rota abre registro de outra AR | — |
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
