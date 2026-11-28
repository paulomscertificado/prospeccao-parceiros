# Design system

Estética de SaaS B2B: limpa, corporativa, com as cores da identidade MS (azul-marinho e verde da tabela de preços).
Tudo em `app/static/estilo.css`; cores como variáveis no `:root`.

**White label (Fase 5):** essas cores são o **padrão** (a AR MS e a plataforma). A marca de cada AR (tabela
`marcas_ar`, Configurações > Marca) troca as variáveis por um `<style>:root{...}</style>` em `base.html`, montado por
`marca.tema`: `--azul` e família = cor principal escurecida até o branco ter contraste 4,5 (WCAG); `--verde-marca` = cor
dos detalhes como veio; `--cta` (botões de ação e escolhas marcadas) = cor dos detalhes escurecida; `--fundo`, `--fonte`
(lista `marca.FONTES`, do Google Fonts) e as do menu (`--menu-texto`, `--menu-rotulo`, `--menu-ativo`, `--menu-sub`,
`--menu-destaque` = o traço da tela aberta: a cor dos detalhes ou branco quando ela tem contraste menor que 3 com a
segunda barra; `--sobre-destaque` = a letra em cima da cor dos detalhes, escura ou branca). O verde de
"deu certo" (selos OK, avisos de sucesso) não muda. Sem marca própria = as cores de sempre. Logo da AR em
`/marca/logo/<ar>/<assinatura>?v=<versão>`; sem logo, o nome curto em texto. A tela de entrada é neutra.
Logo no menu (`templates/_marca_menu.html`): logo, traço e "Parceiros / Prospecção B2B" lado a lado; o logo largo
(largura/altura >= 1,8, ex.: Grupo Certy, `.marca-larga`) fica com até 30 px de altura e 180 px de largura. O logo vai
sobre a cor do menu: branco e com fundo transparente (Configurações > Marca > "Tirar o fundo liso do logo"). A prévia
"Como fica" de Configurações > Marca é o menu de cima em miniatura (`.previa-cima`).

## Menu na barra de cima (27/11/2026)

Pedido da Maria: "altere a visualização do sistema para como está mostrando as imagens". Vale para todas as ARs, com
as cores, a fonte e o logo de cada uma; nenhuma cor de marca fica escrita no CSS. O menu lateral saiu.

- `templates/_menu_cima.html`, incluído por `base.html`. Grupos e telas vêm de `web.menu_em_grupos` (`GRUPOS_DO_MENU`;
  dentro de cada grupo, as telas na ordem de `MENU_EQUIPE`/`MENU_PARCEIRO`, filtradas por permissão e módulo como antes;
  tela fora dos grupos vai para "Outros"). A tela marcada é `web.item_marcado`: mesmo endereço, o começo mais longo ou
  `TELA_DE_OUTRO_ITEM` (WhatsApp, E-mail, Permissões, Categorias e Base de conhecimento marcam Configurações para quem
  as vê; Visuais marca IA SDR; Templates marca Cadências). A rota pode trocar o `caminho` (a campanha de renovação marca
  Renovação).
- **Primeira barra** (`--azul`): logo, grupos (o aberto numa pílula branca; clicar abre a primeira tela do grupo) com o
  número vermelho do grupo, que soma os números das telas dele (`data-soma`), e à direita **Painel master** (só o Admin
  Master), **Avisos** (`#link-avisos`) e a pessoa (`<details class="cima-pessoa">`: Minha conta, Sair, som e avisos na
  tela; fecha ao clicar fora ou com Esc, `static/app.js`).
- **Segunda barra** (`--azul-escuro`): as telas do grupo aberto, com o traço `--menu-destaque` na atual. Só aparece com
  2 telas ou mais no grupo: Visão geral e Configurações (que têm o menu da esquerda) e as telas fora dos grupos (Minha
  conta, Avisos, Painel master) ficam sem ela.
- Os números vermelhos das telas têm os ids de antes (`#contador-conversas`, `#contador-oficial`,
  `#contador-oportunidades`); o `static/notificacoes.js` atualiza esses e a soma de cada grupo e do ☰ (`somarGrupos`).
- Tela menor: até 1540 px some o rótulo ao lado do logo largo (1420 px para os outros logos); até 1300 px saem os
  ícones dos grupos; até 1180 px some o nome da pessoa (fica a inicial).
- Até 980 px (celular e tablet): o `.topo-celular` (☰ com a soma das novidades, logo e "Parceiros") abre o menu como
  gaveta (`.menu.aberto`), com a pessoa em cima e todos os grupos e telas empilhados.
- Conteúdo com até 1360 px de largura, centralizado. Cartões e indicadores com cantos de 14 px, botões de 10 px.

## Cores

Identidade do **Portfólio MS 2026** (`Portfolio MS 2026.pdf`): azul-marinho, verde e branco; logotipo branco em
`app/static/logo-ms.png` (tirado do próprio portfólio), usado no menu, no celular, no login e como ícone da aba.

| Variável | Valor | Uso |
|---|---|---|
| `--azul` / `--azul-escuro` | #0D3B66 / #0A2F57 | Marca, as duas barras do menu de cima, login, botão principal, KPI de destaque |
| `--verde-marca` | #3CC77A | Detalhes como no portfólio: traço sob o título, ponto das etiquetas, traço da tela aberta no menu, inicial da pessoa |
| `--verde` | #1F9D5C | Botões verdes e textos sobre branco (o verde da marca é claro demais para texto branco) |
| `--roxo` | #1E5F96 | Tudo que é IA (faixa IA SDR, botão IA, "Prioridade máxima"): azul médio da marca, sem roxo |
| `--alerta` / `--erro` | #b7791f / #c0392b | Avisos, atrasos, opt-out, ações destrutivas |
| `--fundo` / `--cartao` / `--borda` | #F3F6FA / #fff / #e1e6ed | Superfícies |

## Tipografia

Inter (400–800) para textos e títulos (títulos em 800, letras juntas, com traço verde de 40 px embaixo) e
JetBrains Mono em MAIÚSCULAS espaçadas para rótulos: cabeçalho de tabelas, rótulo dos KPIs e `.etiqueta`
(pílula com ponto verde, como "• PORTFÓLIO INSTITUCIONAL"). Carregadas do Google Fonts em `base.html`.

Potencial do lead: **Prioridade máxima** roxo · **Alto** verde · **Médio** âmbar · **Baixo** cinza (`.selo-*`).

## Componentes

`.cartao` (bloco branco) · `.kpi` (indicador; `.destaque` = azul) · `.faixa` (barra azul de ação principal) ·
`.btn`, `.btn-primario`, `.btn-verde`, `.btn-ia`, `.btn-perigo`, `.btn-pequeno` · `.selo` · `.abas` ·
`.filtros` · `.campos` (grade de formulário) · `.kanban`/`.coluna`/`.card` · `.tempo` (linha do tempo) ·
`.mensagem` (texto pronto para copiar) · `.aviso-ok|erro|alerta|info`.

Responsivo: até 980 px o menu de cima vira gaveta (botão ☰); abaixo de 760 px as grades viram 1–2 colunas.

## Tom de voz

- Telas: frases curtas, sem jargão, dizendo **o que fazer** ("Informe a cidade e escolha o estado.").
- Erros sempre com a solução ("...Espere 15 minutos e tente de novo.").
- Mensagens de prospecção: cordiais, pessoais, curtas, **uma pergunta no final**, saída educada
  ("se não fizer sentido, é só me avisar"). Nada de CAIXA ALTA, promessas de ganho ou excesso de emojis.
