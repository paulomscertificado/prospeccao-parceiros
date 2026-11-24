"""Tela Conversas: as conversas do número conectado (todas) e envio de mensagem para qualquer número.

Cada pessoa vê as conversas do PRÓPRIO número e dos números compartilhados com ela (app/conexoes.py); o
administrador vê todas. As mensagens vêm do WhatsApp Leads pela ponte (tabela mensagens_whatsapp, ver /api/ponte/retorno). O que se
escreve aqui vira um envio "manual" na fila da ponte (ponte_whatsapp.manual) e sai na hora pelo número,
como as respostas escritas na tela Conversas do WhatsApp Leads. Quem pediu SAIR não recebe.

A tela se atualiza sozinha (a conversa aberta a cada 5 s, a lista a cada 15 s). Para gastar pouco do banco da nuvem
(Supabase), cada atualização manda a "marca" do que a tela já tem e o sistema só responde "igual" quando nada mudou;
a conversa e a lista inteiras só vão de novo quando algo mudou (17/11/2026: a conversa inteira, até 300 mensagens,
ia a cada 5 s e a lista era refeita a cada 15 s passando por todas as mensagens; era o que mais gastava).

"Apagar para todos", como no WhatsApp (24/11/2026, pedido da Maria): clicando numa mensagem que saiu, os "Dados da
mensagem" trazem o botão. O pedido vai pela ponte (comando "apagar_mensagem"; o WhatsApp Leads apaga do WhatsApp do
contato) e a mensagem fica "Você apagou esta mensagem" aqui, com quem apagou; o texto continua guardado.

Fotos e áudios (24/11/2026, pedido da Maria: "faça com que whatsapp leads também consiga ler imagens e reproduzir
áudios"): o WhatsApp Leads baixa a foto, a figurinha e o áudio e manda pela ponte (/api/ponte/anexo/<id_wl>, tabela
anexos_whatsapp); a conversa mostra a foto e toca o áudio dentro da mensagem (/conversas/anexo/<id>).
"""

import hashlib
import json
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, undefer

from .. import autorizacao, config, conexoes, sdr, util
from ..banco import agora, gravar_config, ler_config, obter_db
from ..integracoes import whatsapp_leads
from ..leads_servico import historico, pode_ver
from ..modelos import AnexoWhatsApp, ComandoWhatsApp, ContatoWhatsApp, MensagemWhatsApp, PonteWhatsApp, Usuario
from ..seguranca import exige, registrar_log, verificar_csrf
from ..web import tela

rotas = APIRouter()

TELA_ABERTA = "wl_conversas_vista_em"  # com a tela aberta, a ponte com o computador do WhatsApp troca a cada 10 s
VERSAO = "wl_conversas_versao"  # muda quando mensagens são lidas ou um nome muda: as listas abertas se atualizam
# O WhatsApp só apaga para todos até uns 2 dias depois do envio ("cerca de 2 dias", diz a Central de Ajuda dele): o
# mesmo prazo do WhatsApp Leads (whatsapp.HORAS_PARA_APAGAR), que confere de novo pela hora em que a mensagem saiu
HORAS_PARA_APAGAR = 48
APAGADA = "🚫 Você apagou esta mensagem"


def _chave(telefone: str) -> str:
    """Chave da conversa: DDD + número, sem o 55 e com o 9 dos celulares (números estrangeiros: só os dígitos).
    Com o 9 sempre, a conversa é a mesma quer o WhatsApp entregue o número antigo (sem o 9), quer a pessoa
    digite o número completo. Antes a mensagem enviada aqui ia para uma conversa "sem o 9" e não aparecia."""
    return util.com_nono_digito(telefone) or util.so_digitos(telefone)


def _nomes_escolhidos(db: Session) -> dict[str, str]:
    return {c.telefone: c.nome for c in db.execute(select(ContatoWhatsApp)).scalars() if c.nome}


def _de_outra_ar(db: Session, chave: str) -> bool:
    """O telefone já tem nome guardado por outra AR? (o nome é um por telefone até a chave ganhar a AR; white label)"""
    return db.execute(select(ContatoWhatsApp.telefone).where(ContatoWhatsApp.telefone == chave)
                      .execution_options(sem_filtro_de_ar=True)).first() is not None


def _salvar_nome(db: Session, chave: str, nome: str, usuario: Usuario) -> bool:
    """Guarda o nome aqui e pede ao WhatsApp Leads para trocar o nome do contato lá também. False = o telefone já tem
    nome de outra AR: nada muda (nem lá, que é o mesmo computador para as ARs)."""
    nome = nome.strip()[:200]
    contato = db.get(ContatoWhatsApp, chave)
    if contato is None and _de_outra_ar(db, chave):
        return False
    if contato is None:
        db.add(ContatoWhatsApp(telefone=chave, nome=nome))
    else:
        contato.nome, contato.atualizado_em = nome, agora()
    _mudou(db)  # as listas abertas mostram o nome novo
    if nome and config.WHATSAPP_PONTE:
        db.add(ComandoWhatsApp(acao="renomear_contato", usuario_id=usuario.id,
                               dados=json.dumps({"telefone": "55" + chave if len(chave) in (10, 11) else chave,
                                                 "nome": nome}, ensure_ascii=False)))
    return True


def _numeros(db: Session, usuario: Usuario, escolhido: str = "") -> list[str]:
    """Números cujas conversas a pessoa pode ver (todos os dela, ou só o escolhido, se ela puder)."""
    ids = [c.id for c in conexoes.acessiveis(db, usuario)]
    return [escolhido] if escolhido in ids else ids


def _numero_padrao(db: Session, usuario: Usuario) -> str:
    proprio = conexoes.minha(db, usuario)
    if proprio:
        return proprio.id
    acessiveis = conexoes.acessiveis(db, usuario)
    return acessiveis[0].id if acessiveis else ""


def _numero_da_conversa(db: Session, chave: str, numeros: list[str]) -> str:
    """Entre os números que a pessoa vê, o da mensagem mais recente com este contato ("" = nenhum). O "Ver conversa"
    das Oportunidades abre a conversa sem dizer o número: a tela abria o número padrão (o principal), vazio, e a
    resposta, que tinha chegado pelo WhatsApp do Paulo Lucas, não aparecia (24/11/2026, pedido da Maria)."""
    if not chave or not numeros:
        return ""
    return db.execute(select(MensagemWhatsApp.conexao)
                      .where(MensagemWhatsApp.telefone == chave, MensagemWhatsApp.conexao.in_(numeros))
                      .order_by(MensagemWhatsApp.criado_em.desc(), MensagemWhatsApp.id.desc()).limit(1)).scalar() or ""


def _outros_numeros(db: Session, chave: str, numeros: list[str], aberto: str) -> list[str]:
    """Os outros números (dos que a pessoa vê) que também conversaram com este contato, o mais recente primeiro: a
    conversa aberta avisa e abre a de lá com um clique (em 24/11/2026, 79 contatos tinham conversa em 2 números ou mais)."""
    outros = [n for n in numeros if n != aberto]
    if not chave or not outros:
        return []
    return list(db.execute(select(MensagemWhatsApp.conexao)
                           .where(MensagemWhatsApp.telefone == chave, MensagemWhatsApp.conexao.in_(outros))
                           .group_by(MensagemWhatsApp.conexao)
                           .order_by(func.max(MensagemWhatsApp.criado_em).desc())).scalars())


def _tela_vista(db: Session) -> None:
    whatsapp_leads.marcar_tela(db, TELA_ABERTA)


def _mudou(db: Session) -> None:
    """Muda a versão das conversas (um código novo a cada vez: duas mudanças no mesmo segundo também contam)."""
    gravar_config(db, VERSAO, secrets.token_hex(8))


def _marca(*partes) -> str:
    """Assinatura curta do que a tela mostra: igual à da última vez = nada mudou."""
    return hashlib.sha256(json.dumps(partes, default=str).encode()).hexdigest()[:20]


def _motivo_para_nao_apagar(m: MensagemWhatsApp) -> str:
    """Por que esta mensagem não pode ser apagada para todos ("" = pode): como no WhatsApp, só a que saiu e chegou ao
    WhatsApp, até 2 dias depois do envio."""
    if m.apagada_em:
        return "Esta mensagem já foi apagada."
    if m.direcao != "saida":
        return "Só dá para apagar as mensagens que saíram por este número (como no WhatsApp)."
    if m.status != "enviada" or not m.id_wl:
        return "Esta mensagem não chegou a sair: não há o que apagar no WhatsApp do contato."
    if m.criado_em < agora() - timedelta(hours=HORAS_PARA_APAGAR):
        return "O WhatsApp só deixa apagar para todos até 2 dias depois do envio."
    return ""


def mensagem_apagada(db: Session, comando: ComandoWhatsApp) -> None:
    """O WhatsApp Leads apagou a mensagem para todos (o comando "apagar_mensagem" voltou sem erro, /api/ponte/retorno):
    a cópia daqui passa a mostrar "Você apagou esta mensagem", com quem pediu."""
    try:
        dados = json.loads(comando.dados or "{}")
        id_wl = int(dados.get("id_wl") or 0) if isinstance(dados, dict) else 0
    except (TypeError, ValueError):
        return
    m = db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.id_wl == id_wl)).scalars().first() if id_wl else None
    if m is not None and m.apagada_em is None:
        m.apagada_em, m.apagada_por_id = agora(), comando.usuario_id
        _mudou(db)  # a lista também mostra (se era a última mensagem da conversa)


def _marcar_lidas(db: Session, da_conversa: tuple) -> None:
    """As mensagens recebidas da conversa ficam lidas (a lista tira o número de não lidas)."""
    feitas = db.execute(update(MensagemWhatsApp).where(*da_conversa, MensagemWhatsApp.direcao == "entrada",
                                                       MensagemWhatsApp.lida.is_(False)).values(lida=True)
                        .execution_options(synchronize_session=False)).rowcount
    if feitas:
        _mudou(db)  # as listas abertas (desta e de outras pessoas) se atualizam
    db.commit()


@rotas.get("/conversas")
def tela_conversas(request: Request, telefone: str = "", numero: str = "",
                   usuario: Usuario = Depends(exige("conversas.ver")), db: Session = Depends(obter_db)):
    _tela_vista(db)
    base = whatsapp_leads.status()
    numeros = [{"id": c.id, "nome": c.nome, "minha": c.dono_id == usuario.id,
                "conectado": bool(conexoes.situacao(c.id, base).get("conectado"))} for c in conexoes.acessiveis(db, usuario)]
    chave = _chave(telefone) if telefone else ""
    ids = [n["id"] for n in numeros]
    # Sem o número (o "Ver conversa" das Oportunidades) ou com um que a pessoa não vê: abre pelo número em que a
    # conversa com o contato está (a mensagem mais recente); sem conversa, pelo número padrão
    inicial = numero if numero in ids else (_numero_da_conversa(db, chave, ids) or _numero_padrao(db, usuario))
    db.commit()
    return tela(request, "conversas.html", {"telefone_inicial": chave, "ponte": config.WHATSAPP_PONTE,
                                            "numeros": numeros, "numero_inicial": inicial})


@rotas.get("/conversas/api/lista")
def lista(busca: str = "", numero: str = "", marca: str = "", nao_lidas: str = "",
          usuario: Usuario = Depends(exige("conversas.ver")), db: Session = Depends(obter_db)):
    _tela_vista(db)
    numeros = _numeros(db, usuario, numero)
    situacao = _situacao(db, numero or _numero_padrao(db, usuario))
    so_nao_lidas = nao_lidas == "1"  # filtro "Não lidas", como no WhatsApp (23/11/2026)
    # Nenhuma mensagem nova (de nenhum número), nada lido e nenhum nome mudado desde a última vez: a lista é a mesma e
    # não é refeita (é a consulta mais pesada da tela). O maior id vem do índice principal, sem passar pelas mensagens.
    ultima = db.execute(select(func.max(MensagemWhatsApp.id)).execution_options(sem_filtro_de_ar=True)).scalar()
    atual = _marca(ultima, ler_config(db, VERSAO), sorted(numeros), busca.strip(), numero, so_nao_lidas)
    if marca and marca == atual:
        return JSONResponse({"igual": True, "marca": atual, "situacao": situacao})
    nomes_numeros = {c.id: c.nome for c in conexoes.todas(db)}
    nao_lidas_da_conversa = func.sum(((MensagemWhatsApp.direcao == "entrada") & MensagemWhatsApp.lida.is_(False))
                                     .cast(MensagemWhatsApp.id.type))
    # Uma linha por contato e número, a conversa mais recente primeiro (pela data da mensagem)
    consulta = (select(MensagemWhatsApp.conexao, MensagemWhatsApp.telefone,
                       func.max(MensagemWhatsApp.criado_em).label("ultima_em"), nao_lidas_da_conversa.label("nao_lidas"))
                .where(MensagemWhatsApp.conexao.in_(numeros or [""]))
                .group_by(MensagemWhatsApp.conexao, MensagemWhatsApp.telefone)
                .order_by(func.max(MensagemWhatsApp.criado_em).desc()).limit(200))
    if so_nao_lidas:  # só as conversas com recebida não lida (pelo índice das não lidas, sem passar por todas)
        com_nao_lidas = select(MensagemWhatsApp.telefone).where(
            MensagemWhatsApp.conexao.in_(numeros or [""]), MensagemWhatsApp.direcao == "entrada",
            MensagemWhatsApp.lida == False)  # noqa: E712
        consulta = consulta.where(MensagemWhatsApp.telefone.in_(com_nao_lidas)).having(nao_lidas_da_conversa > 0)
    termo = busca.strip()
    if termo:
        filtros = [MensagemWhatsApp.nome.ilike(f"%{termo}%"),
                   MensagemWhatsApp.telefone.in_(select(ContatoWhatsApp.telefone)
                                                 .where(ContatoWhatsApp.nome.ilike(f"%{termo}%")))]
        if util.so_digitos(termo):
            filtros.append(MensagemWhatsApp.telefone.like(f"%{util.so_digitos(termo)}%"))
            if util.com_nono_digito(termo):  # número completo digitado sem o 9: acha a conversa (guardada com o 9)
                filtros.append(MensagemWhatsApp.telefone == util.com_nono_digito(termo))
        consulta = consulta.where(or_(*filtros))
    resultado = []
    escolhidos = _nomes_escolhidos(db)
    linhas = db.execute(consulta).all()
    # A última mensagem e o último nome de todas as conversas da lista em 2 consultas (antes eram 1 ou 2 por conversa,
    # a cada 4 s com a tela aberta: 400 mil consultas em 3 semanas, 14/11/2026)
    ultimas = _ultimas_mensagens(db, {c for c, *_ in linhas}, {t for _, t, *_ in linhas})
    nomes = _ultimos_nomes(db, {t for _, t, *_ in linhas})
    for conexao, telefone, _ultima_em, nao_lidas in linhas:
        m = ultimas.get((conexao, telefone))
        if m is None:
            continue
        nome = escolhidos.get(m.telefone) or m.nome or nomes.get(m.telefone, "")
        resultado.append({"telefone": m.telefone, "telefone_formatado": util.formatar_telefone(m.telefone),
                          "numero": conexao, "numero_nome": nomes_numeros.get(conexao, conexao),
                          "nome": nome, "ultima": APAGADA if m.apagada_em else m.texto[:120],
                          "ultima_direcao": m.direcao, "ultima_apagada": bool(m.apagada_em),
                          "quando": _quando_curto(m.criado_em), "nao_lidas": int(nao_lidas or 0)})
    return JSONResponse({"conversas": resultado, "situacao": situacao, "varios_numeros": len(_numeros(db, usuario)) > 1,
                         "marca": atual,
                         # o número vermelho do menu (23/11/2026): abriu a conversa, ele baixa sem recarregar a tela
                         "nao_lidas_total": conexoes.mensagens_nao_lidas(db, usuario)})


def _ultimas_mensagens(db: Session, conexoes_: set, telefones: set) -> dict:
    """{(conexão, telefone): a última mensagem} numa consulta só, só com o que a lista mostra (texto até 120)."""
    if not telefones:
        return {}
    ordem = func.row_number().over(partition_by=(MensagemWhatsApp.conexao, MensagemWhatsApp.telefone),
                                   order_by=(MensagemWhatsApp.criado_em.desc(), MensagemWhatsApp.id.desc())).label("n")
    sub = (select(MensagemWhatsApp.conexao, MensagemWhatsApp.telefone, MensagemWhatsApp.nome,
                  func.substr(MensagemWhatsApp.texto, 1, 120).label("texto"), MensagemWhatsApp.direcao,
                  MensagemWhatsApp.criado_em, MensagemWhatsApp.apagada_em, ordem)
           .where(MensagemWhatsApp.conexao.in_(conexoes_), MensagemWhatsApp.telefone.in_(telefones)).subquery())
    return {(r.conexao, r.telefone): r for r in db.execute(select(sub).where(sub.c.n == 1)).all()}


def _ultimos_nomes(db: Session, telefones: set) -> dict:
    """{telefone: o último nome que veio do WhatsApp}, numa consulta só."""
    if not telefones:
        return {}
    ordem = func.row_number().over(partition_by=MensagemWhatsApp.telefone,
                                   order_by=MensagemWhatsApp.id.desc()).label("n")
    sub = (select(MensagemWhatsApp.telefone, MensagemWhatsApp.nome, ordem)
           .where(MensagemWhatsApp.telefone.in_(telefones), MensagemWhatsApp.nome != "").subquery())
    return {t: n for t, n, _ in db.execute(select(sub).where(sub.c.n == 1)).all()}


def _quando_curto(momento) -> str:
    """Como no WhatsApp: hora (hoje), "Ontem" ou a data."""
    hoje = agora().date()
    if momento.date() == hoje:
        return momento.strftime("%H:%M")
    if (hoje - momento.date()).days == 1:
        return "Ontem"
    return momento.strftime("%d/%m/%y")


def _situacao(db: Session, numero: str) -> dict:
    s = conexoes.situacao(numero) if numero else {"disponivel": True, "conectado": False}
    return {"disponivel": bool(s.get("disponivel")), "conectado": bool(s.get("conectado")), "erro": s.get("erro", ""),
            "sem_numero": not numero}


@rotas.get("/conversas/api/conversa/{telefone}")
def conversa(telefone: str, numero: str = "", marca: str = "", usuario: Usuario = Depends(exige("conversas.ver")),
             db: Session = Depends(obter_db)):
    _tela_vista(db)
    chave = _chave(telefone)
    numeros = _numeros(db, usuario)
    # sem número (ou com um que a pessoa não vê): o da conversa com o contato, senão o padrão
    numero = numero if numero in numeros else (_numero_da_conversa(db, chave, numeros) or _numero_padrao(db, usuario))
    if not numero:
        return JSONResponse({"erro": "Você ainda não tem número de WhatsApp. Conecte em WhatsApp > Meu WhatsApp."},
                            status_code=403)
    da_conversa = (MensagemWhatsApp.telefone == chave, MensagemWhatsApp.conexao == numero)
    # Primeiro só o que muda: as 30 mensagens mais novas (id e status, sem o texto) e o que está saindo agora. A conversa
    # inteira (até 300 mensagens, com o texto) só vai quando algo mudou: numa conversa longa eram ~60 KB a cada 5 s.
    recentes = db.execute(select(MensagemWhatsApp.id, MensagemWhatsApp.status, MensagemWhatsApp.direcao,
                                 MensagemWhatsApp.lida, MensagemWhatsApp.entregue_em, MensagemWhatsApp.visualizada_em,
                                 MensagemWhatsApp.apagada_em, MensagemWhatsApp.anexo)
                          .where(*da_conversa).order_by(MensagemWhatsApp.id.desc()).limit(30)).all()
    pendentes = [p for p in db.execute(select(PonteWhatsApp).where(
        PonteWhatsApp.manual.is_(True), PonteWhatsApp.conexao == numero,
        PonteWhatsApp.status.in_(["aguardando", "retirada"])).order_by(PonteWhatsApp.id)).scalars().all()
        if _chave(p.telefone) == chave]
    # o contato recebeu ou leu (✓✓), a mensagem foi apagada ou a foto/o áudio chegou: também muda a marca, e a conversa
    # aberta se redesenha
    atual = _marca(chave, numero, [(r.id, r.status, bool(r.entregue_em), bool(r.visualizada_em), bool(r.apagada_em),
                                    r.anexo) for r in recentes], [p.id for p in pendentes])
    igual = bool(marca) and marca == atual
    if not igual or any(r.direcao == "entrada" and not r.lida for r in recentes):
        _marcar_lidas(db, da_conversa)
    if igual:
        return JSONResponse({"igual": True, "marca": atual, "situacao": _situacao(db, numero)})
    mensagens = list(db.execute(select(MensagemWhatsApp.id, MensagemWhatsApp.id_wl, MensagemWhatsApp.direcao,
                                       MensagemWhatsApp.texto, MensagemWhatsApp.status, MensagemWhatsApp.erro,
                                       MensagemWhatsApp.origem, MensagemWhatsApp.nome, MensagemWhatsApp.criado_em,
                                       MensagemWhatsApp.entregue_em, MensagemWhatsApp.visualizada_em,
                                       MensagemWhatsApp.apagada_em, MensagemWhatsApp.apagada_por_id,
                                       MensagemWhatsApp.anexo).where(*da_conversa)
                                .order_by(MensagemWhatsApp.criado_em.desc(), MensagemWhatsApp.id.desc())
                                .limit(300)).all())[::-1]
    lead = sdr.lead_pelo_telefone(db, chave)
    escolhido = db.get(ContatoWhatsApp, chave)
    nome = (escolhido.nome if escolhido and escolhido.nome else "") \
        or next((m.nome for m in reversed(mensagens) if m.nome), "") or (lead.responsavel or lead.empresa if lead else "")
    # "Apagar para todos" (24/11/2026): quem responde pelas Conversas, nas mensagens que ainda dá para apagar
    pode_apagar = autorizacao.pode(usuario, "conversas.enviar") and config.WHATSAPP_PONTE
    ids_apagaram = {m.apagada_por_id for m in mensagens if m.apagada_por_id}
    quem_apagou = dict(db.execute(select(Usuario.id, Usuario.nome).where(Usuario.id.in_(ids_apagaram))).all()) \
        if ids_apagaram else {}
    return JSONResponse({
        "telefone": chave, "telefone_formatado": util.formatar_telefone(chave), "nome": nome, "numero": numero,
        "mensagens": [{"id": m.id, "direcao": m.direcao, "texto": m.texto, "status": m.status, "erro": m.erro,
                       "origem": m.origem, "quando": m.criado_em.strftime("%d/%m %H:%M"),
                       "dia": m.criado_em.strftime("%Y-%m-%d"), "hora": m.criado_em.strftime("%H:%M"),
                       # "Dados da mensagem" (23/11/2026): quando o contato recebeu e quando leu
                       "entregue": util.quando_extenso(m.entregue_em), "lida": util.quando_extenso(m.visualizada_em),
                       "apagada": util.quando_extenso(m.apagada_em),
                       "apagada_por": quem_apagou.get(m.apagada_por_id, ""),
                       # a foto (ou figurinha) e o áudio dentro da mensagem (24/11/2026)
                       "anexo": m.anexo or "", "anexo_url": f"/conversas/anexo/{m.id}" if m.anexo else "",
                       "pode_apagar": bool(pode_apagar) and not _motivo_para_nao_apagar(m)}
                      for m in mensagens],
        "enviando": [{"texto": p.texto, "quando": p.criado_em.strftime("%d/%m %H:%M"),
                      "dia": p.criado_em.strftime("%Y-%m-%d"), "hora": p.criado_em.strftime("%H:%M")} for p in pendentes],
        "lead": {"id": lead.id, "empresa": lead.empresa, "status": lead.status, "opt_out": lead.opt_out}
        if lead and pode_ver(usuario, lead) else None,
        # o mesmo contato também conversou por outro número da pessoa: a tela avisa e abre a de lá (24/11/2026)
        "outros_numeros": _outros_numeros(db, chave, numeros, numero),
        "situacao": _situacao(db, numero),
        "marca": atual,
    })


@rotas.post("/conversas/api/enviar", dependencies=[Depends(verificar_csrf)])
async def enviar(request: Request, usuario: Usuario = Depends(exige("conversas.enviar")), db: Session = Depends(obter_db)):
    dados = await request.json()
    texto = str(dados.get("texto", "")).strip()
    chave = util.com_nono_digito(str(dados.get("telefone", "")))
    if not chave:
        return JSONResponse({"erro": "Digite um celular com DDD, por exemplo (81) 99999-0000."}, status_code=400)
    if not texto:
        return JSONResponse({"erro": "Escreva a mensagem."}, status_code=400)
    if not config.WHATSAPP_PONTE:
        return JSONResponse({"erro": "Neste computador, use a tela Conversas do próprio WhatsApp Leads."}, status_code=400)
    lead = sdr.lead_pelo_telefone(db, chave)
    if lead and lead.opt_out:
        return JSONResponse({"erro": "Este contato pediu para não receber mensagens (opt-out)."}, status_code=409)
    nome = str(dados.get("nome", "")).strip()[:200] or (lead.responsavel or lead.empresa if lead else "")
    numero = str(dados.get("numero") or "") or _numero_padrao(db, usuario)
    if numero not in _numeros(db, usuario):
        return JSONResponse({"erro": "Você ainda não tem número de WhatsApp. Conecte em WhatsApp > Meu WhatsApp "
                                     "(ou peça ao administrador para compartilhar um número)."}, status_code=403)
    try:
        whatsapp_leads.enviar("55" + chave, nome, texto, db=db, manual=True, usuario_id=usuario.id, conexao=numero)
    except whatsapp_leads.ErroWhatsAppLeads as erro:
        return JSONResponse({"erro": str(erro)}, status_code=409)
    if lead:
        historico(db, lead.id, "whatsapp", f"Mensagem enviada pela tela Conversas: {texto[:300]}", usuario, canal="whatsapp")
    if str(dados.get("nome", "")).strip() and not db.get(ContatoWhatsApp, chave):
        _salvar_nome(db, chave, str(dados["nome"]), usuario)  # nome digitado na "Nova mensagem" (se for desta AR)
    db.commit()
    aviso = "" if conexoes.situacao(numero).get("conectado") else "O celular está desconectado: a mensagem sai quando conectar."
    return {"ok": True, "telefone": chave, "numero": numero, "aviso": aviso}


@rotas.post("/conversas/api/nome", dependencies=[Depends(verificar_csrf)])
async def editar_nome(request: Request, usuario: Usuario = Depends(exige("conversas.enviar")), db: Session = Depends(obter_db)):
    """Editar o nome do contato (vale na tela Conversas e no WhatsApp Leads)."""
    dados = await request.json()
    chave = _chave(str(dados.get("telefone", "")))
    nome = str(dados.get("nome", "")).strip()
    if not chave:
        return JSONResponse({"erro": "Contato sem telefone."}, status_code=400)
    if not nome:
        return JSONResponse({"erro": "Digite o nome do contato."}, status_code=400)
    if not _salvar_nome(db, chave, nome, usuario):
        return JSONResponse({"erro": "Este telefone já tem um nome guardado por outra AR."}, status_code=409)
    db.commit()
    return {"ok": True, "nome": nome[:200]}


EXTENSOES_DO_ANEXO = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
                      "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/aac": "aac"}


def _em_partes(request: Request, dados: bytes, tipo: str, cabecalhos: dict) -> Response:
    """O arquivo inteiro ou só o pedaço pedido (cabeçalho Range): o Safari do iPhone pede o áudio aos pedaços e não
    toca se a resposta vier sempre inteira."""
    total = len(dados)
    faixa = re.fullmatch(r"bytes=(\d*)-(\d*)", (request.headers.get("range") or "").strip())
    if not faixa or not (faixa.group(1) or faixa.group(2)):
        return Response(dados, media_type=tipo, headers=cabecalhos)
    if faixa.group(1):
        inicio = int(faixa.group(1))
        fim = min(int(faixa.group(2)), total - 1) if faixa.group(2) else total - 1
    else:  # "bytes=-500": os últimos 500
        inicio, fim = max(total - int(faixa.group(2)), 0), total - 1
    if inicio >= total or inicio > fim:
        return Response(status_code=416, headers={**cabecalhos, "Content-Range": f"bytes */{total}"})
    return Response(dados[inicio:fim + 1], status_code=206, media_type=tipo,
                    headers={**cabecalhos, "Content-Range": f"bytes {inicio}-{fim}/{total}"})


@rotas.get("/conversas/anexo/{mid}")
def anexo_da_mensagem(mid: int, request: Request, usuario: Usuario = Depends(exige("conversas.ver")),
                      db: Session = Depends(obter_db)):
    """A foto (ou figurinha) e o áudio da mensagem (24/11/2026): dentro da conversa e, a foto, inteira numa aba nova
    com um clique. Só nos números cujas conversas a pessoa vê (como a conversa)."""
    m = db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.id == mid)).scalars().first()
    if m is None or not m.anexo or m.conexao not in _numeros(db, usuario):
        return JSONResponse({"erro": "Arquivo não encontrado."}, status_code=404)
    anexo = db.execute(select(AnexoWhatsApp).where(AnexoWhatsApp.id_wl == m.id_wl)
                       .options(undefer(AnexoWhatsApp.dados))).scalars().first()
    if anexo is None or not anexo.dados:
        return JSONResponse({"erro": "Arquivo não encontrado."}, status_code=404)
    nome = f"whatsapp-{mid}.{EXTENSOES_DO_ANEXO.get(anexo.tipo, 'bin')}"
    return _em_partes(request, anexo.dados, anexo.tipo or "application/octet-stream", {
        "Cache-Control": "private, max-age=86400", "Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="{nome}"'})


@rotas.post("/conversas/api/mensagem/{mid}/apagar", dependencies=[Depends(verificar_csrf)])
def apagar_para_todos(mid: int, request: Request, usuario: Usuario = Depends(exige("conversas.enviar")),
                      db: Session = Depends(obter_db)):
    """"Apagar para todos", como no WhatsApp (pedido da Maria em 24/11/2026: "suba a opção de apagar mensagem"): a
    mensagem que saiu some do WhatsApp do contato. Pode quem responde pelas Conversas, nos números que vê (os mesmos do
    envio). O pedido vai para o WhatsApp Leads pela ponte; a tela acompanha em /conversas/api/apagar/{pedido}."""
    m = db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.id == mid)).scalars().first()
    if m is None or m.conexao not in _numeros(db, usuario):
        return JSONResponse({"erro": "Mensagem não encontrada."}, status_code=404)
    motivo = _motivo_para_nao_apagar(m)
    if motivo:
        return JSONResponse({"erro": motivo}, status_code=409)
    if not config.WHATSAPP_PONTE:
        return JSONResponse({"erro": "Neste computador, use a tela Conversas do próprio WhatsApp Leads."}, status_code=400)
    pedido = ComandoWhatsApp(acao="apagar_mensagem", usuario_id=usuario.id,
                             dados=json.dumps({"conexao": m.conexao, "id_wl": m.id_wl}))
    db.add(pedido)
    db.flush()
    registrar_log(db, usuario, "apagou_mensagem_whatsapp", "mensagem_whatsapp", m.id,
                  f"Apagar para todos (Conversas): mensagem de {m.criado_em:%d/%m %H:%M} para {m.telefone}, "
                  f"pelo número {m.conexao}", request, modulo="Conversas")
    db.commit()
    return {"ok": True, "pedido": pedido.id}


@rotas.get("/conversas/api/apagar/{pedido}")
def situacao_do_apagar(pedido: int, usuario: Usuario = Depends(exige("conversas.enviar")),
                       db: Session = Depends(obter_db)):
    """Como está o "Apagar para todos" que a pessoa pediu: esperando o WhatsApp Leads, apagada ou erro (com o motivo)."""
    c = db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.id == pedido)).scalars().first()
    if c is None or c.acao != "apagar_mensagem" or c.usuario_id != usuario.id:
        return JSONResponse({"erro": "Pedido não encontrado."}, status_code=404)
    return {"situacao": {"feito": "apagada", "erro": "erro"}.get(c.status, "esperando"), "erro": c.erro or ""}
