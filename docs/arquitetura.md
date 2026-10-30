# Arquitetura

## Decisões técnicas

| Tema | Escolha | Motivo |
|---|---|---|
| Linguagem / backend | Python 3.12 + **FastAPI** | Mesmo padrão do sistema `whatsapp-leads`; o computador da MS tem Python (não tem Node); um processo só |
| Banco | **SQLAlchemy 2** · SQLite local · **PostgreSQL** em produção | Troca por `DATABASE_URL`, sem mudar código. Contas dos indicadores feitas em Python para funcionar igual nos dois |
| Telas | HTML no servidor (**Jinja2**) + JS simples + **Chart.js** (CDN) | Sem etapa de build, rápido, responsivo, fácil de manter |
| Autenticação | Sessão assinada (cookie `ms_sessao`), PBKDF2-SHA256 310 mil iterações, CSRF, limite de tentativas; verificação em 2 etapas (TOTP) para admin/gestor | Equivalente ao Auth.js, sem dependência extra (QR code com `segno`) |
| IA | Claude via biblioteca `anthropic`, saída em JSON com esquema | Respostas estruturadas e confiáveis; fallback por regras |
| Integrações | Módulos isolados em `app/integracoes/` e `app/prospeccao.py` | Cada fonte/canal entra sem mexer no resto |
| Tarefas automáticas | Laço `asyncio` a cada hora (vencimentos) + threads para buscas longas | Sem Redis/Celery no MVP |

Pensado para a escala da MS (milhares de leads, dezenas de usuários). Para dezenas de milhares de leads
ativos ou vários servidores: mover buscas e enriquecimento para uma fila (RQ/Celery) e o limitador de
tentativas para Redis.

## Fluxo principal

```
Prospecção (Receita / Google / OSM)  ─┐
Importação CSV/Excel                 ─┼─► Deduplicação (CNPJ, domínio, telefone, e-mail)
Cadastro manual                      ─┘        │
                                               ▼
                         Enriquecimento (site + BrasilAPI)  →  Score automático
                                               ▼
                    Campanha = cadência aplicada → Tarefas na Agenda (mensagens personalizadas)
                                               ▼
           Vendedor copia/abre WhatsApp/e-mail (ou envia 1 pela API oficial) → histórico + limites
                                               ▼
      Resposta → cancela tentativas → análise (objeções) → Interessado → Reunião → Proposta → Negociação
                                               ▼
                       Parceiro (EM ATIVAÇÃO) → 1ª venda → ATIVO → indicações (portal)
                                               ▼
              Venda → comissão (regra do parceiro ou do produto) → certificado → alertas 90/60/30/15/7 dias
                                               ▼
                         Tarefa de renovação → nova venda (renovação) → receita recorrente
```

## Banco de dados (schema)

Definido em `app/modelos.py` e `app/base_receita.py`.

| Tabela | Para quê | Campos principais |
|---|---|---|
| `usuarios` | Login e perfis | email (único), senha_hash, perfil (admin/gestor/vendedor/parceiro), parceiro_id, versao_sessao, totp_* e versao_2fa (2 etapas) |
| `leads` | Banco de leads | dados do escritório, critérios do score, status, score, potencial, origem, fonte_url, base_legal, opt_out, datas do funil (contatado_em, respondeu_em, interessado_em, reuniao_em, proposta_em, convertido_em), chaves de dedup (chave_cnpj, chave_dominio, chave_telefone, chave_whatsapp, chave_email) |
| `historico` | Linha do tempo do lead (registro de tratamento LGPD) | tipo (status, contato, resposta, nota, ia, sistema, reuniao, lgpd), canal, descrição, usuário |
| `buscas` | Execuções de "Encontrar novos parceiros" | critérios, fontes, status, contadores |
| `templates` | Mensagens com variáveis | canal, assunto, corpo, nome_meta (template aprovado na Meta) |
| `cadencias` / `passos_cadencia` | Sequências (Dia N, canal, ação, template, hora) | |
| `campanhas` | Cadência aplicada a um grupo de leads | cadencia_id, busca_id, personalizar_ia |
| `tarefas` | Agenda | tipo (prospeccao, followup, reuniao, renovacao, indicacao), lead/cliente/certificado/parceiro, canal, data, hora, ação, mensagem, status |
| `mensagens` | Histórico de envios (base do limite diário e da frequência) | canal, modo (manual/api), direção, status, id_externo |
| `parceiros` | Escritórios parceiros | status (ATIVO, INATIVO, EM ATIVAÇÃO, BLOQUEADO), regra de comissão própria, chave_pix_cripto |
| `clientes` | Clientes finais (indicados) | parceiro_id, status (Indicado, Em contato, Emitido, Perdido) |
| `produtos` | Tabela de preços | preço, custo, comissão padrão (% ou R$), validade em meses |
| `vendas` | Vendas e comissões | valor, custo, comissão, comissao_paga, tipo (nova/renovacao) |
| `certificados` | Controle de vencimentos | data_vencimento, status, ultimo_alerta, parceiro_id |
| `logs` | Auditoria | usuário, ação, entidade, IP |
| `configuracoes` | Regras alteráveis na tela | chave/valor (pesos do score, limites, textos) |
| `base_receita` | Escritórios de contabilidade da base aberta da Receita | cnpj, nome, CNAE, UF, município, endereço, telefones, e-mail, porte, socio_admin/socio_cargo/socios_qtd, regime (MEI/Simples) |

## Lead scoring (IA SDR)

`app/score.py`. Pesos padrão (alteráveis em Configurações > Score): aderência da categoria ao certificado 25,
relacionamento recorrente 10, clientes B2B 10, +100 clientes 10, porte 10, presença digital 10, possibilidade de
indicação 10, programa de parceiros 10, potencial de volume 10, capacidade comercial 10, interesse 20, contato
direto 5. Faixas: 0–30 baixo, 31–60 médio, 61–80 alto, 81+ prioridade máxima. Fit: Muito alto, Alto, Médio,
Baixo potencial ou Sem fit (a pesquisa da IA pode definir o fit; sem IA, regras). Recalculado a cada alteração.

## CRM (IA SDR)

Novo → Pesquisando → Abordagem criada → Contatado → Aguardando resposta → Respondeu → Interessado →
Humano assumiu → Reunião → Negociação → Parceiro → Parceiro ativo, ou Perdido (com motivo: sem interesse,
sem resposta, já possui parceiro, contato inválido, sem fit, opt-out). A IA trabalha até "Interessado".
Detalhes em [ia-sdr.md](ia-sdr.md).

## Segurança

- Senhas: PBKDF2-SHA256 com sal; troca de senha derruba as outras sessões (`versao_sessao`).
- Verificação em 2 etapas (`app/dois_fatores.py`, `config.EXIGIR_2FA`): obrigatória para admin e gestor (e para quem
  já ligou). Depois da senha, a sessão só guarda `pendente_2fa` por 10 minutos; o acesso abre em `/login/codigo`
  (ou `/login/ativar-codigo` na 1ª vez, com QR code). TOTP de 6 dígitos, 30 s, tolera ±30 s; código já usado não
  vale (`totp_ultimo_passo`). Segredo criptografado (`totp_segredo`, Fernet); 8 códigos de recuperação guardados só
  como HMAC (`totp_recuperacao`). "Lembrar este computador" = cookie assinado `ms_aparelho` por 30 dias, invalidado
  por `versao_2fa`. Sessões sem a marca `2fa` de quem precisa voltam para o login. O admin zera em Configurações >
  Usuários (`/configuracoes/usuarios/{id}/zerar-2fa`); `redefinir_senha.py` também zera.
- Sessão: cookie assinado, `SameSite=Lax`, `Secure` em produção, expira após 120 min sem uso.
- CSRF: token por sessão em todo formulário e no cabeçalho `X-CSRF-Token` das chamadas JSON.
- Rate limiting: 5 senhas erradas/15 min por IP+e-mail; 240 alterações/min por IP; 120 webhooks/min.
- SQL injection: só consultas parametrizadas do SQLAlchemy (nenhum SQL montado com texto).
- Criptografia: chave Pix com Fernet (`CHAVE_CRIPTOGRAFIA`).
- Cabeçalhos: `X-Frame-Options`, `nosniff`, `Referrer-Policy`, HSTS em produção. Documentação automática da API desligada.
- Permissões por perfil em toda rota (`app/seguranca.py`) e filtro de dados por vendedor/parceiro.
- Logs de auditoria de login, exportações, importações, alterações e LGPD.
