# Componentes do código

```
prospeccao-parceiros/
├── app/
│   ├── main.py            aplicação FastAPI: sessão, cabeçalhos de segurança, erros, rotina de vencimentos (1x/hora)
│   ├── config.py          lê o .env; status, perfis, canais, UFs, configurações e produtos padrão
│   ├── banco.py           conexão (SQLite/PostgreSQL), sessões, configurações gravadas no banco
│   ├── modelos.py         tabelas (schema) + templates, cadência e produtos iniciais
│   ├── seguranca.py       hash de senha, criptografia, CSRF, limites, login, permissões, auditoria
│   ├── util.py            CNPJ (inclusive alfanumérico), telefone, domínio, datas, moeda
│   ├── score.py           lead scoring (critérios, pesos, faixas)
│   ├── leads_servico.py   criar/deduplicar lead, mudar status (histórico + datas do funil), opt-out,
│   │                      converter em parceiro, anonimização/retensão
│   ├── mensagens.py       variáveis dos templates, limite diário, controle de frequência, palavras de opt-out
│   ├── cadencias.py       aplica uma cadência → tarefas na agenda
│   ├── vendas_servico.py  calculadora de comissão, registrar venda (+ certificado), alertas de vencimento
│   ├── prospeccao.py      busca (Receita, OSM, Google), leitura de sites, BrasilAPI; busca em etapas (trabalhos)
│   ├── base_receita.py    importação dos .zip da Receita (categorias de parceiros; sócio-admin e Simples/MEI) e busca por cidade
│   ├── ia.py              camada de IA (abordagem, próximo passo, objeções, templates, perguntas) + regras sem IA
│   ├── metricas.py        indicadores, séries de gráficos, rankings, perguntas prontas da IA Comercial
│   ├── planilhas.py       leitura CSV/Excel, validação, geração de CSV/Excel/PDF
│   ├── web.py             renderização das telas, filtros de formatação, menu, avisos
│   ├── seed.py            dados FICTÍCIOS de demonstração e remoção
│   ├── pesquisa.py        IA SDR: pesquisa pública do site + perfil do parceiro (trava contra invenção)
│   ├── sdr.py             IA SDR: canal, mensagens por ângulo, classificação de respostas, handoff, avisos
│   ├── campanhas.py       IA SDR: pedido → campanha → aprovação → fila de e-mail → fim de cadência
│   ├── agenda_horarios.py horários livres reais (expediente − reuniões) e marcação de reunião
│   ├── rotinas.py         relógio: fila (1 min), respostas IMAP (5 min), vencimentos/fim de cadência (1 h)
│   ├── trabalhos.py       trabalhos longos em etapas retomáveis + travas (campanha, busca, personalização; nuvem)
│   ├── arquivo_env.py     grava o e-mail da tela no .env (na nuvem: no banco, criptografado)
│   ├── integracoes/
│   │   ├── whatsapp_cloud.py  envio de template pela API oficial, webhook e assinatura
│   │   ├── email_smtp.py      envio de e-mail com opt-out
│   │   └── email_imap.py      leitura das respostas dos leads (IMAP)
│   ├── rotas/
│   │   ├── auth.py        login, primeiro acesso, troca de senha
│   │   ├── painel.py      dashboard, relatórios, exportações, IA Comercial
│   │   ├── leads.py       leads, pipeline, ficha, mensagens, importação, prospecção
│   │   ├── agenda.py      cadências, templates, agenda, personalização de campanha com IA
│   │   ├── comercial.py   parceiros, clientes, vendas, comissões, produtos, vencimentos
│   │   ├── admin.py       configurações, usuários, base da Receita, LGPD
│   │   ├── sdr.py         oportunidades, assumir lead, agenda, campanhas, inteligência, categorias, conhecimento
│   │   ├── portal.py      portal do parceiro
│   │   └── api.py         saúde e webhook do WhatsApp
│   ├── templates/         telas HTML (base.html = menu lateral)
│   └── static/            estilo.css (design system) e app.js (copiar mensagem, avisos)
├── testes/                testes automáticos (pytest)
├── iniciar.py / *.bat     abrir, instalar, testar, redefinir senha, demonstração, importar Receita
├── Dockerfile, docker-compose.yml, requirements*.txt, .env.example
└── docs/
```

## Funções principais

| Função | Arquivo | Faz |
|---|---|---|
| `criar_lead(db, dados, usuario, origem)` | leads_servico | Padroniza, deduplica, calcula score, grava histórico. Devolve `(lead, "")` ou `(existente, motivo)` |
| `achar_duplicado(db, lead)` | leads_servico | Procura por CNPJ, domínio, telefone/WhatsApp, e-mail |
| `mudar_status(db, lead, novo, usuario)` | leads_servico | Histórico, datas do funil, cancela cadência quando responde, cria parceiro |
| `score.calcular(db, lead)` | score | `(score, potencial, [(motivo, pontos, atendido)])` |
| `cadencias.aplicar(db, cadencia, leads, usuario, inicio)` | cadencias | Cria tarefas (pula opt-out, encerrados, quem já está em cadência, fins de semana) |
| `mensagens.bloqueio_de_envio(db, lead, canal)` | mensagens | Motivo para não enviar (opt-out, frequência, limite diário) |
| `registrar_venda(...)` | vendas_servico | Venda + comissão + certificado + ativa o parceiro |
| `processar_vencimentos(db)` | vendas_servico | Tarefas de renovação nas faixas 90/60/30/15/7 dias |
| `executar_busca(busca_id)` | prospeccao | Fontes → dedup → enriquecimento → score |
| `ia.gerar_abordagem / proximo_passo / analisar_resposta` | ia | IA com esquema JSON, ou regras sem chave |
| `metricas.indicadores(db, usuario, periodo)` | metricas | Todos os números do dashboard e relatórios |
