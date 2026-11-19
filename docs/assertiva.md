# Assertiva (consultas de CPF, CNPJ, telefone, e-mail e nome)

Pedido da Maria em 18/11/2026: integrar a API da Assertiva
([documentação v3](https://integracao.assertivasolucoes.com.br/v3/doc), produto **Localize**, seção "Consultas
principais") e deixar cada marca (AR) usar a própria chave, configurada em **Configurações > Integrações**, no mesmo
lugar da CNPJá.

## O que a API faz

| Consulta | Endpoint (GET, `https://api.assertivasolucoes.com.br`) | Devolve |
| --- | --- | --- |
| CNPJ | `/localize/v3/cnpj?cnpj=&idFinalidade=` | dados cadastrais, telefones (fixos e móveis, com WhatsApp e "não perturbe"), e-mails, endereços, sócios |
| CPF | `/localize/v3/cpf?cpf=&idFinalidade=` | dados cadastrais, telefones, e-mails, endereços |
| Telefone | `/localize/v3/telefone?telefone=&idFinalidade=` | pessoas e empresas ligadas ao número |
| E-mail | `/localize/v3/email?email=&idFinalidade=` | pessoas e empresas ligadas ao e-mail |
| Nome ou endereço | `/localize/v3/nome-endereco?buscarPor=&nomeOuRazaoSocial=&uf=&cidade=&idFinalidade=` | pessoas e empresas com o nome |

- **Entrada:** OAuth2 "client credentials". `POST https://api.assertivasolucoes.com.br/oauth2/v3/token` com Basic
  (Client ID : Client Secret) e `grant_type=client_credentials` devolve `access_token` e `expires_in` (segundos). Pedir
  o token **não gasta consulta**: é o botão "Testar as credenciais".
- **Finalidade (LGPD):** `idFinalidade` é obrigatório em toda consulta: 1 confirmação de identidade, 2 ciclo de
  crédito, 4 execução de contrato (a Assertiva encerra em 31/12/2026), 5 legítimo interesse (padrão do sistema,
  serve para prospecção). Cada marca escolhe a dela no quadro da Assertiva.
- **Erros:** 400 dados inválidos, 401 credenciais (o sistema pede um token novo e tenta de novo uma vez), 403 sem
  permissão no produto, 422 regra de negócio, 429 muitas consultas, 5xx instabilidade. Tudo vira aviso em português
  (`assertiva.ErroAssertiva`).
- **Cobrança:** cada consulta é cobrada pela Assertiva, da marca dona das credenciais.

## Como está no sistema

| Peça | Onde |
| --- | --- |
| Credenciais da marca | tabela `contas_assertiva` (`modelos.ContaAssertiva`, uma por AR): Client ID e Client Secret criptografados (`seguranca.criptografar`), finalidade, último teste. Nunca voltam para a tela (só `id_mascarado`) |
| Consultas feitas | tabela `consultas_assertiva` (`modelos.ConsultaAssertiva`): quem, lead, tipo, chave normalizada, finalidade, protocolo e o JSON da resposta. Apagadas depois de 30 dias (`assertiva.apagar_antigas`, rotina de hora em hora em `rotinas.py`) |
| Regras e conversa com a API | `app/assertiva.py`: `salvar`, `testar`, `preparar` (confere CPF/CNPJ/telefone/e-mail/nome), `consultar` (reaproveita a mesma consulta dos últimos 30 dias, a não ser com `de_novo`), `resumo` (o que a tela mostra), `usar_no_lead` |
| Telas e rotas | `app/rotas/assertiva.py`: `/assertiva` (menu "Consulta Assertiva"), `/assertiva/consultar`, `/assertiva/consulta/{id}`, `/leads/{id}/assertiva` (botão "Buscar contatos na Assertiva" na ficha), `/leads/{id}/assertiva/usar`, `/configuracoes/assertiva` (+ `/testar`, `/apagar`) |
| Quadro em Configurações > Integrações | `templates/configuracoes.html` (`id="assertiva"`), montado por `rotas/assertiva.painel` |
| Permissão | `assertiva.consultar` (grupo Leads, módulo `assertiva`, padrão administrador e gestor). Salvar/testar/apagar as credenciais: `configuracoes.alterar`. O módulo "Consultas na Assertiva" (chave `modulo_assertiva`, ligado por padrão) liga e desliga por marca em Painel master > Módulos de cada AR (só o Admin Master; até 19/11/2026 valia para todas as marcas de uma vez, `docs/permissoes.md` > Módulos de cada AR) |
| Testes | `testes/test_assertiva.py` (a Assertiva é simulada: `assertiva._post`/`_get`) |

Regras importantes:

- **Cada marca só usa e só vê o que é dela** (app/isolamento.py): sem credenciais próprias, a marca não consulta
  (nunca usa as de outra). O Admin Master configura e consulta só depois de "Entrar na AR".
- **Só por clique**, com confirmação na tela ("ela é cobrada"); nada consulta sozinho.
- **Reaproveitamento:** a mesma consulta (tipo + documento normalizado) da marca nos últimos 30 dias aparece de novo
  sem cobrar; "Consultar de novo" cobra outra.
- **Registro:** cada consulta vai para o registro de atividades (`consultou_assertiva`, com CPF, telefone e e-mail
  mascarados e o protocolo da Assertiva); usar um dado no lead também (`usou_dado_assertiva`) e fica no histórico do
  lead, com o valor de antes.
- **No lead entra só o que veio na consulta** (telefone como WhatsApp ou telefone, e-mail, sócio como responsável):
  `usar_no_lead` recusa qualquer valor que não esteja no resultado. "Nunca inventar dados de leads" continua valendo.
- **Na tela:** CPF de sócios e de pessoas encontradas aparece mascarado (123.***.***-01); o nome da mãe e o CPF dela,
  que a Assertiva também devolve, não aparecem.
- Telefones com **"não perturbe"** ganham um selo vermelho: o número está no cadastro de quem não quer ligações de
  venda; evite usar para prospecção.
