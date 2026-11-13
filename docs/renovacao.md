# Renovação (avisos de vencimento do certificado)

Pedido da Maria em 12/11/2026: "um espaço para renovação, com as mesmas funcionalidades das Empresas novas, só que a
base vem da planilha". Código em `app/renovacao.py` (regras), `app/rotas/renovacao.py` + `app/templates/renovacao.html`
(tela `/renovacao`, menu "Renovação"). Testes em `testes/test_renovacao.py`. Manual: LEIAME, seção "Renovação".

## Fluxo

1. **Importar** (`ler_planilha` → `importar`): o "Relatório de renovação" da certificadora (.xlsx ou CSV, todas as
   abas; o cabeçalho é achado nas 15 primeiras linhas pela coluna Vencimento). Colunas reconhecidas por nome, sem
   acento (`_campo`): Vencimento, Protocolo, Certificado, Razão Social (o relatório sai com o acento estragado, e o
   caractere estragado é ignorado), CNPJ, Cliente, CPF, Email, Telefone, Parceiro. **Email e Telefone vêm duas
   vezes**: os de antes da coluna Cliente são da empresa, os de depois, da pessoa. **Data Nascimento nunca é lida**
   (LGPD: não precisa). Cada linha vira um `Certificado` com `origem="planilha"` (chave = `protocolo`; sem protocolo,
   documento + tipo + vencimento). Importar de novo atualiza os campos e não mexe na situação. Número na célula do
   Excel perde o zero da frente: `_documento` devolve (CPF com 11, CNPJ com 14).
2. **Contato** (`dados_do_registro`): WhatsApp = primeiro celular (11 dígitos com o 9) entre o telefone da pessoa e o
   da empresa; e-mail = o da pessoa, senão o da empresa. Só da planilha (pedido da Maria): nada é buscado em outro
   lugar.
3. **Campanha** (`criar_campanha`, "Montar campanha agora" com 10/20/30/40/50/100 contatos ou `rodada_diaria`):
   certificados `Ativo`, sem campanha, sem `fora_motivo`, vencendo de amanhã até 30 dias (`a_avisar`), **agrupados por
   contato** (`agrupar`: chave = WhatsApp, senão e-mail). Na planilha de 12/11/2026 um número aparece em 57
   certificados: um aviso por certificado seria spam. Ficam de fora (`motivo_de_fora`, as mesmas regras de
   `cadencias.aplicar`): SAIR (grava `fora_motivo`), pessoa atendendo, já respondeu, já em outra sequência. O trabalho
   em etapas (`campanhas.etapa_gerar`, fase `"renovacao"` → `etapa_preparar`) cria ou reaproveita o lead do contato
   (origem `"Renovação (planilha)"`; lead que já existe com o mesmo WhatsApp é reaproveitado, para as respostas não
   embaralharem), prende os certificados (`campanha_id`, `lead_id`) e calcula datas e textos.
4. **Avisos** (`datas_dos_avisos`): 30, 15, 5 e 1 dia antes do vencimento do PRIMEIRO certificado do contato. Fim de
   semana vem para a sexta antes. Quem entra tarde: 1º aviso hoje (ou no próximo dia útil) e só os seguintes que
   cabem com pelo menos 2 dias entre eles (`INTERVALO_MINIMO_DIAS`). As datas vão prontas para `cadencias.aplicar`
   (`datas_por_lead`); o "dia" dos passos da cadência só ordena. Cada tarefa guarda em `certificado_id` o certificado
   que define as datas (`depois_de_montar`).
   **Teto por dia** (`agenda`, `datas_da_campanha`): com a planilha de 12/11/2026, 100 contatos teriam o 1º aviso no
   mesmo dia e o número só faz `limite_frios_whatsapp` (20) contatos frios por dia (o excesso atrasaria mais de 2 dias
   e ficaria esperando clique). A agenda põe no máximo `teto_por_dia` WhatsApps de renovação por dia, contando os já
   marcados nas outras campanhas de renovação (`carga_marcada`): 1ª passada, o 1º aviso de cada contato no primeiro
   dia com vaga (quem vence antes escolhe antes); 2ª passada, os lembretes nas vagas que sobram, no dia certo ou alguns
   dias antes (sem vaga, o lembrete não vai). Sem vaga nenhuma até o vencimento, o 1º aviso vai no dia menos cheio.
   Começa em `primeiro_dia` (hoje, se o horário de envio de hoje não acabou). Quem só tem e-mail não ocupa vaga.
5. **Textos** (`textos_do_contato`, editáveis na tela, `renov_mensagens`): `{vencimentos}` vira a frase do certificado
   ("O certificado digital e-CNPJ A1 em nome de X vence no dia dd/mm/aaaa." / "O seu certificado..." no e-CPF do
   próprio), a lista (até 5) ou um resumo (mais de 5). Também `{responsavel}`, `{data}`, `{vendedor}`,
   `{minha_empresa}`. Sem preço (regra `sdr.texto_sem_spam` ao editar).
6. **Envio**: `renovacao` está em `campanhas.TIPOS_QUE_SAEM_SOZINHOS` e `TIPOS_WHATSAPP_PRIMEIRO` (igual às Empresas
   novas: WhatsApp sozinho depois da aprovação, e-mail ~2 h depois). Na fila do WhatsApp, no mesmo dia, a renovação vem
   antes (`order_by` com `case`): ela e as Empresas novas dividem o limite de contatos frios do número, e nos dias
   cheios de renovação as Empresas novas esperam. Contato sem celular: só e-mail (não fica WhatsApp esperando número).
7. **Aprovação atrasada** (`reajustar_na_aprovacao`): as datas são contadas de novo do vencimento, com o mesmo teto
   por dia; o que não cabe é cancelado (as outras campanhas empurram tudo para frente).
8. **Parar** (`encerrar_toques`, chamado pelas filas e pela rotina de hora em hora): aviso de certificado que venceu
   ou foi marcado Renovado / Não renovará / Avisos cancelados é cancelado. `mudar_situacao` (botões da tela):
   Renovado/Não renovará/"Cancelar avisos" (status `Avisos cancelados`, em `ENCERRADOS`, aba "Avisos cancelados";
   pedido da Maria em 13/11/2026) cancela os avisos pendentes do contato (se ele tiver outro certificado ativo na mesma campanha, os avisos passam a
   seguir esse outro); Reabrir volta para a fila se a campanha acabou. Cancelar a campanha devolve à fila quem não
   recebeu nenhum aviso (`liberar_da_campanha`); excluir marca `fora_motivo` em quem já recebeu (`antes_de_excluir`).
9. **Arte do aviso** (pedido da Maria em 12/11/2026: "pegue o HTML e vá atualizando para cada cliente"): a arte
   é a do site, `https://mscertificados.com.br/interno/aviso-vencimento` (canvas 1080 x 1350). Com `renov_arte` = 1
   (padrão), `arte_do_toque` monta os dados do toque (`tarefa`, `modelo` cnpj/cpf, `tipo` A1/A3, `nome`, `doc`, `data`)
   só para contato com UM certificado ativo na campanha (com vários, a lista vai no texto). `sdr.enviar_whatsapp_conectado`
   manda em `whatsapp_leads.enviar(arte=...)` → `PonteWhatsApp.arte` (JSON) → a troca da ponte leva `envio["arte"]`. O
   computador do WhatsApp Leads (`app/arte_aviso.py` lá) baixa a página do site (de novo a cada 6 h; última cópia boa
   se o site cair), injeta os dados, escreve "FALTAM N DIAS" ao lado de "AVISO DE VENCIMENTO" e exporta o próprio
   canvas pelo Google Chrome sem janela (`--dump-dom`; o Edge não serve). A imagem sai com o texto de legenda, PARA
   TODOS (também contato frio: risco aceito pela Maria; nas outras campanhas a imagem continua só para quem já
   conversou). Uma cópia volta em `POST /api/ponte/arte/<id da ponte>` (senha da ponte) → `ArteAviso` (guardada
   `DIAS_GUARDANDO_ARTE` dias, `limpar_artes` na rotina de hora em hora; fora do backup) e vai no e-mail do mesmo
   aviso, dentro do HTML (`email_com_arte`, `cid:arte-aviso`, multipart/related em `email_smtp.enviar(imagens=)`).
   Sem Chrome ou com erro, sai só o texto; a tela avisa quando nenhuma arte voltou em 7 dias (`situacao_das_artes`).
10. **Área de teste** (`POST /renovacao/testar`, `enviar_teste`; pedido da Maria em 12/11/2026, "igual à da IA SDR",
    com a opção de mandar a arte): manda os avisos (o 1º, um deles ou os 4) para o WhatsApp ou o e-mail de quem testa,
    com "[TESTE · cliente · aviso]" no começo, pelo número/conta de quem assina as campanhas (`dono`, senão quem
    testa). O contato vem de `contato_do_teste`: o cliente escolhido (com os outros certificados do mesmo contato que
    entrariam na mesma campanha: com mais de um, vai a lista e sem a arte, como no envio de verdade) ou o cliente
    fictício (`EXEMPLO_TESTE`, vence em 30 dias). Com "Mandar a arte junto", o WhatsApp vai pela ponte com
    `arte = {"teste": id do certificado, ...}` (sem `tarefa`), `manual=True`. O teste de e-mail leva a arte que voltou do
    teste de WhatsApp do mesmo cliente na última hora (`arte_do_teste_no_email`). Não mexe em campanha nem certificado.
11. **Número do WhatsApp** (pedido da Maria em 12/11/2026, depois que o teste dela saiu pelo "principal" em MODO
    TESTE, que só simula): `renov_conexao` (tela, só com `campanhas.escolher_numero`) é gravado em cada campanha nova
    (`Campanha.conexao_id`, troca na página da campanha). Vazio = `numero_automatico`: o número de quem assina ou um
    compartilhado, preferindo SEMPRE um conectado por QR a um em modo teste. No teste, o número escolhido no quadro
    (`conexao_teste`) vale como foi escolhido e a tela avisa quando ele está em modo teste (`numero_em_modo_teste`).
    `numeros_para_escolher` lista todos com conectado/modo teste. A área de teste é o 1º quadro da tela.
12. **Dias, horário e início configuráveis** (piloto da Maria de 13/11/2026 a 01/01/2027): `renov_dias` (4 dias,
    `dias_aviso`, padrão 30,15,5,1; piloto 12,6,3,1) — `janela` = o 1º dia (quem entra na campanha), `nomes_dos_avisos`
    nas telas; `renov_hora_inicio` (`hora_inicio`, ex.: 10:00) vai como `hora_minima` para `cadencias.aplicar` →
    `dia_e_hora_futuros`/`hora_natural`/`depois_de(minimo=)` e na aprovação (`campanhas._hora_minima`,
    `_sem_horario_no_passado(minimo)`); `renov_ativo_desde` faz a `rodada_diaria` esperar a data. `criar_campanha(ate=,
    nome=)` monta com todos até uma data (o piloto, até 31/12) e divide o contato em **ondas** (`ondas`: certificados a
    mais de `janela` dias do primeiro da onda): a 1ª onda vai pelo `cadencias.aplicar` normal; as seguintes, em
    `montar_ondas` (aplicar com `permitir_em_andamento`), cada aviso com o `certificado_id` da onda (arte e "Renovado"
    por onda: `arte_do_toque` e `mudar_situacao` olham só a onda do aviso). Os textos terminam com "Se você já renovou,
    pode desconsiderar esta mensagem."
13. **Onde aparece** (pedido da Maria em 13/11/2026: "preciso dela como renovação"): a campanha de renovação é uma
    `Campanha` com `tipo="renovacao"`, aberta na página comum `/campanhas/<id>`, mas a página marca o menu Renovação, mostra
    "Campanha de Renovação" no topo (sem cidade/tom da IA SDR) e o "Voltar" leva à tela Renovação
    (`rotas/sdr.AREAS_DAS_CAMPANHAS`; Empresas novas: igual, para a tela delas). A lista da IA SDR (`/campanhas`) não
    mostra campanhas de renovação: elas ficam no quadro "Campanhas de renovação" da tela Renovação.
14. **Só em dia comercial** (pedido da Maria em 13/11/2026: "segunda a sexta das 10:00 - 18:00"):
    `fora_do_horario(db, momento, margem_minutos)` devolve o motivo no sábado/domingo, antes de `hora_inicio`
    (`renov_hora_inicio`) ou a partir de `hora_fim` (`renov_hora_fim`, padrão 18:00) menos a margem. As filas
    (`campanhas.processar_fila` e `processar_fila_whatsapp`, este com `MARGEM_WHATSAPP_MINUTOS`=10, porque o WhatsApp
    ainda passa pelo computador do WhatsApp Leads) tiram as campanhas `tipo="renovacao"` da consulta fora do horário (as
    outras seguem); `disparar` e `_enviar_toque` (Minha fila) param com o motivo. As datas também: `hora_maxima`/`maximo`
    em `cadencias.aplicar`/`hora_natural`/`dia_e_hora_futuros`/`depois_de`, `campanhas._hora_maxima` e
    `primeiro_dia`; a Renovação sempre pula o fim de semana (`pular_fds=True`, mesmo com a opção geral desligada).
    Vence no sábado ou no domingo ("os de sábados e domingos avisar na sexta"): o último aviso fica na sexta
    (`_limites_para_a_sexta`: os avisos de antes ficam pelo menos `INTERVALO_MINIMO_DIAS` antes dela; ex.: vence no
    domingo com 12, 6, 3 e 1: o de 3 dias vai da quinta para a quarta). Nenhum aviso depois do vencimento.
    **Feriados** ("Sim, pular feriados", mesmo dia): `util.feriados_nacionais(ano)` (fixos + Carnaval, Sexta-feira Santa
    e Corpus Christi a partir de `util.pascoa`) + `renov_feriados` ("Outros feriados" da tela, `feriados_extras`:
    "DD/MM" todo ano, "DD/MM/AAAA" só nele) → `feriados_da_renovacao(db, anos)` / `dias_sem_envio(db)` (este ano e o
    próximo). Feriado conta como fim de semana em tudo: `fora_do_horario`, `datas_dos_avisos`/`agenda`/
    `_limites_para_a_sexta` (parâmetro `feriados`; vence num feriado ou a sexta é feriado: o último aviso vai para o
    dia útil antes), `cadencias.dia_e_hora_futuros`/`depois_de`/`aplicar(feriados=)` e `campanhas._feriados` (montagem
    e `_sem_horario_no_passado` na aprovação). Avisos já marcados num feriado (a piloto, montada antes; ou feriado novo
    salvo na tela): `remarcar_feriados(db, aplicar=True)` leva cada um ao dia útil mais perto (antes, se der) com 2 dias
    dos vizinhos, até o vencimento e com vaga no teto de WhatsApps; sem vaga de WhatsApp, só o e-mail; sem dia, cancela.
    O e-mail vai de novo para ~2 h depois do WhatsApp. A tela chama ao salvar um feriado novo.
    `emails_no_prazo(db, camp)` (na montagem e na aprovação): o e-mail que ficaria para depois do vencimento
    (WhatsApp numa sexta à tarde, vence no sábado) sai no mesmo dia e horário do WhatsApp.
    **Aprovar na tela** (pedido da Maria em 13/11/2026): a tela Renovação mostra no topo a campanha
    `aguardando_aprovacao` com o botão (e a lista de campanhas também); o formulário manda `voltar=/renovacao` e
    `rotas/sdr.acao_campanha` volta para lá (só endereços de `AREAS_DAS_CAMPANHAS`). A página da campanha de renovação
    tem o botão na faixa "APROVAÇÃO NECESSÁRIA".
15. **Respostas**: o fluxo normal (cancela os próximos toques, Oportunidade). A IA SDR não responde
   (`empresas_novas.e_lead_de_venda` inclui a origem "Renovação"). No WhatsApp Leads o contato ganha a etiqueta da IA
   SDR (a Atendente IA de lá não responde).

## Banco

Tabela nova `artes_aviso` (cópia da arte para o e-mail) e coluna `ponte_whatsapp.arte`. Colunas novas em
`certificados` (migração automática): `origem`, `protocolo`, `responsavel`, `whatsapp`, `telefone`,
`email`, `parceiro_nome`, `lead_id`, `campanha_id`, `fora_motivo`, `importado_em`. O controle antigo de vencimentos
(`vendas_servico.processar_vencimentos`, menu Vencimentos, escondido na MS) só marca "Vencido" nos certificados da
planilha e não cria tarefa manual para eles.

Configurações (`renov_*`): `renov_ativo`, `renov_hora`, `renov_maximo_dia`, `renov_canais`, `renov_dono_id`,
`renov_mensagens`, `renov_ultima_rodada`, `renov_ultimo_resultado`, `renov_ultima_importacao`, `renov_arte`.

## Permissões

Mesmas das Empresas novas: ver `campanhas.ver`; importar, montar, configurar, mensagens e situação do certificado
`campanhas.gerenciar`.
