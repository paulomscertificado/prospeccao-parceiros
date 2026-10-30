# LGPD e segurança no sistema

Este documento descreve o que o sistema faz. Não substitui a orientação de um advogado ou do encarregado
de dados (DPO) da MS.

| Exigência | Como o sistema atende |
|---|---|
| Minimização | Campos voltados a dados **empresariais** públicos (escritório, CNPJ, site, telefone comercial). Sócios só a partir de dados públicos da Receita: da base importada fica só o nome e o cargo do responsável (sócio-administrador ou equivalente) e a quantidade de sócios, sem CPF, idade nem os demais sócios. A IA não recebe telefone nem e-mail |
| Origem e base legal | Cada lead grava **origem**, **fonte (URL)** e **base legal** (padrão: legítimo interesse em contato B2B; editável) |
| Consentimento | Indicações do portal exigem confirmação de que o cliente autorizou o contato |
| Opt-out | Um clique na ficha/agenda; automático com "SAIR" no WhatsApp oficial; e-mails com rodapé e `List-Unsubscribe`. Opt-out cancela tarefas e bloqueia novas mensagens e campanhas |
| Histórico de tratamento | Tabela `historico` por lead (contatos, mudanças, IA, LGPD) + `logs` de auditoria (quem, quando, IP) |
| Direito de exclusão | "Excluir dados (LGPD)" anonimiza o lead e guarda só as chaves mínimas para **não contatar de novo** |
| Retenção | Leads encerrados/opt-out sem movimento há N dias (padrão 365) são anonimizados (Configurações > LGPD) |
| Controle de acesso | 4 perfis; vendedor vê só os próprios leads; parceiro só a própria carteira |
| Segurança | Senha com hash PBKDF2, verificação em 2 etapas para administrador e gestor, chave Pix criptografada, sessão com expiração, CSRF, limite de tentativas, consultas parametrizadas (sem SQL injection), cabeçalhos de segurança, HTTPS em produção |
| Anti-spam | Sem disparo em massa; limite diário por canal; intervalo mínimo por lead; WhatsApp oficial só com templates aprovados |

Dados de demonstração são fictícios (domínio `.example`, DDD inexistente) e podem ser apagados em um clique.
