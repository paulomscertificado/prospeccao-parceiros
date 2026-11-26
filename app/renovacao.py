"""Renovação: avisos de vencimento do certificado digital para os clientes da AR (pedido da Maria em 12/11/2026).

1. A equipe exporta o "Relatório de renovação" do sistema da certificadora (Excel) e importa na tela Renovação. Cada
   linha vira um certificado (tabela certificados, origem "planilha", chave = protocolo): vencimento, tipo, razão
   social/CNPJ ou titular/CPF, responsável, WhatsApp, e-mail e parceiro. A data de nascimento que vem na planilha
   nunca é lida (não precisa). Importar de novo atualiza, sem duplicar.
2. A campanha de renovação ("Montar campanha agora" ou a campanha automática do dia) junta os certificados que vencem
   nos próximos 30 dias POR CONTATO: o mesmo WhatsApp (ou e-mail) recebe UMA mensagem em cada aviso, com a lista dos
   certificados dele. Na planilha de 12/11/2026 um número aparece em 57 certificados (grupo de empresas): mandar um
   aviso por certificado seria spam e risco de bloqueio do número. Cada contato vira um lead ("Renovação (planilha)").
3. Quatro avisos contados do vencimento: 30, 15, 5 e 1 dia antes (pedido da Maria). Quem entra tarde começa pelo
   aviso da etapa dos dias que faltam (pedido da Maria em 19/11/2026: vence amanhã = "Último aviso", nunca o 1º),
   com a frase do SAIR, e recebe só os seguintes que ainda cabem, nunca dois em dias seguidos. Aviso que atrasou
   (número desconectado, fila parada) sai com o texto da etapa do dia em que sai (ajustar_a_etapa). Fim de semana:
   o aviso vem para a sexta antes (nunca para depois do vencimento).
4. Depois da aprovação sai como as Empresas novas (campanhas.TIPOS_QUE_SAEM_SOZINHOS e TIPOS_WHATSAPP_PRIMEIRO):
   WhatsApp sozinho primeiro, com as mesmas travas (um a cada 3 minutos, limites por hora/dia/número, contatos frios
   por dia, horário de envio e SAIR), e o e-mail do mesmo aviso ~2 h depois. Na fila do WhatsApp, os avisos de
   renovação do dia saem antes dos outros (têm prazo). A resposta do cliente para os avisos e vai para a equipe (a IA
   não responde: empresas_novas.e_lead_de_venda).
5. Quem já venceu não recebe nada (pedido da Maria): aviso que não saiu até o vencimento é cancelado (encerrar_toques).
   O contato vem só da planilha (pedido da Maria): sem WhatsApp e sem e-mail nela, o certificado fica em "sem contato".
"""

import csv
import io
import json
import re
import unicodedata
import warnings
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select

from . import util
from .banco import agora, gravar_config, ler_config, sessao, usar_config_da_ar
from .modelos import Campanha, Certificado, Lead, Tarefa, Usuario

ORIGEM = "planilha"                   # Certificado.origem dos que vieram do Relatório de renovação
ORIGEM_LEAD = "Renovação (planilha)"  # Lead.origem dos contatos criados aqui
TIPO_CAMPANHA = "renovacao"
DIAS_AVISO = (30, 15, 5, 1)           # dias antes do vencimento (pedido da Maria em 12/11/2026)
JANELA_DIAS = DIAS_AVISO[0]           # entra na campanha quem vence nos próximos 30 dias
INTERVALO_MINIMO_DIAS = 2             # entre dois avisos para o mesmo contato (nunca em dias seguidos)
QUANTIDADES = (10, 20, 30, 40, 50, 100)  # "Montar campanha agora": quantos contatos
MAXIMO_NA_LISTA = 5                   # a mensagem lista até 5 certificados; com mais, vai um resumo
ENCERRADOS = ("Renovado", "Não renovará", "Vencido", "Avisos cancelados")
# "Avisos cancelados": botão "Cancelar avisos" da tela (pedido da Maria em 13/11/2026), sem dizer se renovou ou não
SITUACOES = {"Renovado": "Renovado", "Não renovará": "Não vai renovar", "Avisos cancelados": "Avisos cancelados",
             "Ativo": "Reabrir"}

ANGULOS = {
    "renov_aviso": "1º aviso (30 dias antes)",
    "renov_lembrete": "Lembrete (15 dias antes)",
    "renov_reforco": "Faltam poucos dias (5 dias antes)",
    "renov_ultimo": "Último aviso (1 dia antes)",
}
PRIMEIRO_AVISO = "renov_aviso"  # o único que diz quem escreve e traz o SAIR (ver textos_do_contato, primeiro=)
CADENCIA_NOME = "Renovação – avisos (30, 15, 5 e 1 dia antes do vencimento)"
# O "dia" do passo só ordena e aparece na tela: a data de cada aviso é contada do vencimento de cada contato
# (datas_dos_avisos, passada para cadencias.aplicar em datas_por_lead).
CADENCIA_PASSOS = [(1, "renov_aviso", "1º aviso do vencimento"), (16, "renov_lembrete", "Lembrete do vencimento"),
                   (26, "renov_reforco", "Faltam poucos dias para vencer"), (30, "renov_ultimo", "Último aviso")]

PADRAO = {
    "renov_ativo": "0",               # campanha automática do dia
    "renov_hora": "07:45",
    "renov_maximo_dia": "40",         # contatos por campanha automática
    "renov_canais": "whatsapp,email",
    "renov_dono_id": "",
    "renov_ultima_rodada": "",        # dia em que a campanha automática rodou (AAAA-MM-DD)
    "renov_ultimo_resultado": "",
    "renov_ultima_importacao": "",
    "renov_pontos_fora": "",          # pontos de atendimento da planilha sem avisos (26/11/2026: o Gilberto Contábil)
    "renov_ultima_importacao_em": "",  # quando começou a última importação (AAAA-MM-DDTHH:MM:SS): "todos da planilha"
    "renov_arte": "1",                # a arte do aviso (a do site) vai junto no WhatsApp e no e-mail
    "renov_conexao": "",              # número de WhatsApp dos disparos ("" = automático, sempre um número de verdade)
    "renov_envio_oficial": "0",       # WhatsApp dos avisos pela API oficial da Meta (etapa 2, whatsapp_oficial.py)
    "renov_agenda": "0",              # o calendário para quem toca em "Quero renovar" (API oficial; 23/11/2026)
    "renov_agenda_usuario_id": "",    # de quem é a agenda que recebe os horários ("" = quem cuida do cliente)
    "renov_email_html": "1",          # botão "E-mail em HTML com a marca" (só aparece com o módulo liberado)
    "renov_dias": "30,15,5,1",        # dias antes do vencimento dos 4 avisos (piloto de 13/11/2026: 12, 6, 3 e 1)
    "renov_hora_inicio": "",          # os avisos saem a partir deste horário ("" = o horário de envio geral)
    "renov_hora_fim": "18:00",        # e até este (pedido da Maria em 13/11/2026: segunda a sexta, das 10:00 às 18:00)
    "renov_feriados": "",             # outros feriados sem avisos (cidade/estado): "08/12" todo ano, "08/12/2026" só nele
    "renov_ativo_desde": "",          # a campanha automática só começa nesta data (AAAA-MM-DD; "" = já)
}
URL_DA_ARTE = "https://mscertificados.com.br/interno/aviso-vencimento"  # quem desenha: whatsapp-leads/app/arte_aviso.py
CHAVE_URL_DA_ARTE = "renov_arte_url"  # o endereço da arte de cada marca (quadro 4; só o Admin Master troca)
MARCAS_DA_ARTE = ('id="cv"', "function update")  # o desenho que a página precisa ter (o WhatsApp Leads confere igual)


def url_da_arte(db, ar: int | None) -> str:
    """O endereço da página do site que desenha a arte do aviso da marca `ar` (pedido da Maria em 23/11/2026: um campo
    editável na Renovação, quadro 4, que só o Admin Master troca). Sem endereço próprio, a AR MS usa a do site da MS
    (URL_DA_ARTE) e as outras marcas mandam só o texto (vazio): a arte de uma marca nunca vai no aviso de outra."""
    from . import marca
    from .banco import config_propria_da_ar

    ar = ar or marca.ar_padrao(db)
    proprio = (config_propria_da_ar(db, ar, CHAVE_URL_DA_ARTE) or "").strip()
    if proprio:
        return proprio
    return URL_DA_ARTE if marca.da_ar(db, ar)["e_ms"] else ""


def endereco_publico(url: str) -> bool:
    """https de um site da internet (pelo nome, nunca pelo número), que não leva a este servidor nem à rede interna:
    quem abre a página da arte é o servidor."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    try:
        partes = urlsplit(url)
        porta = partes.port or 443
    except ValueError:
        return False
    host = (partes.hostname or "").lower().rstrip(".")
    if (partes.scheme != "https" or "." not in host or partes.username or partes.password or len(url) > 300
            or host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".arpa"))):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    try:
        enderecos = {i[4][0] for i in socket.getaddrinfo(host, porta, proto=socket.IPPROTO_TCP)}
    except (OSError, UnicodeError):
        return False
    return bool(enderecos) and all(ipaddress.ip_address(e.split("%")[0]).is_global for e in enderecos)


def _pagina_da_arte(url: str) -> str:
    """O HTML da página da arte (segue até 3 mudanças de endereço, sempre para um site da internet)."""
    import httpx

    for _ in range(4):
        r = httpx.get(url, timeout=15, follow_redirects=False)
        if r.is_redirect and r.next_request is not None:
            url = str(r.next_request.url)
            if not endereco_publico(url):
                raise ValueError("a página leva para um endereço que não é de um site da internet")
            continue
        r.raise_for_status()
        return r.text
    raise ValueError("a página muda de endereço vezes demais")


WIX_DADOS_DA_PAGINA = re.compile(r"https://siteassets\.parastorage\.com/pages/pages/thunderbolt\?[^\"'<>\s]+")
WIX_HTML_INCORPORADO = re.compile(r"https://[a-z0-9-]+\.filesusr\.com/html/[A-Za-z0-9_]+\.html")
MOLDURA = re.compile(r"<iframe[^>]+src=[\"']([^\"']+)", re.IGNORECASE)


def _ferramenta_na_moldura(url: str, html: str) -> str:
    """A página do site sem o desenho pode trazer a ferramenta numa moldura (iframe). No Wix (o site do Grupo Certy,
    23/11/2026), o "HTML incorporado" fica noutro endereço (www-<site>.filesusr.com/html/...), que só aparece nos
    dados da página (o módulo "thunderbolt-features" do Wix). Devolve o endereço da moldura com o desenho, ou ""."""
    from urllib.parse import urljoin

    import httpx

    candidatos = [urljoin(url, src) for src in MOLDURA.findall(html)]
    for modulo in WIX_DADOS_DA_PAGINA.findall(html):
        modulo = modulo.replace("&amp;", "&")
        if "module=thunderbolt-features" not in modulo:
            continue
        try:
            candidatos += WIX_HTML_INCORPORADO.findall(_pagina_da_arte(modulo))
        except (httpx.HTTPError, ValueError):
            continue
    for candidato in list(dict.fromkeys(candidatos))[:6]:
        if not endereco_publico(candidato):
            continue
        try:
            pagina = _pagina_da_arte(candidato)
        except (httpx.HTTPError, ValueError):
            continue
        if all(m in pagina for m in MARCAS_DA_ARTE):
            return candidato
    return ""


def conferir_endereco_da_arte(db, ar: int | None, url: str) -> tuple[str, str]:
    """Confere o endereço antes de gravar: (endereço a gravar, problema). Precisa ser https de um site da internet, a
    página abrir e ter o desenho da arte (a ferramenta de aviso do site da MS, copiada com o logo e as cores da marca).
    Se a página do site traz a ferramenta numa moldura (Wix, iframe), grava o endereço da ferramenta."""
    import httpx

    from . import marca

    if not url.lower().startswith("https://"):
        return "", "o endereço precisa começar com https://"
    if url.rstrip("/").lower() == URL_DA_ARTE.lower() and not marca.da_ar(db, ar or marca.ar_padrao(db))["e_ms"]:
        return "", "esse é o endereço da arte da MS, com a marca da MS: use a página com a marca desta AR"
    if not endereco_publico(url):
        return "", "o endereço não é de um site da internet (confira se está certo e se o site está no ar)"
    try:
        html = _pagina_da_arte(url)
    except httpx.HTTPStatusError as erro:
        return "", f"o site respondeu com o erro {erro.response.status_code} (confira o endereço)"
    except httpx.HTTPError:
        return "", "o site não respondeu (confira o endereço e se o site está no ar)"
    except ValueError as erro:
        return "", str(erro)
    if all(m in html for m in MARCAS_DA_ARTE):
        return url, ""
    dentro = _ferramenta_na_moldura(url, html)
    if dentro:
        return dentro, ""
    return "", ("a página abriu, mas não tem o desenho da arte do aviso (precisa ser uma cópia da ferramenta de aviso "
                "do site da MS, com os mesmos campos)")


DIAS_GUARDANDO_ARTE = 10  # a cópia da arte que voltou do computador (para o e-mail) fica só uns dias
# E-mail com a arte: a imagem primeiro (como no WhatsApp, onde o texto é a legenda) e o texto do aviso embaixo
HTML_EMAIL_COM_ARTE = (
    "<!doctype html><html><body style=\"margin:0;padding:24px 12px;background:#F3F6FA\">"
    "<div style=\"max-width:560px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;font-size:15px;"
    "line-height:1.5;color:#0E3B66\">"
    "<img src=\"cid:arte-aviso\" alt=\"Aviso de vencimento do certificado digital\" width=\"540\" "
    "style=\"display:block;width:100%;max-width:540px;height:auto;border-radius:12px;margin:0 0 20px\">"
    "{{mensagem}}"
    "<div style=\"font-size:12px;color:#777;margin:22px 0 0;text-align:center\">{{descadastro}}</div>"
    "</div></body></html>")

# {vencimentos} vira a frase (ou a lista) dos certificados do contato com as datas; {data} é o primeiro vencimento.
MENSAGENS_PADRAO = {
    "renov_aviso": {
        "assunto": "Vencimento do certificado digital ({data})",
        "whatsapp": ("Olá, {responsavel}! Tudo bem? Aqui é {vendedor}, da {minha_empresa}.\n\n{vencimentos}\n\n"
                     "Quer que eu já deixe tudo encaminhado para a renovação, para você não ficar sem certificado?\n\n"
                     "Se você já renovou, pode desconsiderar esta mensagem.\n\n(Se não quiser receber estes avisos, é só responder SAIR.)"),
        "email": ("Olá, {responsavel}! Tudo bem?\n\nAqui é {vendedor}, da {minha_empresa}.\n\n{vencimentos}\n\n"
                  "Quer que eu já deixe tudo encaminhado para a renovação, para você não ficar sem certificado? "
                  "É só responder este e-mail.\n\nSe você já renovou, pode desconsiderar esta mensagem."),
    },
    "renov_lembrete": {
        "assunto": "Lembrete: certificado digital vence em {data}",
        "whatsapp": ("Olá, {responsavel}! Passando para lembrar:\n\n{vencimentos}\n\nPosso te ajudar com a renovação?"
                     "\n\nSe você já renovou, pode desconsiderar esta mensagem."),
        "email": ("Olá, {responsavel}!\n\nPassando para lembrar:\n\n{vencimentos}\n\n"
                  "Posso te ajudar com a renovação? É só responder este e-mail.\n\nSe você já renovou, pode desconsiderar esta mensagem."),
    },
    "renov_reforco": {
        "assunto": "Faltam poucos dias: certificado digital vence em {data}",
        "whatsapp": ("Olá, {responsavel}! Faltam poucos dias:\n\n{vencimentos}\n\n"
                     "Renovando antes do vencimento, você não fica sem certificado. Vamos agendar?\n\nSe você já renovou, pode desconsiderar esta mensagem."),
        "email": ("Olá, {responsavel}!\n\nFaltam poucos dias:\n\n{vencimentos}\n\n"
                  "Renovando antes do vencimento, você não fica sem certificado. Quer agendar a renovação? "
                  "É só responder este e-mail.\n\nSe você já renovou, pode desconsiderar esta mensagem."),
    },
    "renov_ultimo": {
        "assunto": "Último aviso: certificado digital vence em {data}",
        "whatsapp": ("Olá, {responsavel}! Último aviso:\n\n{vencimentos}\n\n"
                     "Se precisar renovar, é só responder aqui que eu te atendo.\n\nSe você já renovou, pode desconsiderar esta mensagem."),
        "email": ("Olá, {responsavel}!\n\nÚltimo aviso:\n\n{vencimentos}\n\n"
                  "Se precisar renovar, é só responder este e-mail que eu te atendo.\n\nSe você já renovou, pode desconsiderar esta mensagem."),
    },
}
CAMPOS_DA_MENSAGEM = ("responsavel", "vencimentos", "data", "vendedor", "minha_empresa")


# ---------------------------------------------------------------- Configurações

def cfg(db, chave: str) -> str:
    valor = ler_config(db, chave)
    return valor if valor != "" else PADRAO.get(chave, "")


def mensagens(db) -> dict:
    try:
        salvas = json.loads(ler_config(db, "renov_mensagens") or "{}")
    except ValueError:
        salvas = {}
    return {a: {**MENSAGENS_PADRAO[a], **(salvas.get(a) or {})} for a in MENSAGENS_PADRAO}


def dono(db) -> Usuario | None:
    uid = util.para_int(cfg(db, "renov_dono_id"))
    return db.get(Usuario, uid) if uid else None


def dias_aviso(db) -> tuple[int, ...]:
    """Os dias antes do vencimento dos 4 avisos (tela Renovação; padrão 30, 15, 5 e 1). Inválido: o padrão."""
    try:
        dias = tuple(sorted({int(x) for x in re.split(r"[,; ]+", cfg(db, "renov_dias")) if x.strip()}, reverse=True))
    except ValueError:
        return DIAS_AVISO
    if len(dias) != len(DIAS_AVISO) or dias[-1] < 1 or dias[0] > 90:
        return DIAS_AVISO
    return dias


def janela(db) -> int:
    """Entra na campanha quem vence até o dia do 1º aviso (ex.: 30 ou 12 dias)."""
    return dias_aviso(db)[0]


def nomes_dos_avisos(dias: tuple[int, ...] = DIAS_AVISO) -> dict:
    """Nome de cada aviso com os dias da configuração (ex.: "1º aviso (12 dias antes)")."""
    def antes(n):
        return "1 dia antes" if n == 1 else f"{n} dias antes"

    return {"renov_aviso": f"1º aviso ({antes(dias[0])})", "renov_lembrete": f"Lembrete ({antes(dias[1])})",
            "renov_reforco": f"Faltam poucos dias ({antes(dias[2])})", "renov_ultimo": f"Último aviso ({antes(dias[3])})"}


def hora_inicio(db) -> str:
    """Os avisos saem a partir deste horário (tela; "" = o horário de envio geral)."""
    valor = cfg(db, "renov_hora_inicio").strip()
    return valor if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", valor) else ""


def hora_fim(db) -> str:
    """Os avisos saem até este horário (tela; padrão 18:00). Inválido: "" (vale só o horário de envio geral)."""
    valor = cfg(db, "renov_hora_fim").strip()
    return valor if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", valor) else ""


def feriados_extras(texto: str) -> tuple[list[str], list[str]]:
    """Os "Outros feriados" da tela: "08/12" (todo ano) ou "08/12/2026" (só naquele ano), separados por vírgula.
    Devolve (os válidos, no formato DD/MM ou DD/MM/AAAA; os que não deu para entender)."""
    validos: list[str] = []
    invalidos: list[str] = []
    for item in re.split(r"[,;\s]+", texto or ""):
        if not item:
            continue
        achou = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", item)
        try:
            if not achou:
                raise ValueError(item)
            dia, mes, ano = int(achou.group(1)), int(achou.group(2)), achou.group(3)
            date(int(ano) if ano else 2028, mes, dia)  # 2028 é bissexto: 29/02 sem ano vale
        except ValueError:
            invalidos.append(item)
            continue
        normal = f"{dia:02d}/{mes:02d}" + (f"/{ano}" if ano else "")
        if normal not in validos:
            validos.append(normal)
    return validos, invalidos


def feriados_da_renovacao(db, anos: tuple[int, ...] | None = None) -> dict[date, str]:
    """Dias em que a Renovação não envia nem marca avisos (pedido da Maria em 13/11/2026: "pular feriados"): os
    feriados nacionais (util.feriados_nacionais, com Carnaval, Sexta-feira Santa e Corpus Christi) e os "Outros
    feriados" da tela (da cidade ou do estado). Padrão: este ano e o próximo."""
    hoje = date.today()
    anos = anos or (hoje.year, hoje.year + 1)
    dias: dict[date, str] = {}
    for ano in anos:
        dias.update(util.feriados_nacionais(ano))
    for item in feriados_extras(cfg(db, "renov_feriados"))[0]:
        partes = [int(x) for x in item.split("/")]
        for ano in ([partes[2]] if len(partes) == 3 else anos):
            try:
                dias.setdefault(date(ano, partes[1], partes[0]), "feriado da tela")
            except ValueError:  # 29/02 em ano que não é bissexto
                pass
    return dias


def dias_sem_envio(db, pessoa: Usuario | None = None) -> frozenset:
    """Os feriados da Renovação (este ano e o próximo), para as contas de datas (o fim de semana já fica de fora). Com
    `pessoa` (quem é a campanha), também os do estado e da cidade dela (app/feriados.py, 18/11/2026)."""
    dias = frozenset(feriados_da_renovacao(db))
    if pessoa is None:
        return dias
    from . import feriados

    return dias | feriados.dias_sem_envio(db, pessoa)


def proximos_feriados(db, quantos: int = 6) -> list[tuple[date, str]]:
    """Os próximos feriados em dia de semana (para a tela mostrar quais já estão incluídos)."""
    hoje = date.today()
    return sorted((d, nome) for d, nome in feriados_da_renovacao(db).items() if d >= hoje and d.weekday() < 5)[:quantos]


# O WhatsApp ainda passa pela fila do computador do WhatsApp Leads (a ponte busca a cada minuto): para de sair 10
# minutos antes do fim, para chegar ao cliente dentro do horário.
MARGEM_WHATSAPP_MINUTOS = 10


def fora_do_horario(db, momento: datetime | None = None, margem_minutos: int = 0) -> str:
    """A Renovação só dispara nos dias comerciais, de segunda a sexta, no horário da tela (pedido da Maria em
    13/11/2026: "segunda a sexta das 10:00 - 18:00"). Devolve o motivo ("" = pode enviar agora). As filas seguram os
    avisos fora do horário: eles saem no próximo horário permitido (ou param, se o certificado vencer antes)."""
    from .cadencias import _minutos

    momento = momento or agora()
    inicio = hora_inicio(db) or util.hora_hhmm(ler_config(db, "horario_envio_inicio"), "08:30")
    fim = hora_fim(db) or util.hora_hhmm(ler_config(db, "horario_envio_fim"), "18:00")
    motivo = f"A Renovação só envia de segunda a sexta, fora os feriados, das {inicio} às {fim}"
    minuto = momento.hour * 60 + momento.minute
    if (momento.weekday() >= 5 or momento.date() in feriados_da_renovacao(db, (momento.year,))
            or minuto < _minutos(inicio, 0) or minuto >= _minutos(fim, 24 * 60) - margem_minutos):
        return motivo
    return ""


def ars_fora_do_horario(db, momento: datetime | None = None, margem_minutos: int = 0) -> set:
    """As marcas cuja Renovação está fora do horário agora: cada uma tem os dias, o horário e os feriados dela
    (24/11/2026). As filas tiram da rodada só os avisos dessas marcas. None = os avisos sem marca (a plataforma)."""
    from .banco import config_da_ar
    from .modelos import Tenant

    fora = set()
    for ar in [None, *db.execute(select(Tenant.id).execution_options(sem_filtro_de_ar=True)).scalars()]:
        with config_da_ar(db, ar):
            if fora_do_horario(db, momento, margem_minutos):
                fora.add(ar)
    return fora


def das_marcas(coluna, ars) -> object:
    """Condição SQL "a linha é de uma destas marcas" (None na lista = as linhas sem marca)."""
    from sqlalchemy import false

    ids = [a for a in ars if a is not None]
    partes = ([coluna.in_(ids)] if ids else []) + ([coluna.is_(None)] if None in ars else [])
    return or_(*partes) if partes else false()


def garantir_cadencia(db):
    from .modelos import Cadencia, PassoCadencia

    cad = db.execute(select(Cadencia).where(Cadencia.nome == CADENCIA_NOME)).scalars().first()
    if cad is None:
        cad = Cadencia(nome=CADENCIA_NOME,
                       descricao="Avisos de vencimento do certificado digital para os clientes (tela Renovação).")
        for dia, angulo, acao in CADENCIA_PASSOS:
            cad.passos.append(PassoCadencia(dia=dia, canal="auto", acao=acao, angulo=angulo))
        db.add(cad)
        db.flush()
    return cad


# ---------------------------------------------------------------- Planilha (Relatório de renovação)

class ErroPlanilha(ValueError):
    """Problema na planilha, com o texto pronto para a tela."""


def _chave(texto) -> str:
    """Cabeçalho comparável: sem acento, minúsculo, só letras e números. O relatório da certificadora sai com o acento
    estragado ("Raz�o Social"): o caractere estragado some e fica "razo social"."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _campo(chave: str) -> str:
    """Coluna da planilha → campo. "" = coluna que não interessa (a data de nascimento nunca é lida)."""
    if not chave or "nasc" in chave:
        return ""
    if chave.startswith(("venc", "validade", "data de validade", "data validade", "expira", "data de expiracao")):
        return "vencimento"
    if chave.startswith("protocolo") or chave in ("pedido", "numero do pedido", "n do pedido"):
        return "protocolo"
    if (chave.startswith("raz") and chave.endswith("social")) or chave in ("empresa", "nome da empresa",
                                                                          "nome empresarial"):
        return "razao_social"
    if chave in ("cpf cnpj", "cnpj cpf", "documento", "cpf ou cnpj", "cnpj ou cpf"):
        return "documento"
    if chave.startswith("cnpj"):
        return "cnpj"
    if chave.startswith("cpf"):
        return "cpf"
    if chave in ("cliente", "titular", "nome", "nome do cliente", "nome do titular", "responsavel",
                 "nome do responsavel", "contato", "pessoa responsavel"):
        return "cliente"
    if chave.startswith(("email", "e mail")):
        return "email"
    if chave.startswith(("telefone", "celular", "whatsapp", "fone")) or chave == "tel":
        return "telefone"
    if chave in ("certificado", "tipo", "tipo de certificado", "tipo do certificado", "produto", "modelo"):
        return "tipo"
    if chave.startswith("parceiro") or chave in ("contador", "indicacao", "indicado por"):
        return "parceiro"
    if chave.startswith("ponto"):  # o ponto de atendimento (ex.: MATRIZ, GILBERTO CONTABIL): pode ficar fora dos avisos
        return "ponto"
    if chave.startswith("unidade"):
        return "unidade"
    return ""


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return re.sub(r"\s+", " ", str(valor)).strip()


def _documento(valor, tamanho: int) -> str:
    """CNPJ (14) ou CPF (11) só com dígitos. Número na célula do Excel perde o zero da frente: volta aqui."""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        d = str(int(valor))
        return d.zfill(tamanho) if len(d) < tamanho else d
    texto = str(valor).strip()
    if tamanho == 14 and re.search(r"[A-Za-z]", texto):
        return util.normalizar_cnpj(texto)  # CNPJ alfanumérico (desde jul/2026)
    return util.so_digitos(texto)


def _abas(nome_arquivo: str, conteudo: bytes) -> list[list[tuple]]:
    nome = (nome_arquivo or "").lower()
    if nome.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # "Workbook contains no default style" (relatório da certificadora)
                livro = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
                abas = [list(aba.iter_rows(values_only=True)) for aba in livro.worksheets]
                livro.close()
        except Exception:
            raise ErroPlanilha("Não consegui abrir o arquivo Excel. Abra no Excel, salve como .xlsx e tente de "
                               "novo.") from None
        return abas
    if nome.endswith(".xls"):
        raise ErroPlanilha("Arquivos .xls antigos não são aceitos. Abra no Excel e salve como .xlsx.")
    if nome.endswith((".csv", ".txt")):
        texto = ""
        for codificacao in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                texto = conteudo.decode(codificacao)
                break
            except UnicodeDecodeError:
                continue
        amostra = texto[:2000]
        separador = ";" if amostra.count(";") >= amostra.count(",") else ","
        return [[tuple(linha) for linha in csv.reader(io.StringIO(texto), delimiter=separador)]]
    raise ErroPlanilha("Envie a planilha em Excel (.xlsx) ou CSV.")


def ler_planilha(nome_arquivo: str, conteudo: bytes) -> tuple[list[dict], list[str]]:
    """Lê o Relatório de renovação (todas as abas). Devolve (registros, problemas). As colunas Email e Telefone vêm
    duas vezes: as que estão antes da coluna Cliente são da empresa; as de depois, da pessoa (responsável/titular)."""
    registros: list[dict] = []
    problemas: list[str] = []
    achou = False
    for numero_aba, linhas in enumerate(_abas(nome_arquivo, conteudo), start=1):
        inicio, cabecalho = None, None
        for i, linha in enumerate(linhas[:15]):  # o cabeçalho pode ter um título em cima
            campos = [_campo(_chave(c)) for c in linha]
            if "vencimento" in campos:
                inicio, cabecalho = i, campos
                break
        if cabecalho is None:
            continue
        achou = True
        pos_cliente = cabecalho.index("cliente") if "cliente" in cabecalho else -1
        colunas: dict[str, int] = {}
        for i, campo in enumerate(cabecalho):
            if campo in ("email", "telefone"):
                campo += "_pessoa" if (pos_cliente < 0 or i > pos_cliente) else "_empresa"
            if campo and campo not in colunas:
                colunas[campo] = i
        for n, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
            if not any(v not in (None, "") for v in linha):
                continue

            def valor(campo, linha=linha):
                i = colunas.get(campo)
                return linha[i] if i is not None and i < len(linha) else None

            onde = f"linha {n}" + (f" (aba {numero_aba})" if numero_aba > 1 else "")
            vencimento = util.para_data(valor("vencimento"))
            if vencimento is None:
                problemas.append(f"{onde}: sem data de vencimento")
                continue
            cnpj, cpf = _documento(valor("cnpj"), 14), _documento(valor("cpf"), 11)
            documento = _documento(valor("documento"), 14)
            if documento and not cnpj and not cpf:
                cnpj, cpf = (documento, "") if len(documento) == 14 else ("", documento.lstrip("0").zfill(11))
            registros.append({
                "linha": onde, "protocolo": _texto(valor("protocolo"))[:30], "vencimento": vencimento,
                "tipo": _texto(valor("tipo"))[:120], "razao_social": _texto(valor("razao_social"))[:200],
                "cnpj": cnpj if len(cnpj) == 14 else "", "cliente": _texto(valor("cliente"))[:200],
                "cpf": cpf if len(cpf) == 11 else "",
                "email_empresa": _texto(valor("email_empresa")).lower(), "telefone_empresa": _texto(valor("telefone_empresa")),
                "email_pessoa": _texto(valor("email_pessoa")).lower(), "telefone_pessoa": _texto(valor("telefone_pessoa")),
                "parceiro": _texto(valor("parceiro"))[:200],
                "unidade": _texto(valor("unidade"))[:160], "ponto": _texto(valor("ponto"))[:120],
            })
    if not achou:
        raise ErroPlanilha("Não achei a coluna Vencimento na planilha. Confira se é o Relatório de renovação (com as "
                           "colunas Vencimento, Certificado, Razão Social, CNPJ, Cliente, CPF, Email e Telefone).")
    return registros, problemas


def _celular(*telefones: str) -> str:
    """O primeiro celular (11 dígitos com o 9) da lista: é o que pode ter WhatsApp."""
    for t in telefones:
        d = util.com_nono_digito(t or "")
        if len(d) == 11 and d[2] == "9":
            return d
    return ""


def dados_do_registro(r: dict) -> dict:
    """Linha da planilha → campos do certificado. Telefone e e-mail da pessoa primeiro (é quem cuida do certificado);
    os da empresa só se faltarem."""
    cnpj, cpf = r["cnpj"], r["cpf"]
    if cnpj:
        nome, documento = r["razao_social"] or r["cliente"], util.formatar_cnpj(cnpj)
    else:
        nome, documento = r["cliente"] or r["razao_social"], util.formatar_cnpj(cpf) if cpf else ""
    telefones = [r["telefone_pessoa"], r["telefone_empresa"]]
    fixo = next((util.normalizar_telefone(t) for t in telefones if util.normalizar_telefone(t)), "")
    email = next((e for e in (r["email_pessoa"], r["email_empresa"]) if util.email_valido(e)), "")
    parceiro = r["parceiro"] if not _chave(r["parceiro"]).startswith("sem") else ""
    zap = _celular(*telefones)
    return {
        "protocolo": r["protocolo"], "cliente_nome": (nome or "(sem nome)")[:200], "cnpj": documento[:20],
        "tipo": r["tipo"], "data_vencimento": r["vencimento"], "responsavel": r["cliente"][:200],
        "whatsapp": util.formatar_telefone(zap) if zap else "", "telefone": util.formatar_telefone(fixo) if fixo else "",
        "email": email[:160], "parceiro_nome": parceiro,
        "ponto": (r.get("ponto") or "")[:120], "unidade": (r.get("unidade") or "")[:160],
    }


def _chave_do_certificado(d) -> tuple:
    if isinstance(d, Certificado):
        d = {"protocolo": d.protocolo, "cnpj": d.cnpj, "cliente_nome": d.cliente_nome, "tipo": d.tipo,
             "data_vencimento": d.data_vencimento}
    if d["protocolo"]:
        return ("protocolo", d["protocolo"])
    return ("documento", util.normalizar_cnpj(d["cnpj"]) or _chave(d["cliente_nome"]), _chave(d["tipo"]),
            d["data_vencimento"])


def importar(db, registros: list[dict], usuario: Usuario | None, arquivo: str = "") -> dict:
    """Grava os certificados da planilha. Importar de novo atualiza (pelo protocolo), sem duplicar; a situação
    (renovado, em campanha...) de quem já estava fica como está."""
    hoje = date.today()
    inicio = agora().replace(microsecond=0)  # os certificados desta planilha ficam com importado_em daqui em diante
    indice = {_chave_do_certificado(c): c for c in db.execute(
        select(Certificado).where(Certificado.origem == ORIGEM)).scalars()}
    resumo = {"linhas": len(registros), "novos": 0, "atualizados": 0, "iguais": 0, "repetidos": 0, "vencidos": 0,
              "sem_contato": 0, "na_janela": 0, "janela": janela(db)}
    vistos = set()
    for r in registros:
        d = dados_do_registro(r)
        chave = _chave_do_certificado(d)
        if chave in vistos:
            resumo["repetidos"] += 1
            continue
        vistos.add(chave)
        cert = indice.get(chave)
        if cert is None:
            cert = Certificado(origem=ORIGEM, status="Ativo" if d["data_vencimento"] >= hoje else "Vencido", **d)
            db.add(cert)
            resumo["novos"] += 1
        else:
            mudou = False
            for campo, novo in d.items():
                if getattr(cert, campo) != novo:
                    setattr(cert, campo, novo)
                    mudou = True
            if cert.status == "Vencido" and cert.data_vencimento >= hoje:
                cert.status, mudou = "Ativo", True
            resumo["atualizados" if mudou else "iguais"] += 1
        cert.importado_em = agora()
        if d["data_vencimento"] < hoje:
            resumo["vencidos"] += 1
        elif d["data_vencimento"] <= hoje + timedelta(days=resumo["janela"]):
            resumo["na_janela"] += 1
        if not (d["whatsapp"] or d["email"]):
            resumo["sem_contato"] += 1
    db.flush()
    texto = (f"{agora():%d/%m/%Y %H:%M}" + (f" – {arquivo}" if arquivo else "") + f": {resumo['linhas']} linhas, "
             f"{resumo['novos']} certificados novos, {resumo['atualizados']} atualizados"
             + (f", {resumo['sem_contato']} sem WhatsApp e sem e-mail" if resumo["sem_contato"] else "")
             + (f", {resumo['vencidos']} já vencidos (não recebem aviso)" if resumo["vencidos"] else "")
             + (f" (por {usuario.nome})" if usuario else "") + ".")
    gravar_config(db, "renov_ultima_importacao", texto)
    gravar_config(db, "renov_ultima_importacao_em", inicio.isoformat())
    return resumo


def inicio_da_ultima_planilha(db) -> datetime | None:
    """Quando começou a última importação da marca (None: importada antes de 26/11/2026, quando isso passou a ser
    guardado). "Montar com todos da planilha" leva só os certificados dela (pedido da Maria em 26/11/2026)."""
    try:
        return datetime.fromisoformat(cfg(db, "renov_ultima_importacao_em"))
    except ValueError:
        return None


# ---------------------------------------------------------------- Contatos (certificados agrupados)

@dataclass
class Contato:
    """Um WhatsApp (ou, sem ele, um e-mail) e os certificados dele, do que vence primeiro ao último."""
    chave: str
    certificados: list

    @property
    def vencimento(self) -> date:
        return self.certificados[0].data_vencimento

    @property
    def whatsapp(self) -> str:
        return next((c.whatsapp for c in self.certificados if c.whatsapp), "")

    @property
    def email(self) -> str:
        return next((c.email for c in self.certificados if util.email_valido(c.email)), "")

    @property
    def telefone(self) -> str:
        return next((c.telefone for c in self.certificados if c.telefone), "")

    @property
    def responsavel(self) -> str:
        return next((c.responsavel for c in self.certificados if c.responsavel), "")


def chave_do_contato(cert: Certificado) -> str:
    zap = util.normalizar_telefone(cert.whatsapp or "")
    if zap:
        return f"whatsapp:{zap}"
    email = (cert.email or "").strip().lower()
    return f"email:{email}" if util.email_valido(email) else ""


def agrupar(certificados) -> tuple[list[Contato], list[Certificado]]:
    """(contatos, certificados sem WhatsApp e sem e-mail). Os contatos vêm do que vence primeiro ao último."""
    grupos: dict[str, list] = {}
    sem_contato = []
    for c in sorted(certificados, key=lambda c: (c.data_vencimento, c.id or 0)):
        chave = chave_do_contato(c)
        if chave:
            grupos.setdefault(chave, []).append(c)
        else:
            sem_contato.append(c)
    return sorted((Contato(k, v) for k, v in grupos.items()), key=lambda c: (c.vencimento, c.chave)), sem_contato


def pontos_fora(db) -> list[str]:
    """Os pontos de atendimento cujos clientes não recebem avisos (quadro 4, por marca; pedido da Maria em 26/11/2026:
    na planilha da MS, 173 certificados eram do ponto Gilberto Contábil). O nome da coluna Ponto da planilha (vale
    também o da coluna Unidade), separados por vírgula, ponto e vírgula ou um por linha."""
    return [p.strip() for p in re.split(r"[\n;,]+", cfg(db, "renov_pontos_fora")) if p.strip()]


def normalizar_pontos(texto: str) -> str:
    """O que a tela grava: os nomes sem espaço sobrando, sem repetir (sem diferença de acento e maiúscula)."""
    vistos, nomes = set(), []
    for nome in re.split(r"[\n;,]+", texto or ""):
        nome = " ".join(nome.split())[:120]
        if _chave(nome) and _chave(nome) not in vistos:
            vistos.add(_chave(nome))
            nomes.append(nome)
    return ", ".join(nomes)


def chaves_dos_pontos_fora(db) -> frozenset:
    return frozenset(k for k in (_chave(p) for p in pontos_fora(db)) if k)


def no_ponto_fora(cert: Certificado, chaves: frozenset) -> bool:
    """O certificado é de um ponto de atendimento (ou unidade) fora dos avisos? Sem acento e sem maiúscula."""
    return bool(chaves) and bool({_chave(cert.ponto), _chave(cert.unidade)} & chaves)


def a_avisar(db, hoje: date | None = None, ate: date | None = None, ar: int | None = None,
             desde: datetime | None = None, com_pontos_fora: bool = False) -> list[Certificado]:
    """Certificados que podem entrar numa campanha: da planilha, ativos, fora de campanha e vencendo até o dia do 1º
    aviso (ex.: 30 ou 12 dias) ou até `ate` (campanha do piloto: até 31/12), de amanhã em diante (o que vence hoje já
    não dá tempo de avisar). `ar`: só os dessa AR (a rodada diária roda sem tela e enxerga todas as ARs: sem o filtro,
    a campanha automática da MS levava os clientes da planilha do Grupo Certy)."""
    hoje = hoje or date.today()
    ate = ate or hoje + timedelta(days=janela(db))
    consulta = select(Certificado).where(
        Certificado.origem == ORIGEM, Certificado.status == "Ativo", Certificado.campanha_id.is_(None),
        func.coalesce(Certificado.fora_motivo, "") == "", Certificado.data_vencimento > hoje,
        Certificado.data_vencimento <= ate)
    if ar:
        consulta = consulta.where(Certificado.tenant_id == ar)
    if desde is not None:  # só os da planilha importada a partir daí (a última: "todos da planilha")
        consulta = consulta.where(Certificado.importado_em >= desde)
    certificados = db.execute(consulta).scalars().all()
    chaves = frozenset() if com_pontos_fora else chaves_dos_pontos_fora(db)
    return [c for c in certificados if not no_ponto_fora(c, chaves)] if chaves else certificados


def _formas_do_celular(numero: str) -> set[str]:
    formas = {numero}
    if len(numero) == 11 and numero[2] == "9":
        formas.add(numero[:2] + numero[3:])  # o mesmo celular guardado sem o 9
    return formas


def lead_do_contato(db, chave: str, ar: int | None = None) -> Lead | None:
    """Lead que já existe para o contato. WhatsApp: qualquer lead com o número (dois leads no mesmo número embaralham
    as respostas). Só e-mail: só um lead de renovação (o contato vem só da planilha). `ar`: só um lead dessa AR (a
    montagem roda em segundo plano e enxerga todas: o cliente do Grupo Certy não pode virar o lead da MS; o mesmo
    número em duas ARs é permitido e a resposta vai para a AR do número que recebeu)."""
    tipo, valor = chave.split(":", 1)
    if tipo == "whatsapp":
        formas = _formas_do_celular(valor)
        consulta = select(Lead).where(or_(Lead.chave_whatsapp.in_(formas), Lead.chave_telefone.in_(formas)))
    else:
        consulta = select(Lead).where(Lead.chave_email == valor, Lead.origem == ORIGEM_LEAD)
    if ar:
        consulta = consulta.where(Lead.tenant_id == ar)
    leads = db.execute(consulta.order_by(Lead.id)).scalars().all()
    return next((l for l in leads if l.origem == ORIGEM_LEAD), leads[0] if leads else None)


def _leads_dos_contatos(db, contatos: list[Contato], ar: int | None = None) -> dict[str, Lead]:
    """lead_do_contato de muitos contatos de uma vez (duas consultas, não uma por contato: a tela abre rápido)."""
    formas: dict[str, str] = {}
    emails: dict[str, str] = {}
    for contato in contatos:
        tipo, valor = contato.chave.split(":", 1)
        if tipo == "whatsapp":
            formas.update({f: contato.chave for f in _formas_do_celular(valor)})
        else:
            emails[valor] = contato.chave
    achados: dict[str, list[Lead]] = {}
    da_ar = [Lead.tenant_id == ar] if ar else []
    if formas:
        for lead in db.execute(select(Lead).where(or_(Lead.chave_whatsapp.in_(formas), Lead.chave_telefone.in_(formas)),
                                                  *da_ar).order_by(Lead.id)).scalars():
            chave = formas.get(lead.chave_whatsapp) or formas.get(lead.chave_telefone)
            if chave:
                achados.setdefault(chave, []).append(lead)
    if emails:
        for lead in db.execute(select(Lead).where(Lead.chave_email.in_(emails), Lead.origem == ORIGEM_LEAD, *da_ar)
                               .order_by(Lead.id)).scalars():
            achados.setdefault(emails[lead.chave_email], []).append(lead)
    return {k: next((l for l in v if l.origem == ORIGEM_LEAD), v[0]) for k, v in achados.items()}


def motivo_de_fora(db, lead: Lead) -> str:
    """Por que o contato não entra numa campanha de renovação agora (as mesmas regras de cadencias.aplicar). "" = pode.
    Desde 26/11/2026 (pedido da Maria: "se eu mandei 746, é para você criar campanha para os 746 certificados, tanto de
    CPF quanto de CNPJ") só quem pediu SAIR (ou foi anonimizado) fica de fora. O cliente atendido por alguém da equipe,
    que já respondeu, marcado como Perdido ou que já recebe os avisos de outro certificado (ex.: na campanha piloto)
    também recebe os avisos dos certificados novos: na planilha de jan-mar/2027 da MS eram 30 contatos (57
    certificados), todos com outro certificado na piloto. Quem responde, é assumido ou é encerrado tem os avisos
    pendentes cancelados na hora (leads_servico.cancelar_tarefas_de_prospeccao)."""
    if lead.opt_out or lead.anonimizado:
        return "pediu para não receber mensagens (SAIR)"
    return ""


def contatos_para_campanha(db, hoje: date | None = None, marcar_saida: bool = False,
                           ate: date | None = None, ar: int | None = None,
                           desde: datetime | None = None) -> tuple[list[Contato], dict]:
    """Contatos que podem entrar numa campanha agora (do que vence primeiro ao último) e quantos certificados ficam de
    fora por motivo. marcar_saida=True grava nos certificados de quem pediu SAIR (vale até alguém reabrir). `ar`: só os
    certificados e os leads dessa AR (ver a_avisar)."""
    certificados = a_avisar(db, hoje, ate, ar, desde, com_pontos_fora=True)
    chaves = chaves_dos_pontos_fora(db)
    do_ponto = {id(c) for c in certificados if no_ponto_fora(c, chaves)}
    contatos, sem_contato = agrupar([c for c in certificados if id(c) not in do_ponto])
    fora: dict[str, int] = {}
    if do_ponto:  # quadro 4: "Pontos de atendimento que não recebem avisos"
        fora["de ponto de atendimento fora dos avisos"] = len(do_ponto)
    if sem_contato:
        fora["sem WhatsApp e sem e-mail na planilha"] = len(sem_contato)
    leads = _leads_dos_contatos(db, contatos, ar)
    livres = []
    for contato in contatos:
        lead = leads.get(contato.chave)
        motivo = motivo_de_fora(db, lead) if lead is not None else ""
        if motivo:
            fora[motivo] = fora.get(motivo, 0) + len(contato.certificados)
            if marcar_saida and (lead.opt_out or lead.anonimizado):
                for c in contato.certificados:
                    c.fora_motivo = motivo[:160]
            continue
        livres.append(contato)
    return livres, fora


# ---------------------------------------------------------------- Datas e textos dos avisos

def _dia_util_antes(d: date, feriados: frozenset = frozenset()) -> date:
    while d.weekday() >= 5 or d in feriados:
        d -= timedelta(days=1)
    return d


def _dia_util_depois(d: date, feriados: frozenset = frozenset()) -> date:
    while d.weekday() >= 5 or d in feriados:
        d += timedelta(days=1)
    return d


def _limites_para_a_sexta(vencimento: date, dias_antes: tuple[int, ...], pular_fds: bool,
                          feriados: frozenset = frozenset()) -> list[date | None]:
    """Vence no sábado ou no domingo (ou num feriado): o último aviso sai no último dia útil antes, a sexta (pedido da
    Maria em 13/11/2026: "os de sábados e domingos avisar na sexta"; se a sexta for feriado, a quinta). Para ele caber,
    cada aviso anterior fica pelo menos INTERVALO_MINIMO_DIAS antes do seguinte (ex.: vence no domingo, avisos 12, 6,
    3 e 1 dia antes: o de 3 dias vai para a quarta, e não para a quinta, onde tirava o lugar do último aviso). Devolve
    o dia máximo de cada aviso (None = sem limite)."""
    total = len(dias_antes)
    if not pular_fds or not total or (vencimento.weekday() < 5 and vencimento not in feriados):
        return [None] * total
    sexta = _dia_util_antes(vencimento, feriados)
    if _dia_util_antes(vencimento - timedelta(days=dias_antes[-1]), feriados) != sexta:
        return [None] * total  # o último aviso não cai na sexta (ex.: 3 dias antes): nada muda
    return [_dia_util_antes(sexta - timedelta(days=INTERVALO_MINIMO_DIAS * (total - 1 - i)), feriados)
            if i < total - 1 else None for i in range(total)]


def _alvos(vencimento: date, pular_fds: bool, dias_antes: tuple[int, ...],
           feriados: frozenset = frozenset()) -> list[date]:
    """O dia de cada aviso contado do vencimento (dia útil antes; quem vence no fim de semana recebe o último aviso na
    sexta, _limites_para_a_sexta), sem olhar o dia de hoje."""
    limites = _limites_para_a_sexta(vencimento, dias_antes, pular_fds, feriados)
    alvos = []
    for indice, dias in enumerate(dias_antes):
        alvo = vencimento - timedelta(days=dias)
        if pular_fds:
            alvo = _dia_util_antes(alvo, feriados)
        if limites[indice] is not None:
            alvo = min(alvo, limites[indice])  # vence no fim de semana: a sexta fica para o último aviso
        alvos.append(alvo)
    return alvos


def _seguintes(datas: list[date | None], alvos: list[date], vencimento: date, desde: int) -> None:
    """Os avisos depois do índice `desde` (já marcado em `datas`): cada um no dia dele, se ficar a
    INTERVALO_MINIMO_DIAS ou mais do anterior (nunca em dias seguidos) e não passar do vencimento."""
    anterior = datas[desde]
    for i in range(desde + 1, len(alvos)):
        if alvos[i] > vencimento or (alvos[i] - anterior).days < INTERVALO_MINIMO_DIAS:
            continue
        datas[i] = anterior = alvos[i]


def etapa_do_dia(vencimento: date, dia: date, pular_fds: bool = True, dias_antes: tuple[int, ...] = DIAS_AVISO,
                 feriados: frozenset = frozenset()) -> int:
    """Qual aviso vale no `dia` para quem vence em `vencimento` (o índice em dias_antes; pedido da Maria em
    19/11/2026: "se o certificado vence dia 20/11, não envie a primeira mensagem, mas a de acordo com os dias que
    faltam"). É o mais adiantado entre: o último aviso cujo dia já chegou, como para quem está na campanha desde o
    começo, e o dos dias que faltam (avisos 12, 6, 3 e 1 dia antes: faltam 8 = 1º aviso, 4 a 6 = lembrete, 2 ou 3 =
    "Faltam poucos dias", 1 ou vence hoje = "Último aviso"). 0 = ainda é cedo (o 1º aviso). Para quem recebe cada aviso
    no dia certo, é sempre o próprio aviso: só o atrasado (ou quem entrou tarde) muda de etapa."""
    alvos = _alvos(vencimento, pular_fds, dias_antes, feriados)
    normais: list[date | None] = [None] * len(alvos)
    if alvos:
        normais[0] = alvos[0]
        _seguintes(normais, alvos, vencimento, 0)
    pelo_calendario = max((i for i, d in enumerate(normais) if d is not None and d <= dia), default=0)
    faltam = (vencimento - dia).days
    pelos_dias = max((i for i, n in enumerate(dias_antes) if n >= faltam), default=0)
    return max(pelo_calendario, pelos_dias)


def datas_dos_avisos(vencimento: date, hoje: date | None = None, pular_fds: bool = True,
                     dias_antes: tuple[int, ...] = DIAS_AVISO, feriados: frozenset = frozenset()) -> list[date | None]:
    """Datas dos 4 avisos (30, 15, 5 e 1 dia antes do vencimento). None = aviso que não vai (a etapa dele já passou,
    ou ficaria a menos de 2 dias do anterior). Quem entra tarde começa pelo aviso da etapa em que está (etapa_do_dia:
    vence amanhã = só o "Último aviso", nunca o 1º; pedido da Maria em 19/11/2026), hoje (ou no próximo dia útil), e
    recebe os seguintes que ainda cabem. Aviso no fim de semana vem para a sexta antes, nunca para depois do
    vencimento; quem vence no sábado ou no domingo recebe o último aviso na sexta (_limites_para_a_sexta). Feriado
    conta como fim de semana (`feriados`, ver dias_sem_envio). Tudo None = não dá mais tempo de avisar."""
    hoje = hoje or date.today()
    datas: list[date | None] = [None] * len(dias_antes)
    primeiro = _dia_util_depois(hoje, feriados) if pular_fds else hoje
    if not dias_antes or primeiro > vencimento:
        return datas
    alvos = _alvos(vencimento, pular_fds, dias_antes, feriados)
    etapa = etapa_do_dia(vencimento, primeiro, pular_fds, dias_antes, feriados)
    datas[etapa] = max(alvos[etapa], primeiro)
    _seguintes(datas, alvos, vencimento, etapa)
    return datas


def _util_seguinte(d: date, pular_fds: bool, feriados: frozenset = frozenset()) -> date:
    d += timedelta(days=1)
    return _dia_util_depois(d, feriados) if pular_fds else d


def _util_anterior(d: date, pular_fds: bool, feriados: frozenset = frozenset()) -> date:
    d -= timedelta(days=1)
    return _dia_util_antes(d, feriados) if pular_fds else d


def primeiro_dia(db, pessoa: Usuario | None = None) -> date:
    """O primeiro dia em que ainda dá para enviar: hoje (se o horário de envio de hoje não acabou) ou o próximo dia de
    envio. Montada à noite, a campanha não marca nada para "hoje" (iria tudo para amanhã, acima do teto)."""
    from . import cadencias

    return cadencias.dia_e_hora_futuros(db, date.today(), True, hora_inicio(db), hora_fim(db),
                                        dias_sem_envio(db, pessoa))[0]


def teto_por_dia(db) -> int:
    """Quantos WhatsApps de renovação cabem por dia no número: o limite de contatos frios (Configurações > Geral;
    quase todo cliente da planilha é frio para o número), ou o limite diário. 0 = sem teto."""
    from .banco import ler_config_int

    return ler_config_int(db, "limite_frios_whatsapp", 0) or ler_config_int(db, "limite_diario_whatsapp", 0)


def carga_marcada(db, desde: date, ignorar_campanha: int | None = None) -> Counter:
    """WhatsApps de renovação já marcados por dia (das campanhas de renovação em aberto)."""
    consulta = (select(Tarefa.data, func.count(Tarefa.id)).join(Campanha, Tarefa.campanha_id == Campanha.id)
                .where(Campanha.tipo == TIPO_CAMPANHA, Tarefa.canal == "whatsapp", Tarefa.data >= desde,
                       Tarefa.status.in_(("pendente", "rascunho"))).group_by(Tarefa.data))
    if ignorar_campanha:
        consulta = consulta.where(Campanha.id != ignorar_campanha)
    return Counter({dia: n for dia, n in db.execute(consulta).all()})


def agenda(vencimentos: list[date], hoje: date, pular_fds: bool = True, carga: Counter | None = None,
           teto: int = 0, dias_antes: tuple[int, ...] = DIAS_AVISO,
           feriados: frozenset = frozenset()) -> list[list[date | None]]:
    """As datas dos avisos de vários contatos com WhatsApp (do que vence primeiro ao último) sem passar de `teto`
    WhatsApps por dia: com 100 clientes vencendo no mês, os 100 primeiros avisos cairiam no mesmo dia e o número só
    faz 20 contatos frios por dia (o resto atrasaria e ficaria esperando clique). Primeiro, o primeiro aviso de todos
    (o da etapa em que cada um está, etapa_do_dia), no primeiro dia com vaga (quem vence antes escolhe antes): ninguém
    fica sem aviso por causa dos lembretes dos outros. Depois, os lembretes nas vagas que sobraram, no dia certo ou
    alguns dias antes (sem vaga, aquele lembrete não vai). teto 0 = sem teto (só as regras de datas_dos_avisos)."""
    if not teto:
        return [datas_dos_avisos(v, hoje, pular_fds, dias_antes, feriados) for v in vencimentos]
    carga = carga if carga is not None else Counter()
    resultado: list[list[date | None]] = []
    for vencimento in vencimentos:
        datas: list[date | None] = [None] * len(dias_antes)
        base = datas_dos_avisos(vencimento, hoje, pular_fds, dias_antes, feriados)
        etapa = next((i for i, d in enumerate(base) if d is not None), None)
        if etapa is not None:
            primeiro = base[etapa]
            dia = primeiro
            while carga[dia] >= teto and _util_seguinte(dia, pular_fds, feriados) <= vencimento:
                dia = _util_seguinte(dia, pular_fds, feriados)
            if carga[dia] >= teto:  # nenhum dia com vaga até o vencimento: o menos cheio (a fila segura o excesso)
                dias, d = [], primeiro
                while d <= vencimento:
                    dias.append(d)
                    d = _util_seguinte(d, pular_fds, feriados)
                dia = min(dias, key=lambda x: (carga[x], x))
            # o aviso que vale no dia em que coube (sem vaga por dias, o 1º aviso pode virar o lembrete)
            etapa = max(etapa, etapa_do_dia(vencimento, dia, pular_fds, dias_antes, feriados))
            carga[dia] += 1
            datas[etapa] = dia
        resultado.append(datas)
    for datas, vencimento in zip(resultado, vencimentos):
        etapa = next((i for i, d in enumerate(datas) if d is not None), None)
        if etapa is None:
            continue
        anterior = datas[etapa]
        alvos = _alvos(vencimento, pular_fds, dias_antes, feriados)
        for i in range(etapa + 1, len(dias_antes)):
            dia = alvos[i]
            while dia >= hoje and (dia - anterior).days >= INTERVALO_MINIMO_DIAS:
                if dia <= vencimento and carga[dia] < teto:
                    carga[dia] += 1
                    datas[i] = anterior = dia
                    break
                dia = _util_anterior(dia, pular_fds, feriados)
    return resultado


def tipo_curto(tipo: str) -> str:
    """"e-CNPJ A1 12 meses - videoconferencia" → "e-CNPJ A1" (o resto não interessa ao cliente)."""
    t = (tipo or "").upper()
    midia = next((m for m in ("A1", "A3") if re.search(rf"\b{m}\b", t)), "")
    if "CNPJ" in t or re.search(r"\bPJ\b", t):
        base = "e-CNPJ"
    elif "CPF" in t or re.search(r"\bPF\b", t):
        base = "e-CPF"
    elif "NF-E" in t or "NFE" in t:
        base = "NF-e"
    else:
        base = ""
    return " ".join(x for x in (base, midia) if x)


def _e_pessoa(cert: Certificado) -> bool:
    return len(util.so_digitos(cert.cnpj or "")) == 11 or tipo_curto(cert.tipo).startswith("e-CPF")


def _nome_proprio(nome: str) -> str:
    """"MARIA DA SILVA" → "Maria da Silva" (nome de gente; razão social fica como veio)."""
    pequenas = {"de", "da", "do", "das", "dos", "e"}
    return " ".join(p.lower() if i and p.lower() in pequenas else p.capitalize()
                    for i, p in enumerate((nome or "").split()))


def _titular(cert: Certificado) -> str:
    nome = util.nome_para_mensagem(cert.cliente_nome or "")
    return _nome_proprio(nome) if _e_pessoa(cert) else nome


def _do_proprio(cert: Certificado) -> bool:
    """e-CPF de quem recebe a mensagem (o titular é o próprio responsável)."""
    return _e_pessoa(cert) and bool(cert.responsavel) and _chave(cert.responsavel) == _chave(cert.cliente_nome)


def bloco_vencimentos(certificados: list[Certificado]) -> str:
    """O que entra no lugar de {vencimentos}: a frase do certificado, a lista (até 5) ou um resumo (mais de 5)."""
    certs = sorted(certificados, key=lambda c: (c.data_vencimento, c.cliente_nome or ""))
    if len(certs) == 1:
        c = certs[0]
        tipo = tipo_curto(c.tipo)
        if _do_proprio(c):
            return f"O seu certificado digital {tipo + ' ' if tipo else ''}vence no dia {c.data_vencimento:%d/%m/%Y}."
        return (f"O certificado digital {tipo + ' ' if tipo else ''}em nome de {_titular(c)} vence no dia "
                f"{c.data_vencimento:%d/%m/%Y}.")
    if len(certs) <= MAXIMO_NA_LISTA:
        linhas = []
        for c in certs:
            tipo = tipo_curto(c.tipo)
            nome = "Seu certificado" if _do_proprio(c) else _titular(c)
            linhas.append(f"• {nome}{f' ({tipo})' if tipo else ''}: vence em {c.data_vencimento:%d/%m/%Y}")
        return "Estes certificados digitais vencem em breve:\n" + "\n".join(linhas)
    return (f"{len(certs)} certificados digitais que você acompanha vencem entre {certs[0].data_vencimento:%d/%m} e "
            f"{certs[-1].data_vencimento:%d/%m/%Y} (o primeiro, em nome de {_titular(certs[0])}). Posso te mandar a "
            "lista completa.")


def _frase_de_apresentacao(modelo: str) -> str:
    """A frase do 1º aviso que diz quem escreve (padrão: "Aqui é {vendedor}, da {minha_empresa}.")."""
    achada = re.search(r"[^.!?\n]*\{minha_empresa\}[^.!?\n]*[.!?]?", modelo or "")
    return achada.group(0).strip() if achada else ""


def _com_apresentacao(modelo: str, frase: str) -> str:
    """O texto de outro aviso com a frase que diz quem escreve logo depois da saudação ("Olá, {responsavel}! Aqui é
    {vendedor}, da {minha_empresa}. Último aviso:"); sem saudação, no começo. Já fala da empresa: fica como está."""
    if not frase or "{minha_empresa}" in (modelo or ""):
        return modelo
    primeira, quebra, resto = (modelo or "").partition("\n")
    achada = re.match(r"(\s*(?:olá|oi|bom dia|boa tarde|boa noite)\b[^!?.\n]*[!?.])\s*(.*)$", primeira, re.IGNORECASE)
    if not achada:
        return f"{frase}\n\n{modelo}"
    return f"{achada.group(1)} {frase}" + (f" {achada.group(2)}" if achada.group(2) else "") + quebra + resto


def textos_do_contato(db, contato: Contato, usuario: Usuario | None, primeiro: str = "",
                      ar: int | None = None) -> dict:
    """Mensagens dos 4 avisos para o contato (WhatsApp, e-mail com a assinatura e assunto). `primeiro`: o aviso que é
    o primeiro contato da campanha quando não é o 1º aviso (entrou tarde ou atrasou; pedido da Maria em 19/11/2026):
    como o 1º aviso, ele diz quem escreve ("Aqui é Thamires, da Grupo Certy.", com a marca de quem é a campanha) e,
    no WhatsApp, traz a frase do SAIR. `ar`: a marca das mensagens quando não é a da pessoa (o teste do Admin Master
    dentro de uma AR sai com a marca dela)."""
    from . import marca

    vendedor = util.primeiro_nome(usuario.nome) if usuario and usuario.perfil != "parceiro" else "a equipe"
    # mensagem de uma AR que não é a da pessoa (o Admin Master testando dentro dela): a marca da AR, sem a empresa que
    # a pessoa representa na Minha conta
    quem = None if ar is not None and usuario is not None and getattr(usuario, "tenant_id", None) != ar else usuario
    m = marca.da_pessoa(quem, ar)
    assinatura = marca.assinatura(quem, vendedor, ar)
    valores = {"responsavel": util.primeiro_nome(contato.responsavel), "vencimentos": bloco_vencimentos(contato.certificados),
               "data": f"{contato.vencimento:%d/%m/%Y}", "vendedor": vendedor, "minha_empresa": m["nome"]}

    def trocar(modelo: str) -> str:
        texto = marca.aplicar(modelo or "", quem, ar)  # só no modelo: o nome do cliente nunca é trocado
        if not valores["responsavel"]:
            texto = re.sub(r",?[ \t]*\{responsavel\}", "", texto)  # "Olá, {responsavel}!" vira "Olá!"
        return re.sub(r"\{(" + "|".join(CAMPOS_DA_MENSAGEM) + r")\}", lambda x: valores[x.group(1)], texto)

    modelos = mensagens(db)
    e_outro = bool(primeiro) and primeiro != PRIMEIRO_AVISO and primeiro in modelos
    if e_outro:
        base = modelos[PRIMEIRO_AVISO]
        modelos = {**modelos, primeiro: {
            **modelos[primeiro],
            "whatsapp": _com_apresentacao(modelos[primeiro]["whatsapp"], _frase_de_apresentacao(base["whatsapp"])),
            "email": _com_apresentacao(modelos[primeiro]["email"], _frase_de_apresentacao(base["email"]))}}
    textos = {a: {"whatsapp": trocar(t["whatsapp"]), "email": trocar(t["email"]) + assinatura,
                  "assunto": trocar(t["assunto"])[:200], "fonte": "renovacao"}
              for a, t in modelos.items()}
    if e_outro:
        textos[primeiro]["whatsapp"] = com_sair(textos[primeiro]["whatsapp"], linha_do_sair(db))
    return textos


# ---------------------------------------------------------------- Campanha

def ondas(contato: Contato, dias_da_janela: int) -> list[Contato]:
    """Os certificados do contato em "ondas": cada onda junta os que vencem até `dias_da_janela` dias depois do
    primeiro dela e recebe os próprios avisos (ex.: um vence em 20/11 e outro em 18/12: dois conjuntos de avisos)."""
    lista: list[Contato] = []
    atual: list = []
    for c in contato.certificados:
        if atual and (c.data_vencimento - atual[0].data_vencimento).days > dias_da_janela:
            lista.append(Contato(contato.chave, atual))
            atual = []
        atual.append(c)
    if atual:
        lista.append(Contato(contato.chave, atual))
    return lista


# "Montar com todos da planilha" (pedido da Maria em 26/11/2026): todos os certificados ativos fora de campanha, de
# qualquer mês, cada contato com os avisos contados do próprio vencimento (como a campanha do piloto, até 31/12)
ATE_TODOS = date(2100, 1, 1)


def criar_campanha(db, usuario: Usuario, quantidade: int | None = None, ate: date | None = None,
                   nome: str = "", desde: datetime | None = None) -> Campanha | None:
    """Campanha de renovação com os contatos que vencem primeiro (no máximo `quantidade`; sem ela, o máximo por dia
    da configuração). `ate`: todos os que vencem até essa data, com os avisos marcados desde já (campanha do piloto de
    13/11/2026, até 31/12); o contato com certificados vencendo em datas distantes recebe uma "onda" de avisos para
    cada uma. Fica "gerando": o trabalho em etapas cadastra os contatos e monta os avisos, e ela vai para a aprovação.
    None = ninguém para avisar agora."""
    from . import trabalhos

    hoje = date.today()
    ar = ar_de_quem_monta(db, usuario)
    contatos, _ = contatos_para_campanha(db, hoje, marcar_saida=True, ate=ate, ar=ar, desde=desde)
    limite = quantidade or (None if ate else util.para_int(cfg(db, "renov_maximo_dia")) or 40)
    escolhidos = contatos[:limite] if limite else contatos
    if not escolhidos:
        db.commit()  # guarda quem pediu SAIR (fora_motivo)
        return None
    dias_da_janela = janela(db)
    grupos = [(onda, n) for c in escolhidos for n, onda in enumerate(ondas(c, dias_da_janela))]
    ultimo = max(c.data_vencimento for g, _ in grupos for c in g.certificados)
    datas = datas_da_campanha(db, [g for g, _ in grupos], pessoa=usuario)
    from . import conexoes

    try:  # o número dos disparos fica gravado na campanha (dá para trocar na página dela): nunca um de modo teste
        numero = numero_do_envio(db, usuario)
    except conexoes.SemNumero:  # sem número agora: vale o escolhido na tela se for de quem monta (ou compartilhado com
        # ele); senão, o automático na hora do envio. Em 17/11/2026 a campanha da Thamires (Grupo Certy) ficou gravada
        # com o número do Paulo Lucas (MS), o da configuração da Renovação
        escolhido = cfg(db, "renov_conexao")
        fixo = db.get(conexoes.ConexaoWhatsApp, escolhido) if escolhido else None
        numero = fixo.id if fixo is not None and conexoes.pode_disparar(usuario, fixo) else ""
    camp = Campanha(tenant_id=ar, nome=(nome or f"Renovação {hoje:%d/%m} – vencem até {ultimo:%d/%m}")[:160],
                    tipo=TIPO_CAMPANHA,
                    objetivo="Renovar o certificado digital dos clientes", quantidade=len(escolhidos),
                    canais=cfg(db, "renov_canais"), status="gerando", usuario_id=usuario.id, inicio=hoje,
                    cadencia_id=garantir_cadencia(db).id, conexao_id=numero or "",
                    envio_oficial=envio_oficial_da_ar(db, ar),  # a chave da marca da campanha (e a API pronta)
                    email_html=cfg(db, "renov_email_html") != "0",
                    pedido=f"Clientes com certificado vencendo até {ultimo:%d/%m/%Y} (planilha de renovação)")
    db.add(camp)
    db.commit()
    trabalhos.iniciar("campanha", camp.id, usuario.id, {"fase": "renovacao", "grupos": [
        {"ids": [c.id for c in g.certificados], "datas": [d.isoformat() if d else None for d in ds], "onda": n}
        for (g, n), ds in zip(grupos, datas)]})
    return camp


def ar_de_quem_monta(db, usuario: Usuario | None) -> int | None:
    """A AR da campanha de renovação: a da tela (inclusive a do Admin Master dentro de uma AR); sem tela (rodada
    diária), a de quem monta (o dono da Renovação); o Admin Master fora de uma AR: a AR MS (ars.PADRAO)."""
    from . import isolamento

    ar = isolamento.ar_da_sessao(db)
    if ar and ar > 0:
        return ar
    if usuario is not None and getattr(usuario, "tenant_id", None):
        return usuario.tenant_id
    return isolamento._id_da_ar(db, "ms")


def datas_da_campanha(db, contatos: list[Contato], ignorar_campanha: int | None = None,
                      pessoa: Usuario | None = None) -> list[list[date | None]]:
    """As datas dos avisos de cada contato (na mesma ordem), com o teto de WhatsApps por dia contando os avisos de
    renovação já marcados nas outras campanhas. Quem só tem e-mail não ocupa vaga do WhatsApp."""
    pular_fds = True  # Renovação: só de segunda a sexta (pedido da Maria em 13/11/2026)
    inicio = primeiro_dia(db, pessoa)
    canais = cfg(db, "renov_canais")
    dias = dias_aviso(db)
    com_zap = ["whatsapp" in canais and bool(c.whatsapp) for c in contatos]
    carga = carga_marcada(db, inicio, ignorar_campanha)
    sem_envio = dias_sem_envio(db, pessoa)  # feriados (pedido da Maria em 13/11/2026) e os da cidade de quem é
    agendadas = iter(agenda([c.vencimento for c, z in zip(contatos, com_zap) if z], inicio, pular_fds, carga,
                            teto_por_dia(db), dias, sem_envio))
    return [next(agendadas) if z else datas_dos_avisos(c.vencimento, inicio, pular_fds, dias, sem_envio)
            for c, z in zip(contatos, com_zap)]


def _nome_do_contato(contato: Contato) -> str:
    nomes = list(dict.fromkeys(c.cliente_nome for c in contato.certificados if c.cliente_nome))
    if len(nomes) == 1:
        return nomes[0][:200]
    base = _nome_proprio(contato.responsavel) if contato.responsavel else nomes[0]
    return f"{base} ({len(contato.certificados)} certificados)"[:200]


def _lead_para_o_contato(db, contato: Contato, usuario: Usuario, ar: int | None = None) -> tuple[Lead | None, str]:
    """Lead do contato: o que já existe na AR da campanha (completando o que faltar com a planilha) ou um novo.
    (None, motivo) = fica de fora agora."""
    from .leads_servico import criar_lead, historico, limpar_campos

    lead = lead_do_contato(db, contato.chave, ar)
    if lead is not None:
        motivo = motivo_de_fora(db, lead)
        if motivo:
            return None, motivo
        mudou = False
        for campo, valor in (("whatsapp", contato.whatsapp), ("email", contato.email), ("telefone", contato.telefone),
                             ("responsavel", contato.responsavel[:120])):
            if valor and not (getattr(lead, campo) or "").strip():
                setattr(lead, campo, valor)
                mudou = True
        if mudou:
            limpar_campos(lead)
        historico(db, lead.id, "sistema", "Entrou numa campanha de renovação do certificado digital.", usuario)
        return lead, ""
    unico = contato.certificados[0] if len(contato.certificados) == 1 else None
    dados = {"empresa": _nome_do_contato(contato), "responsavel": contato.responsavel[:120],
             "whatsapp": contato.whatsapp, "email": contato.email, "telefone": contato.telefone,
             "cnpj": unico.cnpj if unico is not None and not _e_pessoa(unico) else "",
             "observacoes": "Cliente: aviso de renovação do certificado digital (planilha de renovação)."}
    lead, _ = criar_lead(db, dados, usuario, origem=ORIGEM_LEAD, checar_duplicado=False)
    if lead is not None:
        lead.base_legal = "Legítimo interesse: cliente da empresa (renovação do certificado)"
    return lead, ""


def etapa_preparar(campanha_id: int, estado: dict, prazo: float) -> bool:
    """Fase "renovacao" da montagem (campanhas.etapa_gerar): cada contato vira lead (ou usa o que já existe), os
    certificados ficam presos à campanha e saem as datas e os textos dos avisos. True = pronta para montar."""
    import time

    grupos = estado.get("grupos") or []
    estado.setdefault("feitos", 0)
    estado.setdefault("escolhidos", [])
    estado.setdefault("textos", {})
    estado.setdefault("datas", {})
    estado.setdefault("fora", {})
    hoje = date.today()
    while estado["feitos"] < len(grupos):
        if time.monotonic() > prazo:
            return False
        lote = grupos[estado["feitos"]:estado["feitos"] + 10]
        with sessao() as db:
            camp = db.get(Campanha, campanha_id)
            # em segundo plano não há a marca da tela: os textos, os dias, o horário e os feriados são os da Renovação
            # da marca da campanha (26/11/2026: os avisos do Grupo Certy saíam com os textos da plataforma)
            usar_config_da_ar(db, camp.tenant_id)
            usuario = db.get(Usuario, camp.usuario_id)
            pular_fds = True  # Renovação: só de segunda a sexta
            for grupo in lote:
                ids = grupo["ids"] if isinstance(grupo, dict) else grupo
                onda = grupo.get("onda", 0) if isinstance(grupo, dict) else 0
                certs = [c for c in (db.get(Certificado, i) for i in ids)
                         if c is not None and c.status == "Ativo" and c.campanha_id in (None, campanha_id)
                         and c.data_vencimento > hoje]
                if not certs:
                    continue
                certs.sort(key=lambda c: (c.data_vencimento, c.id))
                contato = Contato(chave_do_contato(certs[0]), certs)
                # as datas vêm prontas da criação (agenda com o teto por dia); sem elas, as regras simples
                datas = ([date.fromisoformat(d) if d else None for d in grupo["datas"]]
                         if isinstance(grupo, dict) and grupo.get("datas") and len(certs) == len(ids)
                         else datas_dos_avisos(contato.vencimento, primeiro_dia(db, usuario), pular_fds,
                                               dias_aviso(db), dias_sem_envio(db, usuario)))
                if not any(datas):
                    continue
                if onda:  # 2ª onda do mesmo contato: o lead é o da 1ª (se ela entrou), com avisos próprios
                    lead = lead_do_contato(db, contato.chave, camp.tenant_id)
                    if lead is None or lead.id not in estado["escolhidos"]:
                        continue
                    for c in certs:
                        c.campanha_id, c.lead_id = campanha_id, lead.id
                    estado.setdefault("ondas", {}).setdefault(str(lead.id), []).append(
                        {"textos": textos_do_contato(db, contato, usuario), "cert": certs[0].id,
                         "datas": [d.isoformat() if d else None for d in datas]})
                    continue
                lead, motivo = _lead_para_o_contato(db, contato, usuario, camp.tenant_id)
                if lead is None or lead.id in estado["escolhidos"]:
                    if motivo:
                        estado["fora"][motivo] = estado["fora"].get(motivo, 0) + len(certs)
                    continue
                for c in certs:
                    c.campanha_id, c.lead_id = campanha_id, lead.id
                estado["escolhidos"].append(lead.id)
                # entrou tarde e começa por um aviso que não é o 1º: ele diz quem escreve e traz o SAIR
                estado["textos"][str(lead.id)] = textos_do_contato(db, contato, usuario,
                                                                   primeiro=_angulo_do_primeiro(datas))
                estado["datas"][str(lead.id)] = [d.isoformat() if d else None for d in datas]
            db.commit()
        estado["feitos"] += len(lote)
    estado.pop("grupos", None)
    return True


def datas_do_estado(estado: dict) -> dict[int, list[date | None]] | None:
    """As datas guardadas no trabalho (texto) → {lead_id: [data ou None, ...]} para cadencias.aplicar."""
    datas = estado.get("datas")
    if not datas:
        return None
    return {int(k): [date.fromisoformat(x) if x else None for x in v] for k, v in datas.items()}


def ondas_do_estado(estado: dict) -> dict | None:
    """As ondas seguintes guardadas no trabalho → {lead_id: [{"textos", "cert", "datas": [data ou None]}]}."""
    if not estado.get("ondas"):
        return None
    return {int(k): [{**o, "datas": [date.fromisoformat(x) if x else None for x in o["datas"]]} for o in v]
            for k, v in estado["ondas"].items()}


def montar_ondas(db, camp: Campanha, cadencia, usuario: Usuario, ondas_por_lead: dict) -> int:
    """Os avisos das ondas seguintes (certificado do mesmo contato vencendo bem depois): os mesmos passos, com as
    datas e os textos da onda, na mesma campanha. Cada aviso guarda o certificado da onda. Devolve quantos criou."""
    from . import cadencias

    criadas = 0
    for i in range(max((len(v) for v in ondas_por_lead.values()), default=0)):
        da_vez = {lid: v[i] for lid, v in ondas_por_lead.items() if i < len(v)}
        leads = [lead for lead in (db.get(Lead, lid) for lid in da_vez) if lead is not None]
        antes = db.scalar(select(func.max(Tarefa.id))) or 0
        r = cadencias.aplicar(db, cadencia, leads, usuario, camp.inicio or date.today(), camp.id,
                              {lid: o["textos"] for lid, o in da_vez.items()},
                              [c for c in camp.canais.split(",") if c], "rascunho", camp.cta, camp.tom,
                              foco_whatsapp=True, datas_por_lead={lid: o["datas"] for lid, o in da_vez.items()},
                              permitir_em_andamento=True, hora_minima=hora_inicio(db),
                              hora_maxima=hora_fim(db), feriados=dias_sem_envio(db, usuario))
        db.flush()
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.id > antes)).scalars():
            t.certificado_id = da_vez[t.lead_id]["cert"]
        criadas += r["tarefas"]
    return criadas


def depois_de_montar(db, camp: Campanha) -> None:
    """Cada aviso guarda o certificado que define as datas (o primeiro a vencer do contato), para parar sozinho quando
    ele vencer ou for renovado. Contato que cadencias.aplicar pulou volta para a próxima campanha."""
    certs = db.execute(select(Certificado).where(Certificado.campanha_id == camp.id)
                       .order_by(Certificado.data_vencimento, Certificado.id)).scalars().all()
    primeiro: dict[int, int] = {}
    for c in certs:
        primeiro.setdefault(c.lead_id, c.id)
    com_aviso = set()
    for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id)).scalars():
        if t.certificado_id is None:
            t.certificado_id = primeiro.get(t.lead_id)
        com_aviso.add(t.lead_id)
    for c in certs:
        if c.lead_id not in com_aviso:
            c.campanha_id = None


def reajustar_na_aprovacao(db, camp: Campanha, rascunhos: list[Tarefa]) -> list[Tarefa]:
    """Campanha aprovada depois do dia em que foi montada: as datas são contadas de novo a partir do vencimento (as
    outras campanhas empurram tudo para frente, o que aqui jogaria avisos para depois do vencimento). Aviso que não
    cabe mais é cancelado. Devolve os que continuam."""
    from . import cadencias

    hoje = date.today()
    if not rascunhos or min(t.data for t in rascunhos) >= hoje:
        return rascunhos
    pular_fds = True  # Renovação: só de segunda a sexta
    dono = db.get(Usuario, camp.usuario_id) if camp.usuario_id else None
    sem_envio = dias_sem_envio(db, dono)  # e sem feriados (também os da cidade de quem é a campanha)
    inicio = primeiro_dia(db, dono)
    vencimentos = dict(db.execute(select(Certificado.id, Certificado.data_vencimento)
                                  .where(Certificado.campanha_id == camp.id)).all())
    ordem = {a: i for i, a in enumerate(ANGULOS)}
    por_lead: dict[tuple, list[Tarefa]] = {}
    for t in rascunhos:  # cada onda (lead + certificado que guia os avisos) é contada separada
        por_lead.setdefault((t.lead_id, t.certificado_id), []).append(t)
    dias = dias_aviso(db)
    minimo, maximo = hora_inicio(db), hora_fim(db)

    def vencimento_de(tarefas):
        return next((vencimentos.get(t.certificado_id) for t in tarefas if t.certificado_id), None)

    # do que vence primeiro ao último, com o teto de WhatsApps por dia (como na criação)
    grupos = sorted(por_lead.values(), key=lambda ts: (vencimento_de(ts) or date.max, ts[0].lead_id))
    com_zap = [vencimento_de(ts) is not None and any(t.canal == "whatsapp" for t in ts) for ts in grupos]
    agendadas = iter(agenda([vencimento_de(ts) for ts, z in zip(grupos, com_zap) if z], inicio, pular_fds,
                            carga_marcada(db, inicio, ignorar_campanha=camp.id), teto_por_dia(db), dias, sem_envio))
    continuam = []
    for tarefas, zap_no_grupo in zip(grupos, com_zap):
        vencimento = vencimento_de(tarefas)
        if zap_no_grupo:
            datas = next(agendadas)
        else:
            datas = (datas_dos_avisos(vencimento, inicio, pular_fds, dias, sem_envio) if vencimento
                     else [None] * len(dias))
        zaps = {}
        primeira = next((i for i, d in enumerate(datas) if d is not None), None)
        for t in sorted(tarefas, key=lambda t: t.canal != "whatsapp"):  # o WhatsApp primeiro: o e-mail vem depois dele
            i = ordem.get(t.angulo)
            nova = datas[i] if i is not None and i < len(datas) else None
            if nova is None:
                t.status, t.concluida_em = "cancelada", agora()
                t.resultado = ("A etapa deste aviso já passou: o cliente começa pelo aviso de agora (campanha aprovada "
                               "depois)" if primeira is not None and i is not None and i < primeira
                               else "Não cabe mais antes do vencimento (campanha aprovada depois)")
                continue
            if t.canal == "whatsapp":
                zaps[t.angulo] = t
            if primeira and i == primeira:  # começa por um aviso que não é o 1º: ele diz quem escreve e traz o SAIR
                _textos_de_primeiro(db, t, dono)
            if t.data != nova:
                zap = zaps.get(t.angulo) if t.canal == "email" else None
                if zap is not None:  # o e-mail no dia do WhatsApp do aviso (26/11/2026)
                    t.data, t.hora = cadencias.depois_de(db, zap.data, zap.hora or "09:00", pular_fds=pular_fds,
                                                         minimo=minimo, maximo=maximo, feriados=sem_envio,
                                                         mesmo_dia=True)
                else:
                    t.data = nova
            continuam.append(t)
    return continuam


def linha_do_sair(db) -> str:
    """A frase do SAIR do 1º aviso (tela Renovação): vai também no primeiro WhatsApp do contato quando ele começa por
    outro aviso. "" = o 1º aviso não tem a frase (tirada na tela): nada a acrescentar."""
    texto = mensagens(db)["renov_aviso"]["whatsapp"] or ""
    return next((linha.strip() for linha in reversed(texto.splitlines()) if "SAIR" in linha), "")


def com_sair(texto: str, linha: str) -> str:
    """O texto com a frase do SAIR no fim (se ainda não tem)."""
    if not linha or "SAIR" in (texto or ""):
        return texto
    return (texto or "").rstrip() + "\n\n" + linha


def _angulo_do_primeiro(datas: list) -> str:
    """O aviso que sai primeiro para o contato, quando não é o 1º aviso ("" = é o 1º, ou nenhum)."""
    primeira = next((i for i, d in enumerate(datas) if d is not None), None)
    angulos = list(ANGULOS)
    return angulos[primeira] if primeira and primeira < len(angulos) else ""


def _usar_textos(t: Tarefa, texto: dict) -> None:
    """Grava no aviso os textos novos ({"whatsapp", "email", "assunto"}): o do canal dele e as versões guardadas do outro
    canal que ele já tinha (cadencias.aplicar deixa cada mensagem num canal só)."""
    if t.canal == "email":
        t.assunto, t.mensagem = texto["assunto"], texto["email"]
    else:
        t.mensagem = texto["whatsapp"]
    if (t.mensagem_whatsapp or "").strip():
        t.mensagem_whatsapp = texto["whatsapp"]
    if (t.mensagem_email or "").strip():
        t.mensagem_email = texto["email"]
    if (t.assunto_email or "").strip():
        t.assunto_email = texto["assunto"]


def _textos_de_primeiro(db, t: Tarefa, dono: Usuario | None) -> bool:
    """O aviso `t` é o primeiro contato da campanha, mas não é o 1º aviso: refaz os textos dele dizendo quem escreve
    (e, no WhatsApp, com o SAIR), com a marca de quem é a campanha. False = sem certificado ativo (fica como está)."""
    certs = certificados_do_aviso(db, t)
    if not certs:
        return False
    contato = Contato(chave_do_contato(certs[0]), certs)
    _usar_textos(t, textos_do_contato(db, contato, dono, primeiro=t.angulo)[t.angulo])
    return True


JUNTADO_AO_ATRASADO = "Não saiu: o aviso anterior atrasou e saiu já com o texto desta etapa"
PERTO_DO_ATRASADO = "Não saiu: ficaria a menos de 2 dias do aviso atrasado, que saiu com o texto da etapa de agora"
ETAPA_JA_SAIU = "Não saiu: o aviso desta etapa (ou um depois dela) já tinha sido enviado por este canal"


def _ja_recebeu(db, t: Tarefa) -> bool:
    """O contato já recebeu alguma mensagem desta campanha pelo canal deste aviso?"""
    from . import mensagens as registro
    from .modelos import Mensagem

    return db.execute(select(Mensagem.id).where(
        Mensagem.lead_id == t.lead_id, Mensagem.campanha_id == t.campanha_id, Mensagem.canal == t.canal,
        Mensagem.direcao == "saida", Mensagem.status.in_(registro.ENVIADAS)).limit(1)).first() is not None


def ajustar_a_etapa(db, t: Tarefa, hoje: date | None = None) -> bool:
    """Na hora de sair, o aviso de renovação vai com o texto da etapa em que o cliente está (pedido da Maria em
    19/11/2026: "se o certificado do cliente X vence dia 20/11, não envie a primeira mensagem da campanha de renovação,
    mas a de acordo com os dias que faltam"). Aviso atrasado (número desconectado, fila parada, e-mail esperando a
    conta) cuja etapa já passou ganha o texto, o assunto e o tipo do aviso de agora (etapa_do_dia); os avisos do mesmo
    canal que ele substitui são cancelados, e o seguinte também, se ficaria a menos de INTERVALO_MINIMO_DIAS dias
    (nunca em dias seguidos). O primeiro aviso que o contato recebe na campanha por um canal, quando não é o 1º aviso,
    diz quem escreve, com a marca de quem é a campanha, e no WhatsApp traz o SAIR (textos_do_contato, primeiro=).
    Vale igual para todas as marcas: dias, textos e feriados vêm da campanha e do dono dela, não de quem clica.
    Chamado por todos os envios (filas, Minha fila, Disparar, Agenda e API oficial). Devolve False quando este aviso
    não deve mais sair: o desta etapa (ou um depois dele) já saiu por este canal; ele fica cancelado."""
    from .modelos import PassoCadencia

    if t is None or t.angulo not in ANGULOS or not t.campanha_id or not t.lead_id:
        return True
    camp = db.get(Campanha, t.campanha_id)
    if camp is None or camp.tipo != TIPO_CAMPANHA:
        return True
    hoje = hoje or date.today()
    ordem = list(ANGULOS)
    atual = ordem.index(t.angulo)
    dono = db.get(Usuario, camp.usuario_id) if camp.usuario_id else None
    cert = db.get(Certificado, t.certificado_id) if t.certificado_id else None
    etapa = atual
    if cert is not None and cert.data_vencimento >= hoje:
        etapa = max(atual, etapa_do_dia(cert.data_vencimento, hoje, True, dias_aviso(db), dias_sem_envio(db, dono)))
    if etapa > atual:
        irmaos = db.execute(select(Tarefa).where(
            Tarefa.campanha_id == t.campanha_id, Tarefa.lead_id == t.lead_id, Tarefa.certificado_id == t.certificado_id,
            Tarefa.tipo == "prospeccao", Tarefa.canal == t.canal, Tarefa.id != t.id,
            Tarefa.angulo.in_(ordem[atual + 1:]))).scalars().all()
        if any(i.status == "feita" for i in irmaos):
            t.status, t.concluida_em, t.resultado = "cancelada", agora(), ETAPA_JA_SAIU
            return False
        certs = certificados_do_aviso(db, t)
        if certs:
            novo = ordem[etapa]
            primeiro = novo if not _ja_recebeu(db, t) else ""  # o primeiro contato diz quem escreve (e o SAIR)
            _usar_textos(t, textos_do_contato(db, Contato(chave_do_contato(certs[0]), certs), dono,
                                              primeiro=primeiro)[novo])
            # a cadência da campanha (pode ser de outra AR que a de quem clica: a busca é pelo id dela)
            passos = ({p.angulo: p for p in db.execute(select(PassoCadencia).where(
                PassoCadencia.cadencia_id == camp.cadencia_id).execution_options(sem_filtro_de_ar=True)).scalars()}
                if camp.cadencia_id else {})
            antigo, novo_passo = passos.get(t.angulo), passos.get(novo)
            if novo_passo is not None:
                if antigo is not None and t.acao == antigo.acao:
                    t.acao = novo_passo.acao
                if t.passo_id == (antigo.id if antigo is not None else None):
                    t.passo_id = novo_passo.id
            t.angulo = novo  # telas e relatórios mostram o aviso que saiu de verdade
            for irmao in irmaos:
                if irmao.status not in ("pendente", "rascunho"):
                    continue
                if ordem.index(irmao.angulo) <= etapa:
                    irmao.status, irmao.concluida_em, irmao.resultado = "cancelada", agora(), JUNTADO_AO_ATRASADO
                elif (irmao.data - hoje).days < INTERVALO_MINIMO_DIAS:
                    irmao.status, irmao.concluida_em, irmao.resultado = "cancelada", agora(), PERTO_DO_ATRASADO
    elif (t.canal == "whatsapp" and t.angulo != PRIMEIRO_AVISO and linha_do_sair(db)
          and "SAIR" not in (t.mensagem or "") and not _ja_recebeu(db, t)):
        _textos_de_primeiro(db, t, dono)  # o 1º aviso não saiu (ex.: cancelado no feriado): este se apresenta
    return True


def encerrar_toques(db, hoje: date | None = None) -> int:
    """Cancela os avisos que não devem mais sair: o certificado venceu (pedido da Maria: só quem vai vencer recebe) ou
    foi marcado como renovado / não vai renovar. Devolve quantos foram cancelados."""
    hoje = hoje or date.today()
    fim = select(Certificado.id).where(Certificado.origem == ORIGEM, or_(Certificado.data_vencimento < hoje,
                                                                         Certificado.status.in_(ENCERRADOS)))
    tarefas = db.execute(select(Tarefa).where(
        Tarefa.tipo == "prospeccao", Tarefa.campanha_id.is_not(None), Tarefa.status.in_(("pendente", "rascunho")),
        Tarefa.certificado_id.in_(fim))).scalars().all()
    for t in tarefas:
        cert = t.certificado
        venceu = cert is not None and cert.data_vencimento < hoje
        t.status, t.concluida_em = "cancelada", agora()
        t.resultado = ("Não saiu antes do vencimento (quem já venceu não recebe aviso)" if venceu
                       else "Avisos cancelados na tela Renovação" if cert is not None and cert.status == "Avisos cancelados"
                       else f"Certificado marcado como {SITUACOES.get(cert.status, cert.status).lower()}"
                       if cert is not None else "Certificado não existe mais")
    return len(tarefas)


def emails_no_dia_do_whatsapp(db, camp: Campanha) -> int:
    """O e-mail de cada aviso sai no MESMO dia do WhatsApp do aviso: umas 2 horas depois dele, se couber no horário de
    envio da marca; senão, logo depois dele (cadencias.depois_de com mesmo_dia; a fila de e-mail espera o WhatsApp do
    aviso sair). Pedido da Maria em 26/11/2026: na campanha do Grupo Certy, o WhatsApp do fim da tarde jogava o e-mail
    para o dia útil seguinte, e o do último aviso caía no dia do vencimento. Antes (13/11/2026, "os de sábados e domingos
    avisar na sexta") só o e-mail que passaria do vencimento voltava para o dia do WhatsApp. Roda no fim da montagem e
    na aprovação, com o horário e os feriados da marca da campanha. Devolve quantos mudaram."""
    from . import cadencias
    from .banco import config_da_ar

    tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.tipo == "prospeccao",
                                              Tarefa.status.in_(("rascunho", "pendente")))).scalars().all()
    zaps = {(t.lead_id, t.certificado_id, t.angulo): t for t in tarefas if t.canal == "whatsapp"}
    fora_do_dia = [(t, zaps[(t.lead_id, t.certificado_id, t.angulo)]) for t in tarefas if t.canal == "email"
                   and (t.lead_id, t.certificado_id, t.angulo) in zaps
                   and t.data != zaps[(t.lead_id, t.certificado_id, t.angulo)].data]
    if not fora_do_dia:
        return 0
    dono = db.get(Usuario, camp.usuario_id) if camp.usuario_id else None
    with config_da_ar(db, camp.tenant_id):
        minimo, maximo, sem_envio = hora_inicio(db), hora_fim(db), dias_sem_envio(db, dono)
        for t, zap in fora_do_dia:
            t.data, t.hora = cadencias.depois_de(db, zap.data, zap.hora or "09:00", pular_fds=True, minimo=minimo,
                                                 maximo=maximo, feriados=sem_envio, mesmo_dia=True)
    return len(fora_do_dia)


def _dia_que_cabe(dia: date, vencimento: date, antes: date | None, depois: date | None, inicio: date,
                  sem_envio: frozenset, carga: Counter | None = None, teto: int = 0) -> date | None:
    """O dia útil mais perto de `dia` (primeiro para trás, depois para frente) em que um aviso cabe: a partir de
    `inicio`, até o vencimento, a INTERVALO_MINIMO_DIAS ou mais dos avisos vizinhos do contato e, para o WhatsApp
    (`carga`), com vaga no teto do dia. None = não cabe em dia nenhum."""
    def cabe(d: date) -> bool:
        return (d.weekday() < 5 and d not in sem_envio
                and (antes is None or (d - antes).days >= INTERVALO_MINIMO_DIAS)
                and (depois is None or (depois - d).days >= INTERVALO_MINIMO_DIAS)
                and (carga is None or not teto or carga[d] < teto))

    d = dia - timedelta(days=1)
    while d >= inicio and (antes is None or d > antes):
        if cabe(d):
            return d
        d -= timedelta(days=1)
    d = dia + timedelta(days=1)
    while d <= vencimento and (depois is None or d < depois):
        if cabe(d):
            return d
        d += timedelta(days=1)
    return None


def remarcar_feriados(db, hoje: date | None = None, aplicar: bool = True) -> dict:
    """Os avisos em aberto marcados para um feriado mudam de dia (ver _remarcar_feriados_da_marca), cada marca com os
    feriados, o horário e os dias dela (24/11/2026). Devolve as contas de todas juntas."""
    from .banco import config_da_ar

    ars = set(db.execute(select(Campanha.tenant_id).where(
        Campanha.tipo == TIPO_CAMPANHA, Campanha.status.in_(("aguardando_aprovacao", "ativa", "pausada")))).scalars())
    feito = {"remarcados": 0, "cancelados": 0, "so_email": 0, "mudancas": Counter()}
    for ar in sorted(ars, key=lambda a: a or 0):
        with config_da_ar(db, ar):
            parte = _remarcar_feriados_da_marca(db, hoje, aplicar, ar)
        for chave in ("remarcados", "cancelados", "so_email"):
            feito[chave] += parte[chave]
        feito["mudancas"].update(parte["mudancas"])
    return feito


def _remarcar_feriados_da_marca(db, hoje: date | None, aplicar: bool, ar: int | None) -> dict:
    """Avisos de renovação em aberto marcados para um feriado (a campanha piloto foi montada antes desta regra, ou um
    feriado escrito depois na tela) mudam de dia (pedido da Maria em 13/11/2026: "pular feriados"): o dia útil mais
    perto, antes do feriado se der, respeitando as regras de sempre (2 dias entre os avisos do contato, nada depois do
    vencimento, teto de WhatsApps por dia). Quem vence antes escolhe antes. Se o aviso anterior do contato atrapalha
    (ex.: vence no sábado 26/12, o de 3 dias é na quarta 23/12 e o último cairia no Natal), o anterior recua uns dias e
    este fica no dia útil antes do feriado. Sem vaga de WhatsApp em outro dia, o aviso vai só por e-mail; sem dia
    nenhum, é cancelado. O e-mail do aviso fica para umas 2 horas depois do WhatsApp, como sempre. aplicar=False só
    calcula (para conferir antes). Devolve as contas e as mudanças de dia."""
    from . import cadencias

    hoje = hoje or date.today()
    abertos = ("pendente", "rascunho")
    # os feriados de quem é cada campanha (nacionais, "Outros feriados" e os do estado e da cidade dela: 18/11/2026)
    donos = dict(db.execute(select(Campanha.id, Campanha.usuario_id).where(
        Campanha.tipo == TIPO_CAMPANHA, Campanha.status.in_(("aguardando_aprovacao", "ativa", "pausada")),
        das_marcas(Campanha.tenant_id, {ar}))).all())  # só as campanhas desta marca
    por_dono = {uid: dias_sem_envio(db, db.get(Usuario, uid) if uid else None) for uid in set(donos.values())}
    sem_envio_da = {cid: por_dono[uid] for cid, uid in donos.items()}
    sem_envio = frozenset().union(*por_dono.values()) if por_dono else frozenset()
    todos_os_dias = sem_envio
    feito = {"remarcados": 0, "cancelados": 0, "so_email": 0, "mudancas": Counter()}
    em_feriado = [t for t in db.execute(select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id).where(
        Campanha.tipo == TIPO_CAMPANHA, Campanha.status.in_(("aguardando_aprovacao", "ativa", "pausada")),
        das_marcas(Campanha.tenant_id, {ar}),
        Tarefa.tipo == "prospeccao", Tarefa.status.in_(abertos), Tarefa.data >= hoje,
        Tarefa.data.in_(sorted(sem_envio)))).scalars().all()
        if t.data in sem_envio_da.get(t.campanha_id, frozenset())] if sem_envio else []
    certs = {c.id: c for c in db.execute(select(Certificado).where(
        Certificado.id.in_({t.certificado_id for t in em_feriado if t.certificado_id}))).scalars()} if em_feriado else {}
    if not certs:
        return feito
    teto = teto_por_dia(db)
    carga = carga_marcada(db, hoje)
    minimo, maximo = hora_inicio(db), hora_fim(db)
    inicio = primeiro_dia(db)
    ordem = {a: i for i, a in enumerate(ANGULOS)}
    novas: dict[int, tuple | None] = {}  # id da tarefa -> (data, hora) nova, ou None (cancelar)
    motivos: dict[int, str] = {}
    todas: dict[int, Tarefa] = {}

    def dia_de(t: Tarefa) -> date:
        return novas[t.id][0] if novas.get(t.id) else t.data

    def hora_de(t: Tarefa) -> str:
        return novas[t.id][1] if novas.get(t.id) else (t.hora or "10:07")

    def mover(t: Tarefa, d: date) -> None:
        hora = hora_de(t)
        if d == date.today():  # hoje: um horário que ainda não passou
            hora = cadencias.hora_natural(db, d, minimo, maximo) or hora
        if t.canal == "whatsapp":
            carga[dia_de(t)] -= 1
            carga[d] += 1
        novas[t.id] = (d, hora)

    def cancelar(t: Tarefa, motivo: str) -> None:
        if t.canal == "whatsapp" and novas.get(t.id, ()) is not None:
            carga[dia_de(t)] -= 1
        novas[t.id] = None
        motivos[t.id] = motivo

    ondas = sorted({(t.campanha_id, t.lead_id, t.certificado_id) for t in em_feriado if t.certificado_id in certs},
                   key=lambda k: (certs[k[2]].data_vencimento, k[1] or 0, k[0] or 0))  # quem vence antes escolhe antes
    for campanha_id, lead_id, certificado_id in ondas:
        sem_envio = sem_envio_da.get(campanha_id, todos_os_dias)  # os feriados de quem é esta campanha
        venc = certs[certificado_id].data_vencimento
        avisos: dict[int, dict[str, Tarefa]] = {}
        for t in db.execute(select(Tarefa).where(
                Tarefa.campanha_id == campanha_id, Tarefa.lead_id == lead_id, Tarefa.certificado_id == certificado_id,
                Tarefa.tipo == "prospeccao", Tarefa.status != "cancelada")).scalars():
            if t.angulo in ordem:
                avisos.setdefault(ordem[t.angulo], {})[t.canal] = t
                todas[t.id] = t
        indices = sorted(avisos)

        def principal(i: int) -> Tarefa | None:
            """A tarefa que marca o dia do aviso: o WhatsApp (ou o e-mail, se o WhatsApp não vai)."""
            zap_i, email_i = avisos[i].get("whatsapp"), avisos[i].get("email")
            if zap_i is not None and novas.get(zap_i.id, ()) is not None:
                return zap_i
            return email_i if email_i is not None and novas.get(email_i.id, ()) is not None else None

        def vizinho(pos: int, lado: int) -> date | None:
            outros = [principal(j) for j in (indices[:pos] if lado < 0 else indices[pos + 1:])]
            datas = [dia_de(t) for t in outros if t is not None]
            return (max(datas) if lado < 0 else min(datas)) if datas else None

        def email_depois(i: int, depois: date | None) -> None:
            """O e-mail do aviso: no dia do WhatsApp, umas 2 horas depois dele ou, se isso passar do horário, logo
            depois dele (26/11/2026); se ainda assim não couber antes do próximo aviso (ou do vencimento), junto com o
            WhatsApp (a fila de e-mail espera o WhatsApp da empresa sair)."""
            zap_i, email_i = avisos[i].get("whatsapp"), avisos[i].get("email")
            if (zap_i is None or email_i is None or email_i.status not in abertos
                    or novas.get(zap_i.id, ()) is None or novas.get(email_i.id, ()) is None):
                return
            if zap_i.id not in novas and email_i.data not in sem_envio:
                return  # nada mudou
            d, h = cadencias.depois_de(db, dia_de(zap_i), hora_de(zap_i), pular_fds=True, minimo=minimo,
                                       maximo=maximo, feriados=sem_envio, mesmo_dia=True)
            if d > venc or (depois is not None and d >= depois):
                d, h = dia_de(zap_i), hora_de(zap_i)
            novas[email_i.id] = (d, h)

        def abrir_espaco(pos: int, aviso: Tarefa, usa_zap: bool, depois: date | None) -> date | None:
            """O aviso anterior (em aberto) recua uns dias para este caber no dia útil antes do feriado."""
            j = indices[pos - 1]
            anterior = principal(j)
            if anterior is None or anterior.status not in abertos or dia_de(anterior) in sem_envio:
                return None
            alvo = _dia_util_antes(aviso.data - timedelta(days=1), sem_envio)
            if (alvo < inicio or alvo > venc or (depois is not None and (depois - alvo).days < INTERVALO_MINIMO_DIAS)
                    or (usa_zap and teto and carga[alvo] >= teto)):
                return None
            limite = alvo - timedelta(days=INTERVALO_MINIMO_DIAS)
            if dia_de(anterior) <= limite:
                return None  # o anterior não atrapalha (falta vaga no dia): mexer nele não adianta
            zap_ant = avisos[j].get("whatsapp")
            novo = _dia_que_cabe(limite + timedelta(days=1), venc, vizinho(pos - 1, -1), alvo, inicio, sem_envio,
                                 carga if anterior is zap_ant else None, teto)
            if novo is None:
                return None
            mover(anterior, novo)
            email_depois(j, alvo)
            return alvo

        for pos, i in enumerate(indices):
            aviso = principal(i)
            if aviso is None or aviso.status not in abertos:
                continue
            zap, email = avisos[i].get("whatsapp"), avisos[i].get("email")
            antes, depois = vizinho(pos, -1), vizinho(pos, 1)
            if aviso.data in sem_envio:
                usa_zap = aviso is zap
                dia = _dia_que_cabe(aviso.data, venc, antes, depois, inicio, sem_envio, carga if usa_zap else None,
                                    teto)
                if dia is None and pos > 0:
                    dia = abrir_espaco(pos, aviso, usa_zap, depois)
                    antes = vizinho(pos, -1)
                if dia is not None:
                    mover(aviso, dia)
                elif (usa_zap and email is not None and email.status in abertos
                      and (dia := _dia_que_cabe(aviso.data, venc, antes, depois, inicio, sem_envio)) is not None):
                    cancelar(zap, "Caía num feriado e não havia vaga de WhatsApp em outro dia: o aviso vai só por e-mail")
                    novas[email.id] = (dia, email.hora or "10:07")
                    if dia == date.today():
                        novas[email.id] = (dia, cadencias.hora_natural(db, dia, minimo, maximo) or email.hora or "10:07")
                    feito["so_email"] += 1
                    continue
                else:
                    for t in (zap, email):
                        if t is not None and t.status in abertos:
                            cancelar(t, "Caía num feriado e não coube em outro dia antes do vencimento")
                    continue
            email_depois(i, depois)
    for tid, nova in novas.items():
        t = todas[tid]
        if nova is None:
            feito["cancelados"] += 1
            feito["mudancas"][(t.data, None)] += 1
            if aplicar:
                t.status, t.concluida_em, t.resultado = "cancelada", agora(), motivos.get(tid, "Caía num feriado")
        elif tuple(nova) != (t.data, t.hora):
            feito["remarcados"] += 1
            feito["mudancas"][(t.data, nova[0])] += 1
            if aplicar:
                t.data, t.hora = nova
    return feito


def liberar_da_campanha(db, camp: Campanha) -> int:
    """Campanha de renovação cancelada: os certificados de quem ainda não recebeu nenhum aviso dela voltam para a fila
    (podem entrar numa campanha nova). Quem já recebeu continua preso a ela (não recebe o 1º aviso de novo)."""
    avisados = set(db.execute(select(Tarefa.lead_id).where(Tarefa.campanha_id == camp.id,
                                                           Tarefa.status == "feita")).scalars())
    livres = 0
    for c in db.execute(select(Certificado).where(Certificado.campanha_id == camp.id)).scalars():
        if c.lead_id not in avisados and c.status == "Ativo":
            c.campanha_id = None
            livres += 1
    return livres


def antes_de_excluir(db, camp: Campanha) -> None:
    """Campanha de renovação excluída: quem já recebeu aviso dela não entra em outra sozinho (fica marcado); os outros
    voltam para a fila."""
    liberar_da_campanha(db, camp)
    for c in db.execute(select(Certificado).where(Certificado.campanha_id == camp.id)).scalars():
        c.campanha_id = None
        if c.status == "Ativo":
            c.fora_motivo = f"já recebeu aviso na campanha excluída \"{camp.nome}\""[:160]


def ativos_do_lead(db, lead: Lead) -> list[Certificado]:
    """Certificados da planilha ainda ativos do contato deste lead (os que receberam aviso por ele), do que vence
    primeiro ao último. Usado no descarte "Já renovou" da tela Oportunidades."""
    return db.execute(select(Certificado).where(Certificado.lead_id == lead.id, Certificado.origem == ORIGEM,
                                                Certificado.status == "Ativo")
                      .order_by(Certificado.data_vencimento, Certificado.id)).scalars().all()


def mudar_situacao(db, cert: Certificado, situacao: str, usuario: Usuario | None) -> int:
    """Renovado / Não renovará / Avisos cancelados: os avisos que ainda não saíram param, WhatsApp e e-mail (se o contato
    tiver outro certificado na mesma onda, os avisos continuam por ele). Ativo (Reabrir): volta para a fila se a
    campanha dele já acabou. Devolve quantos avisos foram cancelados."""
    cert.status = situacao
    cancelados = 0
    tarefas = []
    if cert.campanha_id and cert.lead_id:
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cert.campanha_id, Tarefa.lead_id == cert.lead_id,
                                                  Tarefa.status.in_(("pendente", "rascunho")))).scalars().all()
    if situacao in ("Renovado", "Não renovará", "Avisos cancelados") and tarefas:
        # os avisos guiados por este certificado (a onda dele) continuam por outro certificado ativo da mesma onda; sem
        # outro, param. Os avisos das outras ondas do contato não mudam.
        outro = db.execute(select(Certificado).where(
            Certificado.campanha_id == cert.campanha_id, Certificado.lead_id == cert.lead_id, Certificado.id != cert.id,
            Certificado.status == "Ativo", Certificado.data_vencimento >= cert.data_vencimento,
            Certificado.data_vencimento <= cert.data_vencimento + timedelta(days=janela(db)))
            .order_by(Certificado.data_vencimento)).scalars().first()
        for t in tarefas:
            if t.certificado_id != cert.id:
                continue
            if outro is not None:
                t.certificado_id = outro.id
                continue
            t.status, t.concluida_em = "cancelada", agora()
            t.resultado = (("Avisos cancelados" if situacao == "Avisos cancelados"
                            else f"Certificado marcado como {SITUACOES[situacao].lower()}")
                           + (f" por {usuario.nome}" if usuario else ""))
            cancelados += 1
    if situacao == "Ativo":
        cert.fora_motivo = ""
        if not tarefas:
            cert.campanha_id = None  # a campanha dele acabou: pode entrar numa nova
    return cancelados


def automatica_na_ar(db, ar: int | None) -> bool:
    """A campanha automática do dia (rodada_diaria) roda para esta AR? Por enquanto só para a AR principal (a de
    marca.ar_padrao). Nas outras a tela não mostra o liga/desliga nem o horário (26/11/2026: o Grupo Certy ligou às
    08:45 achando que ia rodar) e as campanhas são montadas no quadro 3."""
    from . import marca

    return ar is not None and ar == marca.ar_padrao(db)


def rodada_diaria() -> str:
    """Chamado pelo relógio (a cada 15 min): uma vez por dia, depois do horário configurado, monta a campanha do dia
    com quem entrou nos 30 dias antes do vencimento. Devolve o que aconteceu ("" = nada a fazer)."""
    from . import marca
    from .banco import usar_config_da_ar

    with sessao() as db:
        usar_config_da_ar(db, marca.ar_padrao(db))  # a campanha automática é a da AR MS: o dono e o número dela
        if cfg(db, "renov_ativo") != "1":
            return ""
        hoje = date.today()
        if cfg(db, "renov_ativo_desde") and hoje.isoformat() < cfg(db, "renov_ativo_desde")[:10]:
            return ""  # piloto de 13/11/2026: o sistema assume sozinho a partir de 01/01/2027
        if cfg(db, "renov_ultima_rodada") == hoje.isoformat() or agora().strftime("%H:%M") < cfg(db, "renov_hora"):
            return ""
        gravar_config(db, "renov_ultima_rodada", hoje.isoformat())
        usuario = dono(db)
        if usuario is None:
            texto = f"{agora():%d/%m %H:%M} – escolha quem é o dono das campanhas de renovação."
        else:
            db.commit()
            camp = criar_campanha(db, usuario)
            texto = (f"{agora():%d/%m %H:%M} – " + (f"campanha do dia montada com {camp.quantidade} contatos (aguarda "
                                                     "aprovação)." if camp else "nenhum cliente novo para avisar hoje."))
        gravar_config(db, "renov_ultimo_resultado", texto)
        db.commit()
        return texto


# ---------------------------------------------------------------- Arte do aviso (a do site)

def arte_do_toque(db, tarefa: Tarefa | None) -> dict | None:
    """Os dados para o computador do WhatsApp Leads desenhar a arte do aviso neste toque (com "url", a página da arte
    da marca da campanha: url_da_arte), ou None (sai só o texto). Só para contato com UM certificado na campanha: a
    arte é de um certificado; com vários, a lista vai no texto. Pedido da Maria em 12/11/2026, com a arte também para
    quem nunca conversou (risco aceito)."""
    if tarefa is None or not tarefa.certificado_id or not tarefa.campanha_id or cfg(db, "renov_arte") != "1":
        return None
    url = url_da_arte(db, tarefa.tenant_id)
    if not url:  # marca sem a página da arte: só o texto
        return None
    camp = db.get(Campanha, tarefa.campanha_id)
    if camp is None or camp.tipo != TIPO_CAMPANHA:
        return None
    certs = certificados_do_aviso(db, tarefa)
    if len(certs) != 1:
        return None
    dados = _arte_do_certificado(certs[0])
    return {"tarefa": tarefa.id, **dados, "url": url} if dados else None


def aplicar_email_html(db, ligado: bool) -> int:
    """O botão "E-mail em HTML com a marca" vale também para as campanhas de renovação em andamento (os e-mails que
    ainda não saíram). Devolve quantas campanhas mudaram."""
    mudaram = 0
    for camp in db.execute(select(Campanha).where(Campanha.tipo == TIPO_CAMPANHA, Campanha.status.in_(
            ("ativa", "aguardando_aprovacao", "gerando")))).scalars():
        if (camp.email_html is not False) != ligado:
            camp.email_html = ligado
            mudaram += 1
    return mudaram


def envio_oficial_da_ar(db, ar: int | None) -> bool:
    """A marca `ar` manda os avisos pela API oficial? A chave dela (Renovação, quadro 4; por marca desde 22/11/2026) e a
    API oficial dela pronta: marca sem a conta pronta fica no QR code (senão os avisos ficariam parados)."""
    from . import whatsapp_oficial
    from .banco import usar_config_da_ar

    tinha, antes = "ar_config" in db.info, db.info.get("ar_config")
    usar_config_da_ar(db, ar)
    try:
        ligado = cfg(db, "renov_envio_oficial") == "1"
    finally:
        if tinha:
            db.info["ar_config"] = antes
        else:
            db.info.pop("ar_config", None)
    return ligado and not whatsapp_oficial.falta_para_renovacao(db, ar)


def aplicar_envio_oficial(db, ligado: bool) -> int:
    """Liga/desliga a API oficial também nas campanhas de renovação em andamento (os avisos que ainda não saíram passam
    a sair pelo número oficial, ou voltam para o QR code). Ao ligar, só as campanhas das marcas com a API oficial
    pronta (as outras continuam no QR code). Devolve quantas campanhas mudaram."""
    from . import whatsapp_oficial

    mudaram, prontas = 0, {}
    for camp in db.execute(select(Campanha).where(Campanha.tipo == TIPO_CAMPANHA, Campanha.status.in_(
            ("ativa", "aguardando_aprovacao", "gerando")))).scalars():
        if ligado:
            if camp.tenant_id not in prontas:
                prontas[camp.tenant_id] = not whatsapp_oficial.falta_para_renovacao(db, camp.tenant_id)
            if not prontas[camp.tenant_id]:
                continue  # a marca desta campanha não tem a API oficial pronta: continua no QR code
        if bool(camp.envio_oficial) != ligado:
            camp.envio_oficial = ligado
            mudaram += 1
    return mudaram


def certificados_do_aviso(db, tarefa: Tarefa) -> list[Certificado]:
    """Os certificados ativos do contato na campanha deste aviso, só os da onda dele (a do certificado guia), do que
    vence primeiro ao último. Usado na arte e no modelo da API oficial."""
    certs = db.execute(select(Certificado).where(Certificado.campanha_id == tarefa.campanha_id,
                                                 Certificado.lead_id == tarefa.lead_id,
                                                 Certificado.status == "Ativo")).scalars().all()
    guia = db.get(Certificado, tarefa.certificado_id) if tarefa.certificado_id else None
    if guia is not None:  # só os certificados da onda deste aviso
        limite = guia.data_vencimento + timedelta(days=janela(db))
        certs = [c for c in certs if guia.data_vencimento <= c.data_vencimento <= limite]
    return sorted(certs, key=lambda c: (c.data_vencimento, c.cliente_nome or "", c.id or 0))


def _dias_que_faltam(vencimento: date, hoje: date) -> str:
    dias = (vencimento - hoje).days
    if dias < 0:
        return "já venceu"
    return "vence hoje" if dias == 0 else "falta 1 dia" if dias == 1 else f"faltam {dias} dias"


def valores_do_modelo(db, tarefa: Tarefa | None, hoje: date | None = None) -> dict | None:
    """Os valores do modelo do aviso na API oficial da Meta, cada um numa linha só (a Meta não aceita quebra de linha
    nos valores): o nome do contato, o certificado (ou a lista) e o vencimento. None: o aviso não tem certificado
    ativo."""
    if tarefa is None or not tarefa.campanha_id or not tarefa.lead_id:
        return None
    certs = certificados_do_aviso(db, tarefa)
    if not certs:
        return None
    hoje = hoje or date.today()
    lead = tarefa.lead
    responsavel = next((c.responsavel for c in certs if c.responsavel), "") or (lead.responsavel if lead else "")
    nome = util.primeiro_nome(responsavel or "") or "tudo bem"
    if len(certs) == 1:
        c = certs[0]
        tipo = tipo_curto(c.tipo)
        if _do_proprio(c):
            descricao = f"seu {tipo}" if tipo else "seu certificado"
        else:
            descricao = f"{tipo + ' ' if tipo else ''}em nome de {_titular(c)}"
        vencimento = f"{c.data_vencimento:%d/%m/%Y} ({_dias_que_faltam(c.data_vencimento, hoje)})"
    elif len(certs) <= MAXIMO_NA_LISTA:
        partes = []
        for c in certs:
            tipo = tipo_curto(c.tipo)
            quem = "seu certificado" if _do_proprio(c) else _titular(c)
            partes.append(f"{quem}{f' ({tipo})' if tipo else ''}, vence em {c.data_vencimento:%d/%m}")
        descricao = f"{len(certs)} certificados: " + "; ".join(partes)
        vencimento = (f"a partir de {certs[0].data_vencimento:%d/%m/%Y} "
                      f"({_dias_que_faltam(certs[0].data_vencimento, hoje)})")
    else:
        descricao = f"{len(certs)} certificados digitais que você acompanha (o primeiro em nome de {_titular(certs[0])})"
        vencimento = f"entre {certs[0].data_vencimento:%d/%m} e {certs[-1].data_vencimento:%d/%m/%Y}"
    return {"nome": nome, "certificados": descricao[:600], "vencimento": vencimento}


def _arte_do_certificado(cert: Certificado) -> dict | None:
    """Os campos da arte do site para um certificado (None: tipo sem A1/A3, que a arte não tem)."""
    curto = tipo_curto(cert.tipo)
    midia = curto[-2:] if curto[-2:] in ("A1", "A3") else ""
    if not midia:
        return None
    return {"modelo": "cpf" if _e_pessoa(cert) else "cnpj", "tipo": midia, "nome": (cert.cliente_nome or "")[:200],
            "doc": cert.cnpj or "", "data": cert.data_vencimento.isoformat()}


def email_com_arte(db, tarefa: Tarefa | None, texto: str, link_descadastro: str = "") -> tuple[str, dict]:
    """O e-mail do aviso com a arte que foi no WhatsApp do mesmo aviso (o computador mandou uma cópia de volta):
    (html, {cid: png}). Sem a arte, ("", {}) e o e-mail sai só com o texto."""
    from types import SimpleNamespace

    from . import visual
    from .modelos import ArteAviso

    if tarefa is None or tarefa.canal != "email" or not tarefa.campanha_id or cfg(db, "renov_arte") != "1":
        return "", {}
    zaps = select(Tarefa.id).where(Tarefa.campanha_id == tarefa.campanha_id, Tarefa.lead_id == tarefa.lead_id,
                                   Tarefa.angulo == tarefa.angulo, Tarefa.canal == "whatsapp")
    arte = db.execute(select(ArteAviso).where(ArteAviso.tarefa_id.in_(zaps))
                      .order_by(ArteAviso.id.desc()).limit(1)).scalars().first()
    if arte is None:
        return "", {}
    html = visual.montar_html(SimpleNamespace(html=HTML_EMAIL_COM_ARTE), texto, {}, link_descadastro)
    return html, {"arte-aviso": arte.imagem}


def limpar_artes(db, hoje: date | None = None) -> int:
    """Apaga as cópias das artes com mais de DIAS_GUARDANDO_ARTE dias (já foram no WhatsApp e no e-mail)."""
    from sqlalchemy import delete

    from .banco import agora as _agora
    from .modelos import ArteAviso

    limite = _agora() - timedelta(days=DIAS_GUARDANDO_ARTE)
    return db.execute(delete(ArteAviso).where(ArteAviso.criado_em < limite)).rowcount or 0


def situacao_das_artes(db, dias: int = 7) -> dict:
    """Para a tela: dos avisos que saíram com a arte nos últimos dias, quantos o computador desenhou de fato (a cópia
    voltou). Nenhuma de volta = o computador não está conseguindo (ex.: sem o Google Chrome)."""
    from .modelos import ArteAviso, PonteWhatsApp

    desde = agora() - timedelta(days=dias)
    pedidas = db.scalar(select(func.count(PonteWhatsApp.id)).where(
        PonteWhatsApp.arte != "", PonteWhatsApp.criado_em >= desde, PonteWhatsApp.status.in_(("na_fila", "retirada")))) or 0
    feitas = db.scalar(select(func.count(ArteAviso.id)).where(ArteAviso.criado_em >= desde)) or 0
    return {"pedidas": pedidas, "feitas": feitas}


# ---------------------------------------------------------------- Número de WhatsApp (teste e disparos)
# Pedido da Maria em 12/11/2026, depois que o teste dela não chegou: saiu pelo número "principal", que estava em MODO
# TESTE (o WhatsApp Leads só simula o envio). Ela escolhe o número do teste e o dos disparos; no automático, a
# Renovação nunca escolhe um número em modo teste se houver um de verdade conectado.

def numeros_para_escolher(db, dono: Usuario | None = None) -> list[dict]:
    """Os números de WhatsApp cadastrados, com a situação: conectado e se está em modo teste (simulado). Com `dono`,
    só os dele ou compartilhados com ele (os disparos: regra da Maria em 13/11/2026; o teste pode usar qualquer um)."""
    from . import conexoes
    from .integracoes import whatsapp_leads

    base = whatsapp_leads.status()
    lista = []
    for c in conexoes.todas(db):
        if dono is not None and not conexoes.pode_disparar(dono, c):
            continue
        s = conexoes.situacao(c.id, base)
        numero = util.normalizar_telefone(str(s.get("numero") or ""))
        lista.append({"id": c.id, "nome": c.nome or c.id, "conectado": bool(s.get("conectado")),
                      "teste": s.get("tipo") == "teste", "numero": util.formatar_telefone(numero) if numero else ""})
    return lista


def numero_automatico(db, remetente: Usuario | None) -> str:
    """Sem número escolhido: o de quem assina, ou um compartilhado com ele e conectado, sempre preferindo um número DE
    VERDADE a um em modo teste (que só simula: a mensagem não chega). Lança conexoes.SemNumero."""
    from . import conexoes
    from .integracoes import whatsapp_leads

    if remetente is None:
        raise conexoes.SemNumero("Escolha quem assina as campanhas de renovação.")
    return conexoes.para_enviar(db, remetente)  # já prefere um número de verdade a um em modo teste


def numero_do_envio(db, remetente: Usuario | None, escolhido: str = "", teste: bool = False) -> str:
    """O número por onde sai: o escolhido (no teste), senão o da configuração da Renovação, senão o automático.
    Número escolhido e desconectado: avisa (lança conexoes.SemNumero), nunca troca sozinho. Fora do teste, só um número
    de quem assina ou compartilhado com ele (regra da Maria em 13/11/2026: nunca misturar os disparos)."""
    from . import conexoes
    from .integracoes import whatsapp_leads

    escolhido = escolhido or cfg(db, "renov_conexao")
    c = db.get(conexoes.ConexaoWhatsApp, escolhido) if escolhido else None
    if c is not None and not teste and remetente is not None and not conexoes.pode_disparar(remetente, c):
        c = None
    if c is None:
        return numero_automatico(db, remetente)
    base = whatsapp_leads.status()
    if not base.get("disponivel"):
        raise conexoes.SemNumero(base.get("erro") or "O computador com o WhatsApp Leads está desligado.")
    if not conexoes.situacao(c.id, base).get("conectado"):
        raise conexoes.SemNumero(f"O número {c.nome or c.id} está desconectado. Conecte em WhatsApp ou escolha outro.")
    return c.id


def numero_em_modo_teste(id_conexao: str) -> bool:
    from . import conexoes

    return conexoes.em_modo_teste(id_conexao)


# ---------------------------------------------------------------- Área de teste (como a da IA SDR)

EXEMPLO_TESTE = {"cliente_nome": "EMPRESA EXEMPLO LTDA", "cnpj": "11.222.333/0001-81", "tipo": "e-CNPJ A1 12 meses"}
def avisos_teste(db) -> dict:
    nomes = nomes_dos_avisos(dias_aviso(db))
    return {"renov_aviso": "Só o 1º aviso", **{a: f"Só: {n}" for a, n in list(nomes.items())[1:]},
            "todos": "Os 4 avisos"}


def exemplos_para_teste(db, limite: int = 40) -> list[tuple[Certificado, int]]:
    """Clientes da planilha para escolher no teste (os que vencem primeiro) e quantos certificados o contato teria
    na mesma campanha (com mais de um, vai a lista no texto e não vai a arte)."""
    hoje = date.today()
    certs = db.execute(select(Certificado).where(
        Certificado.origem == ORIGEM, Certificado.status == "Ativo", Certificado.data_vencimento > hoje)
        .order_by(Certificado.data_vencimento, Certificado.id).limit(600)).scalars().all()
    no_mes = Counter(chave_do_contato(c) for c in certs if c.data_vencimento <= hoje + timedelta(days=janela(db)))
    return [(c, no_mes.get(chave_do_contato(c), 1) if chave_do_contato(c) else 1) for c in certs[:limite]]


def contato_do_teste(db, cert_id: int, remetente: Usuario | None) -> Contato:
    """O contato do teste: o cliente escolhido (com os outros certificados do mesmo contato que entrariam na mesma
    campanha) ou um cliente fictício (cert_id 0) que vence daqui a 30 dias, com o nome de quem assina."""
    hoje = date.today()
    if not cert_id:
        exemplo = Certificado(origem=ORIGEM, protocolo="", status="Ativo", data_vencimento=hoje + timedelta(days=janela(db)),
                              responsavel=(remetente.nome if remetente else ""), **EXEMPLO_TESTE)
        return Contato("teste:exemplo", [exemplo])
    cert = db.get(Certificado, cert_id)
    if cert is None or cert.origem != ORIGEM:
        raise ValueError("Esse cliente não está na planilha de renovação.")
    chave = chave_do_contato(cert)
    certs = [cert]
    if chave:
        limite = max(hoje + timedelta(days=janela(db)), cert.data_vencimento)
        certs = [c for c in db.execute(select(Certificado).where(
            Certificado.origem == ORIGEM, Certificado.status == "Ativo", Certificado.data_vencimento > hoje,
            Certificado.data_vencimento <= limite)).scalars() if chave_do_contato(c) == chave]
        if cert not in certs:
            certs.append(cert)
    return Contato(chave or f"teste:{cert.id}", sorted(certs, key=lambda c: (c.data_vencimento, c.id)))


def arte_do_teste_no_email(db, cert_id: int, dados_arte: dict) -> bytes | None:
    """A arte que o computador desenhou no teste de WhatsApp deste cliente na última hora (a cópia volta pela ponte):
    vai no teste de e-mail. A arte é desenhada só no computador do WhatsApp Leads."""
    from .modelos import ArteAviso, PonteWhatsApp

    itens = db.execute(select(PonteWhatsApp).where(
        PonteWhatsApp.manual.is_(True), PonteWhatsApp.arte != "", PonteWhatsApp.criado_em >= agora() - timedelta(hours=1))
        .order_by(PonteWhatsApp.id.desc()).limit(50)).scalars().all()
    for item in itens:
        try:
            dados = json.loads(item.arte)
        except ValueError:
            continue
        if dados.get("teste") == cert_id and all(dados.get(k) == dados_arte.get(k) for k in ("nome", "data", "tipo")):
            arte = db.execute(select(ArteAviso).where(ArteAviso.ponte_id == item.id)).scalars().first()
            if arte is not None:
                return arte.imagem
    return None


def enviar_teste(db, usuario: Usuario, cert_id: int, canal: str, destino: str, avisos: str = "renov_aviso",
                 com_arte: bool = True, conexao: str = "", ar: int | None = None) -> dict:
    """Ambiente de teste (como o da IA SDR): manda os avisos para o WhatsApp ou o e-mail DE QUEM ESTÁ TESTANDO, com
    "[TESTE]" no começo, do jeito que o cliente receberia (o texto e, se marcado, a arte do site). Sai pelo número e
    pelo e-mail de quem assina as campanhas de renovação; o WhatsApp, pelo número escolhido no teste (`conexao`), senão
    pelo dos disparos da Renovação, senão o automático. Nenhum cliente recebe nada e nenhuma campanha muda."""
    from types import SimpleNamespace

    from . import config, conexoes, contas_email, visual
    from .integracoes import email_smtp, whatsapp_leads

    remetente = dono(db) or usuario
    contato = contato_do_teste(db, cert_id, remetente)
    textos = textos_do_contato(db, contato, remetente, ar=ar)  # a marca da AR da tela (o Admin Master não tem a sua)
    angulos = list(ANGULOS) if avisos == "todos" else [avisos if avisos in ANGULOS else "renov_aviso"]
    cert = contato.certificados[0]
    # a arte é de UM certificado: com vários no mesmo contato, o cliente recebe a lista no texto (o teste mostra igual)
    # a arte da marca do cliente (o fictício: a da tela, `ar`); marca sem a página da arte: só o texto
    url = url_da_arte(db, getattr(cert, "tenant_id", None) or ar)
    com_arte = com_arte and bool(url)
    dados_arte = _arte_do_certificado(cert) if com_arte and len(contato.certificados) == 1 else None
    if dados_arte:
        dados_arte["url"] = url
    feito = {"enviadas": 0, "erros": [], "arte": False, "remetente": remetente.nome,
             "certificados": len(contato.certificados), "arte_pedida": com_arte, "numero": "", "modo_teste": False}
    numero, conta, imagem_email = "", None, None
    try:
        if canal == "whatsapp":
            numero = numero_do_envio(db, remetente, conexao, teste=True)
            c = db.get(conexoes.ConexaoWhatsApp, numero)
            feito["numero"], feito["modo_teste"] = (c.nome if c else numero), numero_em_modo_teste(numero)
        else:
            conta = contas_email.para_enviar(db, remetente)
    except (conexoes.SemNumero, contas_email.SemConta) as erro:
        feito["erros"].append(f"{'WhatsApp' if canal == 'whatsapp' else 'E-mail'}: {erro}")
        return feito
    if canal == "email" and dados_arte:
        imagem_email = arte_do_teste_no_email(db, cert_id, dados_arte)
    nomes = nomes_dos_avisos(dias_aviso(db))
    for angulo in angulos:
        t = textos[angulo]
        rotulo = f"[TESTE · {cert.cliente_nome[:60]} · {nomes[angulo]}]"
        try:
            if canal == "whatsapp":
                arte = {"teste": cert_id, **dados_arte} if dados_arte and config.WHATSAPP_PONTE else None
                whatsapp_leads.enviar(destino, "Teste", f"{rotulo}\n\n{t['whatsapp']}", db=db, manual=True,
                                      usuario_id=usuario.id, conexao=numero, arte=arte)
                feito["arte"] = feito["arte"] or bool(arte)
            else:
                html, imagens = "", {}
                if imagem_email:
                    html = visual.montar_html(SimpleNamespace(html=HTML_EMAIL_COM_ARTE), f"{rotulo}\n\n{t['email']}", {})
                    imagens = {"arte-aviso": imagem_email}
                    feito["arte"] = True
                elif visual.html_da_marca_ligado(db) and cfg(db, "renov_email_html") != "0":  # sem a arte: com a marca
                    html = visual.html_da_marca(db, getattr(cert, "tenant_id", None), f"{rotulo}\n\n{t['email']}")
                email_smtp.enviar(destino, f"[TESTE] {t['assunto']}", f"{rotulo}\n\n{t['email']}", lead_id=None,
                                  conta=conta, html=html, **({"imagens": imagens} if imagens else {}))
            feito["enviadas"] += 1
        except (email_smtp.ErroEmail, whatsapp_leads.ErroWhatsAppLeads) as erro:
            feito["erros"].append(f"{'E-mail' if canal == 'email' else 'WhatsApp'}: {erro}")
            break
    return feito


def campanhas_recentes(db, limite: int = 30) -> list[Campanha]:
    return db.execute(select(Campanha).where(Campanha.tipo == TIPO_CAMPANHA)
                      .order_by(Campanha.criado_em.desc()).limit(limite)).scalars().all()


def e_lead_de_renovacao(lead: Lead) -> bool:
    return (lead.origem or "") == ORIGEM_LEAD


def situacao_na_tela(cert: Certificado, hoje: date | None = None, dias_da_janela: int = JANELA_DIAS,
                     pontos: frozenset = frozenset()) -> tuple[str, str]:
    """(classe do selo, texto) para a lista da tela Renovação. `pontos`: os pontos de atendimento fora dos avisos."""
    hoje = hoje or date.today()
    if cert.status in ("Renovado", "Não renovará", "Avisos cancelados"):
        return ("selo-ok" if cert.status == "Renovado" else "", SITUACOES[cert.status])
    if cert.status == "Vencido" or cert.data_vencimento < hoje:
        return ("", "Venceu")
    if cert.campanha_id:
        return ("selo-azul", "Em campanha")
    if cert.fora_motivo:
        return ("selo-alerta", "Fora: " + cert.fora_motivo)
    if no_ponto_fora(cert, pontos):
        return ("", f"Ponto fora dos avisos ({cert.ponto or cert.unidade})")
    if not chave_do_contato(cert):
        return ("selo-erro", "Sem WhatsApp e sem e-mail")
    if cert.data_vencimento <= hoje:
        return ("", "Vence hoje")
    if cert.data_vencimento <= hoje + timedelta(days=dias_da_janela):
        return ("selo-alerta", "Pronto para avisar")
    return ("", f"Aviso a partir de {cert.data_vencimento - timedelta(days=dias_da_janela):%d/%m}")
