# Design system

Estética de SaaS B2B: limpa, corporativa, com as cores da identidade MS (azul-marinho e verde da tabela de preços).
Tudo em `app/static/estilo.css`; cores como variáveis no `:root`.

## Cores

| Variável | Valor | Uso |
|---|---|---|
| `--azul` / `--azul-escuro` | #0f3a64 / #0a2a49 | Marca, menu lateral, botão principal, faixa de destaque |
| `--verde` | #1fa463 | Ações positivas (WhatsApp, converter, encontrar), sucesso |
| `--roxo` | #6b46c1 | Tudo que é IA; selo "Prioridade máxima" |
| `--alerta` / `--erro` | #b7791f / #c0392b | Avisos, atrasos, opt-out, ações destrutivas |
| `--fundo` / `--cartao` / `--borda` | #f4f6f9 / #fff / #e1e6ed | Superfícies |

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
