"""Tela Minha fila: os disparos da pessoa num lugar só. O que está na fila do WhatsApp agora, o que ainda vai sair
(e por que ainda não saiu), o que saiu ou falhou e o registro (log) dos disparos. Cada um vê os próprios; admin e
gestor podem ver a fila de outra pessoa ou da equipe toda."""

from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .. import autorizacao, campanhas, config, mensagens, sdr, util
from ..banco import agora, ler_config, obter_db
from ..modelos import Campanha, Lead, LogAuditoria, Mensagem, Tarefa, Usuario
from ..seguranca import exige, registrar_log, ve_tudo, verificar_csrf
from ..web import avisar, tela, voltar
from .envios import STATUS_ENVIO

rotas = APIRouter()


def _numero_da_pessoa(db, usuario: Usuario) -> str:
    """O WhatsApp da pessoa (o limite diário é de cada número); sem número próprio, o principal da MS."""
    from .. import conexoes

    proprio = conexoes.minha(db, usuario)
    return proprio.id if proprio else conexoes.PRINCIPAL


ABAS = ("proximos", "fila", "historico", "registro")
PERIODOS = [("todos", "Todos"), ("ate_hoje", "Hoje e atrasados"), ("atrasados", "Atrasados"), ("hoje", "Hoje"),
            ("amanha", "Amanhã"), ("proximos", "Próximos dias")]
# Situação de cada toque que ainda não saiu: (rótulo curto do filtro, cor do selo). Nesta ordem na tela.
SITUACOES = {
    "clique": ("Aguardando seu clique", "selo-alerta"),
    "sem_whatsapp": ("WhatsApp em branco", "selo-erro"),
    "sem_email": ("Sem e-mail", "selo-erro"),
    "email_manual": ("E-mail só pelo Disparar", "selo-alerta"),
    "horario": ("Fora do horário", "selo-baixo"),
    "programado": ("Programado", "selo-azul"),
    "rodada": ("Sai na próxima rodada", "selo-ok"),
    "sozinho": ("Sai sozinho", "selo-ok"),
    "parado": ("Automação parada", "selo-baixo"),
}
DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
LIMITE_PENDENTES = 600  # toques olhados por vez (atrasados primeiro)
LIMITE_MOSTRAR = 200    # toques mostrados de uma vez (a página não pode ficar pesada; os filtros acham o resto)


def _situacao(t: Tarefa, hoje: date, no_horario: bool, conversaram: set[int], email_auto: bool,
              whats_auto: bool, automaticas: set[int] = frozenset(),
              com_anterior: set[int] = frozenset(), recentes: set[int] = frozenset(),
              espera_whatsapp: set[int] = frozenset()) -> tuple[str, str]:
    """(situação, explicação) de por que o toque ainda não saiu, em linguagem simples. O que pede uma ação da pessoa
    (WhatsApp ou e-mail em branco) aparece também nos toques dos próximos dias, para dar tempo de corrigir.
    automaticas = campanhas cujo WhatsApp sai sozinho depois da aprovação (campanhas.campanhas_que_saem_sozinhas);
    com_anterior = toques que esperam o toque anterior da mesma empresa sair (campanhas.toques_com_anterior_pendente);
    recentes = leads que receberam WhatsApp há menos de 20 h (campanhas.leads_com_whatsapp_recente);
    espera_whatsapp = e-mails de Empresas novas que esperam o WhatsApp da empresa sair primeiro
    (campanhas.emails_que_esperam_whatsapp)."""
    lead = t.lead
    if not lead or not sdr.automacao_ativa(lead):
        return "parado", "Automação parada para este lead (respondeu, opt-out ou está com alguém)"
    if t.canal == "email" and not lead.email:
        return "sem_email", "Sem e-mail cadastrado"
    if t.canal == "whatsapp" and not (lead.whatsapp or "").strip():
        return "sem_whatsapp", "WhatsApp em branco: cadastre o número na ficha da empresa para a mensagem sair"
    da_campanha_automatica = campanhas.toque_sai_sozinho(t, automaticas, hoje)
    sozinho = t.canal == "whatsapp" and whats_auto and (
        da_campanha_automatica or bool(lead.consentimento) or lead.id in conversaram)
    espera_anterior = t.canal == "whatsapp" and t.id in com_anterior
    if t.data > hoje:
        quando = f"Programado para {t.data:%d/%m} às {t.hora or '09:00'}"
        if t.canal == "whatsapp":
            quando += (" (espera o toque anterior sair)" if espera_anterior
                       else " (sai sozinho)" if sozinho else " (vai esperar o seu clique)")
        elif t.id in espera_whatsapp:
            quando += " (depois do WhatsApp desta empresa)"
        return "programado", quando
    if t.canal == "email":
        if not email_auto:
            return "email_manual", "Envio automático de e-mail desligado: use Disparar campanha e-mail"
        if not no_horario:
            return "horario", "Aguardando o horário de envio"
        if t.data == hoje and (t.hora or "00:00") > agora().strftime("%H:%M"):
            return "programado", f"Programado para hoje às {t.hora}"
        if t.id in espera_whatsapp:
            return "programado", "Sai sozinho depois do WhatsApp desta empresa (o WhatsApp tem prioridade)"
        return "rodada", "Sai na próxima rodada da fila (a cada minuto)"
    if espera_anterior:
        return "clique", "Aguardando: o toque anterior desta empresa ainda não saiu (envie o anterior primeiro)"
    if sozinho:
        if not no_horario:
            return "horario", "Aguardando o horário de envio"
        if t.data == hoje and (t.hora or "00:00") > agora().strftime("%H:%M"):
            return "programado", f"Programado para hoje às {t.hora} (sai sozinho)"
        if lead.id in recentes:
            return "programado", ("Sai sozinho depois: a empresa recebeu WhatsApp há menos de "
                                  f"{campanhas.HORAS_MINIMAS_FILA_AUTOMATICA} h (nunca dois no mesmo dia)")
        if da_campanha_automatica:
            return "sozinho", f"Sai sozinho: {campanhas.motivo_automatico(automaticas, t.campanha_id)} (um por vez, com pausas)"
        return "sozinho", "Sai sozinho (contato já conversou com a MS)"
    if t.campanha_id in automaticas:
        return "clique", (f"Aguardando seu clique: atrasado mais de {campanhas.DIAS_ATRASO_AUTOMATICO} dias, "
                          "não sai sozinho")
    return "clique", "Aguardando seu clique (WhatsApp de hoje ou Disparar campanha WhatsApp)"


def _no_periodo(p: dict, periodo: str, hoje: date) -> bool:
    d = p["t"].data
    if periodo == "ate_hoje":
        return d <= hoje
    if periodo == "atrasados":
        return d < hoje
    if periodo == "hoje":
        return d == hoje
    if periodo == "amanha":
        return d == hoje + timedelta(days=1)
    if periodo == "proximos":
        return d > hoje
    return True


def _agrupar_por_dia(itens: list[dict], hoje: date) -> list[dict]:
    """Atrasados num grupo só; depois um grupo por dia (Hoje, Amanhã, Quinta-feira...), na ordem do envio."""
    grupos = []
    atrasados = [p for p in itens if p["atrasado"]]
    if atrasados:
        grupos.append({"titulo": "Atrasados", "detalhe": "de dias anteriores", "atrasado": True, "itens": atrasados})
    por_dia: dict[date, list] = {}
    for p in itens:
        if not p["atrasado"]:
            por_dia.setdefault(p["t"].data, []).append(p)
    for d in sorted(por_dia):
        semana = DIAS_SEMANA[d.weekday()]
        if d == hoje:
            titulo, detalhe = "Hoje", f"{semana}, {d:%d/%m}"
        elif d == hoje + timedelta(days=1):
            titulo, detalhe = "Amanhã", f"{semana}, {d:%d/%m}"
        else:
            titulo, detalhe = semana.capitalize(), f"{d:%d/%m}"
        grupos.append({"titulo": titulo, "detalhe": detalhe, "atrasado": False, "itens": por_dia[d]})
    return grupos


@rotas.get("/fila")
def minha_fila(request: Request, de: str = "", canal: str = "", aba: str = "proximos", periodo: str = "todos",
               situacao: str = "", campanha: str = "", busca: str = "",
               usuario: Usuario = Depends(exige("fila.ver")), db: Session = Depends(obter_db)):
    hoje = date.today()
    aba = aba if aba in ABAS else "proximos"
    periodo = periodo if periodo in dict(PERIODOS) else "todos"
    situacao = situacao if situacao in SITUACOES else ""
    alvo_id = usuario.id
    if ve_tudo(usuario, "fila.ver") and de:
        alvo_id = None if de == "todos" else (util.para_int(de) or usuario.id)

    def do_alvo_tarefa(q):
        if alvo_id is None:
            return q
        return q.where(or_(Campanha.usuario_id == alvo_id, Lead.vendedor_id == alvo_id))

    def do_alvo_mensagem(q):
        if alvo_id is None:
            return q
        return q.where(or_(Mensagem.usuario_id == alvo_id, Lead.vendedor_id == alvo_id, Campanha.usuario_id == alvo_id))

    canais = [canal] if canal in ("email", "whatsapp") else ["email", "whatsapp"]

    # 1) Pendentes: toques das campanhas ativas que ainda não saíram (atrasados, hoje e próximos 7 dias)
    pend_q = (select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id).outerjoin(Lead, Tarefa.lead_id == Lead.id)
              .where(Tarefa.status == "pendente", Campanha.status == "ativa",
                     # toque do canal, ou de outro canal mas com a versão reserva deste canal pronta
                     or_(Tarefa.canal.in_(canais),
                         *([Tarefa.mensagem_whatsapp != ""] if "whatsapp" in canais else []),
                         *([Tarefa.mensagem_email != ""] if "email" in canais else [])),
                     Tarefa.canal.in_(["email", "whatsapp"]),
                     Tarefa.data <= hoje + timedelta(days=7)))
    tarefas = db.execute(do_alvo_tarefa(pend_q).options(selectinload(Tarefa.lead))  # o lead junto: sem 1 consulta por toque
                         .order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(LIMITE_PENDENTES)).scalars().all()
    no_horario = mensagens.dentro_do_horario(db)
    conversaram = campanhas.leads_que_conversaram(db, [t.lead_id for t in tarefas if t.canal == "whatsapp"])
    email_auto = ler_config(db, "enviar_email_automatico") == "1"
    whats_auto = ler_config(db, "enviar_whatsapp_automatico") == "1"
    automaticas = campanhas.campanhas_que_saem_sozinhas(db)
    com_anterior = campanhas.toques_com_anterior_pendente(db, tarefas)
    recentes = campanhas.leads_com_whatsapp_recente(db, [t.lead_id for t in tarefas if t.canal == "whatsapp"])
    espera_whatsapp = campanhas.emails_que_esperam_whatsapp(db, tarefas)
    pendentes = []
    for t in tarefas:
        chave, motivo = _situacao(t, hoje, no_horario, conversaram, email_auto, whats_auto, automaticas, com_anterior,
                                  recentes, espera_whatsapp)
        rotulo, classe = SITUACOES[chave]
        pendentes.append({"t": t, "situacao": chave, "rotulo": rotulo, "classe": classe, "motivo": motivo,
                          "atrasado": t.data < hoje, "dias": (hoje - t.data).days})

    # Filtros da aba Próximos envios: campanha e busca valem para tudo; o período e a situação mostram quantos há
    # em cada opção, já com os outros filtros aplicados
    nomes_camp = {c.id: c.nome for c in db.execute(select(Campanha)).scalars()}
    camp_id = util.para_int(campanha) or 0
    termo = util.chave_texto(busca)
    base = [p for p in pendentes if (not camp_id or p["t"].campanha_id == camp_id)
            and (not termo or termo in util.chave_texto(p["t"].lead.empresa if p["t"].lead else ""))]
    na_situacao = [p for p in base if not situacao or p["situacao"] == situacao]
    contagem_periodo = {chave: sum(1 for p in na_situacao if _no_periodo(p, chave, hoje)) for chave, _ in PERIODOS}
    no_periodo = [p for p in base if _no_periodo(p, periodo, hoje)]
    contagem_situacao = {chave: sum(1 for p in no_periodo if p["situacao"] == chave) for chave in SITUACOES}
    filtrados = [p for p in no_periodo if not situacao or p["situacao"] == situacao]
    por_campanha: dict[int, int] = {}
    for p in pendentes:
        por_campanha[p["t"].campanha_id] = por_campanha.get(p["t"].campanha_id, 0) + 1
    opcoes_campanha = sorted(((cid, nomes_camp.get(cid, f"Campanha {cid}"), n) for cid, n in por_campanha.items()),
                             key=lambda o: o[1].lower())
    atuais = {"de": de, "canal": canal, "aba": aba, "periodo": periodo, "situacao": situacao,
              "campanha": str(camp_id or ""), "busca": busca.strip()}

    def url_fila(**mudancas) -> str:
        """Endereço desta tela com os filtros atuais e as mudanças pedidas (valor padrão fica fora do endereço)."""
        params = {k: v for k, v in {**atuais, **mudancas}.items()
                  if v and not (k == "aba" and v == "proximos") and not (k == "periodo" and v == "todos")}
        return "/fila" + ("?" + urlencode(params) if params else "")

    # 2) Na fila do WhatsApp agora e 3) histórico (últimos 7 dias): saiu, falhou, foi lida...
    desde = agora().replace(hour=0, minute=0, second=0) - timedelta(days=7)
    msg_q = (select(Mensagem).outerjoin(Lead, Mensagem.lead_id == Lead.id)
             .outerjoin(Campanha, Mensagem.campanha_id == Campanha.id)
             .where(Mensagem.canal.in_(canais), Mensagem.status != "recebida", Mensagem.criado_em >= desde))
    envios = db.execute(do_alvo_mensagem(msg_q).order_by(Mensagem.criado_em.desc(), Mensagem.id.desc())
                        .limit(300)).scalars().all()
    na_fila = [m for m in envios if m.status == "na_fila"]
    historico = [m for m in envios if m.status != "na_fila"]

    # 4) Log dos disparos e testes feitos pela pessoa
    log_q = select(LogAuditoria).where(or_(LogAuditoria.acao.like("disparou_campanha%"),
                                           LogAuditoria.acao == "testou_campanha"),
                                       LogAuditoria.criado_em >= agora() - timedelta(days=30))
    if alvo_id is not None:
        log_q = log_q.where(LogAuditoria.usuario_id == alvo_id)
    logs = db.execute(log_q.order_by(LogAuditoria.criado_em.desc()).limit(50)).scalars().all()

    inicio_hoje = agora().replace(hour=0, minute=0, second=0)
    resumo = {
        "hoje": sum(1 for p in pendentes if p["t"].data <= hoje),
        "atrasados": sum(1 for p in pendentes if p["atrasado"]),
        "na_fila": len(na_fila),
        "enviadas_hoje": sum(1 for m in historico if m.criado_em >= inicio_hoje and m.status != "falhou"),
        "falharam": sum(1 for m in historico if m.status == "falhou"),
        "email_hoje": mensagens.enviadas_hoje(db, "email"), "email_limite": mensagens.limite_diario(db, "email"),
        "whats_hoje": mensagens.enviadas_hoje(db, "whatsapp", _numero_da_pessoa(db, usuario)),
        "whats_limite": mensagens.limite_diario(db, "whatsapp"),
    }
    ids_t = {m.tarefa_id for m in historico if m.tarefa_id}
    tarefas_por_id = {t.id: t for t in db.execute(select(Tarefa).where(Tarefa.id.in_(ids_t))).scalars()} if ids_t else {}
    ids = {m.lead_id for m in envios if m.lead_id}
    leads_por_id = {l.id: l for l in db.execute(select(Lead).where(Lead.id.in_(ids))).scalars()} if ids else {}
    pessoas = db.execute(select(Usuario).where(Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars().all() \
        if ve_tudo(usuario, "fila.ver") else []
    return tela(request, "fila.html", {
        "pendentes": pendentes, "na_fila": na_fila, "historico": historico, "logs": logs, "resumo": resumo,
        "leads_por_id": leads_por_id, "nomes_camp": nomes_camp, "STATUS_ENVIO": STATUS_ENVIO, "hoje": hoje,
        "no_horario": no_horario, "pessoas": pessoas, "filtro_de": "todos" if alvo_id is None else str(alvo_id),
        "filtro_canal": canal, "horario": (ler_config(db, "horario_envio_inicio"), ler_config(db, "horario_envio_fim")),
        "CANAIS": config.CANAIS, "canais_do_toque": campanhas.canais_do_toque,
        "texto_do_canal": campanhas.texto_do_canal, "tarefas_por_id": tarefas_por_id,
        # aba Próximos envios: filtros, contagens e grupos por dia
        "aba": aba, "periodo": periodo, "situacao": situacao, "campanha": camp_id, "busca": busca.strip(),
        "PERIODOS": PERIODOS, "SITUACOES": SITUACOES, "contagem_periodo": contagem_periodo,
        "contagem_situacao": contagem_situacao, "grupos": _agrupar_por_dia(filtrados[:LIMITE_MOSTRAR], hoje),
        "limite_mostrar": LIMITE_MOSTRAR, "ids_mostrados": [p["t"].id for p in filtrados[:LIMITE_MOSTRAR]],
        "total_filtrados": len(filtrados), "opcoes_campanha": opcoes_campanha, "url_fila": url_fila,
        "filtrando": bool(situacao or camp_id or termo or periodo != "todos"),
    })


@rotas.post("/fila/enviar/{tid:int}", dependencies=[Depends(verificar_csrf)])
async def enviar_agora(request: Request, tid: int, usuario: Usuario = Depends(exige("fila.enviar")), db: Session = Depends(obter_db)):
    """Botão "Enviar agora" (pendente) ou "Enviar de novo" (não saiu) da Minha fila."""
    form = await request.form()
    t = db.get(Tarefa, tid)
    camp = db.get(Campanha, t.campanha_id) if t and t.campanha_id else None
    if t is None or camp is None:
        raise HTTPException(404)
    lead = t.lead
    if not autorizacao.pode(usuario, "fila.enviar", dono={camp.usuario_id, lead.vendedor_id if lead else None}):
        raise HTTPException(404)
    if t.status not in ("pendente", "feita") or camp.status != "ativa":
        avisar(request, "Este toque não pode mais ser enviado (campanha parada ou toque cancelado).", "erro")
        return voltar(str(form.get("voltar_para") or "/fila"))
    canal = str(form.get("canal") or "")
    canal = canal if canal in ("email", "whatsapp") else ""
    texto = str(form.get("texto") or "").strip()
    if texto and canal:  # popup do Histórico: o texto editado vale para este reenvio
        campanhas.editar_texto_do_canal(t, canal, texto[:5000], str(form.get("assunto") or ""))
    erro = campanhas.enviar_toque_agora(db, t, usuario, canal)
    if erro:
        avisar(request, f"Não saiu: {erro}", "alerta")
    else:
        registrar_log(db, usuario, f"disparou_campanha_{t.canal}", "campanha", camp.id,
                      f"1 envio manual ({lead.empresa if lead else ''})", request)
        avisar(request, "Mensagem colocada na fila do WhatsApp." if t.canal == "whatsapp" else "E-mail enviado.")
    db.commit()
    return voltar(str(form.get("voltar_para") or "/fila"))


def _toque_permitido(db, usuario: Usuario, tid: int) -> Tarefa | None:
    """O toque de campanha, se a pessoa pode mexer nele (o dono da campanha ou o responsável pelo lead)."""
    t = db.get(Tarefa, tid)
    camp = db.get(Campanha, t.campanha_id) if t and t.campanha_id else None
    if t is None or camp is None:
        return None
    lead = t.lead
    if not autorizacao.pode(usuario, "fila.enviar", dono={camp.usuario_id, lead.vendedor_id if lead else None}):
        return None
    return t


@rotas.post("/fila/cancelar/{tid:int}", dependencies=[Depends(verificar_csrf)])
async def cancelar_envio(request: Request, tid: int, usuario: Usuario = Depends(exige("fila.enviar")),
                         db: Session = Depends(obter_db)):
    """Botão Cancelar de um envio que ainda não saiu (Minha fila e Envios)."""
    form = await request.form()
    destino = str(form.get("voltar_para") or "/fila")
    t = _toque_permitido(db, usuario, tid)
    if t is None:
        raise HTTPException(404)
    if t.status != "pendente":
        avisar(request, "Este envio já saiu ou já foi cancelado.", "alerta")
        return voltar(destino)
    nome = t.lead.empresa if t.lead else "a empresa"
    campanhas.cancelar_toques(db, [t], usuario)
    registrar_log(db, usuario, "cancelou_envio", "tarefa", t.id, f"{t.canal} de {t.data:%d/%m} ({nome})", request)
    avisar(request, f"Envio para {nome} cancelado: ele não vai mais sair.")
    db.commit()
    return voltar(destino)


@rotas.post("/fila/cancelar-varios", dependencies=[Depends(verificar_csrf)])
async def cancelar_varios(request: Request, usuario: Usuario = Depends(exige("fila.enviar")),
                          db: Session = Depends(obter_db)):
    """Botão "Cancelar os N envios mostrados": cancela os envios que estão na tela com os filtros escolhidos."""
    form = await request.form()
    destino = str(form.get("voltar_para") or "/fila")
    ids = [i for i in (util.para_int(x) for x in str(form.get("ids") or "").split(",")) if i][:LIMITE_MOSTRAR]
    tarefas = [t for t in (_toque_permitido(db, usuario, i) for i in ids) if t is not None and t.status == "pendente"]
    total = campanhas.cancelar_toques(db, tarefas, usuario)
    if total:
        registrar_log(db, usuario, "cancelou_envios", "fila", None, f"{total} envios cancelados de uma vez", request)
        avisar(request, f"{total} envio(s) cancelado(s): eles não vão mais sair.")
    else:
        avisar(request, "Nenhum envio para cancelar (já saíram ou já foram cancelados).", "alerta")
    db.commit()
    return voltar(destino)


@rotas.post("/fila/mensagem/{tid:int}", dependencies=[Depends(verificar_csrf)])
async def editar_mensagem(request: Request, tid: int, usuario: Usuario = Depends(exige("fila.enviar")), db: Session = Depends(obter_db)):
    """Popup da Minha fila: altera o texto da versão de e-mail ou de WhatsApp de um toque que ainda não saiu."""
    form = await request.form()
    t = db.get(Tarefa, tid)
    camp = db.get(Campanha, t.campanha_id) if t and t.campanha_id else None
    if t is None or camp is None:
        raise HTTPException(404)
    lead = t.lead
    if not autorizacao.pode(usuario, "fila.enviar", dono={camp.usuario_id, lead.vendedor_id if lead else None}):
        raise HTTPException(404)
    canal = str(form.get("canal") or "")
    texto = str(form.get("texto") or "")
    destino = str(form.get("voltar_para") or "/fila")
    if canal not in ("email", "whatsapp") or t.status not in ("pendente", "rascunho"):
        avisar(request, "Esta mensagem não pode mais ser alterada (já saiu ou foi cancelada).", "erro")
        return voltar(destino)
    if not texto.strip():
        avisar(request, "A mensagem não pode ficar vazia.", "erro")
        return voltar(destino)
    campanhas.editar_texto_do_canal(t, canal, texto[:5000], str(form.get("assunto") or ""))
    registrar_log(db, usuario, "editou_mensagem", "tarefa", t.id, f"{canal} ({lead.empresa if lead else ''})", request)
    avisar(request, f"Mensagem de {'e-mail' if canal == 'email' else 'WhatsApp'} alterada.")
    db.commit()
    return voltar(destino)
