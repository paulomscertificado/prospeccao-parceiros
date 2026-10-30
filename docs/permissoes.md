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
| Alcance | coluna `escopo` | `tudo`, `equipe` (dono na mesma equipe; sem equipe = próprios) ou `proprios` — só nas permissões marcadas `com_escopo` |
| Exceção | `excecoes_permissao` | PERMITIR ou NEGAR para uma pessoa, com alcance, prazo (`ate`) e motivo |
| Módulo | `configuracoes` (`mostrar_vendas`, `mostrar_agenda`, `modulo_*`) | Liga/desliga partes inteiras para todos |

**Ordem de decisão:** módulo desligado → NEGAR do usuário → PERMITIR do usuário → papel → nega.

Regras fixas de segurança:
- O papel **Administrador** tem sempre tudo e não é editável; `permissoes.gerenciar` não aceita NEGAR (ninguém tranca
  o sistema).
- **Parceiro** só recebe permissões do portal; a equipe nunca recebe `portal.usar` (vale mesmo se alguém gravar uma
  exceção direto no banco).
- Quem tiver `configuracoes.alterar`, `usuarios.gerenciar` ou `permissoes.gerenciar` (pelo papel ou exceção) precisa da
  verificação em 2 etapas (`dois_fatores.precisa`).
- `usuarios.perfil` continua sendo o **tipo base** (decide portal × equipe e 2FA); `papel_id` só é usado por papéis
  criados na tela.

## Padrões (migração sem ninguém ganhar nem perder acesso)

O campo `padrao` de cada permissão reproduz o acesso de antes: `A` = só administrador, `G` = administrador e gestor,
`F` = + Funcionário MS, `E` = toda a equipe, `P` = parceiro. Administrador e gestor recebem `tudo`; funcionário e
vendedor recebem `proprios` nas permissões com alcance. `autorizacao.preparar` (chamado por `banco.criar_tabelas`)
cria os papéis que faltam e, para cada permissão **nova** do catálogo (ainda fora de `permissoes_conhecidas`), dá o
padrão do perfil base — nunca desfaz o que o administrador escolheu. O catálogo entra na versão do esquema, então a
nuvem prepara o banco de novo quando uma permissão nova aparece.

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
`whatsapp.gerenciar_todos`/`whatsapp.compartilhar_todos`.

## Furos fechados com esta mudança

- `POST /clientes/{id}`: editava cliente de outro vendedor e ligava a qualquer parceiro.
- `POST /vencimentos/{id}/status`: mudava a situação de qualquer certificado.
- `GET /exportar/vencimentos.*`: exportava todos os certificados para qualquer perfil.
- `POST /vendas/nova`: aceitava cliente, parceiro e certificado de outro vendedor; a tela listava os clientes de todos.
- `POST /leads/{id}/agendar`: marcava reunião em lead de outro vendedor.
- Módulos Vendas e Agenda desligados só sumiam do menu; agora a rota também fica bloqueada.

## Tela (menu Permissões, `permissoes.gerenciar`)

- `GET /permissoes?aba=papeis&papel=<codigo>` · `POST /permissoes/papel/{id}` (campos `p__<permissao>` = alcance ou
  `tudo`) · `POST /permissoes/papel/novo` (`nome`, `copiar_de`) · `POST /permissoes/papel/{id}/excluir`
- `GET /permissoes?aba=usuarios&pessoa=<id>` (exceções + acesso real) · `POST /permissoes/excecao` · `POST
  /permissoes/excecao/{id}/remover`
- `GET /permissoes?aba=equipes` · `POST /permissoes/equipes/{id}` (0 = nova; `excluir=1`)
- `GET /permissoes?aba=modulos` · `POST /permissoes/modulos` (`m__<modulo>=on`)

Toda gravação vai para o Registro de atividades (`alterou_papel`, `criou_papel`, `excecao_permissao`, ...).
