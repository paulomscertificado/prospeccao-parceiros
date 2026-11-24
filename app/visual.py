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
(avaliação de 12/11/2026).

E-mail com a marca (padrão, pedido da Maria em 16/11/2026): sem visual escolhido na campanha, a IA SDR e as Empresas
novas mandam do 2º e-mail em diante um HTML leve feito com a marca da AR (faixa com o logo e a cor, o texto do toque e
o descadastro discreto): html_da_marca. O 1º e-mail para cada empresa continua só em texto (contato frio responde
melhor e cai menos no spam ou na aba Promoções). É um MÓDULO ("email_html", autorizacao.MODULOS): o Admin Master libera
por marca no Painel master (Módulos de cada AR); prévia em Campanhas > Visuais."""

import hashlib
import html as html_lib
import re

from sqlalchemy import and_, or_, select

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

    # campo vazio (empresa sem o nome do responsável): "Olá, {{nome}}!" vira "Olá!" e "Oi {{nome}}, tudo bem?" vira
    # "Oi, tudo bem?", como no texto (mensagens.aplicar_variaveis); antes a arte saía com "Olá, ! Tudo bem?" (23/11/2026)
    def sem_o_vazio(m):
        return "" if not str(valores.get(m.group(1)) or "").strip() else m.group(0)

    html = re.sub(r"[ \t]*,[ \t]*\{\{\s*(\w+)\s*\}\}(?=[ \t]*[!?.])", sem_o_vazio, html)
    html = re.sub(r"[ \t]+\{\{\s*(\w+)\s*\}\}(?=[ \t]*,)", sem_o_vazio, html)
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
    """O HTML do e-mail deste toque, ou vazio (sai só o texto): o visual escolhido na campanha ou, sem ele, o e-mail
    com a marca da AR (do 2º e-mail em diante, se estiver ligado)."""
    from . import mensagens

    visual = _da_tarefa(db, tarefa, "email")
    if visual is not None and (visual.html or "").strip():
        return montar_html(visual, texto, mensagens.valores_variaveis(db, lead, quem), link_descadastro)
    if usa_html_da_marca(db, tarefa):
        return html_da_marca(db, tarefa.tenant_id, texto, link_descadastro)
    return ""


# ---------------------------------------------------------------- E-mail com a marca (padrão)

CHAVE_HTML_DA_MARCA = "modulo_email_html"  # o módulo "email_html" (autorizacao.MODULOS), de cada AR
TIPOS_COM_HTML_DA_MARCA = ("parceiros", "empresas_novas")  # IA SDR e Empresas novas (a Renovação manda a arte)
COR_PADRAO = "#123a63"
FONTE_DO_EMAIL = "Arial, Helvetica, sans-serif"  # letra que todo programa de e-mail tem
ASSINATURA_EXEMPLO = "\n\nAtenciosamente,\nPaulo\n{marca}"


def html_da_marca_ligado(db) -> bool:
    """O módulo está liberado para a marca? (o Admin Master libera por AR; a rotina lê a configuração da AR da tarefa).
    Mesma regra dos outros módulos (autorizacao.modulos_ligados): só "0" desliga; o padrão dele é "0"."""
    from .banco import ler_config

    return ler_config(db, CHAVE_HTML_DA_MARCA) != "0"


def primeiro_email(db, tarefa: Tarefa) -> bool:
    """É o 1º e-mail desta campanha para a empresa? Conta o que já saiu e o que ainda vai sair antes dele (um e-mail
    cancelado antes não conta: aí este vira o primeiro)."""
    anterior = db.execute(select(Tarefa.id).where(
        Tarefa.campanha_id == tarefa.campanha_id, Tarefa.lead_id == tarefa.lead_id, Tarefa.canal == "email",
        Tarefa.id != tarefa.id, Tarefa.status.in_(("feita", "pendente", "rascunho")),
        or_(Tarefa.data < tarefa.data, and_(Tarefa.data == tarefa.data, Tarefa.id < tarefa.id))).limit(1)).first()
    return anterior is None


def usa_html_da_marca(db, tarefa: Tarefa | None) -> bool:
    """Este toque sai com o e-mail com a marca? Só na IA SDR e nas Empresas novas, com a opção ligada e do 2º e-mail
    da campanha para a empresa em diante."""
    if tarefa is None or not tarefa.campanha_id or not tarefa.lead_id or not html_da_marca_ligado(db):
        return False
    camp = db.get(Campanha, tarefa.campanha_id)
    if camp is None or camp.tipo not in TIPOS_COM_HTML_DA_MARCA or camp.email_html is False:
        return False  # o botão "E-mail em HTML com a marca" desmarcado na campanha: tudo em texto
    return not primeiro_email(db, tarefa)


def usa_html_da_marca_na_renovacao(db, tarefa: Tarefa | None) -> bool:
    """Renovação: o e-mail do aviso que vai SEM a arte (quem tem vários certificados, arte desligada ou que não ficou
    pronta) sai com a marca, com o módulo liberado e o botão marcado na tela Renovação. Em todos os avisos: quem recebe
    é cliente, não contato frio (a arte, quando existe, continua valendo: campanhas._enviar_email_da_tarefa)."""
    if tarefa is None or not tarefa.campanha_id or not html_da_marca_ligado(db):
        return False
    camp = db.get(Campanha, tarefa.campanha_id)
    return camp is not None and camp.tipo == "renovacao" and camp.email_html is not False


def _cor(valor: str) -> str:
    valor = (valor or "").strip()
    return valor if re.fullmatch(r"#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}", valor) else COR_PADRAO


def _logo_para_email(m: dict) -> str:
    """O endereço completo do logo da AR (o programa de e-mail do lead busca na internet). Sem o sistema publicado na
    internet (computador local), o e-mail vai sem logo: o nome da empresa vai no lugar."""
    if not m.get("logo_url") or any(x in config.URL_PUBLICA for x in ("localhost", "127.0.0.1")):
        return ""
    return config.URL_PUBLICA.rstrip("/") + m["logo_url"]


def _logo_na_previa(db, ar: int | None) -> str:
    """O logo dentro da própria prévia da tela (data:): ela fica num quadro isolado, que não busca nada no servidor."""
    import base64

    from . import marca

    achado = marca.logo(db, ar) if ar else None
    if not achado:
        return ""
    dados, tipo = achado
    return f"data:{tipo};base64,{base64.b64encode(dados).decode('ascii')}"


def _com_links(html: str, cor: str) -> str:
    """Endereços do texto (site, wa.me do convite) viram links clicáveis no HTML (no texto o programa já faz isso)."""
    def link(m):
        endereco = m.group(0)
        destino = endereco if endereco.startswith("http") else "https://" + endereco
        return f'<a href="{destino}" style="color:{cor};text-decoration:underline">{endereco}</a>'

    return re.sub(r"(?:https?://|\bwa\.me/)[^\s<]*[^\s<.,;:!?)\]]", link, html)


def html_da_marca(db, ar: int | None, texto: str, link_descadastro: str = "", na_tela: bool = False) -> str:
    """O e-mail em HTML leve com a marca da AR: faixa com o logo (ou o nome) na cor da marca, o texto do toque (o
    mesmo da versão em texto, com a assinatura de quem envia) e o descadastro discreto embaixo. Uma imagem só e a letra
    comum dos programas de e-mail: cara de e-mail de pessoa, não de propaganda."""
    from . import marca

    m = marca.da_ar(db, ar) if ar else marca.da_plataforma(db)
    nome = html_lib.escape(m.get("nome") or "")
    cor = _cor(m.get("cor"))
    logo = (_logo_na_previa(db, ar) if na_tela else "") or _logo_para_email(m)
    if logo:
        proporcao = float(m.get("logo_proporcao") or 0)
        largura = f' width="{min(220, round(36 * proporcao))}"' if proporcao > 0 else ""
        cabeca = (f'<img src="{html_lib.escape(logo)}" alt="{nome}" height="36"{largura} '
                  f'style="display:block;height:36px;max-width:220px;border:0;outline:none">')
    else:
        cabeca = (f'<span style="font-family:{FONTE_DO_EMAIL};font-size:18px;font-weight:bold;color:#ffffff">'
                  f'{nome}</span>')
    if link_descadastro:
        sair = (f'Não quer mais receber nossos e-mails? <a href="{html_lib.escape(link_descadastro)}" '
                f'style="color:#6b7280;text-decoration:underline">Clique aqui</a>.')
    else:
        sair = "Para não receber mais e-mails, responda com a palavra SAIR."
    corpo = _com_links(texto_em_html(texto), cor)
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{nome}</title></head>'
        '<body style="margin:0;padding:0;background:#f3f4f6">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f3f4f6">'
        '<tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;max-width:600px;background:#ffffff;border-radius:10px">'
        f'<tr><td style="background:{cor};padding:16px 28px;border-radius:10px 10px 0 0">{cabeca}</td></tr>'
        f'<tr><td style="padding:26px 28px 12px;font-family:{FONTE_DO_EMAIL};font-size:15px;line-height:1.6;'
        f'color:#1f2933">{corpo}</td></tr>'
        '</table>'
        f'<p style="max-width:600px;margin:14px auto 0;font-family:{FONTE_DO_EMAIL};font-size:12px;line-height:1.5;'
        f'color:#6b7280;text-align:center">{sair}</p>'
        '</td></tr></table></body></html>')


def previa_da_marca(db, ar: int | None) -> str:
    """O e-mail com a marca com um texto de exemplo (tela Campanhas > Visuais)."""
    from . import marca

    m = marca.da_ar(db, ar) if ar else marca.da_plataforma(db)
    texto = TEXTO_EXEMPLO + ASSINATURA_EXEMPLO.format(marca=m.get("nome") or "")
    return html_da_marca(db, ar, texto, f"{config.URL_PUBLICA}/descadastrar/exemplo", na_tela=True)


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
        if (camp.tipo in TIPOS_COM_HTML_DA_MARCA and camp.email_html is not False and html_da_marca_ligado(db)):
            return "e-mail com a marca · do 2º e-mail em diante"
        return ""
    visual = db.get(VisualCampanha, camp.visual_id)
    if visual is None:
        return "visual apagado (os toques saem só com texto)"
    canais = [("e-mail" if c == "email" else "WhatsApp (só para quem já conversou)")
              for c in camp.visual_canais.split(",") if c in CANAIS]
    return f"{visual.nome} · {' e '.join(canais)} · {TOQUES.get(camp.visual_toques, '').lower()}"


# ---------------------------------------------------------------- No teste da campanha

def _no_teste(db, camp: Campanha, marca_ligada: bool | None = None) -> dict[str, tuple[int, str]]:
    """{canal: (desde, regra)}: em que toque o HTML do e-mail e a imagem do WhatsApp começam nesta campanha (desde 0 =
    em nenhum, 1 = em todos, 2 = do 2º em diante: o 1º contato sai só em texto) e a regra dita para a pessoa. A mesma
    regra do envio (html_do_email, imagem_do_whatsapp), lida da campanha sem olhar toque por toque."""
    resposta = {"email": (0, ""), "whatsapp": (0, "")}
    if camp.tipo == "renovacao":  # a Renovação manda a arte do aviso e tem o teste próprio (tela Renovação)
        return resposta
    escolhido = db.get(VisualCampanha, camp.visual_id) if camp.visual_id else None
    if escolhido is not None and not escolhido.ativo:
        escolhido = None
    canais = (camp.visual_canais or "").split(",")
    desde = 1 if camp.visual_toques == "todos" else 2
    if escolhido is not None and "email" in canais and (escolhido.html or "").strip():
        resposta["email"] = (desde, f'a arte "{escolhido.nome}" vai '
                                    + ("em todos os e-mails" if desde == 1 else "do 2º toque em diante"))
    elif camp.tipo in TIPOS_COM_HTML_DA_MARCA and camp.email_html is not False and (
            html_da_marca_ligado(db) if marca_ligada is None else marca_ligada):
        resposta["email"] = (2, "o e-mail com a marca vai do 2º e-mail em diante")
    if escolhido is not None and "whatsapp" in canais and escolhido.imagem_hash:
        resposta["whatsapp"] = (desde, f'a imagem da arte "{escolhido.nome}" vai '
                                       + ("em todas as mensagens" if desde == 1 else "do 2º toque em diante"))
    return resposta


def dicas_do_teste(db, camp: Campanha, marca_ligada: bool | None = None) -> dict:
    """O aviso da área "Testar antes de aprovar" para cada canal da campanha, antes do envio (pedido da Maria em
    23/11/2026: o teste do 1º contato chegou só em texto e parecia que o HTML não saía). {"email": texto,
    "email_desde": n, "whatsapp": texto, "whatsapp_desde": n}; com desde 2 a tela oferece "Todos os 4 toques"."""
    dicas = {}
    for canal, (desde, regra) in _no_teste(db, camp, marca_ligada).items():
        texto = ""
        if desde:
            texto = regra[:1].upper() + regra[1:] + (": o 1º contato sai só em texto." if desde == 2 else ".")
            if canal == "whatsapp":
                texto += " No envio de verdade, a imagem só vai para quem já conversou; no teste, ela vem para você."
        elif canal == "email" and camp.tipo != "renovacao":
            onde = "na tela Empresas novas" if camp.tipo == "empresas_novas" else "no passo 4 da Nova campanha"
            texto = (f"Os e-mails desta campanha saem só em texto: ela não tem arte no e-mail (a arte se escolhe "
                     f'{onde}, em "Visual").')
        dicas[canal], dicas[f"{canal}_desde"] = texto, desde
    return dicas


def depois_do_teste(db, camp: Campanha, canal: str, enviadas: int, com_visual: int,
                    todos_os_toques: bool = False) -> tuple[str, str]:
    """Depois do teste: (o que completa o aviso de enviado, alerta). Ex.: ("2 com o HTML; o 1º contato vai só em
    texto", "") ou, quando foi só o 1º contato e o HTML começa no 2º, ("", "O teste foi só em texto porque ...")."""
    if not enviadas:
        return "", ""
    desde, regra = _no_teste(db, camp)[canal]
    o_que = "o HTML" if canal == "email" else "a imagem"
    if com_visual >= enviadas:
        return (f"todos com {o_que}" if enviadas > 1 else f"com {o_que}"), ""
    if com_visual:
        return f"{com_visual} com {o_que}" + ("; o 1º contato vai só em texto" if desde == 2 else ""), ""
    if desde == 2 and not todos_os_toques:
        return "", (f"O teste foi só em texto porque o 1º contato sai assim: {regra}. Para ver, teste de novo "
                    f'escolhendo "Todos os 4 toques" em "Quais toques".')
    if canal == "email" and not desde:
        return "", dicas_do_teste(db, camp)["email"]
    return "", ""
