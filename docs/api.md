# Rotas e API

Todas as rotas exigem login (exceto `/login`, `/primeiro-acesso`, `/api/saude` e os webhooks).
Todo `POST` exige o token CSRF (campo `csrf` no formulário ou cabeçalho `X-CSRF-Token`).
Perfis: A = administrador, G = gestor, V = vendedor, P = parceiro.

## Telas

| Rota | Perfis | O que faz |
|---|---|---|
| `GET /` | A G V | Dashboard (`?periodo=7d|30d|90d|12m|tudo&vendedor=ID`) |
| `GET /prospeccao` | A G V | Encontrar novos parceiros (`?pedido=texto livre` preenche o formulário) |
| `POST /prospeccao/buscar` | A G V | Inicia a busca em segundo plano |
| `GET /prospeccao/busca/{id}` | A G V | Resultado ordenado por score + iniciar campanha |
| `GET /leads` | A G V | Lista com filtros e ações em lote |
| `POST /leads/acoes` | A G V | Lote: `acao=cadencia|vendedor|status|recalcular` |
| `GET /leads/pipeline` | A G V | Kanban |
| `GET/POST /leads/novo` | A G V | Cadastro (com deduplicação) |
| `GET/POST /leads/{id}` | A G V | Ficha / salvar |
| `POST /leads/{id}/qualificar` | A G V | Score + abordagem (IA ou regras) |
| `POST /leads/{id}/proximo-passo` | A G V | Próximo melhor passo |
| `POST /leads/{id}/enriquecer` | A G V | Dados públicos do site e do CNPJ |
| `POST /leads/{id}/contato` · `/resposta` · `/nota` · `/tarefa` | A G V | Registros |
| `POST /leads/{id}/converter` | A G V | Converte em parceiro |
| `POST /leads/{id}/opt-out` · `/excluir` | A G V · A G | LGPD |
| `POST /leads/{id}/enviar` | A G V | Envia 1 mensagem pela API oficial (WhatsApp/SMTP) |
| `GET/POST /leads/importar` | A G V | Importação CSV/Excel |
| `GET /cadencias` · `/cadencias/{id}` · `/templates/{id}` | A G V (edição A G) | Cadências, templates, campanhas |
| `GET /agenda` | A G V | Agenda (`?ver=hoje|semana|proximas|feitas&canal=&tipo=`) |
| `POST /agenda/{id}/{acao}` | A G V | `feita`, `respondeu`, `pular`, `remarcar`, `invalido`, `opt-out` |
| `GET/POST /parceiros/{id}` | A G V | Ficha do parceiro (0 = novo) |
| `GET /clientes` · `POST /clientes/{id}` | A G V | Clientes |
| `GET /vendas` · `POST /vendas/nova` | A G V | Vendas (`?renovar=ID_CERTIFICADO`) |
| `GET /comissoes` · `POST /comissoes/pagar` · `POST /produtos/{id}` | A G V · A · A | Comissões, calculadora, produtos |
| `GET /vencimentos` · `POST /vencimentos/importar` | A G V · A G | Vencimentos |
| `GET /relatorios` · `/relatorios/exportar.{csv|xlsx|pdf}` | A G V | Relatórios |
| `GET /exportar/{tipo}.{csv|xlsx|pdf}` | A G V | tipo = leads, parceiros, clientes, vendas, comissoes, vencimentos |
| `GET/POST /ia` | A G V | IA Comercial (`?pergunta=codigo` para as perguntas prontas) |
| `GET /configuracoes` e `POST /configuracoes/...` | A | Geral, score, usuários, integrações, base da Receita, LGPD, logs |
| `GET /portal`, `/portal/indicar`, `/portal/clientes`, `/portal/vencimentos` | P | Portal do parceiro |
| `GET /oportunidades` · `POST /oportunidades/{id}/descartar` | A G V | Novas oportunidades (handoff) |
| `POST /leads/{id}/assumir` | A G V | Assumir lead: para toda automação |
| `GET/POST /leads/{id}/agendar` | A G V | Horários livres reais e marcação de reunião |
| `POST /leads/{id}/pesquisar` · `/abordagem-sdr` | A G V | Perfil do parceiro e mensagens SDR (4 ângulos) |
| `GET /campanhas` · `GET/POST /campanhas/nova` · `GET /campanhas/{id}` | A G V | Campanhas da IA SDR (`?pedido=` texto livre) |
| `POST /campanhas/{id}/{acao}` | A G (aprovar/cancelar) · A G V | `aprovar`, `cancelar`, `pausar`, `retomar`, `editar-mensagem`, `remover-lead` |
| `GET /inteligencia` · `POST /inteligencia/sugerir-categorias` | A G V · A G | Inteligência de Prospecção |
| `GET /categorias` · `POST /categorias/{id}` | A G · A | Categorias de parceiros |
| `GET /conhecimento` · `POST /conhecimento/{id}` | A G V · A G | Base de conhecimento |
| `GET /notificacoes` | A G V | Avisos |

Vendedor só vê os próprios leads e tarefas (404 nos dos outros).

## API JSON

| Rota | Corpo | Resposta |
|---|---|---|
| `POST /api/leads/{id}/status` | `{"status": "Interessado", "motivo": ""}` | `{"ok": true, "status", "score", "potencial"}` |
| `POST /api/mensagens/registrar` | `{"lead_id", "canal", "corpo", "assunto", "tarefa_id"}` | `{"ok": true, "aviso": ""}` ou 409 se opt-out |
| `GET /api/saude` | — | `{"ok": true}` |

## Webhook do WhatsApp Cloud API

- `GET /api/webhooks/whatsapp` — verificação (`hub.mode`, `hub.verify_token`, `hub.challenge`).
- `POST /api/webhooks/whatsapp` — exige `X-Hub-Signature-256` válido (`WHATSAPP_APP_SECRET`).
  Mensagem recebida de um telefone conhecido → registra resposta (status "Respondeu", cancela a cadência);
  texto "SAIR/PARAR/CANCELAR..." → opt-out. Status `delivered/read/failed` atualizam a mensagem enviada.

## Variáveis dos templates

`{{nome}}` (primeiro nome do responsável), `{{empresa}}`, `{{cidade}}`, `{{estado}}`, `{{especialidade}}`,
`{{vendedor}}`, `{{comissao}}`, `{{link_parceria}}`. Sem nome conhecido, "Olá, {{nome}}!" vira "Olá!".

## Formatos

- Importação de leads e de certificados: ver `instalacao.md` (seção 8) e a tela de Vencimentos.
- Exportação CSV: separador `;`, UTF-8 com BOM (abre direto no Excel). Excel: `.xlsx` com cabeçalho fixo. PDF: A4 paisagem.
