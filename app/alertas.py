"""Avisos por e-mail quando algo para (auditoria de 11/11/2026, P0.2: em 07/11 os números ficaram 19 horas parados
sem ninguém saber).

A cada 5 minutos (rotinas.rodada) o sistema confere:
- o computador com o WhatsApp Leads (a ponte) parado há mais de 15 minutos;
- número de WhatsApp em uso desconectado há mais de 15 minutos;
- o banco perto de encher (80% do tamanho contratado);
- uma rotina (fila de e-mail, fila do WhatsApp, leitura de respostas...) falhando 3 vezes seguidas;
- e-mails da fila falhando (5 ou mais na última hora);
- número com os contatos frios pausados por pedidos de SAIR (mensagens.limite_de_frios);
- o agendador que ficou mais de 30 minutos sem rodar (aviso quando ele volta);
- a cópia de segurança (backup) feita no computador da MS parada há mais de 3 dias e meio.

Cada problema vira UM e-mail para os administradores (ou para a lista em Configurações), um lembrete a cada 12 horas
enquanto durar e um e-mail de "resolvido" quando volta ao normal. Também aparece no sino do sistema.
Só roda na nuvem (no computador local o sistema é uma cópia de testes)."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select, text

from . import config
from .banco import agora, gravar_config, ler_config, ler_config_int, ler_config_json, sessao
from .modelos import Mensagem, Notificacao, Usuario

log = logging.getLogger(__name__)

ESTADO = "alertas_estado"        # {chave: {"titulo", "texto", "link", "desde", "avisado_em"}}
FALHAS = "alertas_falhas"        # {rotina: {"seguidas", "erro", "desde"}}
ULTIMA_RODADA = "alertas_ultima_rodada"
REPETIR = timedelta(hours=12)    # lembrete enquanto o problema durar
ESPERA_PONTE = timedelta(minutes=15)
ESPERA_NUMERO = timedelta(minutes=15)
FALHAS_SEGUIDAS = 3
BURACO_DO_AGENDADOR = timedelta(minutes=30)
BACKUP_ATRASADO = timedelta(hours=84)  # 3 dias e meio (o fim de semana sem backup não avisa)
NOMES_ROTINAS = {"fila_email": "fila de e-mails", "fila_whatsapp": "fila do WhatsApp",
                 "sincronizar_whatsapp": "leitura das respostas do WhatsApp", "ler_emails": "leitura das respostas por e-mail",
                 "empresas_novas": "busca diária de Empresas novas", "rotina_hora": "rotina de hora em hora"}


def ligado() -> bool:
    return config.NA_NUVEM or config.ALERTAS_LIGADOS


def destinatarios(db) -> list[str]:
    """Quem recebe os avisos: a lista de Configurações (alertas_emails) ou, se vazia, os administradores ativos."""
    lista = [e.strip() for e in (ler_config(db, "alertas_emails") or "").replace(";", ",").split(",") if "@" in e]
    if lista:
        return lista
    return [u.email for u in db.execute(select(Usuario).where(Usuario.perfil == "admin", Usuario.ativo.is_(True))
                                        .order_by(Usuario.id)).scalars() if u.email]


# ---------------------------------------------------------------- O que está errado agora

def _ler_data(texto) -> datetime | None:
    try:
        return datetime.fromisoformat(str(texto)) if texto else None
    except ValueError:
        return None


def _numeros_em_uso(db) -> set[str]:
    """Números que mandaram WhatsApp nos últimos 7 dias (número parado de quem não usa não gera aviso)."""
    return set(db.execute(select(Mensagem.conexao).where(
        Mensagem.canal == "whatsapp", Mensagem.direcao == "saida", Mensagem.conexao != "",
        Mensagem.criado_em >= agora() - timedelta(days=7)).distinct()).scalars())


def _nomes_dos_numeros(db) -> dict[str, str]:
    from .modelos import ConexaoWhatsApp

    return {c.id: c.nome or c.id for c in db.execute(select(ConexaoWhatsApp)).scalars()}


def tamanho_do_banco_mb(db) -> float | None:
    if db.get_bind().dialect.name != "postgresql":
        return None
    return (db.execute(text("select pg_database_size(current_database())")).scalar() or 0) / 1024 / 1024


def problemas_agora(db) -> dict[str, dict]:
    """{chave: {"titulo", "texto", "link", "desde"}} dos problemas de agora. "desde" = quando começou (se souber)."""
    from . import mensagens

    agora_ = agora()
    achados: dict[str, dict] = {}

    if config.WHATSAPP_PONTE:
        status = ler_config_json(db, "wl_status", {}) or {}
        visto = _ler_data(status.get("visto_em"))
        if visto is None or agora_ - visto > ESPERA_PONTE:
            achados["ponte"] = {
                "titulo": "WhatsApp parado: o computador do WhatsApp Leads não responde",
                "texto": (f"Desde {visto:%d/%m às %H:%M} " if visto else "Faz tempo que ")
                + "o computador que mantém os WhatsApps conectados não fala com o sistema. Enquanto isso nenhum "
                "WhatsApp sai nem chega, e as respostas dos leads não aparecem.\n\nO que fazer: ligar o computador, "
                "conferir a internet e abrir o ligar_nuvem.bat do WhatsApp Leads.",
                "link": "/whatsapp", "desde": visto.isoformat() if visto else ""}
        else:
            em_uso = _numeros_em_uso(db)
            nomes = _nomes_dos_numeros(db)
            listados = status.get("conexoes")
            if listados is None:  # versão antiga do WhatsApp Leads: um número só
                listados = {"principal": {"conectado": status.get("conectado"), "estado": status.get("estado")}}
            # Número que o computador não conhece sai pelo principal (WhatsApp Leads, automacoes.Fila._enviar):
            # é o principal que precisa estar conectado.
            vigiados = {cx if cx in listados else "principal" for cx in em_uso}
            for id_conexao in sorted(vigiados):
                dados = listados.get(id_conexao) or {}
                if not dados.get("conectado"):
                    nome = nomes.get(id_conexao, id_conexao)
                    achados[f"numero:{id_conexao}"] = {
                        "titulo": f"WhatsApp desconectado: {nome}",
                        "texto": (f"O número \"{nome}\" está desconectado ({(dados or {}).get('estado') or 'sem conexão'}). "
                                  "As mensagens dele ficam paradas até ele voltar.\n\nO que fazer: abrir o WhatsApp > "
                                  "Meu WhatsApp no sistema e ler o QR code de novo com o celular desse número."),
                        "link": "/whatsapp", "espera": ESPERA_NUMERO}
            pausa = ler_config_int(db, "pausa_frios_sair", 0)
            for id_conexao in sorted(em_uso) if pausa else []:
                if mensagens.pedidos_para_sair_hoje(db, id_conexao) >= pausa:
                    nome = nomes.get(id_conexao, id_conexao)
                    achados[f"pausado:{id_conexao}:{agora_.date().isoformat()}"] = {
                        "titulo": f"WhatsApp {nome}: contatos frios pausados hoje",
                        "texto": (f"Hoje {pausa} ou mais pessoas pediram para sair "
                                  f"depois de receber mensagem do número \"{nome}\". Para proteger o número contra "
                                  "bloqueio, os contatos frios dele ficam parados até amanhã (quem já conversou com a "
                                  "MS continua recebendo).\n\nVale revisar o texto da campanha e a lista de empresas."),
                        "link": "/envios"}

    tamanho = tamanho_do_banco_mb(db)
    contratado = ler_config_int(db, "limite_banco_mb", 500)
    if tamanho is not None and contratado and tamanho >= 0.8 * contratado:
        achados["banco"] = {
            "titulo": f"Banco de dados quase cheio: {tamanho:.0f} de {contratado} MB",
            "texto": (f"O banco da nuvem está com {tamanho:.0f} MB ({tamanho / contratado:.0%} do plano). Se encher, o "
                      "sistema para de gravar (leads, mensagens, respostas).\n\nO que fazer: avisar quem cuida do "
                      "sistema para liberar espaço ou passar o Supabase para o plano pago."),
            "link": "/configuracoes?aba=integracoes"}

    for rotina, dados in (ler_config_json(db, FALHAS, {}) or {}).items():
        if (dados or {}).get("seguidas", 0) >= FALHAS_SEGUIDAS:
            nome = NOMES_ROTINAS.get(rotina, rotina)
            achados[f"rotina:{rotina}"] = {
                "titulo": f"Erro repetido na {nome}",
                "texto": (f"A {nome} falhou {dados['seguidas']} vezes seguidas. Último erro: {dados.get('erro', '')}"
                          "\n\nO que fazer: avisar quem cuida do sistema (o erro completo fica no registro da Vercel)."),
                "link": "/envios", "desde": dados.get("desde", "")}

    backup = ler_config_json(db, "backup_ultimo", {}) or {}
    feito = _ler_data(backup.get("em"))
    if feito is not None and agora_ - feito > BACKUP_ATRASADO:
        achados["backup"] = {
            "titulo": "A cópia de segurança (backup) não é feita há dias",
            "texto": (f"O último backup do banco foi em {feito:%d/%m às %H:%M}. Ele é feito todo dia, depois do "
                      "meio-dia, pelo computador da MS (o Supabase grátis não tem backup).\n\nO que fazer: deixar o "
                      "computador ligado depois do meio-dia ou dar dois cliques em fazer_backup.bat."),
            "link": "/configuracoes?aba=integracoes", "desde": feito.isoformat()}

    desde = agora_ - timedelta(hours=1)
    falhas, total = db.execute(select(
        func.count(Mensagem.id).filter(Mensagem.status == "falhou"), func.count(Mensagem.id)).where(
        Mensagem.canal == "email", Mensagem.direcao == "saida", Mensagem.criado_em >= desde)).one()
    if falhas >= 5 and falhas >= total / 2:
        achados["email"] = {
            "titulo": "E-mails da fila não estão saindo",
            "texto": (f"Na última hora {falhas} de {total} e-mails falharam. Pode ser a senha de app do Google, a caixa "
                      "de envio cheia ou o servidor recusando.\n\nO que fazer: abrir Envios > Enviados (filtro "
                      "\"Não saiu\") para ver o erro e conferir Configurações > E-mail."),
            "link": "/envios"}
    return achados


# ---------------------------------------------------------------- Mandar, lembrar e avisar que resolveu

def _avisar(db, assunto: str, corpo: str, link: str) -> bool:
    """E-mail para a lista + aviso no sino dos administradores. Devolve se o e-mail saiu."""
    from .integracoes import email_smtp

    for admin in db.execute(select(Usuario).where(Usuario.perfil == "admin", Usuario.ativo.is_(True))).scalars():
        db.add(Notificacao(usuario_id=admin.id, texto=assunto[:300], link=link))
    if not email_smtp.configurado():
        log.warning("Aviso sem e-mail (e-mail de envio não configurado): %s", assunto)
        return False
    saiu = False
    for destino in destinatarios(db):
        try:
            email_smtp.enviar(destino, f"[Prospecção MS] {assunto}"[:200],
                              f"{corpo}\n\nAbrir o sistema: {config.URL_PUBLICA}{link}\n\n"
                              "(Aviso automático do sistema de Prospecção da MS.)", com_rodape=False)
            saiu = True
        except email_smtp.ErroEmail as erro:
            log.warning("Aviso por e-mail não saiu para %s: %s", destino, erro)
    return saiu


def _duracao(inicio: datetime, fim: datetime) -> str:
    minutos = max(int((fim - inicio).total_seconds() // 60), 0)
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    return f"{horas} h {resto:02d} min" if horas < 48 else f"{horas // 24} dias"


def verificar(db=None) -> dict:
    """Confere tudo e manda os avisos novos, os lembretes e os "resolvido". Devolve o que fez."""
    if db is None:
        with sessao() as nova:
            return verificar(nova)
    agora_ = agora()
    estado: dict = ler_config_json(db, ESTADO, {}) or {}
    feito = {"novos": 0, "lembretes": 0, "resolvidos": 0}
    atuais = problemas_agora(db)
    for chave, p in atuais.items():
        anterior = estado.get(chave) or {}
        desde = _ler_data(anterior.get("desde")) or _ler_data(p.get("desde")) or agora_
        espera = p.get("espera") or timedelta(0)
        registro = {"titulo": p["titulo"], "texto": p["texto"], "link": p["link"], "desde": desde.isoformat(),
                    "avisado_em": anterior.get("avisado_em", "")}
        avisado = _ler_data(registro["avisado_em"])
        if avisado is None and agora_ - desde >= espera:
            _avisar(db, f"⚠️ {p['titulo']}", p["texto"], p["link"])
            registro["avisado_em"] = agora_.isoformat()
            feito["novos"] += 1
        elif avisado is not None and agora_ - avisado >= REPETIR:
            _avisar(db, f"⚠️ Continua: {p['titulo']}", f"Começou há {_duracao(desde, agora_)}.\n\n{p['texto']}", p["link"])
            registro["avisado_em"] = agora_.isoformat()
            feito["lembretes"] += 1
        estado[chave] = registro
    for chave in [c for c in estado if c not in atuais]:
        anterior = estado.pop(chave)
        if anterior.get("avisado_em") and not chave.startswith("pausado:"):
            desde = _ler_data(anterior.get("desde")) or agora_
            _avisar(db, f"✅ Resolvido: {anterior['titulo']}",
                    f"Voltou ao normal às {agora_:%H:%M} de {agora_:%d/%m} (durou {_duracao(desde, agora_)}).",
                    anterior.get("link", "/"))
            feito["resolvidos"] += 1
    gravar_config(db, ESTADO, estado)
    db.commit()
    return feito


def ativos(db) -> list[dict]:
    """Os problemas avisados que ainda estão abertos (para a tela de Configurações)."""
    estado = ler_config_json(db, ESTADO, {}) or {}
    return [{"chave": c, **v} for c, v in sorted(estado.items(), key=lambda kv: kv[1].get("desde", ""))]


# ---------------------------------------------------------------- Chamado pelas rotinas

def falhou(rotina: str, erro: Exception) -> None:
    """Uma rotina deu erro: conta as falhas seguidas (3 seguidas = aviso)."""
    if not ligado():
        return
    try:
        with sessao() as db:
            falhas = ler_config_json(db, FALHAS, {}) or {}
            dados = falhas.get(rotina) or {"seguidas": 0, "desde": agora().isoformat()}
            dados["seguidas"] = int(dados.get("seguidas", 0)) + 1
            dados["erro"] = (str(erro).splitlines() or [type(erro).__name__])[0][:300] or type(erro).__name__
            falhas[rotina] = dados
            gravar_config(db, FALHAS, falhas)
            db.commit()
    except Exception:  # noqa: BLE001 - o banco pode ser o problema: só registra no log
        log.exception("Não consegui guardar a falha da rotina %s", rotina)


def funcionou(rotina: str) -> None:
    """A rotina rodou sem erro: zera as falhas dela (só grava se havia falha)."""
    if not ligado():
        return
    try:
        with sessao() as db:
            falhas = ler_config_json(db, FALHAS, {}) or {}
            if rotina in falhas:
                falhas.pop(rotina)
                gravar_config(db, FALHAS, falhas)
                db.commit()
    except Exception:  # noqa: BLE001
        log.exception("Não consegui zerar as falhas da rotina %s", rotina)


def marcar_rodada() -> None:
    """Chamado a cada rodada do agendador: se ele ficou mais de 30 minutos sem rodar, avisa (quando volta)."""
    if not ligado():
        return
    try:
        with sessao() as db:
            agora_ = agora()
            ultima = _ler_data(ler_config(db, ULTIMA_RODADA))
            gravar_config(db, ULTIMA_RODADA, agora_.isoformat(timespec="seconds"))
            if ultima is not None and agora_ - ultima > BURACO_DO_AGENDADOR:
                _avisar(db, "⚠️ O agendador ficou parado e voltou agora",
                        f"Entre {ultima:%d/%m %H:%M} e {agora_:%d/%m %H:%M} ({_duracao(ultima, agora_)}) ninguém "
                        "chamou o sistema: nenhum e-mail saiu, nenhuma resposta foi lida e nenhuma campanha andou. "
                        "Já voltou a funcionar.\n\nHoje quem chama o sistema a cada minuto é o computador da MS (e o "
                        "agendador da nuvem, se estiver ligado). Se o computador foi desligado, isso explica.",
                        "/envios")
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("Não consegui marcar a rodada do agendador")
