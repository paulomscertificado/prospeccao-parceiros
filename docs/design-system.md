# Design system

Estética de SaaS B2B: limpa, corporativa, com as cores da identidade MS (azul-marinho e verde da tabela de preços).
Tudo em `app/static/estilo.css`; cores como variáveis no `:root`.

## Cores

Identidade do **Portfólio MS 2026** (`Portfolio MS 2026.pdf`): azul-marinho, verde e branco; logotipo branco em
`app/static/logo-ms.png` (tirado do próprio portfólio), usado no menu, no celular, no login e como ícone da aba.

| Variável | Valor | Uso |
|---|---|---|
| `--azul` / `--azul-escuro` | #0D3B66 / #0A2F57 | Marca, menu lateral (degradê), login, botão principal, KPI de destaque |
| `--verde-marca` | #3CC77A | Detalhes como no portfólio: traço sob o título, ponto das etiquetas, item ativo do menu |
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

Responsivo: abaixo de 760 px o menu vira gaveta (botão ☰) e as grades viram 1–2 colunas.

## Tom de voz

- Telas: frases curtas, sem jargão, dizendo **o que fazer** ("Informe a cidade e escolha o estado.").
- Erros sempre com a solução ("...Espere 15 minutos e tente de novo.").
- Mensagens de prospecção: cordiais, pessoais, curtas, **uma pergunta no final**, saída educada
  ("se não fizer sentido, é só me avisar"). Nada de CAIXA ALTA, promessas de ganho ou excesso de emojis.
