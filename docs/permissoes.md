# Permissões em camadas

Código: `app/autorizacao.py` (regras), `app/rotas/permissoes.py` + `templates/permissoes.html` (tela), testes em
`testes/test_permissoes.py`. Manual da usuária: `LEIAME.md` > Perfis de acesso > Permissões.

## Por que este desenho

A MS é **uma empresa só**. O modelo Plataforma > White Label > Tenant > Unidade **não** foi criado: deixaria cada
consulta e cada tela mais complicada sem ganho hoje. O que existe é a camada de **Equipes** (unidades), opcional.
Como **todo** acesso passa por um ponto só (`autorizacao.pode`/`filtrar`/`exige`), acrescentar empresas no futuro é
uma mudança localizada: uma coluna `empresa_id` nos registros e mais uma condição em `filtrar` e `dono_de`.

## Camadas

| Camada | Onde fica | O que faz |
|---|---|---|
| Papel | `papeis` + `permissoes_papel` | Conjunto de permissões, cada uma com um alcance. 5 papéis do sistema (código = perfil) + papéis criados na tela (código `p_...`, copiados de gestor/funcionário/vendedor) |
| Permissão | `autorizacao.CATALOGO` | Ação no padrão `recurso.acao` (ex.: `leads.exportar`, `usuarios.gerenciar`) |
| Alcance | coluna `escopo` | `tudo`, `abaixo` (a pessoa e quem tem papel de nível menor, na mesma AR), `equipe` (dono na mesma equipe; sem equipe = próprios) ou `proprios` — só nas permissões marcadas `com_escopo` |
| Exceção | `excecoes_permissao` | PERMITIR ou NEGAR para uma pessoa, com alcance, prazo (`ate`) e motivo |
| Módulo | `configuracoes_ar` da AR; sem valor próprio, `configuracoes` da plataforma (`mostrar_vendas`, `mostrar_agenda`, `modulo_*`) | Liga/desliga partes inteiras de cada AR (só o Admin Master muda; ver "Módulos de cada AR") |

**Ordem de decisão:** módulo desligado → NEGAR do usuário → PERMITIR do usuário → papel → nega.

Regras fixas de segurança:
- **Admin master** (`Usuario.master`; pedido da Maria em 13/11/2026, depois de validar a escalada de privilégio):
  quem fez o primeiro acesso (na MS, o Paulo Marinho; `autorizacao.garantir_master` marca o administrador ativo mais
  antigo se faltar). Só ele cria ou promove administradores e dá papéis/permissões de administração (`SENSIVEIS`);
  o cadastro, a senha, o 2FA e as permissões dele só ele altera; os de outro administrador (ou de quem tem poder de
  administração), só o master (`motivo_para_nao_alterar`, `motivo_para_nao_dar_papel`). Ninguém muda o próprio papel,
  as próprias exceções, o próprio papel em Permissões, a própria equipe nem se desativa.
- Compartilhar WhatsApp/e-mail de outra pessoa (`motivo_para_nao_compartilhar`): quem não é o dono (nem o master)
  não se inclui, não libera para toda a equipe e não mexe nos de administradores.
- `testes/test_escalada_de_privilegio.py`: gestor, funcionário, vendedor e parceiro tentam virar admin (403 em tudo);
  admin comum tenta tomar a conta do master; gestor com "Criar e editar usuários" tenta se promover; gestor tenta se
  compartilhar o WhatsApp de um admin.
- O papel **Administrador** tem sempre tudo e não é editável; `permissoes.gerenciar` não aceita NEGAR (ninguém tranca
  o sistema).
- **Parceiro** só recebe permissões do portal; a equipe nunca recebe `portal.usar` (vale mesmo se alguém gravar uma
  exceção direto no banco).
- Quem tiver `configuracoes.alterar`, `usuarios.gerenciar` ou `permissoes.gerenciar` (pelo papel ou exceção) precisa da
  verificação em 2 etapas (`dois_fatores.precisa`).
- `usuarios.perfil` continua sendo o **tipo base** (decide portal × equipe e 2FA); `papel_id` só é usado por papéis
  criados na tela.

- `oportunidades.ver` não tem alcance desde 16/11/2026 (pedido da Maria: "deixe aberto para toda equipe ver"): quem
  tem a permissão vê e atende todas as oportunidades da AR. A ficha do lead continua no alcance de `leads.ver` e o
  "Assumir lead" da ficha no de `leads.editar`.

## Módulos de cada AR

Os módulos (`autorizacao.MODULOS`: Vendas, Agenda, IA SDR, Prospecção, Assertiva, Conversas, IA Comercial, Portal e
E-mail em HTML) ligam e desligam partes inteiras: desligado, as permissões do módulo somem (o menu e as rotas fecham).
Quem abre uma tela de módulo desligado lê quem liga e onde (`mensagem_sem_permissao`: "Quem liga é o admin master, em
Painel master > Módulos de cada AR"; fora de uma AR, "em Permissões > Módulos (padrão da plataforma)"; até 19/11/2026
mandava todos para Permissões > Módulos, aba que só o master vê). Cada AR tem os seus e só o Admin Master muda: em
**Painel master > Módulos de cada AR** (`POST /master/ar/{id}/modulos`) ou em Permissões > Módulos estando dentro da
AR (fora de uma AR, essa tela muda o padrão da plataforma). A AR sem valor próprio usa o da plataforma; sem nenhum, o
de `config.CONFIG_PADRAO` (Vendas, Agenda e E-mail em HTML começam desligados; os outros, ligados).

**Módulo novo:** entrada em `autorizacao.MODULOS`, a chave em `banco.CHAVES_DA_AR` **e** em `banco.CHAVES_SO_MASTER`
e, se começar desligado, o "0" em `config.CONFIG_PADRAO`. Fora das duas listas, o Painel master grava na plataforma e o
que o master faz numa AR vale para todas: aconteceu com a Assertiva até 19/11/2026 (no banco de produção nenhuma AR
nem a plataforma tinham valor gravado, então não houve nada a limpar). Teste: `testes/test_modulos_por_ar.py` (toda
chave de módulo nas duas listas; desligar a Assertiva do Grupo Certy não muda a MS nem a plataforma, o painel mostra
cada AR com o seu estado, e o menu "Consulta Assertiva" e a permissão `assertiva.consultar` somem só no Grupo Certy,
com o aviso apontando o Painel master).

## Hierarquia (17/11/2026)

Pedido da Maria: "quero que quem for acima veja as coisas de quem está abaixo". O nível vem do tipo base do papel
(`autorizacao.NIVEIS`: administrador 4 > gestor 3 > funcionário 2 > vendedor 1 > parceiro 0; papel criado na tela = o
nível do papel de que foi copiado; o admin master fica acima de todos). O alcance `abaixo` ("Eu e quem está abaixo")
alcança os registros da própria pessoa e os de quem tem nível menor, na mesma AR, inclusive de quem já saiu
(`autorizacao.ids_abaixo`). Colegas do mesmo nível não se veem; quem está abaixo não vê o de quem está acima.

| Papel | Alcance padrão nas permissões com alcance |
|---|---|
| Administrador | `tudo` (vê tudo da AR) |
| Gestor | `abaixo` em todas: vê e cuida do que é dele e de quem está abaixo (não do que é do administrador) |
| Funcionário | `abaixo` nas de ver/exportar (`autorizacao.so_ver`), `proprios` nas de mexer (editar, enviar, aprovar) |
| Vendedor | `proprios` |

`autorizacao._aplicar_hierarquia` trocou uma vez só (config `permissoes_hierarquia`) os papéis Gestor e Funcionário
do sistema que ainda estavam no padrão antigo (`tudo` e `proprios`); o que o administrador tinha mudado à mão ficou.
Os filtros "de quem" das telas (Campanhas, Minha fila, Leads, Pipeline, Agenda, Dashboard) aparecem para quem alcança
outras pessoas (`autorizacao.escolhe_de_quem`) e listam só elas (`autorizacao.pessoas_visiveis`).

**Renovação e Empresas novas** valem para a AR toda (planilha da certificadora, busca paga na CNPJá). As Empresas
novas (tela, textos, "Buscar agora") exigem `campanhas.configurar`. A **Renovação tem grupo próprio** desde
26/11/2026 (pedido da Maria: "o módulo de renovação não está aparecendo" nas Exceções por pessoa; antes vinha
dentro de `campanhas.configurar`, e dar a Renovação a alguém dava também a busca paga): `renovacao.ver` abre a tela
e `renovacao.gerenciar` mexe nela (planilha, "Montar", teste, textos, configurações e a situação dos
certificados). As três são de administrador e gestor por padrão. A separação (`autorizacao._separar_renovacao`, uma
vez só, config `permissoes_renovacao_separada`) deu as duas novas a cada papel que tinha `campanhas.configurar`, com
o mesmo alcance, tirou dos que não tinham e copiou as exceções: ninguém ganhou nem perdeu acesso. Teste:
`testes/test_renovacao_permissoes.py`. As campanhas dessas telas seguem a hierarquia (`campanhas.ver`) e o
APROVAR só aparece para quem pode aprovar aquela campanha. Quem não configura vê as campanhas de renovação que alcança na
lista de Campanhas. Teste: `testes/test_hierarquia.py`.

## Padrões (migração sem ninguém ganhar nem perder acesso)

O campo `padrao` de cada permissão reproduz o acesso de antes: `A` = só administrador, `G` = administrador e gestor,
`F` = + Funcionário MS, `E` = toda a equipe, `P` = parceiro. Administrador recebe `tudo`; desde a hierarquia de
17/11/2026 o gestor recebe `abaixo`, o funcionário `abaixo` nas de ver e `proprios` nas de mexer, e o vendedor
`proprios` nas permissões com alcance. `autorizacao.preparar` (chamado por `banco.criar_tabelas`)
cria os papéis que faltam e, para cada permissão **nova** do catálogo (ainda fora de `permissoes_conhecidas`), dá o
padrão do perfil base — nunca desfaz o que o administrador escolheu. O catálogo entra na versão do esquema, então a
nuvem prepara o banco de novo quando uma permissão nova aparece. Mudar o `padrao` de uma permissão que os papéis já
conhecem não chega a eles sozinho: precisa de um ajuste de uma vez só, guardado por uma configuração, como
`_aplicar_hierarquia` (`permissoes_hierarquia`, 17/11/2026) e `_liberar_apagar_conversa`
(`permissoes_apagar_conversa_todos`, 25/11/2026: "Apagar conversa" de administrador e gestor para a equipe toda).

## Como proteger uma rota nova

1. Acrescente a permissão em `CATALOGO` (grupo, nome, `com_escopo`, `modulo`, `padrao`).
2. Na rota: `usuario: Usuario = Depends(exige("recurso.acao"))`.
3. Registro com dono: `autorizacao.garantir(usuario, "recurso.acao", obj)` (404 se não alcança). Novo tipo de registro:
   ensine o dono em `dono_de`.
4. Listas, relatórios e exportações: `autorizacao.filtrar(consulta, usuario, "recurso.acao", Modelo.coluna_dono)`.
5. Botões nas telas: `{% if pode('recurso.acao') %}` (e `ve_tudo_em('...')` para filtros "de todos"). É só conforto: a
   rota confere de novo.
6. Menu: `web.PERMISSAO_DO_MENU`.
7. O teste `test_toda_rota_da_equipe_confere_permissao` falha se uma rota ficar sem porteiro.

## Donos de cada registro (`dono_de`)

| Registro | Dono |
|---|---|
| Lead, Parceiro, Venda | `vendedor_id` |
| Cliente, Certificado | vendedor do parceiro (sem parceiro = sem dono; vencimentos sem parceiro aparecem para todos, como antes) |
| Campanha, Busca | `usuario_id` |
| Tarefa | `usuario_id` ou o vendedor do lead |
| Oportunidade | vendedor do lead (sem vendedor = qualquer um da equipe pode assumir, como antes) |

Os números do Dashboard, relatórios e IA Comercial usam o alcance de `painel.ver` (`metricas.NUMEROS`). E-mail e
WhatsApp continuam com as regras de dono/compartilhamento de `contas_email.py` e `conexoes.py`; o "gerenciar de
todos" e o "compartilhar de todos" viraram `email.gerenciar_todas`/`email.compartilhar_todas` e
`whatsapp.gerenciar_todos`/`whatsapp.compartilhar_todos`. `campanhas.whatsapp_sozinho` (só admin) liga o WhatsApp
que sai sozinho depois da aprovação numa campanha de parceiros. `email.outro_dominio` (admin e gestor) libera cadastrar o
próprio e-mail em outro domínio/servidor (ver `docs/configuracao.md`); é conferida a cada envio.

## Furos fechados com esta mudança

- `POST /clientes/{id}`: editava cliente de outro vendedor e ligava a qualquer parceiro.
- `POST /vencimentos/{id}/status`: mudava a situação de qualquer certificado.
- `GET /exportar/vencimentos.*`: exportava todos os certificados para qualquer perfil.
- `POST /vendas/nova`: aceitava cliente, parceiro e certificado de outro vendedor; a tela listava os clientes de todos.
- `POST /leads/{id}/agendar`: marcava reunião em lead de outro vendedor.
- Módulos Vendas e Agenda desligados só sumiam do menu; agora a rota também fica bloqueada.

## Tela (Configurações > Pessoas e acesso, `permissoes.gerenciar`)

Desde 15/11/2026 as telas de Permissões ficam dentro das Configurações (moldura `templates/_configuracoes.html`, menu de
seções à esquerda; cada rota passa `secao`). No menu lateral do sistema, "Permissões", "WhatsApp" e "E-mail" só aparecem
para quem não vê as Configurações (`web.DENTRO_DAS_CONFIGURACOES`); para essa pessoa a moldura mostra só a tela, sem o
menu das Configurações (`self.config()` em `_configuracoes.html`). Papéis: grupos de permissões que abrem e fecham (`.grupo-permissao`). Exceções: a lista de
pessoas separada por marca (`permissoes._pessoas_por_ar`). Configurações > Usuários: um quadro por marca
(`admin._grupos_de_usuarios`); a pessoa nova criada pelo Admin Master fora das ARs vai para a marca do quadro (`ar`),
e equipe, parceiro e papel precisam ser da mesma marca (`salvar_usuario`). Teste: `testes/test_usuarios_por_marca.py`.

- `GET /permissoes?aba=papeis&papel=<codigo>` · `POST /permissoes/papel/{id}` (campos `p__<permissao>` = alcance ou
  `tudo`) · `POST /permissoes/papel/novo` (`nome`, `copiar_de`) · `POST /permissoes/papel/{id}/excluir`
- `GET /permissoes?aba=usuarios&pessoa=<id>` (exceções + acesso real) · `POST /permissoes/excecao` · `POST
  /permissoes/excecao/{id}/remover`
- `GET /permissoes?aba=equipes` · `POST /permissoes/equipes/{id}` (0 = nova; `excluir=1`)
- `GET /permissoes?aba=modulos` · `POST /permissoes/modulos` (`m__<modulo>=on`)

Toda gravação vai para o Registro de atividades (`alterou_papel`, `criou_papel`, `excecao_permissao`, ...).
