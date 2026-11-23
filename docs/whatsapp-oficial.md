# API oficial do WhatsApp (Plataforma do WhatsApp Business, da Meta)

Pedido da Maria em 16/11/2026: trocar aos poucos o WhatsApp por QR code (WhatsApp Leads, não oficial, risco de
banimento, teto de 20 contatos frios por número por dia) pela API oficial da Meta. Documentação da Meta:
<https://developers.facebook.com/documentation/business-messaging/whatsapp/overview>.

## Situação da MS (16/11/2026)

Portfólio "MS - Certificação Digital" **verificado**; número **+55 81 8343-0717** conectado na plataforma (selo do
app WhatsApp Business: provavelmente coexistência, o app continua no celular), Identificação do número
`1425129957352130`, limite **2.000** conversas iniciadas pela empresa por 24 h (sobe para 10.000 com 1.000 clientes
únicos em 7 dias com alta qualidade). Cobrança da conta em USD. Esse número não está no WhatsApp Leads.

**17/11/2026:** a conta do Facebook do Paulo Marinho, única administradora do portfólio da MS, tem restrição definitiva
de publicidade e não liga app nem adiciona pessoas. Decisão da Maria: a API vai para um **portfólio novo no Facebook de
Carol, com um número novo** (no modelo novo de contas da Meta, número não muda de portfólio). Em 18/11/2026 a Maria
começou a montar o portfólio pela conta de Carol (passo a passo abaixo); nada salvo ainda no sistema.

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
| 2 | Modelos do WhatsApp (criar, mandar para aprovação, acompanhar) e ligação dos toques da **Renovação** aos modelos (utilidade) | **no ar (16/11/2026)**, desligado até a Meta aprovar e o admin ligar |
| 3 | Cópia das conversas oficiais (tela **API Oficial**) | **no ar (21/11/2026)** |
| 3b | Responder dentro da janela de 24 h pela API (IA SDR, envio manual pela tela API Oficial) | a fazer |
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
  aprovado para um número da equipe; sem modelo, texto simples), `/whatsapp/oficial/remover`
  e `/whatsapp/oficial/ativar` (abaixo). Teste recusado pela Meta: o motivo aparece no aviso (preso no alto da
  tela, `.avisos-da-acao` do `base.html`, 19/11/2026) e fica no registro de atividades (`teste_whatsapp_oficial_recusado`,
  `teste_aviso_whatsapp_oficial_recusado`). Desde 19/11/2026 o teste sem modelo vai como **texto simples**
  (`TEXTO_DE_TESTE`, de graça; a Meta só entrega para quem escreveu ao número nas últimas 24 h, erro 131047): o
  `hello_world` só sai dos números de teste da Meta (erro 131058, visto no número da MS). Falha de entrega avisada
  pelo webhook de uma mensagem que não é de um lead (ex.: o teste) fica no registro (`whatsapp_oficial_nao_entregue`).
  Token/chave em branco ao salvar = continuam os de antes. O ID da conta do WhatsApp Business pode ficar em branco:
  ao testar, o sistema descobre pelo token (`whatsapp_cloud.contas_do_token`: permissões granulares do
  `debug_token`) e **liga o app à conta** (`whatsapp_cloud.inscrever_app`, `POST /{waba}/subscribed_apps`; sem isso o
  webhook não recebe as respostas da conta). No modelo novo da Meta essa conta é a
  **conta de mensagens** (Configurações do negócio > Contas > Contas de mensagens). O token de um usuário do sistema
  **administrador** vale para todos os ativos e vem sem contas nas permissões granulares: aí o sistema procura nas
  contas atribuídas a ele (`whatsapp_cloud.contas_atribuidas`, `GET /{usuário}/assigned_whatsapp_business_accounts`) e,
  com mais de uma, fica com a que tem o número (`numeros_da_conta`; a de teste sai) — `whatsapp_oficial.conta_do_numero`
  (caso real da MS em 19/11/2026). O ID preenchido na tela de uma conta sem o número é avisado (`numero_fora_da_conta`)
  e o webhook completa a conta que estiver sem ID (`contas_por_numero`: o `entry.id` de cada evento). É o que o "Início rápido" do app faria; ele cria um número de teste e,
  para a MS, foi travado pela Meta em 16/11/2026 ("impedido temporariamente"): não é preciso usá-lo. A situação
  guarda `app_ligado` e os `avisos` (mostrados na tela).
- **Ativar o número** (pedido da Maria em 18/11/2026): número novo precisa ser **registrado** na Cloud API
  (`POST /{phone_number_id}/register` com `messaging_product` e `pin` de 6 números, a verificação em duas etapas do
  número). A Meta só aceita pela API, não pelo Gerenciador do WhatsApp nem pelo painel do app, e conta 10 pedidos por
  número a cada 72 h (erro 133016). Tela: quadro "Ativar o número na Meta" (`#ativar`, senha e repetição) →
  `POST /whatsapp/oficial/ativar` → `whatsapp_oficial.ativar_numero` (erros da Meta explicados em `ERROS_DA_ATIVACAO`).
  A senha não é guardada, some das mensagens de erro e não vai para o registro de atividades (que guarda as tentativas
  que chegaram à Meta). O teste de conexão pergunta à parte `status,platform_type,code_verification_status`
  (`whatsapp_cloud.registro_do_numero`; se a Meta recusar, o teste não cai) e guarda `ativado` (`numero_ativado`:
  `CLOUD_API`) e `status_numero`. Sem ativar: a tela avisa ("Achado na Meta, mas ainda não ativado") e a Renovação não
  liga o envio pela API (`falta_para_renovacao`). Testes: `testes/test_whatsapp_oficial.py`.
- **Cliente da Meta**: `integracoes/whatsapp_cloud.py` — `consultar_numero` (campos `display_phone_number`,
  `verified_name`, `quality_rating`, `whatsapp_business_manager_messaging_limit`, `name_status`),
  `registro_do_numero`, `registrar_numero`, `enviar_modelo`,
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

## Etapa 2 (no ar): Renovação pelo número oficial

Pedido da Maria em 16/11/2026: "que continue fazendo essa campanha mas que seja enviada pela API da Meta".

- **Modelos** (tabela `modelos_whatsapp_oficial`, `modelos.ModeloWhatsAppOficial`, por conta/AR): dois, categoria
  **utilidade** (`UTILITY`; a Meta pode mudar para marketing: `categoria_meta`), idioma `pt_BR`:
  `aviso_vencimento_certificado_arte` (cabeçalho IMAGEM) e `aviso_vencimento_certificado` (só texto; vale para todos e é
  o que precisa estar aprovado para ligar). Corpo (`whatsapp_oficial.corpo_renovacao`, com o nome da marca da AR):
  `{{1}}` primeiro nome do contato, `{{2}}` o certificado ("e-CNPJ A1 em nome de ...") ou a lista numa linha, `{{3}}` o
  vencimento ("21/11/2026 (faltam 5 dias)"); valores sem quebra de linha (`renovacao.valores_do_modelo`, os
  certificados da onda do aviso: `certificados_do_aviso`). Rodapé "Para não receber estes avisos, toque em Parar
  avisos." e 3 botões de resposta rápida: **Quero renovar**, **Já renovei**, **Parar avisos**.
  `whatsapp_oficial.pedir_modelos_renovacao` (tela: Configurações > WhatsApp > API oficial > "Enviar os modelos para a
  Meta aprovar", `POST /whatsapp/oficial/modelos`): primeiro adota o que já existe na Meta com esses nomes; aprovado ou
  em análise fica; recusado/pausado vai de novo (`whatsapp_cloud.editar_modelo`); novo: `criar_modelo`
  (`POST /{waba}/message_templates`). A imagem de exemplo do modelo com a arte (`app/static/renovacao/aviso_exemplo.png`,
  dados fictícios, desenhada pelo `arte_aviso.gerar`) sobe pelo envio em partes da Meta (`app_do_token` +
  `subir_exemplo`: `POST /{app}/uploads` e o `header_handle`). Situação: `atualizar_modelos` (botão "Atualizar a
  situação", `POST /whatsapp/oficial/modelos/atualizar`, e a rotina de hora em hora `atualizar_modelos_pendentes`).
  "Enviar um aviso de exemplo" (`POST /whatsapp/oficial/modelos/teste`, `enviar_teste_renovacao`): EMPRESA EXEMPLO LTDA
  com a arte de exemplo; os botões do exemplo não fazem nada.
- **Ligar** (tela Renovação, quadro 4, só quem escolhe o número: `campanhas.escolher_numero`): "Enviar o WhatsApp dos
  avisos pela API oficial da Meta" grava `renov_envio_oficial` e marca `Campanha.envio_oficial` nas campanhas de
  renovação em andamento (`renovacao.aplicar_envio_oficial`; campanha nova já nasce com ele em `criar_campanha`). Só
  liga com `whatsapp_oficial.falta_para_renovacao(ar) == ""` (conta com token, testada, com a chave secreta do app,
  sem a qual o webhook recusa as respostas e os botões, e o modelo só de texto aprovado). Desligar volta para o QR code.
- **Fila** (`whatsapp_oficial.processar_fila`, passo `fila_whatsapp_oficial` do relógio, até `POR_RODADA` = 5 avisos por
  minuto): toques pendentes de WhatsApp das campanhas com `envio_oficial`, no horário da AR e da Renovação (segunda a
  sexta, sem feriados), até `DIAS_ATRASO_AUTOMATICO` de atraso, um aviso por vez para cada empresa
  (`_toque_anterior_pendente`) e nunca dois WhatsApps automáticos em menos de 20 h. Valem opt-out, controle de
  frequência e o limite da campanha (`mensagens.bloqueio_de_envio` sem número); o teto de contatos frios e os limites
  por número são do QR code e não valem (o limite é o da Meta: 2.000 conversas por dia no número da MS). A fila do QR
  code (`campanhas.processar_fila_whatsapp`) pula essas campanhas (`Campanha.envio_oficial.is_not(True)`); o clique
  ("Enviar" da Minha fila, "Disparar campanha") também sai pela API (`campanhas._enviar_toque`, `disparar`). A Meta
  recusou um aviso: tenta de novo depois de `NOVA_TENTATIVA_MIN` (30 min); problema da conta: a rodada para.
  Registro: `Mensagem` com `modo="oficial"`, `status="enviada"`, `id_externo` = wamid (a situação entregue/lida/falhou
  chega pelo webhook), `conexao="oficial:<phone_number_id>"` (Oportunidades mostra "WhatsApp oficial (API da Meta)") e o
  texto preenchido com os botões.
- **Arte** (`whatsapp_oficial.arte_do_envio`): com o modelo com a arte aprovado e a arte do aviso cabendo
  (`renovacao.arte_do_toque`: AR MS, um certificado), a nuvem pede ao computador do WhatsApp Leads um comando
  `desenhar_arte` (`comandos_whatsapp`, coluna nova `tarefa_id`; até `ARTES_POR_RODADA` por rodada). O computador
  desenha (`ponte_nuvem._arte_pedida`) e devolve em `POST /api/ponte/arte-pedido/{id}` (senha da ponte; vira
  `artes_aviso` com `ponte_id=0`, que o e-mail do mesmo aviso também usa). A rodada seguinte sobe a arte para a Meta
  (`subir_midia`, `POST /{phone_number_id}/media`) e manda o modelo com ela. Sem a arte em `ESPERA_DA_ARTE_MIN` (15 min)
  ou com erro (computador desligado, sem Chrome, versão antiga do WhatsApp Leads: "pedido desconhecido"), sai o modelo
  só de texto. Quem tem vários certificados recebe sempre o só de texto, com a lista.
- **Botões** (payload `renov:<ação>:<tarefa>`, `whatsapp_cloud.ler_webhook` → `botao`; `whatsapp_oficial.tratar_botao`,
  chamado pelo webhook antes do SAIR): confere se a tarefa é da AR do número e do mesmo telefone (senão segue como
  resposta comum). **Quero renovar**: oportunidade quente "QUER RENOVAR" (`config.CLASSES_QUENTES`), lead Interessado,
  aviso para a equipe toda. **Já renovei**: com um certificado ativo, ele vira Renovado e os avisos param, sem trabalho
  para a equipe; com vários, oportunidade morna "JÁ RENOVOU" para conferir qual. **Parar avisos**: opt-out em todas as
  ARs (como o SAIR). Os três cancelam os próximos avisos.
- **Testes**: `testes/test_whatsapp_oficial_renovacao.py` (Meta imitada) e, no WhatsApp Leads,
  `testes/teste_ponta_a_ponta.py` (pedido `desenhar_arte`).
- **Mensagem de teste da tela** (22/11/2026): escrito o nome de um modelo do aviso de vencimento (sem ligar para
  maiúsculas), vai preenchido com os dados de exemplo (`whatsapp_oficial.modelo_do_aviso_pelo_nome` →
  `enviar_teste_renovacao(nome=)`): antes ia sem os 3 campos e a Meta recusava (erro 132000; com maiúscula, 132001, "o
  nome não existe"). Recusas 132000/132001 explicadas na tela (`ERROS_DO_TESTE`). Texto simples: a Meta aceita e só
  depois avisa que não entregou fora das 24 h (131047, "Re-engagement message"): o aviso da tela lembra disso e o motivo
  aparece na tela API Oficial.
- **A chave é de cada marca** (22/11/2026): `renov_envio_oficial` está em `banco.CHAVES_DA_AR` (cada marca liga a dela
  na tela Renovação) e só vale para a marca com a API oficial pronta (`renovacao.envio_oficial_da_ar`, na criação da
  campanha; `aplicar_envio_oficial` ao ligar pula as campanhas das marcas sem a API pronta). Antes valia para todas: ligada
  na MS, as campanhas do Grupo Certy (sem API oficial) iriam para o número oficial e os avisos ficariam parados.
- **Uso decidido pela Maria (22/11/2026):** o número oficial fica só para os avisos de renovação (nada de prospecção
  fria por ele, que é o que mais derruba uma conta oficial; as campanhas de parceiros e Empresas novas continuam no QR code).
- **Falta (etapa 3b)**: responder o cliente pelo sistema dentro da janela de 24 h (oferecido; a Maria preferiu deixar o
  número só para os avisos). Até lá a equipe responde pelo
  próprio WhatsApp ou por telefone (o número oficial foi ligado direto na API: não abre em celular nenhum, e um número
  que já está na API não passa para a "coexistência" app + API da Meta).

## Tela API Oficial (no ar desde 21/11/2026)

Pedido da Maria: "preciso ver as respostas dos clientes em algum lugar ... separado das conversas ... como API
Oficial". Item **API Oficial** no menu (`rotas/oficial.py`, `templates/oficial.html`), separado da tela Conversas (que
é a dos números por QR code do WhatsApp Leads).

- **O que guarda** (tabela `mensagens_oficiais`, modelo `MensagemOficial`, na AR da conta): tudo o que o número oficial
  manda (os avisos da Renovação como o cliente viu, com o corpo do modelo preenchido, o rodapé e os botões, e
  "[com a arte do aviso]" quando foi com a arte; o aviso de exemplo; o teste de conexão) e tudo o que chega nele, de
  cliente ou não (texto, toque nos botões, mídia como "[image]"), com o nome do perfil do WhatsApp e o lead quando o
  telefone é de um lead da AR. `whatsapp_oficial.guardar_conversa` (no webhook e nos envios; a mesma mensagem da Meta
  não entra duas vezes, pelo `wamid`) e `atualizar_entrega` (enviada → entregue → lida, nunca volta; falhou guarda o
  motivo). Antes disso, mensagem de quem não era lead era descartada.
- **A tela**: lista das conversas (a mais recente primeiro, com as não lidas) e a conversa aberta, no visual da tela
  Conversas; busca por nome, empresa ou telefone; link para a ficha do lead (quem pode vê-lo); abrir a conversa marca
  as que chegaram como lidas. Com a aba à vista, confere a cada 20 s (`/oficial/marca`) e recarrega se algo mudou.
- **Quem vê**: permissão `oficial.ver` (equipe toda, como as Oportunidades), módulo `api_oficial` (por AR, só o Admin
  Master liga e desliga; ligado por padrão) e o item só aparece na AR que tem a API oficial configurada, com o número
  vermelho das mensagens novas (`web.tela`: `tem_api_oficial`, `oficial_nao_lidas`; some quando alguém abre a
  conversa). Cada AR só vê as do número dela.
- **Na tela WhatsApp** (23/11/2026, pedido da Maria: "a API não aparece aqui por quê? pois preciso compartilhar as
  conversas com a equipe"): quadro "Número oficial (API da Meta)" junto dos números do QR code
  (`templates/_numero_oficial.html`, `rotas/whatsapp._numeros_oficiais`), para quem tem `oficial.ver` ou
  `whatsapp.gerenciar_todos`: o número de cada AR que a pessoa enxerga (o Admin Master fora de uma AR vê o de todas),
  a situação do último teste e **quem vê as conversas** (`autorizacao.quem_tem(db, "oficial.ver", ar)`: a equipe
  ativa da AR com a permissão, com os módulos da AR; sem o Admin Master). Não tem "Compartilhar": é da empresa, e quem
  vê é quem tem a permissão (para tirar alguém, exceção NEGAR em Configurações > Exceções por pessoa). Botões "Abrir
  as conversas" (`/oficial`) e "Configurar" (`#oficial`, só dentro da AR). Teste: `testes/test_numero_oficial_na_tela.py`.
- **Guarda**: o mesmo prazo da cópia das conversas (`guarda_conversas_meses`, 12 meses; `leads_servico.apagar_conversas_antigas`).
- Testes: `testes/test_tela_api_oficial.py` e a conferência no `test_whatsapp_oficial_renovacao.py`.

## Passo a passo na Meta (o que a AR faz)

Revisto em 18/11/2026. No modelo novo de contas da Meta (set-out/2026) a "conta do WhatsApp Business" aparece também
como "conta de mensagens" (modelos, cobrança e webhooks) e os nomes dos botões mudam com o tempo.

1. **Portfólio**: business.facebook.com > Criar portfólio empresarial. Quem cria precisa de uma conta do Facebook sem
   restrição (Qualidade da conta) e com autenticação de dois fatores; ponha um segundo administrador. A verificação da
   empresa (Central de segurança) corre junto: sem ela, até 250 contatos por dia e 2 números no portfólio.
2. **App**: Meta for Developers (<https://developers.facebook.com/apps>) > Criar app > caso de uso "Conectar-se com
   clientes pelo WhatsApp" > o portfólio > Começar a usar a API > Criar uma conta do WhatsApp Business. Não precisa do
   número de teste. (O app antigo da MS, "MS API off", ID 1838539180819325, ficou no portfólio travado.)
3. **Número**: Configuração da API > Adicionar número de telefone (ou Gerenciador do WhatsApp > Números de telefone):
   nome de exibição, número que não esteja em nenhum WhatsApp, código por SMS ou ligação.
4. **Pagamento**: Gerenciador do WhatsApp > Faturamento: cartão da empresa (sem ele nenhum modelo sai, nem o teste).
5. **App ao vivo**: Configurações do app > Básico (ícone, Política de Privacidade
   <https://mscertificados.com.br/politica-de-privacidade/>, categoria) > Publicar. Em modo de desenvolvimento o
   webhook não recebe as mensagens de números reais.
6. **Token**: Configurações do negócio > Usuários > Usuários do sistema > adicionar (Admin) > atribuir o app e a conta
   de mensagens do número (controle total; Contas > Contas de mensagens) > Gerar token: o app, validade "Nunca", permissões `whatsapp_business_messaging`,
   `whatsapp_business_management` e `business_management`.
7. **No sistema**: Configurações > WhatsApp > API oficial da Meta: Identificação do número de telefone, token e chave
   secreta do app (Meta for Developers > app > Configurações do app > Básico); o ID da conta é opcional > **Salvar e
   testar** (liga o app à conta).
8. **Ativar o número** (número novo): senha de 6 números no quadro "Ativar o número na Meta".
9. **Webhook**: Meta for Developers > app > WhatsApp > Configuração: URL de retorno e token de verificação mostrados na
   tela do sistema; assinar o campo `messages`.
10. **Enviar teste**: mande antes um "oi" do seu celular para o número oficial; o teste vai como texto simples.
11. Etapa 2: **Enviar os modelos para a Meta aprovar**; aprovado, **Enviar um aviso de exemplo** e ligar o envio pela
    API na tela Renovação (quadro 4).
