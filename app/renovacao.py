"""Renovação: avisos de vencimento do certificado digital para os clientes da MS (pedido da Maria em 12/11/2026).

1. A equipe exporta o "Relatório de renovação" do sistema da certificadora (Excel) e importa na tela Renovação. Cada
   linha vira um certificado (tabela certificados, origem "planilha", chave = protocolo): vencimento, tipo, razão
   social/CNPJ ou titular/CPF, responsável, WhatsApp, e-mail e parceiro. A data de nascimento que vem na planilha
   nunca é lida (não precisa). Importar de novo atualiza, sem duplicar.
2. A campanha de renovação ("Montar campanha agora" ou a campanha automática do dia) junta os certificados que vencem
   nos próximos 30 dias POR CONTATO: o mesmo WhatsApp (ou e-mail) recebe UMA mensagem em cada aviso, com a lista dos
   certificados dele. Na planilha de 12/11/2026 um número aparece em 57 certificados (grupo de empresas): mandar um
   aviso por certificado seria spam e risco de bloqueio do número. Cada contato vira um lead ("Renovação (planilha)").
3. Quatro avisos contados do vencimento: 30, 15, 5 e 1 dia antes (pedido da Maria). Quem entra tarde recebe o 1º
   aviso na hora e só os seguintes que ainda cabem, nunca dois em dias seguidos. Fim de semana: o aviso vem para a
   sexta antes (nunca para depois do vencimento).
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
from .banco import agora, gravar_config, ler_config, sessao
from .modelos import Campanha, Certificado, Lead, Tarefa, Usuario

ORIGEM = "planilha"                   # Certificado.origem dos que vieram do Relatório de renovação
ORIGEM_LEAD = "Renovação (planilha)"  # Lead.origem dos contatos criados aqui
TIPO_CAMPANHA = "renovacao"
DIAS_AVISO = (30, 15, 5, 1)           # dias antes do vencimento (pedido da Maria em 12/11/2026)
JANELA_DIAS = DIAS_AVISO[0]           # entra na campanha quem vence nos próximos 30 dias
INTERVALO_MINIMO_DIAS = 2             # entre dois avisos para o mesmo contato (nunca em dias seguidos)
QUANTIDADES = (10, 20, 30, 40, 50, 100)  # "Montar campanha agora": quantos contatos
MAXIMO_NA_LISTA = 5                   # a mensagem lista até 5 certificados; com mais, vai um resumo
ENCERRADOS = ("Renovado", "Não renovará", "Vencido")
SITUACOES = {"Renovado": "Renovado", "Não renovará": "Não vai renovar", "Ativo": "Reabrir"}

ANGULOS = {
    "renov_aviso": "1º aviso (30 dias antes)",
    "renov_lembrete": "Lembrete (15 dias antes)",
    "renov_reforco": "Faltam poucos dias (5 dias antes)",
    "renov_ultimo": "Último aviso (1 dia antes)",
}
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
    "renov_arte": "1",                # a arte do aviso (a do site) vai junto no WhatsApp e no e-mail
    "renov_conexao": "",              # número de WhatsApp dos disparos ("" = automático, sempre um número de verdade)
    "renov_dias": "30,15,5,1",        # dias antes do vencimento dos 4 avisos (piloto de 13/11/2026: 12, 6, 3 e 1)
    "renov_hora_inicio": "",          # os avisos saem a partir deste horário ("" = o horário de envio geral)
    "renov_hora_fim": "18:00",        # e até este (pedido da Maria em 13/11/2026: segunda a sexta, das 10:00 às 18:00)
    "renov_ativo_desde": "",          # a campanha automática só começa nesta data (AAAA-MM-DD; "" = já)
}
URL_DA_ARTE = "https://mscertificados.com.br/interno/aviso-vencimento"  # quem desenha: whatsapp-leads/app/arte_aviso.py
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


# O WhatsApp ainda passa pela fila do computador do WhatsApp Leads (a ponte busca a cada minuto): para de sair 10
# minutos antes do fim, para chegar ao cliente dentro do horário.
MARGEM_WHATSAPP_MINUTOS = 10


def fora_do_horario(db, momento: datetime | None = None, margem_minutos: int = 0) -> str:
    """A Renovação só dispara nos dias comerciais, de segunda a sexta, no horário da tela (pedido da Maria em
    13/11/2026: "segunda a sexta das 10:00 - 18:00"). Devolve o motivo ("" = pode enviar agora). As filas seguram os
    avisos fora do horário: eles saem no próximo horário permitido (ou param, se o certificado vencer antes)."""
    from .cadencias import _minutos

    momento = momento or agora()
    inicio = hora_inicio(db) or ler_config(db, "horario_envio_inicio") or "08:30"
    fim = hora_fim(db) or ler_config(db, "horario_envio_fim") or "18:00"
    motivo = f"A Renovação só envia de segunda a sexta, das {inicio} às {fim}"
    minuto = momento.hour * 60 + momento.minute
    if momento.weekday() >= 5 or minuto < _minutos(inicio, 0) or minuto >= _minutos(fim, 24 * 60) - margem_minutos:
        return motivo
    return ""


def garantir_cadencia(db):
    from .modelos import Cadencia, PassoCadencia

    cad = db.execute(select(Cadencia).where(Cadencia.nome == CADENCIA_NOME)).scalars().first()
    if cad is None:
        cad = Cadencia(nome=CADENCIA_NOME,
                       descricao="Avisos de vencimento do certificado digital para os clientes da MS (tela Renovação).")
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
    return resumo


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


def a_avisar(db, hoje: date | None = None, ate: date | None = None) -> list[Certificado]:
    """Certificados que podem entrar numa campanha: da planilha, ativos, fora de campanha e vencendo até o dia do 1º
    aviso (ex.: 30 ou 12 dias) ou até `ate` (campanha do piloto: até 31/12), de amanhã em diante (o que vence hoje já
    não dá tempo de avisar)."""
    hoje = hoje or date.today()
    ate = ate or hoje + timedelta(days=janela(db))
    return db.execute(select(Certificado).where(
        Certificado.origem == ORIGEM, Certificado.status == "Ativo", Certificado.campanha_id.is_(None),
        func.coalesce(Certificado.fora_motivo, "") == "", Certificado.data_vencimento > hoje,
        Certificado.data_vencimento <= ate)).scalars().all()


def _formas_do_celular(numero: str) -> set[str]:
    formas = {numero}
    if len(numero) == 11 and numero[2] == "9":
        formas.add(numero[:2] + numero[3:])  # o mesmo celular guardado sem o 9
    return formas


def lead_do_contato(db, chave: str) -> Lead | None:
    """Lead que já existe para o contato. WhatsApp: qualquer lead com o número (dois leads no mesmo número embaralham
    as respostas). Só e-mail: só um lead de renovação (o contato vem só da planilha)."""
    tipo, valor = chave.split(":", 1)
    if tipo == "whatsapp":
        formas = _formas_do_celular(valor)
        consulta = select(Lead).where(or_(Lead.chave_whatsapp.in_(formas), Lead.chave_telefone.in_(formas)))
    else:
        consulta = select(Lead).where(Lead.chave_email == valor, Lead.origem == ORIGEM_LEAD)
    leads = db.execute(consulta.order_by(Lead.id)).scalars().all()
    return next((l for l in leads if l.origem == ORIGEM_LEAD), leads[0] if leads else None)


def _leads_dos_contatos(db, contatos: list[Contato]) -> dict[str, Lead]:
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
    if formas:
        for lead in db.execute(select(Lead).where(or_(Lead.chave_whatsapp.in_(formas), Lead.chave_telefone.in_(formas)))
                               .order_by(Lead.id)).scalars():
            chave = formas.get(lead.chave_whatsapp) or formas.get(lead.chave_telefone)
            if chave:
                achados.setdefault(chave, []).append(lead)
    if emails:
        for lead in db.execute(select(Lead).where(Lead.chave_email.in_(emails), Lead.origem == ORIGEM_LEAD)
                               .order_by(Lead.id)).scalars():
            achados.setdefault(emails[lead.chave_email], []).append(lead)
    return {k: next((l for l in v if l.origem == ORIGEM_LEAD), v[0]) for k, v in achados.items()}


def motivo_de_fora(db, lead: Lead) -> str:
    """Por que o contato não entra numa campanha agora (as mesmas regras de cadencias.aplicar). "" = pode."""
    from .sdr import com_humano

    if lead.opt_out or lead.anonimizado:
        return "pediu para não receber mensagens (SAIR)"
    if lead.automacao_pausada or com_humano(lead):
        return "uma pessoa da equipe está atendendo"
    if lead.perdido or lead.etapa >= 2:
        return f"já respondeu ({lead.status}): a equipe cuida"
    if db.execute(select(Tarefa.id).where(Tarefa.lead_id == lead.id, Tarefa.tipo == "prospeccao",
                                          Tarefa.status.in_(["pendente", "rascunho"])).limit(1)).first():
        return "já está recebendo outra sequência de mensagens"
    return ""


def contatos_para_campanha(db, hoje: date | None = None, marcar_saida: bool = False,
                           ate: date | None = None) -> tuple[list[Contato], dict]:
    """Contatos que podem entrar numa campanha agora (do que vence primeiro ao último) e quantos certificados ficam de
    fora por motivo. marcar_saida=True grava nos certificados de quem pediu SAIR (vale até alguém reabrir)."""
    contatos, sem_contato = agrupar(a_avisar(db, hoje, ate))
    fora: dict[str, int] = {}
    if sem_contato:
        fora["sem WhatsApp e sem e-mail na planilha"] = len(sem_contato)
    leads = _leads_dos_contatos(db, contatos)
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

def _dia_util_antes(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _limites_para_a_sexta(vencimento: date, dias_antes: tuple[int, ...], pular_fds: bool) -> list[date | None]:
    """Vence no sábado ou no domingo: o último aviso sai na sexta antes (pedido da Maria em 13/11/2026: "os de sábados e
    domingos avisar na sexta"). Para a sexta caber, cada aviso anterior fica pelo menos INTERVALO_MINIMO_DIAS antes do
    seguinte (ex.: vence no domingo, avisos 12, 6, 3 e 1 dia antes: o de 3 dias vai para a quarta, e não para a quinta,
    onde tirava o lugar do último aviso). Devolve o dia máximo de cada aviso (None = sem limite)."""
    total = len(dias_antes)
    if not pular_fds or vencimento.weekday() < 5 or not total:
        return [None] * total
    sexta = _dia_util_antes(vencimento)
    if _dia_util_antes(vencimento - timedelta(days=dias_antes[-1])) != sexta:
        return [None] * total  # o último aviso não cai na sexta (ex.: 3 dias antes): nada muda
    return [_dia_util_antes(sexta - timedelta(days=INTERVALO_MINIMO_DIAS * (total - 1 - i))) if i < total - 1 else None
            for i in range(total)]


def datas_dos_avisos(vencimento: date, hoje: date | None = None, pular_fds: bool = True,
                     dias_antes: tuple[int, ...] = DIAS_AVISO) -> list[date | None]:
    """Datas dos 4 avisos (30, 15, 5 e 1 dia antes do vencimento). None = aviso que não cabe (já passou, ou ficaria a
    menos de 2 dias do anterior). Quem entra tarde recebe o 1º aviso hoje (ou no próximo dia útil). Aviso no fim de
    semana vem para a sexta antes, nunca para depois do vencimento; quem vence no sábado ou no domingo recebe o último
    aviso na sexta (_limites_para_a_sexta). Tudo None = não dá mais tempo de avisar."""
    hoje = hoje or date.today()
    datas: list[date | None] = []
    anterior = None
    limites = _limites_para_a_sexta(vencimento, dias_antes, pular_fds)
    for indice, dias in enumerate(dias_antes):
        alvo = vencimento - timedelta(days=dias)
        if pular_fds:
            alvo = _dia_util_antes(alvo)
        if limites[indice] is not None:
            alvo = min(alvo, limites[indice])  # vence no fim de semana: a sexta fica para o último aviso
        if indice == 0:
            alvo = max(alvo, hoje)
            if pular_fds:
                alvo = util.proximo_dia_util(alvo)
            if alvo > vencimento:
                return [None] * len(dias_antes)
        elif alvo < hoje or alvo > vencimento or (alvo - anterior).days < INTERVALO_MINIMO_DIAS:
            datas.append(None)
            continue
        datas.append(alvo)
        anterior = alvo
    return datas


def _util_seguinte(d: date, pular_fds: bool) -> date:
    d += timedelta(days=1)
    return util.proximo_dia_util(d) if pular_fds else d


def _util_anterior(d: date, pular_fds: bool) -> date:
    d -= timedelta(days=1)
    return _dia_util_antes(d) if pular_fds else d


def primeiro_dia(db) -> date:
    """O primeiro dia em que ainda dá para enviar: hoje (se o horário de envio de hoje não acabou) ou o próximo dia de
    envio. Montada à noite, a campanha não marca nada para "hoje" (iria tudo para amanhã, acima do teto)."""
    from . import cadencias

    return cadencias.dia_e_hora_futuros(db, date.today(), True, hora_inicio(db), hora_fim(db))[0]


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
           teto: int = 0, dias_antes: tuple[int, ...] = DIAS_AVISO) -> list[list[date | None]]:
    """As datas dos avisos de vários contatos com WhatsApp (do que vence primeiro ao último) sem passar de `teto`
    WhatsApps por dia: com 100 clientes vencendo no mês, os 100 primeiros avisos cairiam no mesmo dia e o número só
    faz 20 contatos frios por dia (o resto atrasaria e ficaria esperando clique). Primeiro, o 1º aviso de todos, no
    primeiro dia com vaga (quem vence antes escolhe antes): ninguém fica sem aviso por causa dos lembretes dos outros.
    Depois, os lembretes nas vagas que sobraram, no dia certo ou alguns dias antes (sem vaga, aquele lembrete não vai).
    teto 0 = sem teto (só as regras de datas_dos_avisos)."""
    if not teto:
        return [datas_dos_avisos(v, hoje, pular_fds, dias_antes) for v in vencimentos]
    carga = carga if carga is not None else Counter()
    resultado: list[list[date | None]] = []
    for vencimento in vencimentos:
        datas: list[date | None] = [None] * len(dias_antes)
        primeiro = datas_dos_avisos(vencimento, hoje, pular_fds, dias_antes)[0]
        if primeiro is not None:
            dia = primeiro
            while carga[dia] >= teto and _util_seguinte(dia, pular_fds) <= vencimento:
                dia = _util_seguinte(dia, pular_fds)
            if carga[dia] >= teto:  # nenhum dia com vaga até o vencimento: o menos cheio (a fila segura o excesso)
                dias, d = [], primeiro
                while d <= vencimento:
                    dias.append(d)
                    d = _util_seguinte(d, pular_fds)
                dia = min(dias, key=lambda x: (carga[x], x))
            carga[dia] += 1
            datas[0] = dia
        resultado.append(datas)
    for datas, vencimento in zip(resultado, vencimentos):
        anterior = datas[0]
        if anterior is None:
            continue
        limites = _limites_para_a_sexta(vencimento, dias_antes, pular_fds)
        for i, dias in enumerate(dias_antes[1:], start=1):
            dia = vencimento - timedelta(days=dias)
            dia = _dia_util_antes(dia) if pular_fds else dia
            if limites[i] is not None:
                dia = min(dia, limites[i])  # vence no fim de semana: a sexta fica para o último aviso
            while dia >= hoje and (dia - anterior).days >= INTERVALO_MINIMO_DIAS:
                if dia <= vencimento and carga[dia] < teto:
                    carga[dia] += 1
                    datas[i] = anterior = dia
                    break
                dia = _util_anterior(dia, pular_fds)
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


def textos_do_contato(db, contato: Contato, usuario: Usuario | None) -> dict:
    """Mensagens dos 4 avisos para o contato (WhatsApp, e-mail com a assinatura e assunto)."""
    from . import marca

    vendedor = util.primeiro_nome(usuario.nome) if usuario and usuario.perfil != "parceiro" else "a equipe"
    m = marca.da_pessoa(usuario)
    assinatura = marca.assinatura(usuario, vendedor)
    valores = {"responsavel": util.primeiro_nome(contato.responsavel), "vencimentos": bloco_vencimentos(contato.certificados),
               "data": f"{contato.vencimento:%d/%m/%Y}", "vendedor": vendedor, "minha_empresa": m["nome"]}

    def trocar(modelo: str) -> str:
        texto = marca.aplicar(modelo or "", usuario)  # só no modelo: o nome do cliente nunca é trocado
        if not valores["responsavel"]:
            texto = re.sub(r",?[ \t]*\{responsavel\}", "", texto)  # "Olá, {responsavel}!" vira "Olá!"
        return re.sub(r"\{(" + "|".join(CAMPOS_DA_MENSAGEM) + r")\}", lambda x: valores[x.group(1)], texto)

    return {a: {"whatsapp": trocar(t["whatsapp"]), "email": trocar(t["email"]) + assinatura,
                "assunto": trocar(t["assunto"])[:200], "fonte": "renovacao"}
            for a, t in mensagens(db).items()}


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


def criar_campanha(db, usuario: Usuario, quantidade: int | None = None, ate: date | None = None,
                   nome: str = "") -> Campanha | None:
    """Campanha de renovação com os contatos que vencem primeiro (no máximo `quantidade`; sem ela, o máximo por dia
    da configuração). `ate`: todos os que vencem até essa data, com os avisos marcados desde já (campanha do piloto de
    13/11/2026, até 31/12); o contato com certificados vencendo em datas distantes recebe uma "onda" de avisos para
    cada uma. Fica "gerando": o trabalho em etapas cadastra os contatos e monta os avisos, e ela vai para a aprovação.
    None = ninguém para avisar agora."""
    from . import trabalhos

    hoje = date.today()
    contatos, _ = contatos_para_campanha(db, hoje, marcar_saida=True, ate=ate)
    limite = quantidade or (None if ate else util.para_int(cfg(db, "renov_maximo_dia")) or 40)
    escolhidos = contatos[:limite] if limite else contatos
    if not escolhidos:
        db.commit()  # guarda quem pediu SAIR (fora_motivo)
        return None
    dias_da_janela = janela(db)
    grupos = [(onda, n) for c in escolhidos for n, onda in enumerate(ondas(c, dias_da_janela))]
    ultimo = max(c.data_vencimento for g, _ in grupos for c in g.certificados)
    datas = datas_da_campanha(db, [g for g, _ in grupos])
    from . import conexoes

    try:  # o número dos disparos fica gravado na campanha (dá para trocar na página dela): nunca um de modo teste
        numero = numero_do_envio(db, usuario)
    except conexoes.SemNumero:  # computador desligado agora: vale o escolhido na tela (ou o automático no envio)
        numero = cfg(db, "renov_conexao")
    camp = Campanha(nome=(nome or f"Renovação {hoje:%d/%m} – vencem até {ultimo:%d/%m}")[:160], tipo=TIPO_CAMPANHA,
                    objetivo="Renovar o certificado digital dos clientes", quantidade=len(escolhidos),
                    canais=cfg(db, "renov_canais"), status="gerando", usuario_id=usuario.id, inicio=hoje,
                    cadencia_id=garantir_cadencia(db).id, conexao_id=numero or "",
                    pedido=f"Clientes com certificado vencendo até {ultimo:%d/%m/%Y} (planilha de renovação)")
    db.add(camp)
    db.commit()
    trabalhos.iniciar("campanha", camp.id, usuario.id, {"fase": "renovacao", "grupos": [
        {"ids": [c.id for c in g.certificados], "datas": [d.isoformat() if d else None for d in ds], "onda": n}
        for (g, n), ds in zip(grupos, datas)]})
    return camp


def datas_da_campanha(db, contatos: list[Contato], ignorar_campanha: int | None = None) -> list[list[date | None]]:
    """As datas dos avisos de cada contato (na mesma ordem), com o teto de WhatsApps por dia contando os avisos de
    renovação já marcados nas outras campanhas. Quem só tem e-mail não ocupa vaga do WhatsApp."""
    pular_fds = True  # Renovação: só de segunda a sexta (pedido da Maria em 13/11/2026)
    inicio = primeiro_dia(db)
    canais = cfg(db, "renov_canais")
    dias = dias_aviso(db)
    com_zap = ["whatsapp" in canais and bool(c.whatsapp) for c in contatos]
    carga = carga_marcada(db, inicio, ignorar_campanha)
    agendadas = iter(agenda([c.vencimento for c, z in zip(contatos, com_zap) if z], inicio, pular_fds, carga,
                            teto_por_dia(db), dias))
    return [next(agendadas) if z else datas_dos_avisos(c.vencimento, inicio, pular_fds, dias)
            for c, z in zip(contatos, com_zap)]


def _nome_do_contato(contato: Contato) -> str:
    nomes = list(dict.fromkeys(c.cliente_nome for c in contato.certificados if c.cliente_nome))
    if len(nomes) == 1:
        return nomes[0][:200]
    base = _nome_proprio(contato.responsavel) if contato.responsavel else nomes[0]
    return f"{base} ({len(contato.certificados)} certificados)"[:200]


def _lead_para_o_contato(db, contato: Contato, usuario: Usuario) -> tuple[Lead | None, str]:
    """Lead do contato: o que já existe (completando o que faltar com a planilha) ou um novo. (None, motivo) = fica de
    fora agora."""
    from .leads_servico import criar_lead, historico, limpar_campos

    lead = lead_do_contato(db, contato.chave)
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
             "observacoes": "Cliente da MS: aviso de renovação do certificado digital (planilha de renovação)."}
    lead, _ = criar_lead(db, dados, usuario, origem=ORIGEM_LEAD, checar_duplicado=False)
    if lead is not None:
        lead.base_legal = "Legítimo interesse: cliente da MS (renovação do certificado)"
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
                         else datas_dos_avisos(contato.vencimento, primeiro_dia(db), pular_fds, dias_aviso(db)))
                if not any(datas):
                    continue
                if onda:  # 2ª onda do mesmo contato: o lead é o da 1ª (se ela entrou), com avisos próprios
                    lead = lead_do_contato(db, contato.chave)
                    if lead is None or lead.id not in estado["escolhidos"]:
                        continue
                    for c in certs:
                        c.campanha_id, c.lead_id = campanha_id, lead.id
                    estado.setdefault("ondas", {}).setdefault(str(lead.id), []).append(
                        {"textos": textos_do_contato(db, contato, usuario), "cert": certs[0].id,
                         "datas": [d.isoformat() if d else None for d in datas]})
                    continue
                lead, motivo = _lead_para_o_contato(db, contato, usuario)
                if lead is None or lead.id in estado["escolhidos"]:
                    if motivo:
                        estado["fora"][motivo] = estado["fora"].get(motivo, 0) + len(certs)
                    continue
                for c in certs:
                    c.campanha_id, c.lead_id = campanha_id, lead.id
                estado["escolhidos"].append(lead.id)
                estado["textos"][str(lead.id)] = textos_do_contato(db, contato, usuario)
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
                              hora_maxima=hora_fim(db))
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
    inicio = primeiro_dia(db)
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
                            carga_marcada(db, inicio, ignorar_campanha=camp.id), teto_por_dia(db), dias))
    continuam = []
    for tarefas, zap_no_grupo in zip(grupos, com_zap):
        vencimento = vencimento_de(tarefas)
        if zap_no_grupo:
            datas = next(agendadas)
        else:
            datas = datas_dos_avisos(vencimento, inicio, pular_fds, dias) if vencimento else [None] * len(dias)
        zaps = {}
        for t in sorted(tarefas, key=lambda t: t.canal != "whatsapp"):  # o WhatsApp primeiro: o e-mail vem depois dele
            i = ordem.get(t.angulo)
            nova = datas[i] if i is not None and i < len(datas) else None
            if nova is None:
                t.status, t.concluida_em = "cancelada", agora()
                t.resultado = "Não cabe mais antes do vencimento (campanha aprovada depois)"
                continue
            if t.canal == "whatsapp":
                zaps[t.angulo] = t
            if t.data != nova:
                zap = zaps.get(t.angulo) if t.canal == "email" else None
                if zap is not None:
                    t.data, t.hora = cadencias.depois_de(db, zap.data, zap.hora or "09:00", pular_fds=pular_fds,
                                                         minimo=minimo, maximo=maximo)
                else:
                    t.data = nova
            continuam.append(t)
    return continuam


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
                       else f"Certificado marcado como {SITUACOES.get(cert.status, cert.status).lower()}"
                       if cert is not None else "Certificado não existe mais")
    return len(tarefas)


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


def mudar_situacao(db, cert: Certificado, situacao: str, usuario: Usuario | None) -> int:
    """Renovado / Não renovará: os avisos que ainda não saíram param (se o contato tiver outro certificado na mesma
    campanha, os avisos continuam por ele). Ativo (Reabrir): volta para a fila se a campanha dele já acabou.
    Devolve quantos avisos foram cancelados."""
    cert.status = situacao
    cancelados = 0
    tarefas = []
    if cert.campanha_id and cert.lead_id:
        tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cert.campanha_id, Tarefa.lead_id == cert.lead_id,
                                                  Tarefa.status.in_(("pendente", "rascunho")))).scalars().all()
    if situacao in ("Renovado", "Não renovará") and tarefas:
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
            t.resultado = (f"Certificado marcado como {SITUACOES[situacao].lower()}"
                           + (f" por {usuario.nome}" if usuario else ""))
            cancelados += 1
    if situacao == "Ativo":
        cert.fora_motivo = ""
        if not tarefas:
            cert.campanha_id = None  # a campanha dele acabou: pode entrar numa nova
    return cancelados


def rodada_diaria() -> str:
    """Chamado pelo relógio (a cada 15 min): uma vez por dia, depois do horário configurado, monta a campanha do dia
    com quem entrou nos 30 dias antes do vencimento. Devolve o que aconteceu ("" = nada a fazer)."""
    with sessao() as db:
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
    """Os dados para o computador do WhatsApp Leads desenhar a arte do aviso (a do site, URL_DA_ARTE) neste toque, ou
    None (sai só o texto). Só para contato com UM certificado na campanha: a arte é de um certificado; com vários, a
    lista vai no texto. Pedido da Maria em 12/11/2026, com a arte também para quem nunca conversou (risco aceito)."""
    if tarefa is None or not tarefa.certificado_id or not tarefa.campanha_id or cfg(db, "renov_arte") != "1":
        return None
    camp = db.get(Campanha, tarefa.campanha_id)
    if camp is None or camp.tipo != TIPO_CAMPANHA:
        return None
    certs = db.execute(select(Certificado).where(Certificado.campanha_id == camp.id, Certificado.lead_id == tarefa.lead_id,
                                                 Certificado.status == "Ativo")).scalars().all()
    guia = db.get(Certificado, tarefa.certificado_id)
    if guia is not None:  # só os certificados da onda deste aviso
        limite = guia.data_vencimento + timedelta(days=janela(db))
        certs = [c for c in certs if guia.data_vencimento <= c.data_vencimento <= limite]
    if len(certs) != 1:
        return None
    dados = _arte_do_certificado(certs[0])
    return {"tarefa": tarefa.id, **dados} if dados else None


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

def numeros_para_escolher(db) -> list[dict]:
    """Todos os números de WhatsApp cadastrados, com a situação: conectado e se está em modo teste (simulado)."""
    from . import conexoes
    from .integracoes import whatsapp_leads

    base = whatsapp_leads.status()
    lista = []
    for c in conexoes.todas(db):
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


def numero_do_envio(db, remetente: Usuario | None, escolhido: str = "") -> str:
    """O número por onde sai: o escolhido (no teste), senão o da configuração da Renovação, senão o automático.
    Número escolhido e desconectado: avisa (lança conexoes.SemNumero), nunca troca sozinho."""
    from . import conexoes
    from .integracoes import whatsapp_leads

    escolhido = escolhido or cfg(db, "renov_conexao")
    c = db.get(conexoes.ConexaoWhatsApp, escolhido) if escolhido else None
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
                 com_arte: bool = True, conexao: str = "") -> dict:
    """Ambiente de teste (como o da IA SDR): manda os avisos para o WhatsApp ou o e-mail DE QUEM ESTÁ TESTANDO, com
    "[TESTE]" no começo, do jeito que o cliente receberia (o texto e, se marcado, a arte do site). Sai pelo número e
    pelo e-mail de quem assina as campanhas de renovação; o WhatsApp, pelo número escolhido no teste (`conexao`), senão
    pelo dos disparos da Renovação, senão o automático. Nenhum cliente recebe nada e nenhuma campanha muda."""
    from types import SimpleNamespace

    from . import config, conexoes, contas_email, visual
    from .integracoes import email_smtp, whatsapp_leads

    remetente = dono(db) or usuario
    contato = contato_do_teste(db, cert_id, remetente)
    textos = textos_do_contato(db, contato, remetente)
    angulos = list(ANGULOS) if avisos == "todos" else [avisos if avisos in ANGULOS else "renov_aviso"]
    cert = contato.certificados[0]
    # a arte é de UM certificado: com vários no mesmo contato, o cliente recebe a lista no texto (o teste mostra igual)
    dados_arte = _arte_do_certificado(cert) if com_arte and len(contato.certificados) == 1 else None
    feito = {"enviadas": 0, "erros": [], "arte": False, "remetente": remetente.nome,
             "certificados": len(contato.certificados), "arte_pedida": com_arte, "numero": "", "modo_teste": False}
    numero, conta, imagem_email = "", None, None
    try:
        if canal == "whatsapp":
            numero = numero_do_envio(db, remetente, conexao)
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


def situacao_na_tela(cert: Certificado, hoje: date | None = None, dias_da_janela: int = JANELA_DIAS) -> tuple[str, str]:
    """(classe do selo, texto) para a lista da tela Renovação."""
    hoje = hoje or date.today()
    if cert.status in ("Renovado", "Não renovará"):
        return ("selo-ok" if cert.status == "Renovado" else "", SITUACOES[cert.status])
    if cert.status == "Vencido" or cert.data_vencimento < hoje:
        return ("", "Venceu")
    if cert.campanha_id:
        return ("selo-azul", "Em campanha")
    if cert.fora_motivo:
        return ("selo-alerta", "Fora: " + cert.fora_motivo)
    if not chave_do_contato(cert):
        return ("selo-erro", "Sem WhatsApp e sem e-mail")
    if cert.data_vencimento <= hoje:
        return ("", "Vence hoje")
    if cert.data_vencimento <= hoje + timedelta(days=dias_da_janela):
        return ("selo-alerta", "Pronto para avisar")
    return ("", f"Aviso a partir de {cert.data_vencimento - timedelta(days=dias_da_janela):%d/%m}")
