"""Tela API Oficial: as conversas do número da API oficial da Meta (pedido da Maria em 21/11/2026: "preciso ver as
respostas dos clientes em algum lugar, ... coloque em um lugar separado das conversas ... como API Oficial").

O número oficial está ligado direto na API e não abre em celular nenhum: é aqui que a equipe acompanha. Aparece tudo o
que o número mandou (os avisos da Renovação, os testes), com a situação da entrega que a Meta avisa, e tudo o que chegou
nele, de cliente ou não (tabela mensagens_oficiais, guardada por whatsapp_oficial.guardar_conversa no webhook e nos
envios). Cada AR vê só as do número dela (isolamento). Responder por aqui ainda não (etapa 3 da API oficial): a equipe
fala com o cliente pelo próprio WhatsApp ou por telefone.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from .. import autorizacao, util, whatsapp_oficial
from ..banco import obter_db
from ..modelos import ContaWhatsAppOficial, ImagemOficial, Lead, MensagemOficial, Usuario
from ..seguranca import exige
from ..web import tela

rotas = APIRouter()

LIMITE_CONVERSAS = 200  # conversas na lista (as mais recentes primeiro)
LIMITE_MENSAGENS = 300  # mensagens mostradas da conversa aberta (as últimas)
NOMES_DO_TIPO = {"botao": "tocou no botão", "modelo": "aviso (modelo aprovado pela Meta)",
                 "calendario": "calendário para marcar a renovação", "formulario": "escolheu no calendário"}
MIDIAS = whatsapp_oficial.NOMES_DAS_MIDIAS
EXTENSOES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


def _marca(db: Session) -> str:
    """Assinatura do que a tela mostra (mensagem nova, entrega que mudou ou conversa lida): mudou, a tela recarrega."""
    ultima, mudou, nao_lidas = db.execute(select(
        func.max(MensagemOficial.id), func.max(MensagemOficial.atualizado_em),
        func.sum(case((and_(MensagemOficial.direcao == "entrada", MensagemOficial.lida.is_(False)), 1), else_=0)))
    ).one()
    return f"{ultima or 0}-{mudou or ''}-{nao_lidas or 0}"


def _conversas(db: Session, busca: str) -> list[dict]:
    """As conversas (uma por telefone), da mais recente para a mais antiga, com a última mensagem e as não lidas."""
    resumo = (select(MensagemOficial.telefone, func.max(MensagemOficial.id).label("ultima"),
                     func.sum(case((and_(MensagemOficial.direcao == "entrada", MensagemOficial.lida.is_(False)), 1),
                                   else_=0)).label("nao_lidas"))
              .group_by(MensagemOficial.telefone))
    termo = busca.strip()
    if termo:
        condicoes = [MensagemOficial.nome.ilike(f"%{termo}%"),
                     MensagemOficial.lead_id.in_(select(Lead.id).where(Lead.empresa.ilike(f"%{termo}%")))]
        digitos = util.so_digitos(termo)
        if len(digitos) >= 4:
            condicoes.append(MensagemOficial.telefone.like(f"%{digitos}%"))
        resumo = resumo.where(or_(*condicoes))
    linhas = db.execute(resumo.order_by(func.max(MensagemOficial.criado_em).desc(), func.max(MensagemOficial.id).desc())
                        .limit(LIMITE_CONVERSAS)).all()
    if not linhas:
        return []
    ultimas = {m.id: m for m in db.execute(select(MensagemOficial).where(
        MensagemOficial.id.in_([l.ultima for l in linhas]))).scalars()}
    telefones = [l.telefone for l in linhas]
    nomes, leads = _nomes_e_leads(db, telefones)
    return [{"telefone": l.telefone, "ultima": ultimas.get(l.ultima), "nao_lidas": int(l.nao_lidas or 0),
             "nome": nomes.get(l.telefone) or (leads[l.telefone].empresa if l.telefone in leads else ""),
             "lead": leads.get(l.telefone)} for l in linhas]


def _nomes_e_leads(db: Session, telefones: list[str]) -> tuple[dict[str, str], dict[str, Lead]]:
    """O nome do perfil do WhatsApp mais recente de cada telefone e o lead ligado a ele (se houver)."""
    nomes: dict[str, str] = {}
    for telefone, nome in db.execute(select(MensagemOficial.telefone, MensagemOficial.nome).where(
            MensagemOficial.telefone.in_(telefones), MensagemOficial.nome != "").order_by(MensagemOficial.id.desc())):
        nomes.setdefault(telefone, nome)
    ids: dict[str, int] = {}
    for telefone, lead_id in db.execute(select(MensagemOficial.telefone, MensagemOficial.lead_id).where(
            MensagemOficial.telefone.in_(telefones), MensagemOficial.lead_id.is_not(None))
            .order_by(MensagemOficial.id.desc())):
        ids.setdefault(telefone, lead_id)
    por_id = {l.id: l for l in db.execute(select(Lead).where(Lead.id.in_(set(ids.values())))).scalars()} if ids else {}
    return nomes, {t: por_id[i] for t, i in ids.items() if i in por_id}


def _quando(momento) -> str:
    """Hora curta da lista: hoje = 16:14; ontem; neste ano = 20/11; antes = 20/11/2025."""
    if momento is None:
        return ""
    hoje = date.today()
    if momento.date() == hoje:
        return momento.strftime("%H:%M")
    if momento.date() == hoje - timedelta(days=1):
        return "ontem"
    return momento.strftime("%d/%m" if momento.year == hoje.year else "%d/%m/%Y")


def _partes(texto: str) -> dict:
    """O aviso que foi com a arte guarda isso na 1ª linha: a tela mostra como etiqueta, fora do texto."""
    texto = texto or ""
    marca = whatsapp_oficial.MARCA_DA_ARTE
    if marca in texto[:80]:
        return {"arte": True, "texto": texto.replace(marca, "", 1)}
    return {"arte": False, "texto": texto}


def _midia(m: MensagemOficial, imagens: set[int]) -> dict:
    """Mídia que chegou: a foto aparece (com a legenda, se veio); senão, o que é e por que não aparece. Foto e figurinha
    o relógio baixa da Meta em até 1 minuto (pedido da Maria em 23/11/2026); áudio, vídeo e documento não aparecem."""
    legenda = "" if m.texto in MIDIAS else (m.texto or "")
    if m.id in imagens:
        return {"rotulo": "", "legenda": legenda}
    nome = MIDIAS.get(m.texto, "Imagem" if m.midia_id else "Mídia")
    if not m.midia_id:
        return {"rotulo": f"{nome} (não aparece aqui)", "legenda": legenda}
    if whatsapp_oficial.foto_perdida(m):
        return {"rotulo": f"{nome}: a Meta não entregou, não dá para ver aqui", "legenda": legenda}
    return {"rotulo": f"{nome}: aparece aqui em instantes", "legenda": legenda}


def _previa(m: MensagemOficial | None) -> str:
    """A linha de baixo de cada conversa da lista: a última mensagem (foto com o 📷, como no WhatsApp)."""
    if m is None:
        return ""
    texto = _partes(m.texto)["texto"]
    if m.tipo == "midia":
        texto = ("📷 " if m.midia_id else "") + MIDIAS.get(texto, texto)
    return ("↗ " if m.direcao == "saida" else "") + texto.replace("\n", " ")


def _iniciais(nome: str, telefone: str) -> str:
    partes = [p for p in (nome or "").split() if p[:1].isalnum()]
    if partes:
        return (partes[0][0] + (partes[1][0] if len(partes) > 1 else "")).upper()
    return (telefone or "?")[-2:]


@rotas.get("/oficial")
def tela_oficial(request: Request, telefone: str = "", busca: str = "",
                 usuario: Usuario = Depends(exige("oficial.ver")), db: Session = Depends(obter_db)):
    contas = db.execute(select(ContaWhatsAppOficial).where(ContaWhatsAppOficial.token_cripto != "")
                        .order_by(ContaWhatsAppOficial.id)).scalars().all()
    conversas = _conversas(db, busca)
    chave = whatsapp_oficial.chave_da_conversa(telefone) if telefone else ""
    if not chave and conversas and not busca:
        chave = conversas[0]["telefone"]  # sem escolha: a conversa mais recente
    mensagens, aberta = [], None
    if chave:
        mensagens = list(reversed(db.execute(select(MensagemOficial).where(MensagemOficial.telefone == chave)
                                             .order_by(MensagemOficial.id.desc()).limit(LIMITE_MENSAGENS)).scalars().all()))
        aberta = next((c for c in conversas if c["telefone"] == chave), None)
        if aberta is None and mensagens:  # conversa fora da lista (busca): os dados dela
            nomes, leads = _nomes_e_leads(db, [chave])
            aberta = {"telefone": chave, "nome": nomes.get(chave) or (leads[chave].empresa if chave in leads else ""),
                      "lead": leads.get(chave), "nao_lidas": 0, "ultima": mensagens[-1]}
        lidas = [m for m in mensagens if m.direcao == "entrada" and not m.lida]
        for m in lidas:  # abriu a conversa: as que chegaram ficam lidas (sai o número vermelho do menu)
            m.lida = True
        if lidas:
            db.commit()
            if aberta is not None:
                aberta["nao_lidas"] = 0
    abre_lead = {c["lead"].id for c in conversas + ([aberta] if aberta else [])
                 if c and c.get("lead") is not None and autorizacao.pode(usuario, "leads.ver", c["lead"])}
    # pedido da Maria em 23/11/2026 ("não consigo ver a imagem das mensagens para saber se saíram corretas"): a arte
    # que foi no aviso aparece dentro da mensagem, como no WhatsApp
    imagens = set(db.execute(whatsapp_oficial.imagens_das_mensagens([m.id for m in mensagens],
                                                                    ImagemOficial.mensagem_id)).scalars())
    return tela(request, "oficial.html", {
        "contas": contas, "conversas": conversas, "aberta": aberta, "mensagens": mensagens, "busca": busca,
        "chave": chave, "abre_lead": abre_lead, "marca_da_tela": _marca(db), "NOMES_DO_TIPO": NOMES_DO_TIPO,
        "iniciais": _iniciais, "quando": _quando, "partes": _partes, "imagens": imagens, "midia": _midia,
        "previa": _previa})


@rotas.get("/oficial/imagem/{mensagem_id:int}")
def imagem_da_mensagem(mensagem_id: int, usuario: Usuario = Depends(exige("oficial.ver")),
                       db: Session = Depends(obter_db)):
    """A imagem que foi na mensagem (a arte do aviso): dentro da conversa e, com um clique, inteira numa aba nova."""
    linha = db.execute(whatsapp_oficial.imagens_das_mensagens([mensagem_id]).limit(1)).scalars().first()
    if linha is None or not linha.imagem:
        raise HTTPException(404)
    nome = f"aviso-{mensagem_id}.{EXTENSOES.get(linha.tipo, 'png')}"
    return Response(linha.imagem, media_type=linha.tipo or "image/png",
                    headers={"Cache-Control": "private, max-age=86400", "Content-Disposition": f'inline; filename="{nome}"'})


@rotas.get("/oficial/marca")
def marca_da_tela(usuario: Usuario = Depends(exige("oficial.ver")), db: Session = Depends(obter_db)):
    """A tela aberta pergunta de vez em quando (só com a aba à vista) se algo mudou; mudou, ela recarrega."""
    return {"marca": _marca(db)}
