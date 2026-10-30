# Documentação técnica – Prospecção de Parceiros

| Documento | Conteúdo |
|---|---|
| [instalacao.md](instalacao.md) | 1. Como instalar · 2. Como configurar o banco · 7. Como criar usuários · 8. Como importar leads · 9. Como criar uma campanha |
| [ia-sdr.md](ia-sdr.md) | **IA SDR**: arquitetura, fluxo de dados, integrações, banco, estratégia de IA, segurança, conformidade e MVP |
| [configuracao.md](configuracao.md) | 3. IA · 4. WhatsApp · 5. E-mail · 6. APIs externas (Receita, Google Places, OpenStreetMap, BrasilAPI) |
| [deploy-vercel.md](deploy-vercel.md) | **Publicar na Vercel**: o que muda na nuvem, trabalhos em etapas, agendador, ponte do WhatsApp, passo a passo |
| [deploy.md](deploy.md) | 10. Como colocar o sistema em produção (Docker + PostgreSQL + HTTPS) |
| [arquitetura.md](arquitetura.md) | Decisões técnicas, fluxo, banco de dados (schema), segurança |
| [permissoes.md](permissoes.md) | **Permissões em camadas**: papéis, permissões `recurso.acao`, alcance, exceções, equipes, módulos, como proteger uma rota nova |
| [api.md](api.md) | Rotas (telas e API JSON), webhooks, formatos de importação/exportação |
| [componentes.md](componentes.md) | O que cada arquivo/módulo do código faz |
| [design-system.md](design-system.md) | Cores, componentes visuais, tom de voz das mensagens |
| [lgpd.md](lgpd.md) | Como o sistema trata dados pessoais (LGPD) |

Manual da usuária final: [`../LEIAME.md`](../LEIAME.md).

Ao mudar o código: rode `testar.bat` e atualize o documento correspondente.

- [manual-fluxo-campanhas.md](manual-fluxo-campanhas.md) — manual da equipe: envios de e-mail e WhatsApp depois da aprovação (apresentação em PDF: `Apresentacao - Fluxo das campanhas.pdf`, fonte em `apresentacao/`)
- `Plataforma de Prospeccao - O que faz.pdf` — visão geral do que a plataforma faz e suas habilidades (fonte em `apresentacao/plataforma.html`)
