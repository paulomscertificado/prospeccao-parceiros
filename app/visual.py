"""Visual das campanhas: e-mail em HTML e imagem no WhatsApp (nov/2026).

Onde se cadastra: Campanhas > Visuais (app/rotas/visuais.py). Cada visual tem:
- HTML do e-mail: o layout. {{mensagem}} recebe o texto do toque (o mesmo da versão em texto, já personalizado
  para a empresa); {{nome}}, {{empresa}}, {{cidade}}, {{vendedor}} e {{descadastro}} (link de 1 clique) são
  preenchidos no envio. Sem {{descadastro}}, o rodapé de descadastro entra no fim (obrigatório por lei e pelos
  provedores). O e-mail sai com as DUAS versões (texto e HTML): o programa de e-mail mostra o HTML; os filtros de
  spam e quem não abre HTML veem o texto.
- Imagem do WhatsApp (PNG, JPG, GIF ou WebP, até 1 MB): sai com o texto do toque como legenda.
- Imagens do HTML: ficam guardadas aqui e são servidas em /visual/arquivo/<id>/<nome> (endereço público, para o
  programa de e-mail do lead conseguir mostrar).

Onde se usa: na Nova campanha da IA SDR e na configuração das Empresas novas escolhe-se o visual, os canais
(e-mail, WhatsApp) e os toques: "seguintes" (do 2º toque em diante, recomendado: o 1º contato frio responde melhor
só com texto) ou "todos". Ao montar a campanha, cada toque fica marcado (Tarefa.com_visual); o visual em si é lido
na hora do envio (trocar o HTML depois vale para o que ainda não saiu).

Proteção do número de WhatsApp: a imagem só sai para quem JÁ conversou com a MS (campanhas.whatsapp_liberado).
Para contato frio sai só o texto: imagem de número desconhecido parece propaganda e aumenta bloqueio e denúncia
(avaliação de 12/11/2026)."""

import hashlib
import html as html_lib
import re

from sqlalchemy import select

from . import config
from .modelos import ArquivoVisual, Campanha, Lead, Tarefa, VisualCampanha

LIMITE_IMAGEM = 1_000_000   # 1 MB por imagem: e-mail pesado vai para o spam e o WhatsApp comprime de todo jeito
LIMITE_HTML = 200_000       # o Gmail corta e-mails com mais de ~100 KB de HTML
SECOES = {"sdr": "IA SDR (parceiros)", "empresas_novas": "Empresas novas (venda)"}
CANAIS = {"email": "E-mail (HTML)", "whatsapp": "WhatsApp (imagem com o texto)"}
TOQUES = {"seguintes": "Do 2º toque em diante (recomendado)", "todos": "Em todos os toques"}
EXEMPLO = {"nome": "Ana", "empresa": "Escritório Exemplo", "cidade": "Recife", "vendedor": "Paulo"}
TEXTO_EXEMPLO = ("Olá, Ana! Tudo bem?\n\nAqui vai o texto do toque, igual ao da versão sem visual, já com o nome da "
                 "empresa e de quem assina.\n\nFaz sentido conversarmos?")


# ---------------------------------------------------------------- Arquivos

def tipo_da_imagem(dados: bytes) -> str:
    """Tipo pelo conteúdo (não pelo nome do arquivo). Vazio = não é imagem aceita."""
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if dados.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if dados[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    return ""


def problema_na_imagem(dados: bytes) -> str:
    if not dados:
        return "O arquivo está vazio."
    if len(dados) > LIMITE_IMAGEM:
        return f"A imagem tem {len(dados) / 1_000_000:.1f} MB; o máximo é 1 MB (diminua ou comprima antes)."
    if not tipo_da_imagem(dados):
        return "O arquivo não é uma imagem PNG, JPG, GIF ou WebP."
    return ""


def nome_seguro(nome: str) -> str:
    """Nome de arquivo para o endereço público: sem acento, espaço ou caminho."""
    from . import util

    base = util.chave_texto(nome or "imagem").replace(" ", "-")
    base = re.sub(r"[^a-z0-9._-]+", "", base).strip(".-") or "imagem"
    return base[:120]


def guardar_imagem(visual: VisualCampanha, dados: bytes, nome: str) -> None:
    visual.imagem, visual.imagem_tipo = dados, tipo_da_imagem(dados)
    visual.imagem_nome, visual.imagem_hash = nome_seguro(nome), hashlib.sha256(dados).hexdigest()


def url_arquivo(arquivo: ArquivoVisual) -> str:
    return f"{config.URL_PUBLICA}/visual/arquivo/{arquivo.id}/{arquivo.nome}"


# ---------------------------------------------------------------- HTML do e-mail

def limpar_html(html: str) -> str:
    """Tira o que programa de e-mail não executa e que não pode rodar na prévia: scripts, eventos (onclick...) e
    links javascript:."""
    html = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", html or "", flags=re.I | re.S)
    html = re.sub(r"<script\b[^>]*/?>", "", html, flags=re.I)
    html = re.sub(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    return re.sub(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", r'\1="#"', html, flags=re.I)


def texto_em_html(texto: str) -> str:
    """O texto do toque dentro do HTML: escapado, com parágrafos e quebras de linha."""
    partes = [p.strip() for p in re.split(r"\n\s*\n", (texto or "").strip()) if p.strip()]
    return "".join(f"<p style=\"margin:0 0 14px\">{html_lib.escape(p).replace(chr(10), '<br>')}</p>" for p in partes)


def montar_html(visual: VisualCampanha, texto: str, valores: dict, link_descadastro: str = "") -> str:
    """O e-mail em HTML pronto para um lead."""
    html = limpar_html(visual.html)
    if link_descadastro:
        rodape_link = (f'<a href="{html_lib.escape(link_descadastro)}">Não quero mais receber e-mails</a>')
    else:
        rodape_link = "Para não receber mais e-mails, responda com a palavra SAIR."
    tem_descadastro = "{{descadastro}}" in html.replace(" ", "")
    html = re.sub(r"\{\{\s*mensagem\s*\}\}", lambda _m: texto_em_html(texto), html)
    html = re.sub(r"\{\{\s*descadastro\s*\}\}", lambda _m: rodape_link, html)
    html = re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: html_lib.escape(str(valores.get(m.group(1), ""))), html)
    if not tem_descadastro:
        rodape = (f'<div style="font-family:Arial,sans-serif;font-size:12px;color:#777;margin:18px 0 0;'
                  f'text-align:center">{rodape_link}</div>')
        html = re.sub(r"</body\s*>", rodape + "</body>", html, count=1, flags=re.I) if re.search(
            r"</body\s*>", html, re.I) else html + rodape
    return html


def previa(visual: VisualCampanha) -> str:
    """O HTML com um texto e dados de exemplo (para a tela)."""
    return montar_html(visual, TEXTO_EXEMPLO, EXEMPLO, f"{config.URL_PUBLICA}/descadastrar/exemplo")


# ---------------------------------------------------------------- Na campanha

def disponiveis(db, secao: str) -> list[VisualCampanha]:
    """Visuais ativos que podem ser escolhidos nesta parte do sistema (sdr ou empresas_novas)."""
    return [v for v in db.execute(select(VisualCampanha).where(VisualCampanha.ativo.is_(True))
                                  .order_by(VisualCampanha.nome)).scalars()
            if secao in (v.usar_em or "").split(",")]


def escolha_do_formulario(db, form, secao: str, prefixo: str = "visual") -> tuple[int | None, str, str]:
    """(visual_id, canais, toques) escolhidos num formulário. Visual que não pode ser usado aqui = nenhum."""
    from . import util

    vid = util.para_int(form.get(f"{prefixo}_id"))
    visual = db.get(VisualCampanha, vid) if vid else None
    if visual is None or not visual.ativo or secao not in (visual.usar_em or "").split(","):
        return None, "", "seguintes"
    canais = ",".join(c for c in CANAIS if form.get(f"{prefixo}_{c}"))
    toques = str(form.get(f"{prefixo}_toques") or "seguintes")
    return visual.id, canais, toques if toques in TOQUES else "seguintes"


def no_toque(camp: Campanha | None, indice: int) -> bool:
    """Este toque da cadência usa o visual? (indice 0 = primeiro contato)"""
    if camp is None or not camp.visual_id or not camp.visual_canais:
        return False
    return camp.visual_toques == "todos" or indice > 0


def _da_tarefa(db, tarefa: Tarefa | None, canal: str) -> VisualCampanha | None:
    if tarefa is None or not tarefa.com_visual or not tarefa.campanha_id:
        return None
    camp = db.get(Campanha, tarefa.campanha_id)
    if camp is None or not camp.visual_id or canal not in (camp.visual_canais or "").split(","):
        return None
    visual = db.get(VisualCampanha, camp.visual_id)
    return visual if visual is not None and visual.ativo else None


def html_do_email(db, tarefa: Tarefa | None, lead: Lead | None, quem, texto: str, link_descadastro: str = "") -> str:
    """O HTML do e-mail deste toque, ou vazio (sai só o texto)."""
    from . import mensagens

    visual = _da_tarefa(db, tarefa, "email")
    if visual is None or not (visual.html or "").strip():
        return ""
    return montar_html(visual, texto, mensagens.valores_variaveis(db, lead, quem), link_descadastro)


def imagem_do_whatsapp(db, tarefa: Tarefa | None, lead: Lead | None, so_para_quem_conversou: bool = True):
    """O visual cuja imagem vai junto no WhatsApp deste toque, ou None (sai só o texto). Só para quem já conversou
    com a MS: contato frio recebe só o texto (proteção do número)."""
    from . import campanhas

    visual = _da_tarefa(db, tarefa, "whatsapp")
    if visual is None or not visual.imagem_hash:
        return None
    if so_para_quem_conversou and (lead is None or not campanhas.whatsapp_liberado(db, lead)):
        return None
    return visual


def resumo_da_campanha(db, camp: Campanha) -> str:
    """Ex.: "Folheto parceria · e-mail e WhatsApp (só para quem já conversou) · do 2º toque em diante"."""
    if not camp.visual_id or not camp.visual_canais:
        return ""
    visual = db.get(VisualCampanha, camp.visual_id)
    if visual is None:
        return "visual apagado (os toques saem só com texto)"
    canais = [("e-mail" if c == "email" else "WhatsApp (só para quem já conversou)")
              for c in camp.visual_canais.split(",") if c in CANAIS]
    return f"{visual.nome} · {' e '.join(canais)} · {TOQUES.get(camp.visual_toques, '').lower()}"
