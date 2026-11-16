# API oficial do WhatsApp (Plataforma do WhatsApp Business, da Meta)

Pedido da Maria em 16/11/2026: trocar aos poucos o WhatsApp por QR code (WhatsApp Leads, não oficial, risco de
banimento, teto de 20 contatos frios por número por dia) pela API oficial da Meta. Documentação da Meta:
<https://developers.facebook.com/documentation/business-messaging/whatsapp/overview>.

## Situação da MS (16/11/2026)

Portfólio "MS - Certificação Digital" **verificado**; número **+55 81 8343-0717** conectado na plataforma (selo do
app WhatsApp Business: provavelmente coexistência, o app continua no celular), Identificação do número
`1425129957352130`, limite **2.000** conversas iniciadas pela empresa por 24 h (sobe para 10.000 com 1.000 clientes
únicos em 7 dias com alta qualidade). Cobrança da conta em USD. Esse número não está no WhatsApp Leads.

## Regras da Meta que mudam o jeito de prospectar

- **Aceitação (opt-in)**: só pode receber mensagem da empresa quem deu o número e aceitou receber mensagens dela
  (<https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in>). Renovação (clientes)
  encaixa; Empresas novas e parceiros frios não têm aceite (decisão pendente da Maria).
- **Primeira mensagem só com modelo aprovado** (`type: template`); texto livre só na janela de 24 h depois da
  última mensagem do contato.
- **Limite por portfólio** (todas as contas e números dele juntos): 250 → 2.000 (empresa verificada) → 10.000 →
  100.000 → ilimitado, automático com boa qualidade.
- **Preço por mensagem entregue** (desde 01/07/2025), por categoria: marketing, utilidade, autenticação, serviço.
  Respostas da empresa dentro da janela: 1.000 grátis por mês por número. Mensagens do cliente: grátis.

## Etapas

| Etapa | O quê | Situação |
|---|---|---|
| 1 | Conta oficial por AR (chaves protegidas), teste de conexão, mensagem de teste, webhook (respostas, SAIR, situação) | **no ar (16/11/2026)** |
| 2 | Modelos do WhatsApp (criar, mandar para aprovação, acompanhar) e ligação dos toques da **Renovação** aos modelos (utilidade) | a fazer |
| 3 | Respostas dentro da janela de 24 h pela API (IA SDR, Conversas, envio manual) e cópia das conversas oficiais | a fazer |
| 4 | Campanhas de parceiros/Empresas novas pela API (depende da decisão sobre o opt-in) | decisão da Maria |
| 5 | White label: a plataforma como Provedor de Tecnologia da Meta e Cadastro Incorporado (cada AR liga o próprio número) | depois da validação |

## Etapa 1 (no ar)

- **Tabela** `contas_whatsapp_oficial` (`modelos.ContaWhatsAppOficial`, por AR, `DaAR`): `nome`, `waba_id`,
  `phone_number_id` (Identificação do número), `numero` (do último teste), `token_cripto` e `segredo_cripto`
  (`seguranca.criptografar`; nunca voltam para a tela), `verificacao` (token de verificação do webhook, gerado
  aqui), `situacao` (JSON do último teste), `testado_em`. Um número não entra em duas contas.
- **Tela**: Configurações > WhatsApp, quadro "API oficial da Meta" (`#oficial`), permissão
  `whatsapp.gerenciar_todos`; o Admin Master configura dentro da AR ("Entrar na AR"). Rotas:
  `POST /whatsapp/oficial` (salvar e testar), `/whatsapp/oficial/testar`, `/whatsapp/oficial/teste` (um modelo
  aprovado para um número da equipe; padrão `hello_world`/`en_US`, o de exemplo da Meta), `/whatsapp/oficial/remover`.
  Token/chave em branco ao salvar = continuam os de antes. O ID da conta do WhatsApp Business pode ficar em branco:
  ao testar, o sistema descobre pelo token (`whatsapp_cloud.contas_do_token`: permissões granulares do
  `debug_token`) e **liga o app à conta** (`whatsapp_cloud.inscrever_app`, `POST /{waba}/subscribed_apps`; sem isso o
  webhook não recebe as respostas da conta). É o que o "Início rápido" do app faria; ele cria um número de teste e,
  para a MS, foi travado pela Meta em 16/11/2026 ("impedido temporariamente"): não é preciso usá-lo. A situação
  guarda `app_ligado` e os `avisos` (mostrados na tela).
- **Cliente da Meta**: `integracoes/whatsapp_cloud.py` — `consultar_numero` (campos `display_phone_number`,
  `verified_name`, `quality_rating`, `whatsapp_business_manager_messaging_limit`, `name_status`), `enviar_modelo`,
  `enviar_texto_por`, `numeros_do_webhook`, `ler_webhook` (com o `phone_number_id` de cada item), `assinatura_confere`.
  Versão da API: `WHATSAPP_API_VERSAO` (padrão `v27.0`). Telefone de destino: 55 + DDD + celular com o 9
  (`util.com_nono_digito`). A forma antiga (variáveis `WHATSAPP_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID`, botão "Enviar pela
  API" da ficha) continua funcionando.
- **Webhook** `/api/webhooks/whatsapp`: a verificação aceita o token de qualquer conta (ou `WHATSAPP_VERIFY_TOKEN`);
  o POST confere `X-Hub-Signature-256` com a chave secreta da conta do `phone_number_id` do evento (ou
  `WHATSAPP_APP_SECRET`). Status `sent/delivered/read/failed` → `Mensagem.status` (`enviada/entregue/lida/falhou`, com
  o erro). Mensagem recebida: "SAIR" (`mensagens.pede_opt_out`) vale para todas as ARs; o resto vai para o lead da AR
  do número (`sdr.lead_pelo_telefone(..., conta.tenant_id)`) e entra em `sdr.processar_resposta` (classifica, para os
  toques, avisa a equipe). Nesta etapa nada é respondido sozinho pelo número oficial: a equipe responde pelo app
  WhatsApp Business do celular.
- **Testes**: `testes/test_whatsapp_oficial.py` (Meta imitada; nada sai de verdade).

## Passo a passo na Meta (o que a AR faz)

1. Meta for Developers (<https://developers.facebook.com/apps>) > Criar app (Empresa) > adicionar o produto
   **WhatsApp** e ligar ao portfólio da empresa. Não precisa concluir o "Início rápido" (número de teste). Na MS:
   app "MS API off" (ID 1838539180819325), em modo de desenvolvimento.
2. Configurações do negócio > Usuários > **Usuários do sistema** > adicionar (Admin) > atribuir o app e a conta do
   WhatsApp (controle total) > **Gerar token**: o app, validade "Nunca", permissões `whatsapp_business_messaging` e
   `whatsapp_business_management`.
3. No sistema: Configurações > WhatsApp > API oficial da Meta: Identificação do número de telefone, token e chave
   secreta do app (Meta for Developers > app > Configurações do app > Básico); o ID da conta do WhatsApp Business é
   opcional > **Salvar e testar** (liga o app à conta).
4. Webhook: Meta for Developers > app > WhatsApp > Configuração: URL de retorno e token de verificação mostrados na
   tela do sistema; assinar o campo `messages`.
5. **Enviar teste** para o próprio celular. Forma de pagamento na conta do WhatsApp para os modelos pagos.
