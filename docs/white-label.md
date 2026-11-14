# White label: várias ARs (marcas) na mesma plataforma

Plano completo (diagnóstico, arquitetura, regras de acesso, fluxo de navegação e as 7 fases com portão): documento
"Plataforma White Label – Diagnóstico e Arquitetura" (https://claude.ai/artifact/5hJjyDGvMam8aEADVQpNKq).
O dono da plataforma e Admin Master é o Paulo Marinho (`Usuario.master`).

| Fase | O quê | Portão (só segue quando) | Situação |
|---|---|---|---|
| 0 | Vercel Pro, Supabase Pro, relógio das filas na nuvem, ambiente de teste | 7 dias seguidos sem a reserva do computador | Código do relógio publicado (`app/relogio.py`); planos esperando o cartão |
| 1 | A AR entra nos dados (`tenants` + `tenant_id`) | nenhuma linha sem AR, contagens iguais, nenhuma ligação cruzando ARs | **Concluída em 14/11/2026**: ensaio no banco de teste e aplicação na nuvem com a conferência OK (leads: 1.387 na AR MS, 111 no Grupo Certy); linhas novas de hora em hora |
| 2 | Isolamento obrigatório (filtro, porteiro com AR, RLS, testes nas 178 rotas) | nenhuma rota abre registro de outra AR | **Parte 1 (isolamento dos dados) no ar desde 14/11/2026**; **parte 2 (configurações por AR) no ar desde 14/11/2026**; RLS, `NOT NULL` e índices adiados (ver abaixo) |
| 3 | Permissões por AR e painel /master | admin de uma AR não alcança outra nem o /master | **No ar desde 14/11/2026** (painel /master, o que é da plataforma só o master muda, módulos por AR); admins das ARs promovidos em 14/11/2026 |
| 4 | WhatsApp, e-mail e filas por AR | uma AR parada não atrasa as outras | **Fila justa e avisos por AR no ar desde 14/11/2026**; WhatsApp Leads: decidido servidor central na nuvem (14/11/2026), espera a contratação |
| 5 | Marca (white label) | nenhuma tela ou mensagem mostra a MS em outra AR | **No ar desde 14/11/2026**: um endereço para todas (tela de entrada neutra), marca de cada AR nas telas e nas mensagens; marca do Grupo Certy gravada pelo manual (falta o logo); nome e domínio da plataforma depois |
| 6 | Auditoria, LGPD e planos | exportar e apagar uma AR de teste sem tocar nas outras | **Auditoria e LGPD no ar desde 14/11/2026** (quem agiu como quem; exportar e apagar uma AR, ensaiados no banco de teste); planos e cobrança depois da validação (decidido em 14/11/2026) |

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

## Fase 3: permissões por AR e painel /master

**Administrador de AR** = perfil `admin` que não é o Admin Master. Pelo isolamento ele já vê e mexe só na própria AR;
desde a Fase 3 também não muda o que vale para todas as ARs: papéis do sistema, modelos de mensagem e cadências sem AR,
categorias e módulos (`autorizacao.pode_mudar` / `da_plataforma`, mensagem `MSG_DA_PLATAFORMA`). Ele cria os próprios
(papel novo copiando de um do sistema, modelo e cadência novos), que nascem na AR dele. Nomes que são únicos no sistema
todo (código do papel, nome da equipe) são conferidos também nas outras ARs (`sem_filtro_de_ar`).

**Painel /master** (`app/rotas/master.py`, link "Painel master" só para o Admin Master; para os outros as rotas dão
404): lista das ARs com pessoas, leads, campanhas ativas, WhatsApps e administradores; **Entrar na AR** pede o motivo,
grava em `acessos_master` e põe a AR na sessão (`request.session["ar_entrada"]` → `isolamento.ligar`), com faixa no
topo e o botão "Sair da AR"; **Nova AR** (nome, apelido, CNPJ; avisa dos planos pagos); **Suspender/Reativar**
(pessoa de AR suspensa não entra: `seguranca.usuario_logado`); **Módulos de cada AR** (as chaves de
`autorizacao.MODULOS` estão em `banco.CHAVES_DA_AR` e em `CHAVES_SO_MASTER`: cada AR tem as suas, só o master muda; o
menu lê as da AR da pessoa em `web.tela`).

**Testes:** `testes/test_master.py` (o portão: administradora do Grupo Certy recebe 404 no /master e não muda papel,
modelo, cadência, categoria nem módulo da plataforma; o master entra com motivo, vê só a AR e sai; AR suspensa não
entra; módulos por AR; papel de mesmo nome em duas ARs). O teste do porteiro (`test_permissoes`) voltou a enxergar as
rotas (o FastAPI novo guarda os routers incluídos à parte).

**Feito em 14/11/2026:** administradores das ARs promovidos (Paulo Lucas e Jefferson na AR MS, Thamires no Grupo
Certy; só o Admin Master dá o papel de administrador, e ele pede o código do celular na entrada).

## Fase 4: filas justas e avisos por AR

**Fila justa** (`campanhas._revezar` / `_anotar_vez`, configuração `revezamento:<canal>`): as filas de e-mail e de
WhatsApp buscam os toques prontos com a AR de cada um e põem na frente os da AR que mandou há mais tempo (dentro da AR,
a ordem de sempre). A regra da Maria continua igual para a plataforma toda: um envio automático por vez por canal, com
3 a 4 minutos sorteados entre eles; só muda quem tem a vez.

**Uma AR parada não trava as outras:** limite do dia ou da hora de uma AR (e-mail) ou limite que não é do número
(WhatsApp) para só aquela AR naquela rodada (`ars_paradas`); só o computador do WhatsApp Leads fora do ar para tudo
(vale para todas). Os limites de e-mail contam só os envios da AR que está sendo tratada (`mensagens._contar_saida` com
`usar_config_da_ar`), então o volume de uma AR não gasta o limite da outra.

**Avisos por AR** (`alertas._admins`, `destinatarios(db, ar, todos)`, `_avisar(..., ar, todos)`): número desconectado
e pausa de contatos frios vão para o Admin Master (ou a lista `alertas_emails`) e para os administradores da AR dona do
número; computador do WhatsApp parado vai para todos os administradores (afeta todas as ARs); banco, backup, rotina,
relógio e e-mails da fila vão para a plataforma (Admin Master ou a lista). O "resolvido" segue o mesmo caminho.

**Testes:** `testes/test_fila_justa.py` (ordem da vez; limite de uma AR contando só os envios dela; o portão: AR MS no
limite e o e-mail do Grupo Certy sai na mesma rodada; quem recebe cada aviso).

**Decidido em 14/11/2026:** um servidor central **na nuvem** (máquina virtual) para todas as ARs, no lugar do computador da MS (que hoje liga o WhatsApp Leads e cai junto com ele). Guia e instalador prontos em `whatsapp-leads/docs/servidor-nuvem-passo-a-passo.md` e `whatsapp-leads/servidor/` (Hostinger VPS KVM 1, Brasil, Ubuntu 24.04, Pix ou boleto). Uma AR que quiser o próprio computador continua possível depois (a parte abaixo).
Com a resposta: tabela `instancias_whatsapp` (AR, token próprio, último sinal), a ponte (`/api/ponte/*`) identifica a
instância pelo token e só entrega os envios dos números da AR dela, e o estado (`wl_status`) passa a ser por instância.

## Fase 5: marca de cada AR

**Endereço (decidido em 14/11/2026):** um só para todas as ARs, o atual da Vercel (`URL_PUBLICA`). A tela de entrada
fica neutra (sem a MS) e a marca da AR (nome, logo, cores, site) aparece depois de entrar, pela AR da pessoa. A MS
fica igual às outras. O nome e o domínio da plataforma ficam para depois; subdomínio por AR e domínio próprio
(`tenant_dominios`) adiados.
**Por quê:** sem custo e sem nada para as ARs configurarem agora. Aceito: a marca só aparece depois de entrar e os
links dos e-mails (descadastro, avisos) levam o endereço da Vercel.
**Marca de cada AR** (`app/marca.py`, tabela `marcas_ar`, Configurações > Marca): nome nas mensagens, nome curto
nas telas, artigo ("a MS", "o Grupo Certy"), apresentação, site, domínio do e-mail da equipe, cores (principal,
detalhes, fundo), fonte (lista `FONTES`) e logo (PNG/JPG/WebP até 300 KB; SVG não, pode levar código). As telas
recebem `marca` (`web.tela`): `{{ marca.curto }}`, `{{ marca.frase('com') }}` ("com a MS", "com o Grupo Certy"),
`{{ marca.logo_url }}`, `{{ marca.css }}`. Antes de entrar e para o Admin Master fora das ARs: a plataforma
(`plataforma_nome`, "sua empresa" nas frases). A marca fica na memória 5 minutos (tráfego do Supabase); o logo, no
navegador, por uma semana (o endereço muda com a versão).
**Mensagens:** os modelos continuam escritos com o nome da MS e `marca.aplicar` troca pela empresa de quem envia: a
"empresa que eu represento" (Minha conta) ou, sem ela, a marca da AR (Admin Master: a AR MS). O que é só da MS
(validação em Recife, a arte do aviso de vencimento do site da MS, o WhatsApp do convite) sai para as outras.
`banco.CHAVES_DA_MARCA` (nome, link e texto do programa de parceria, WhatsApp do convite): sem valor próprio da AR, vêm
da marca dela (`marca.config_da_marca`), nunca da plataforma; os textos da MS que eram da plataforma passaram para a
AR MS (`marca.garantir`, uma vez por publicação, que também cria a marca da AR MS com o logo de sempre e troca o papel
"Funcionário MS" por "Funcionário"). E-mail da equipe: o domínio da marca da AR (`contas_email.dominio_da_equipe` e
`dominio_ok`, também na hora de enviar). Alertas, PDF dos relatórios, autenticador (2 etapas) e prompts da IA: neutros
ou com a marca de quem pede.
**O que é da plataforma** (e-mail principal, chave da CNPJá, base da Receita, listas importadas, backup e relógio):
só o Admin Master vê e muda (`admin._so_da_plataforma`).
**Teste do portão:** `testes/test_marca_ar.py` (uma administradora do Grupo Certy percorre todas as telas, as abas das
Configurações e os modelos e cadências da plataforma sem achar a MS; as mensagens dela saem com a marca dela).
Ensaio no Postgres de teste (14/11/2026): marca da AR MS criada com o logo, textos da MS só nela, marca do Grupo Certy
gravada; dados das ARs iguais antes e depois (MS 189.492 linhas, Grupo Certy 1.234).

**Para mudar depois:** a Vercel aceita até 50 domínios por projeto, também no Hobby (subdomínio = registro CNAME no DNS
do dono do domínio; vários de uma vez = `*.dominio` com a validação delegada em `_acme-challenge`). Um `.com.br` custa
R$ 40 por ano no Registro.br (Pix ou boleto).

## Fase 6: auditoria e LGPD

**Quem agiu como quem** (`isolamento._ar_nas_novas`): o que o Admin Master faz DENTRO de uma AR (depois de "Entrar na
AR") fica no histórico (`logs`) daquela AR, com o nome dele e marcado "[Admin Master dentro da AR]"; os
administradores da AR veem em Configurações > Logs. Fora de uma AR, o histórico dele é da plataforma.
As entradas dele nas ARs (motivo, início e fim) ficam em `acessos_master` (painel /master).

**Exportar uma AR** (`exportar_ar.py`/`.bat`, `ars.exportar`): um SQLite só com as linhas da AR (as tabelas dela, a
própria AR, as configurações e as entradas do Admin Master nela), fechado com uma senha digitada (mínimo 10
caracteres; a mesma criptografia do backup) em `dados/exportacoes/ar_<apelido>_<data>.db.cripto`. Nada fica aberto no
computador. A senha vai para a AR por outro caminho.

**Apagar uma AR** (`apagar_ar.py`/`.bat`, `ars.apagar`): só com a exportação do mesmo dia, digitando o apelido e SIM;
a AR MS nunca (`PROTEGIDAS`). Apaga só linhas com o `tenant_id` dela (desfaz antes as ligações em ciclo e apaga leads,
buscas, parceiros e pessoas por último) e a própria AR; registra no histórico da plataforma.

**Testes e ensaio:** `testes/test_lgpd_ar.py` (exporta só a AR; apaga sem mudar as outras nem a plataforma; travas do
script; histórico do master dentro da AR). Ensaio no Postgres de teste (14/11/2026): AR de ensaio exportada e apagada
(6 linhas); AR MS (189.492 linhas) e Grupo Certy (1.234) iguais antes e depois.

**Decidido em 14/11/2026:** planos e cobrança só depois da validação da plataforma ("por enquanto não vamos pensar em
nada de cobrança ou valores"); os limites de hoje (por número, por dia e por AR) continuam valendo.

**Outras decisões de 14/11/2026:** a mesma empresa pode receber mensagens de duas ARs (cada AR é independente; a
reserva de 60 dias continua valendo entre as pessoas de uma mesma AR; o nome escolhido de um contato na tela
Conversas é um por telefone: a segunda AR não troca nem vê o da primeira, `conversas._de_outra_ar`); a chave da
CNPJá continua da plataforma (sem preferência; rever com os planos); o caio barreto continua administrador da AR MS.
