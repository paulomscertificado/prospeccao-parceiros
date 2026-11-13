"""Telas da IA SDR: Novas oportunidades (handoff), Campanhas (com aprovação), Inteligência de Prospecção,
Categorias de parceiros, Base de conhecimento e avisos."""

import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import agenda_horarios, autorizacao, campanhas, config, hoje as fila_hoje, ia, metricas, sdr, util, visual
from ..banco import agora, ler_config, obter_db
from ..leads_servico import historico, limpar_campos
from ..modelos import (Cadencia, Campanha, Categoria, Conhecimento, Lead, Mensagem, Notificacao, Oportunidade, Tarefa,
                       Usuario)
from ..seguranca import exige, registrar_log, ve_tudo, verificar_csrf
from ..web import avisar, tela, voltar
from .fila import DIAS_SEMANA

rotas = APIRouter()


def _lead(db: Session, lead_id: int, usuario: Usuario, permissao: str = "leads.editar") -> Lead:
    return autorizacao.garantir(usuario, permissao, db.get(Lead, lead_id))


def _equipe(db: Session):
    return list(db.execute(select(Usuario).where(Usuario.perfil.in_(["vendedor", "gestor", "admin"]),
                                                 Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars())


# ---------------------------------------------------------------- Novas oportunidades (handoff)

ABAS_OPORTUNIDADES = ("novas", "assumidas", "descartadas", "respostas")
STATUS_DA_ABA = {"novas": "nova", "assumidas": "assumida", "descartadas": "descartada"}
PERIODOS_OP = [("tudo", "Tudo"), ("hoje", "Hoje"), ("ontem", "Ontem"), ("7d", "Últimos 7 dias"),
               ("30d", "Últimos 30 dias"), ("antes", "Mais de 30 dias")]
TEMPERATURAS_OP = [("quente", "🔥 Quentes", "selo-erro"), ("morna", "Para analisar (mornas)", "selo-alerta")]
CANAIS_OP = [("whatsapp", "💬 WhatsApp", ""), ("email", "✉️ E-mail", ""), ("outro", "Outro canal", "")]
# Tipos de resposta (aba Todas as respostas), pela classificação da IA
CLASSES_OP = [("interesse", "Com interesse", "selo-ok"), ("analisar", "Para analisar", "selo-alerta"),
              ("sem_interesse", "Sem interesse", "selo-erro"), ("saiu", "Pediu para sair", "selo-erro"),
              ("robo", "Resposta automática (robô)", "selo-baixo"), ("outras", "Outras", "selo-azul")]
LIMITE_CARTOES = 50    # cartões completos na aba Novas (cada um junta campanha, canal e a conversa)
LIMITE_LINHAS = 200    # linhas nas outras abas (a página não pode ficar pesada; os filtros acham o resto)
LIMITE_OLHADOS = 3000  # registros olhados para os filtros e as contagens (os mais recentes)


def _no_periodo_op(quando: datetime, periodo: str, hoje: date) -> bool:
    d = quando.date()
    if periodo == "hoje":
        return d == hoje
    if periodo == "ontem":
        return d == hoje - timedelta(days=1)
    if periodo == "7d":
        return d > hoje - timedelta(days=7)
    if periodo == "30d":
        return d > hoje - timedelta(days=30)
    if periodo == "antes":
        return d <= hoje - timedelta(days=30)
    return True


def _canal_op(canal: str) -> str:
    return canal if canal in ("whatsapp", "email") else "outro"


def _classe_op(classificacao: str) -> str:
    """Tipo da resposta para o filtro da aba Todas as respostas."""
    if classificacao in config.CLASSES_QUENTES:
        return "interesse"
    if classificacao in config.CLASSES_MORNAS:
        return "analisar"
    return {"SEM INTERESSE": "sem_interesse", "OPT-OUT": "saiu", config.CLASSE_AUTOMATICA: "robo"}.get(classificacao,
                                                                                                       "outras")


def _tempo_curto(delta: timedelta) -> str:
    """12 min, 3 h, 2 dias (para "esperando há..." e "levou...")."""
    minutos = max(int(delta.total_seconds() // 60), 0)
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    return f"{horas} h" if horas < 48 else f"{horas // 24} dias"


def _grupos_por_dia(itens: list[dict], hoje: date) -> list[dict]:
    """Um grupo por dia, do mais recente: Hoje, Ontem, o dia da semana (últimos 7 dias) e depois a data.
    Os itens já chegam em ordem (do mais recente para o mais antigo); cada um traz "quando"."""
    grupos: list[dict] = []
    for item in itens:
        d = item["quando"].date()
        if not grupos or grupos[-1]["data"] != d:
            semana = DIAS_SEMANA[d.weekday()]
            if d == hoje:
                titulo, detalhe = "Hoje", f"{semana}, {d:%d/%m}"
            elif d == hoje - timedelta(days=1):
                titulo, detalhe = "Ontem", f"{semana}, {d:%d/%m}"
            elif d > hoje - timedelta(days=7):
                titulo, detalhe = semana.capitalize(), f"{d:%d/%m}"
            else:
                titulo, detalhe = f"{d:%d/%m/%Y}", semana
            grupos.append({"data": d, "titulo": titulo, "detalhe": detalhe, "itens": []})
        grupos[-1]["itens"].append(item)
    return grupos


@rotas.get("/oportunidades")
def oportunidades(request: Request, ver: str = "novas", periodo: str = "tudo", temperatura: str = "", canal: str = "",
                  classe: str = "", busca: str = "", usuario: Usuario = Depends(exige("oportunidades.ver")),
                  db: Session = Depends(obter_db)):
    hoje, momento = date.today(), agora()
    ve_respostas = autorizacao.pode(usuario, "oportunidades.respostas")
    ver = "assumidas" if ver == "tratadas" else ver  # endereço antigo (Assumidas/descartadas)
    if ver not in ABAS_OPORTUNIDADES or (ver == "respostas" and not ve_respostas):
        ver = "novas"
    periodo = periodo if periodo in dict(PERIODOS_OP) else "tudo"
    temperatura = temperatura if temperatura in {c for c, *_ in TEMPERATURAS_OP} else ""
    canal = canal if canal in {c for c, *_ in CANAIS_OP} else ""
    classe = classe if classe in {c for c, *_ in CLASSES_OP} else ""
    busca = busca.strip()[:100]
    termo = util.chave_texto(busca)

    # Avisos sobre oportunidades contam como lidos ao abrir a tela.
    for n in db.execute(select(Notificacao).where(Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False),
                                                  Notificacao.link.like("/oportunidades%"))).scalars():
        n.lida = True
    db.commit()

    def visiveis(*colunas):
        """As oportunidades que a pessoa alcança (dela, da equipe ou todas, conforme a permissão)."""
        return autorizacao.filtrar(select(*colunas).join(Lead, Oportunidade.lead_id == Lead.id), usuario,
                                   "oportunidades.ver", Lead.vendedor_id, sem_dono=True)

    por_status = dict(db.execute(visiveis(Oportunidade.status, func.count(Oportunidade.id))
                                 .group_by(Oportunidade.status)).all())
    respostas_q = (select(Mensagem.id, Mensagem.criado_em, Mensagem.canal, Lead.empresa, Lead.classificacao_resposta)
                   .join(Lead, Mensagem.lead_id == Lead.id).where(Mensagem.status == "recebida"))
    abas = {"novas": por_status.get("nova", 0), "assumidas": por_status.get("assumida", 0),
            "descartadas": por_status.get("descartada", 0),
            "respostas": db.execute(select(func.count()).select_from(respostas_q.subquery())).scalar() or 0
            if ve_respostas else 0}

    # Números do topo: o que espera alguém, quanto tempo levou para alguém atender e quantas respostas chegaram.
    # "Últimos N dias" = hoje e os N-1 dias antes (igual ao botão de filtro, para o número bater com a lista).
    desde_7d = datetime.combine(hoje - timedelta(days=6), datetime.min.time())
    desde_30d = datetime.combine(hoje - timedelta(days=29), datetime.min.time())
    novas_leves = db.execute(visiveis(Oportunidade.temperatura, Oportunidade.criado_em)
                             .where(Oportunidade.status == "nova")).all()
    tratadas_30 = db.execute(visiveis(Oportunidade.criado_em, Oportunidade.assumida_em)
                             .where(Oportunidade.status != "nova", Oportunidade.assumida_em.is_not(None),
                                    Oportunidade.assumida_em >= desde_30d)).all()
    esperas = sorted(max((a - c).total_seconds(), 0) for c, a in tratadas_30)
    resumo = {
        "novas": len(novas_leves),
        "quentes": sum(1 for t, _ in novas_leves if t == "quente"),
        "esperando_demais": sum(1 for _, c in novas_leves if momento > fila_hoje.prazo_para_assumir(db, c)),
        "tratadas_30": len(esperas),
        "tempo_mediano": _tempo_curto(timedelta(seconds=esperas[len(esperas) // 2])) if esperas else "",
        "respostas_7": db.execute(select(func.count()).select_from(
            respostas_q.where(Mensagem.criado_em >= desde_7d).subquery())).scalar() or 0
        if ve_respostas else 0,
    }

    contexto = {"ver": ver, "periodo": periodo, "temperatura": temperatura, "canal": canal, "classe": classe,
                "busca": busca, "abas": abas, "resumo": resumo, "ve_tudo": ve_respostas,
                "cor_classe": {c: cor for c, _, cor in CLASSES_OP},
                "filtrando": bool(periodo != "tudo" or temperatura or canal or classe or termo)}
    filtros = {"periodo": lambda i: _no_periodo_op(i["quando"], periodo, hoje),
               "canal": lambda i: not canal or i["canal"] == canal}

    if ver == "respostas":
        # Admin/gestor: TODAS as respostas que chegaram (inclusive sem interesse e opt-out, que não viram oportunidade)
        linhas = db.execute(respostas_q.order_by(Mensagem.criado_em.desc(), Mensagem.id.desc())
                            .limit(LIMITE_OLHADOS)).all()
        itens = [{"id": mid, "quando": criado, "canal": _canal_op(c), "classe": _classe_op(cl or "")}
                 for mid, criado, c, empresa, cl in linhas if not termo or termo in util.chave_texto(empresa)]
        filtros["classe"] = lambda i: not classe or i["classe"] == classe
        limite = LIMITE_LINHAS
    else:
        linhas = db.execute(visiveis(Oportunidade.id, Oportunidade.temperatura, Oportunidade.canal,
                                     Oportunidade.criado_em, Oportunidade.assumida_em, Lead.empresa)
                            .where(Oportunidade.status == STATUS_DA_ABA[ver])
                            .order_by((Oportunidade.criado_em if ver == "novas" else
                                       func.coalesce(Oportunidade.assumida_em, Oportunidade.criado_em)).desc())
                            .limit(LIMITE_OLHADOS)).all()
        # Novas: pela data da resposta. Assumidas e descartadas: pela data em que alguém assumiu ou descartou
        itens = [{"id": oid, "temperatura": temp, "canal": _canal_op(c), "criado": criado,
                  "quando": criado if ver == "novas" else (assumida or criado)}
                 for oid, temp, c, criado, assumida, empresa in linhas if not termo or termo in util.chave_texto(empresa)]
        filtros["temperatura"] = lambda i: not temperatura or i["temperatura"] == temperatura
        limite = LIMITE_CARTOES if ver == "novas" else LIMITE_LINHAS
        # Em cada dia, as quentes primeiro; depois da mais nova para a mais antiga
        itens.sort(key=lambda i: (i["quando"].date(), ver == "novas" and i["temperatura"] == "quente", i["quando"]),
                   reverse=True)

    def quantos(chave: str, nesta_opcao) -> int:
        """O número em cada botão de filtro: quantos passam nesta opção e nos OUTROS filtros (como na Minha fila)."""
        return sum(1 for i in itens if nesta_opcao(i) and all(f(i) for nome, f in filtros.items() if nome != chave))

    # Botões de filtro: (opção, nome, quantos, cor do ponto). Canal e tipo de resposta sem nenhum ficam escondidos.
    chips = {"periodo": [(c, nome, quantos("periodo", lambda i, c=c: _no_periodo_op(i["quando"], c, hoje)), "")
                         for c, nome in PERIODOS_OP]}
    for chave, opcoes, escolhida in (("canal", CANAIS_OP, canal), ("temperatura", TEMPERATURAS_OP, temperatura),
                                     ("classe", CLASSES_OP, classe)):
        if chave in filtros:
            chips[chave] = [(c, nome, n, ponto) for c, nome, ponto in opcoes
                            for n in [quantos(chave, lambda i, c=c, k=chave: i[k] == c)]
                            if n or escolhida == c or chave == "temperatura"]
    contexto["chips"] = chips
    filtrados = [i for i in itens if all(f(i) for f in filtros.values())]
    mostrados = filtrados[:limite]
    ids = [i["id"] for i in mostrados]
    contexto.update({"total_filtrados": len(filtrados), "limite": limite, "olhou_tudo": len(linhas) < LIMITE_OLHADOS,
                     "ids_mostrados": ids})

    if ver == "respostas":
        mensagens_por_id = {m.id: m for m in db.execute(select(Mensagem).where(Mensagem.id.in_(ids))).scalars()} if ids else {}
        ids_leads = {m.lead_id for m in mensagens_por_id.values()}
        ops_do_lead: dict[int, Oportunidade] = {}
        for o in db.execute(select(Oportunidade).where(Oportunidade.lead_id.in_(ids_leads))
                            .order_by(Oportunidade.criado_em.desc())).scalars() if ids_leads else []:
            ops_do_lead.setdefault(o.lead_id, o)  # a mais recente de cada lead
        ids_camp = {m.campanha_id for m in mensagens_por_id.values() if m.campanha_id}
        for i in mostrados:
            i["m"] = mensagens_por_id[i["id"]]
        contexto.update({
            "leads_resposta": {l.id: l for l in db.execute(select(Lead).where(Lead.id.in_(ids_leads))).scalars()}
            if ids_leads else {},
            "ops_do_lead": ops_do_lead,
            "nomes_camp": {c.id: c.nome for c in db.execute(select(Campanha).where(Campanha.id.in_(ids_camp))).scalars()}
            if ids_camp else {},
        })
    else:
        ops = {o.id: o for o in db.execute(select(Oportunidade).where(Oportunidade.id.in_(ids)).options(
            selectinload(Oportunidade.lead), selectinload(Oportunidade.responsavel))).scalars()} if ids else {}
        for i in mostrados:
            o = i["o"] = ops[i["id"]]
            i["espera"] = _tempo_curto(momento - o.criado_em)
            i["prazo"] = fila_hoje.prazo_para_assumir(db, o.criado_em)  # 2 horas úteis
            i["esperando_demais"] = momento > i["prazo"]
            i["levou"] = _tempo_curto(o.assumida_em - o.criado_em) if o.assumida_em else ""
        # Resumo completo (campanha, dono, canal, o que enviamos) só nos cartões da aba Novas
        contexto["resumos"] = {i["o"].id: sdr.resumo_handoff(db, i["o"].lead) for i in mostrados} if ver == "novas" else {}
    contexto["grupos"] = _grupos_por_dia(mostrados, hoje)

    atuais = {"ver": ver, "periodo": periodo, "temperatura": temperatura, "canal": canal, "classe": classe,
              "busca": busca}

    def url_op(**mudancas) -> str:
        """Endereço desta tela com os filtros atuais e as mudanças pedidas (valor padrão fica fora do endereço)."""
        params = {k: v for k, v in {**atuais, **mudancas}.items()
                  if v and not (k == "ver" and v == "novas") and not (k == "periodo" and v == "tudo")}
        return "/oportunidades" + ("?" + urlencode(params) if params else "")

    contexto["url_op"] = url_op
    contexto["voltar"] = url_op()
    resposta = tela(request, "oportunidades.html", contexto)
    resposta.headers["Cache-Control"] = "no-store"  # voltar no navegador recarrega (sem cartão já assumido)
    return resposta


def _destino_seguro(destino: str) -> str:
    """Só volta para uma tela do próprio sistema."""
    return destino if destino.startswith("/") and not destino.startswith("//") else "/oportunidades"


def _descartar(db: Session, op: Oportunidade, usuario: Usuario, motivo: str) -> None:
    """Descarta a oportunidade (e os cartões repetidos do mesmo lead que ainda estão em Novas), com o motivo."""
    for o in db.execute(select(Oportunidade).where(Oportunidade.lead_id == op.lead_id,
                                                   Oportunidade.status == "nova")).scalars():
        o.status, o.responsavel_id, o.assumida_em, o.motivo = "descartada", usuario.id, agora(), motivo
    op.status, op.responsavel_id, op.assumida_em, op.motivo = "descartada", usuario.id, agora(), motivo
    historico(db, op.lead_id, "sistema", f"Oportunidade descartada por {usuario.nome} ({motivo}).", usuario)


SEM_MOTIVO = "Escolha o motivo do descarte (ele ensina o que ajustar nas campanhas). Nada foi descartado."


@rotas.post("/oportunidades/{oid:int}/descartar", dependencies=[Depends(verificar_csrf)])
def descartar(request: Request, oid: int, voltar_para: str = Form("/oportunidades"), motivo: str = Form(""),
              usuario: Usuario = Depends(exige("oportunidades.ver")), db: Session = Depends(obter_db)):
    op = db.get(Oportunidade, oid)
    if not op or not autorizacao.pode(usuario, "oportunidades.ver", op, sem_dono=True):
        raise HTTPException(404)
    if motivo not in config.MOTIVOS_DESCARTE:
        avisar(request, SEM_MOTIVO, "erro")
        return voltar(_destino_seguro(voltar_para))
    _descartar(db, op, usuario, motivo)
    db.commit()
    avisar(request, f"Oportunidade de {op.lead.empresa if op.lead else 'lead'} descartada (está na aba Descartadas; "
                    "lá dá para voltar com ela para Novas).")
    return voltar(_destino_seguro(voltar_para))


@rotas.post("/oportunidades/descartar-varias", dependencies=[Depends(verificar_csrf)])
def descartar_varias(request: Request, ids: str = Form(""), voltar_para: str = Form("/oportunidades"),
                     motivo: str = Form(""), usuario: Usuario = Depends(exige("oportunidades.ver")),
                     db: Session = Depends(obter_db)):
    """Botão "Descartar as N mostradas" (aba Novas, só com algum filtro escolhido), com um motivo para todas."""
    if motivo not in config.MOTIVOS_DESCARTE:
        avisar(request, SEM_MOTIVO, "erro")
        return voltar(_destino_seguro(voltar_para))
    escolhidas = [i for i in (util.para_int(x) for x in ids.split(",")) if i][:LIMITE_CARTOES]
    total = 0
    for op in db.execute(select(Oportunidade).where(Oportunidade.id.in_(escolhidas))).scalars().all() if escolhidas else []:
        if op.status == "nova" and autorizacao.pode(usuario, "oportunidades.ver", op, sem_dono=True):
            _descartar(db, op, usuario, motivo)
            total += 1
    if total:
        registrar_log(db, usuario, "descartou_oportunidades", "oportunidade", None,
                      f"{total} oportunidades descartadas de uma vez", request)
        avisar(request, f"{total} oportunidade(s) descartada(s). Estão na aba Descartadas, se precisar voltar com alguma.")
    else:
        avisar(request, "Nenhuma oportunidade para descartar (já foram assumidas ou descartadas).", "alerta")
    db.commit()
    return voltar(_destino_seguro(voltar_para))


@rotas.post("/oportunidades/{oid:int}/reabrir", dependencies=[Depends(verificar_csrf)])
def reabrir(request: Request, oid: int, voltar_para: str = Form("/oportunidades?ver=descartadas"),
            usuario: Usuario = Depends(exige("oportunidades.ver")), db: Session = Depends(obter_db)):
    """Desfaz um descarte: a oportunidade volta para a aba Novas."""
    op = db.get(Oportunidade, oid)
    if not op or not autorizacao.pode(usuario, "oportunidades.ver", op, sem_dono=True):
        raise HTTPException(404)
    if op.status != "descartada":
        avisar(request, "Só dá para voltar com uma oportunidade descartada.", "alerta")
    else:
        op.status, op.responsavel_id, op.assumida_em, op.motivo = "nova", None, None, ""
        historico(db, op.lead_id, "sistema", f"Oportunidade voltou para Novas ({usuario.nome} desfez o descarte).",
                  usuario)
        db.commit()
        avisar(request, f"A oportunidade de {op.lead.empresa if op.lead else 'lead'} voltou para Novas.")
    return voltar(_destino_seguro(voltar_para))


@rotas.post("/leads/{lead_id:int}/assumir", dependencies=[Depends(verificar_csrf)])
def assumir(request: Request, lead_id: int, voltar_para: str = Form(""), usuario: Usuario = Depends(exige("oportunidades.ver")),
            db: Session = Depends(obter_db)):
    lead = autorizacao.garantir(usuario, "oportunidades.ver", db.get(Lead, lead_id), sem_dono=True)
    sdr.assumir_lead(db, lead, usuario)
    registrar_log(db, usuario, "assumiu_lead", "lead", lead.id, request=request)
    db.commit()
    avisar(request, f"Você assumiu {lead.empresa}. A automação deste lead foi parada"
                    + (" e a oportunidade saiu das novas (está na aba Assumidas)." if voltar_para.startswith("/oportunidades")
                       else "."))
    return voltar(voltar_para if voltar_para.startswith("/") and not voltar_para.startswith("//")
                  else f"/leads/{lead_id}#handoff")


@rotas.get("/leads/{lead_id:int}/agendar")
def agendar_tela(request: Request, lead_id: int, responsavel: int | None = None, usuario: Usuario = Depends(exige("leads.editar")),
                 db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    resp = db.get(Usuario, responsavel or lead.humano_id or lead.vendedor_id or usuario.id) or usuario
    return tela(request, "agendar.html", {"lead": lead, "responsavel": resp, "equipe": _equipe(db),
                                          "horarios": agenda_horarios.horarios_livres(db, resp, dias=10, quantidade=30),
                                          "nomes_dia": agenda_horarios.NOMES_DIA})


@rotas.post("/leads/{lead_id:int}/agendar", dependencies=[Depends(verificar_csrf)])
def agendar(request: Request, lead_id: int, responsavel_id: int = Form(...), quando: str = Form(...),
            canal: str = Form("video"), pauta: str = Form(""), usuario: Usuario = Depends(exige("leads.editar")),
            db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)  # antes não conferia de quem era o lead
    resp = db.get(Usuario, responsavel_id)
    if not resp:
        raise HTTPException(404)
    try:
        momento = datetime.fromisoformat(quando)
        agenda_horarios.agendar(db, lead, resp, momento, canal, usuario, pauta)
    except (ValueError, agenda_horarios.HorarioIndisponivel) as erro:
        avisar(request, str(erro) if isinstance(erro, agenda_horarios.HorarioIndisponivel) else "Horário inválido.", "erro")
        return voltar(f"/leads/{lead_id}/agendar?responsavel={responsavel_id}")
    if not lead.humano_id:
        sdr.assumir_lead(db, lead, resp)
    db.commit()
    avisar(request, f"Reunião marcada com {lead.empresa} em {momento:%d/%m às %H:%M} ({resp.nome}).")
    return voltar(f"/leads/{lead_id}")


# ---------------------------------------------------------------- Pesquisa e abordagem de um lead

@rotas.post("/leads/{lead_id:int}/enviar-whatsapp", dependencies=[Depends(verificar_csrf)])
def enviar_whatsapp(request: Request, lead_id: int, texto: str = Form(...), angulo: str = Form(""),
                    usuario: Usuario = Depends(exige("leads.editar")), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    try:
        msg = sdr.enviar_whatsapp_conectado(db, texto, usuario, lead=lead)
        msg.angulo = angulo[:20]
        db.commit()
        avisar(request, "Mensagem colocada na fila do WhatsApp conectado. Ela sai respeitando as pausas e o horário.")
    except sdr.EnvioRecusado as erro:
        avisar(request, str(erro), "erro")
    return voltar(f"/leads/{lead_id}")


@rotas.post("/leads/{lead_id:int}/pesquisar", dependencies=[Depends(verificar_csrf)])
def pesquisar(request: Request, lead_id: int, usuario: Usuario = Depends(exige("leads.editar")), db: Session = Depends(obter_db)):
    from ..pesquisa import pesquisar_lead

    lead = _lead(db, lead_id, usuario)
    pesquisar_lead(db, lead, usuario)
    db.commit()
    avisar(request, f"Pesquisa concluída: {lead.fit}, score {lead.score}.")
    return voltar(f"/leads/{lead_id}#perfil")


@rotas.post("/leads/{lead_id:int}/abordagem-sdr", dependencies=[Depends(verificar_csrf)])
def abordagem_sdr(request: Request, lead_id: int, cta: str = Form(""), tom: str = Form("consultivo"),
                  usuario: Usuario = Depends(exige("leads.editar")), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    if not lead.pesquisado_em:
        from ..pesquisa import pesquisar_lead

        pesquisar_lead(db, lead, usuario)
    msgs = sdr.gerar_mensagens(db, lead, usuario, cta, tom)
    q = json.loads(lead.qualificacao) if lead.qualificacao else {}
    q["sdr"] = {"mensagens": msgs, "canal": sdr.escolher_canal(db, lead), "em": agora().strftime("%d/%m/%Y %H:%M")}
    lead.qualificacao = json.dumps(q, ensure_ascii=False)
    if lead.status in ("Novo", "Pesquisando"):
        lead.status = "Abordagem criada"
    historico(db, lead.id, "ia", "Abordagem SDR criada (4 toques: apresentação, praticidade, receita, encerramento).",
              usuario)
    db.commit()
    return voltar(f"/leads/{lead_id}#sdr")


# ---------------------------------------------------------------- Campanhas

FILTROS_CAMPANHA = {"todas": "Todas", "aprovacao": "Aguardando aprovação", "ativas": "Em andamento",
                    "erro": "Com erro", "arquivadas": "Arquivadas"}


def _campanha(db: Session, cid: int, usuario: Usuario, permissao: str = "campanhas.ver") -> Campanha:
    """A campanha, se a pessoa pode vê-la: cada um vê as próprias; administrador e gestor veem todas."""
    camp = db.get(Campanha, cid)
    if not camp or not autorizacao.pode(usuario, permissao, camp):
        raise HTTPException(404)
    return camp


@rotas.get("/campanhas")
def lista_campanhas(request: Request, ver: str = "todas", de: str = "", usuario: Usuario = Depends(exige("campanhas.ver")),
                    db: Session = Depends(obter_db)):
    # cada um com as suas campanhas (ou as da equipe); quem vê todas escolhe de quem
    consulta = autorizacao.filtrar(select(Campanha), usuario, "campanhas.ver", Campanha.usuario_id)
    if ve_tudo(usuario, "campanhas.ver"):
        if de in ("", "minhas"):
            de = "minhas"  # padrão: as campanhas de quem está usando a conta
            consulta = consulta.where(Campanha.usuario_id == usuario.id)
        elif util.para_int(de):
            consulta = consulta.where(Campanha.usuario_id == util.para_int(de))
    consulta = consulta.where(Campanha.arquivada.is_(ver == "arquivadas"))
    if ver == "aprovacao":
        consulta = consulta.where(Campanha.status == "aguardando_aprovacao")
    elif ver == "ativas":
        consulta = consulta.where(Campanha.status.in_(["ativa", "pausada", "gerando"]))
    elif ver == "erro":
        consulta = consulta.where(Campanha.status == "erro")
    lista = db.execute(consulta.order_by(Campanha.criado_em.desc()).limit(200)).scalars().all()
    contagens = {}
    for c in lista:
        contagens[c.id] = dict(db.execute(select(Tarefa.status, func.count()).where(Tarefa.campanha_id == c.id)
                                          .group_by(Tarefa.status)).all())
    nomes_cat = {c.codigo: c.nome for c in db.execute(select(Categoria)).scalars()}
    pessoas = {u.id: u.nome for u in db.execute(select(Usuario)).scalars()}
    equipe_ = ([] if not ve_tudo(usuario, "campanhas.ver") else
               sorted({c.usuario_id for c in db.execute(select(Campanha)).scalars() if c.usuario_id},
                      key=lambda i: pessoas.get(i, "")))
    return tela(request, "campanhas.html", {"campanhas": lista, "contagens": contagens, "ver": ver, "de": de,
                                            "filtros": FILTROS_CAMPANHA, "nomes_cat": nomes_cat, "pessoas": pessoas,
                                            "equipe_campanhas": equipe_})


def _cadencias_da_ia(db: Session) -> list[Cadencia]:
    """Cadências que servem para campanha da IA SDR: todo toque tem um ângulo (a mensagem certa para cada toque).
    As da Agenda (com ligação e LinkedIn, sem ângulo) ficam de fora: a campanha não faz ligação nem LinkedIn."""
    from .. import empresas_novas, renovacao

    ativas, nomes = [], set()
    for c in db.execute(select(Cadencia).where(Cadencia.ativa.is_(True)).order_by(Cadencia.id)).scalars():
        if c.nome not in nomes:  # uma de cada nome (a nuvem já criou cadência em dobro)
            nomes.add(c.nome)
            ativas.append(c)
    da_ia = [c for c in ativas if c.passos and all(p.angulo for p in c.passos)
             and c.nome not in (empresas_novas.CADENCIA_NOME, renovacao.CADENCIA_NOME)]  # de venda / renovação
    return da_ia or ativas


@rotas.get("/campanhas/nova")
def nova_campanha(request: Request, pedido: str = "", base: str = "", usuario: Usuario = Depends(exige("campanhas.criar")),
                  db: Session = Depends(obter_db)):
    from .. import bases_importadas

    entendido = campanhas.interpretar_pedido(db, pedido) if pedido else None
    ultima = db.execute(select(Campanha).where(Campanha.cidade != "", Campanha.usuario_id == usuario.id)
                        .order_by(Campanha.criado_em.desc()).limit(1)).scalars().first()
    # base: a pedida, senão a da última campanha do usuário, senão a primeira disponível
    ultima_base = db.execute(select(Campanha.base).where(Campanha.usuario_id == usuario.id, Campanha.tipo == "parceiros")
                             .order_by(Campanha.criado_em.desc()).limit(1)).scalar()
    base = bases_importadas.escolher(db, base or ultima_base or "")
    contagem = (bases_importadas.contar(db, base, entendido["estado"], entendido["cidade"])
                if entendido and entendido.get("cidade") and entendido.get("estado") else {})
    if not contagem:
        cidade = (entendido or {}).get("cidade") or (ultima.cidade if ultima else "Recife")
        uf = (entendido or {}).get("estado") or (ultima.estado if ultima else "PE")
        contagem = bases_importadas.contar(db, base, uf, cidade)
    return tela(request, "campanha_nova.html", {
        "pedido": pedido, "entendido": entendido, "contagem": contagem,
        "bases": bases_importadas.opcoes(db), "base": base,
        "numeros_admin": _numeros_para_admin(db, usuario),
        "ultima_cidade": ultima.cidade if ultima else "", "ultima_uf": ultima.estado if ultima else "",
        "categorias": db.execute(select(Categoria).where(Categoria.ativa.is_(True)).order_by(Categoria.prioridade)).scalars().all(),
        "cadencias": _cadencias_da_ia(db), "cadencia_sdr": campanhas.cadencia_sdr(db), "ia_ligada": ia.disponivel(),
        "visuais": visual.disponiveis(db, "sdr"),
        "whatsapp_sozinho_padrao": ler_config(db, "whatsapp_sozinho_padrao") != "0",
    })


@rotas.get("/api/contagem")
def contagem_cidade(cidade: str = "", uf: str = "", base: str = "", usuario: Usuario = Depends(exige("campanhas.criar")),
                    db: Session = Depends(obter_db)):
    """Quantas empresas de cada categoria existem na cidade, na base escolhida (para a tela de nova campanha).
    Lista importada sem cidade = o estado inteiro."""
    from .. import bases_importadas

    base = bases_importadas.escolher(db, base)
    if uf not in config.UFS or (not cidade.strip() and not bases_importadas.e_lista(base)):
        return {}
    return bases_importadas.contar(db, base, uf, cidade.strip())


@rotas.post("/campanhas/nova", dependencies=[Depends(verificar_csrf)])
async def criar_campanha(request: Request, usuario: Usuario = Depends(exige("campanhas.criar")), db: Session = Depends(obter_db)):
    from .. import bases_importadas

    form = await request.form()
    cats = [c for c in form.getlist("categorias") if c]
    cidade, uf = str(form.get("cidade", "")).strip(), str(form.get("estado", "")).strip().upper()
    base = bases_importadas.escolher(db, str(form.get("base") or ""))
    if cidade == "__todas__":
        cidade = ""  # "Todas as cidades": só vale para lista importada (a da Receita exige a cidade)
    if not cats or (not cidade and not bases_importadas.e_lista(base)) or uf not in config.UFS:
        avisar(request, "Informe a região (cidade e estado) e pelo menos um segmento.", "erro")
        return voltar("/campanhas/nova?pedido=" + util.chave_texto(str(form.get("pedido", "")))[:200])
    canais = [c for c in form.getlist("canais") if c in ("whatsapp", "email", "linkedin")] or ["whatsapp", "email"]
    escolha_cta, cta_livre = str(form.get("cta") or ""), str(form.get("cta_livre") or "").strip()
    cta = cta_livre if escolha_cta in ("", "__minha__") and cta_livre else ("" if escolha_cta == "__minha__" else escolha_cta)
    cta = cta.strip()
    if cta and cta != config.CTA_VARIAR and not sdr.texto_seguro(cta):
        avisar(request, "A pergunta final não pode ter valores, porcentagem, desconto, exclusividade, contrato nem "
                        "frase de propaganda. Escreva de outro jeito.", "erro")
        return voltar("/campanhas/nova?pedido=" + util.chave_texto(str(form.get("pedido", "")))[:200])
    camp = Campanha(
        nome=str(form.get("nome") or _nome_automatico(db, cats, cidade or uf)).strip()[:160],
        pedido=str(form.get("pedido", ""))[:2000], categorias=",".join(cats), cidade=cidade, estado=uf, base=base,
        quantidade=max(1, min(util.para_int(form.get("quantidade")) or util.para_int(form.get("quantidade_outra")) or 20, 500)), canais=",".join(canais),
        objetivo=str(form.get("objetivo") or "Encontrar parceiros")[:200],
        tom=str(form.get("tom")) if str(form.get("tom")) in config.TONS else "consultivo",
        cta=cta[:200], cadencia_id=util.para_int(form.get("cadencia_id")), usuario_id=usuario.id,
        conexao_id=_numero_escolhido(db, usuario, form),
        whatsapp_sozinho=ler_config(db, "whatsapp_sozinho_padrao") != "0",  # regra desde 12/11/2026 (pedido da Maria)
        inicio=util.para_data(form.get("inicio")) or date.today(), status="gerando", personalizar_ia=ia.disponivel(),
    )
    camp.visual_id, camp.visual_canais, camp.visual_toques = visual.escolha_do_formulario(db, form, "sdr")
    db.add(camp)
    db.flush()
    registrar_log(db, usuario, "criou_campanha", "campanha", camp.id,
                  f"{camp.nome}: {camp.categorias} {cidade or 'todas as cidades'}/{uf} ({bases_importadas.nome(db, base)})", request)
    db.commit()
    campanhas.gerar_em_segundo_plano(camp.id)
    return voltar(f"/campanhas/{camp.id}")


def _numeros_para_admin(db: Session, usuario: Usuario) -> list[dict]:
    """Números de WhatsApp que o administrador pode escolher para disparar a campanha (com a situação de cada um)."""
    from .. import conexoes
    from ..integracoes import whatsapp_leads

    if not autorizacao.pode(usuario, "campanhas.escolher_numero"):
        return []
    base = whatsapp_leads.status()
    return [{"id": c.id, "nome": c.nome, "conectado": bool(conexoes.situacao(c.id, base).get("conectado"))}
            for c in conexoes.todas(db)]


def _numero_escolhido(db: Session, usuario: Usuario, form) -> str:
    """Só o administrador escolhe o número; vazio = automático (número do responsável pelo lead)."""
    from .. import conexoes

    escolhido = str(form.get("conexao_id") or "")
    if not autorizacao.pode(usuario, "campanhas.escolher_numero") or not escolhido or db.get(conexoes.ConexaoWhatsApp, escolhido) is None:
        return ""
    return escolhido


def _nome_automatico(db: Session, cats: list[str], cidade: str) -> str:
    nomes = [n for (n,) in db.execute(select(Categoria.nome).where(Categoria.codigo.in_(cats)))]
    segmento = nomes[0] if len(nomes) == 1 else f"{len(nomes)} segmentos"
    return f"{segmento} – {cidade} – {date.today():%d/%m}"


@rotas.get("/campanhas/{cid:int}")
def ver_campanha(request: Request, cid: int, usuario: Usuario = Depends(exige("campanhas.ver")), db: Session = Depends(obter_db)):
    from .. import conexoes

    camp = _campanha(db, cid, usuario)
    nomes = {c.codigo: c.nome for c in db.execute(select(Categoria)).scalars()}
    whatsapp_hoje = campanhas.whatsapp_de_hoje(db, camp) if camp.status == "ativa" else []
    numero, sem_numero = "", ""
    if whatsapp_hoje:
        try:
            numero_id = (conexoes.da_campanha(db, camp)
                         or conexoes.para_enviar(db, conexoes.responsavel(db, None, usuario)))
            numero = (db.get(conexoes.ConexaoWhatsApp, numero_id).nome if db.get(conexoes.ConexaoWhatsApp, numero_id)
                      else numero_id)
        except conexoes.SemNumero as erro:
            sem_numero = str(erro)
    ids_fixo = [int(i) for i in (camp.so_fixo or "").split(",") if i.isdigit()]
    so_fixo = db.execute(select(Lead).where(Lead.id.in_(ids_fixo))).scalars().all() if ids_fixo else []
    testaveis_q = (select(Campanha).where(Campanha.arquivada.is_(False),
                                          Campanha.status.in_(["aguardando_aprovacao", "ativa", "pausada"]))
                   .order_by(Campanha.criado_em.desc()).limit(50))
    testaveis_q = autorizacao.filtrar(testaveis_q, usuario, "campanhas.ver", Campanha.usuario_id)
    testaveis = db.execute(testaveis_q).scalars().all()
    if camp not in testaveis:
        testaveis.insert(0, camp)
    contagem = campanhas.mensagens_para_teste(db, [t.id for t in testaveis])
    from .. import bases_importadas

    return tela(request, "campanha.html", {
        "nome_base": bases_importadas.nome(db, camp.base or "receita"),
        "testaveis": [{"id": t.id, "nome": t.nome, **contagem[t.id]} for t in testaveis],
        "so_fixo": so_fixo,
        "emails_invalidos": campanhas.emails_invalidos(db, camp),
        "responsaveis_diferentes": campanhas.responsaveis_diferentes(db, camp),
        "andamento": campanhas.andamento(db, camp) if camp.status not in ("gerando", "erro") else [],
        "whatsapp_hoje": whatsapp_hoje, "numero_whatsapp": numero, "sem_numero": sem_numero,
        "disparar": {k: len(v) for k, v in campanhas.para_disparar(db, camp).items()},
        "numeros_admin": _numeros_para_admin(db, usuario), "visual_resumo": visual.resumo_da_campanha(db, camp),
        "pode_whatsapp_sozinho": autorizacao.pode(usuario, "campanhas.whatsapp_sozinho"),
        "pode_gerenciar": autorizacao.pode(usuario, "campanhas.gerenciar", camp),
        "dono": db.get(Usuario, camp.usuario_id) if camp.usuario_id else None,
        "c": camp, "resumo": campanhas.resumo_aprovacao(db, camp), "nomes_categorias": nomes,
        "rodando": camp.status == "gerando", "pode_aprovar": True,
        "aprovador": db.get(Usuario, camp.aprovado_por_id) if camp.aprovado_por_id else None,
    })


@rotas.post("/campanhas/{cid:int}/{acao}", dependencies=[Depends(verificar_csrf)])
async def acao_campanha(request: Request, cid: int, acao: str, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                        db: Session = Depends(obter_db)):
    camp = _campanha(db, cid, usuario, "campanhas.gerenciar")
    form = await request.form()
    if acao in ("arquivar", "desarquivar", "excluir"):
        if not autorizacao.pode(usuario, "campanhas.gerenciar", camp):
            avisar(request, "Só quem criou a campanha (ou o administrador/gestor) pode arquivar ou excluir.", "erro")
            return voltar(f"/campanhas/{cid}")
        if acao == "excluir":
            if camp.status in ("ativa", "pausada") and not autorizacao.pode(usuario, "campanhas.excluir_andamento"):
                avisar(request, "Esta campanha está em andamento: peça ao administrador ou gestor para excluir.", "erro")
                return voltar(f"/campanhas/{cid}")
            nome = camp.nome
            campanhas.excluir(db, camp, usuario)
            registrar_log(db, usuario, "excluiu_campanha", "campanha", cid, nome, request)
            db.commit()
            avisar(request, f"Campanha \"{nome}\" excluída. As empresas continuam em Leads.")
            return voltar("/campanhas")
        camp.arquivada = acao == "arquivar"
        registrar_log(db, usuario, acao + "_campanha", "campanha", cid, camp.nome, request)
        db.commit()
        avisar(request, "Campanha arquivada (veja em Arquivadas)." if camp.arquivada else "Campanha de volta à lista.")
        return voltar("/campanhas" if camp.arquivada else f"/campanhas/{cid}")
    if acao == "assumir-empresas":
        r = campanhas.assumir_empresas(db, camp, usuario)
        registrar_log(db, usuario, "assumiu_empresas_campanha", "campanha", cid, f"{r['empresas']} empresas", request)
        db.commit()
        dono = db.get(Usuario, camp.usuario_id) if camp.usuario_id else None
        texto = (f"{r['empresas']} empresa(s) passaram para {dono.nome if dono else 'quem criou a campanha'} e "
                 f"{r['mensagens']} mensagem(ns) tiveram a assinatura trocada.")
        if r["mantidas"]:
            texto += (f" {r['mantidas']} empresa(s) continuam com o responsável atual porque ele já conversou com elas "
                      "(tire da campanha se não for para enviar).")
        avisar(request, texto)
        return voltar(f"/campanhas/{cid}")
    if acao == "conferir-emails":
        r = campanhas.conferir_emails(db, camp)
        registrar_log(db, usuario, "conferiu_emails_campanha", "campanha", cid,
                      f"{r['invalidos']} de {r['conferidos']} inválidos", request)
        db.commit()
        if r["invalidos"]:
            avisar(request, f"Conferi {r['conferidos']} e-mails: {r['invalidos']} não existem (domínio sem e-mail ou "
                            f"endereço mal escrito) e saíram da campanha ({r['toques_cancelados']} envios cancelados). "
                            "As devoluções \"Endereço não encontrado\" também tiram o e-mail sozinhas.")
        else:
            avisar(request, f"Conferi {r['conferidos']} e-mails: nenhum com domínio inexistente. Endereços que só "
                            "falham na entrega (caixa que não existe) saem sozinhos quando a devolução chega.")
        return voltar(f"/campanhas/{cid}")
    if acao == "aprovar" and camp.status == "aguardando_aprovacao":
        n = campanhas.aprovar(db, camp, usuario)
        registrar_log(db, usuario, "aprovou_campanha", "campanha", cid, f"{n} tarefas", request)
        if camp.whatsapp_sozinho:
            avisar(request, f"Campanha aprovada: {n} contatos programados. Os e-mails e os WhatsApps entram na fila e "
                            "saem sozinhos, cada um no seu horário (WhatsApp: um a cada 3 minutos, com os limites do número).")
        else:
            avisar(request, f"Campanha aprovada: {n} contatos programados. Os WhatsApps de cada dia aparecem aqui na "
                            "campanha para enviar com um clique (para quem já conversou com a MS, saem sozinhos); "
                            "e-mails saem pela fila.")
    elif acao == "cancelar" and camp.status in ("aguardando_aprovacao", "ativa", "gerando", "erro"):
        n = campanhas.cancelar(db, camp, usuario)
        registrar_log(db, usuario, "cancelou_campanha", "campanha", cid, f"{n} tarefas", request)
        avisar(request, "Campanha cancelada. Nenhuma mensagem pendente será enviada.")
    elif acao == "pausar" and camp.status == "ativa":
        camp.status = "pausada"
        avisar(request, "Campanha pausada: a fila não envia nada desta campanha até retomar.")
    elif acao == "retomar" and camp.status == "pausada":
        camp.status = "ativa"
        avisar(request, "Campanha retomada.")
    elif acao == "editar-mensagem":
        t = db.get(Tarefa, util.para_int(form.get("tarefa_id")) or 0)
        if t and t.campanha_id == cid and t.status in ("rascunho", "pendente"):
            novo = str(form.get("mensagem", "")).strip()
            regra = sdr.texto_sem_spam if camp.tipo in ("empresas_novas", "renovacao") else sdr.texto_seguro
            if not regra(novo):
                avisar(request, "A mensagem tem termos que a SDR não pode usar (valores, %, desconto, exclusividade, "
                                "contrato ou frases de spam). Ajuste o texto.", "erro")
            else:
                t.mensagem, t.assunto = novo, str(form.get("assunto", t.assunto))[:200]
                outro = str(form.get("outro_modelo", "")).strip()
                if outro and regra(outro):
                    if t.canal == "email":
                        t.mensagem_whatsapp = outro
                    else:
                        t.mensagem_email, t.assunto_email = outro, str(form.get("outro_assunto", t.assunto_email))[:200]
                if t.canal == "email":
                    t.mensagem_email, t.assunto_email = t.mensagem, t.assunto
                else:
                    t.mensagem_whatsapp = t.mensagem
                avisar(request, "Mensagens atualizadas.")
    elif acao == "trocar-canal":
        t = db.get(Tarefa, util.para_int(form.get("tarefa_id")) or 0)
        if t and t.campanha_id == cid and t.status in ("rascunho", "pendente") and t.canal in ("email", "whatsapp"):
            if t.canal == "whatsapp" and t.mensagem_email:
                t.canal, t.mensagem, t.assunto = "email", t.mensagem_email, t.assunto_email
            elif t.canal == "email" and t.mensagem_whatsapp:
                t.canal, t.mensagem, t.assunto = "whatsapp", t.mensagem_whatsapp, ""
            t.acao = f"Contato por {t.canal}"
            avisar(request, f"Este toque agora vai por {'e-mail' if t.canal == 'email' else 'WhatsApp'}.")
    elif acao == "whatsapp-lead":
        lead = db.get(Lead, util.para_int(form.get("lead_id")))
        digitos = util.normalizar_telefone(str(form.get("whatsapp", "")))
        if not lead or not db.execute(select(Tarefa.id).where(Tarefa.campanha_id == cid, Tarefa.lead_id == lead.id)).first():
            avisar(request, "Empresa não encontrada nesta campanha.", "erro")
        elif len(digitos) < 10:
            avisar(request, "Digite o WhatsApp com DDD, por exemplo (81) 99999-0000.", "erro")
        else:
            lead.whatsapp = digitos
            limpar_campos(lead)  # formata e recalcula a chave: sem ela, a resposta pelo WhatsApp não acha a empresa
            historico(db, lead.id, "contato", f"WhatsApp encontrado pelo time e cadastrado: {util.formatar_telefone(digitos)}",
                      usuario)
            avisar(request, f"WhatsApp de {lead.empresa} salvo. As mensagens da campanha vão para este número.")
        db.commit()
        return voltar(f"/campanhas/{cid}#ligacoes")
    elif acao == "corrigir-email":
        lead = db.get(Lead, util.para_int(form.get("lead_id")) or 0)
        if not lead or not db.execute(select(Tarefa.id).where(Tarefa.campanha_id == cid, Tarefa.lead_id == lead.id)).first():
            avisar(request, "Empresa não encontrada nesta campanha.", "erro")
        else:
            try:
                r = campanhas.corrigir_email(db, camp, lead, str(form.get("email", "")), usuario)
            except ValueError as erro:
                texto = str(erro)
                avisar(request, f"{lead.empresa}: {texto[:1].upper()}{texto[1:]}.", "erro")
            else:
                partes = []
                if r["reenvio"]:
                    partes.append("o e-mail que tinha voltado será reenviado hoje")
                if r["reativados"]:
                    partes.append(f"{r['reativados']} envio(s) parado(s) voltaram para o cronograma")
                resumo = "; ".join(partes)
                avisar(request, f"E-mail de {lead.empresa} corrigido." + (f" {resumo[:1].upper()}{resumo[1:]}."
                                                                          if resumo else ""))
        db.commit()
        return voltar(f"/campanhas/{cid}#emails-invalidos")
    elif acao == "testar":
        alvo = _campanha(db, util.para_int(form.get("campanha_teste")) or cid, usuario)
        canal = "whatsapp" if form.get("canal_teste") == "whatsapp" else "email"
        if canal == "email":
            destino = str(form.get("email_teste", "")).strip()
            invalido = "Digite um e-mail de teste válido." if not util.email_valido(destino) else ""
        else:
            digitos = util.normalizar_telefone(str(form.get("whatsapp_teste", "")))
            destino = "55" + digitos if digitos else ""
            invalido = "Digite o seu celular com DDD para receber o teste no WhatsApp." if not digitos else ""
        if invalido:
            avisar(request, invalido, "erro")
        else:
            r = campanhas.enviar_teste(db, alvo, usuario, canal, destino, util.para_int(form.get("empresas")) or 1,
                                       form.get("toques") == "todos")
            registrar_log(db, usuario, "testou_campanha", "campanha", alvo.id,
                          f"{r['enviadas']} mensagens de {canal} de teste para {destino}", request)
            if r["enviadas"]:
                para = destino if canal == "email" else util.formatar_telefone(destino[2:])
                avisar(request, f"Teste da campanha \"{alvo.nome}\" enviado: {r['enviadas']} "
                                f"{'e-mail(s)' if canal == 'email' else 'WhatsApp(s)'} para {para}. Nenhum lead recebeu nada.")
            for erro in r["erros"]:
                avisar(request, erro, "erro")
            if not r["enviadas"] and not r["erros"]:
                avisar(request, f"A campanha \"{alvo.nome}\" não tem mensagens de "
                                f"{'e-mail' if canal == 'email' else 'WhatsApp'} para testar. Escolha o outro canal.", "alerta")
        db.commit()
        return voltar(f"/campanhas/{cid}#testar")
    elif acao in ("disparar-whatsapp", "disparar-email"):
        canal = acao.split("-")[1]
        nome = "WhatsApp" if canal == "whatsapp" else "e-mail"
        if camp.status != "ativa":
            avisar(request, "Só dá para disparar uma campanha aprovada e ativa.", "erro")
            return voltar(f"/campanhas/{cid}")
        r = campanhas.disparar(db, camp, usuario, canal)
        partes = [f"{r['enviados']} mensagem(ns) de {nome} "
                  + ("na fila do WhatsApp (sai uma por vez, com pausas)" if canal == "whatsapp" else "enviada(s)")]
        motivos = campanhas.resumo_dos_motivos(r["motivos"])
        if r["bloqueados"]:
            partes.append(f"{r['bloqueados']} não saíram agora" + (f": {motivos}" if motivos else ""))
        if r["parou"]:
            partes.append("Parou: " + r["parou"])
        partes += r["erros"]
        # o motivo fica no registro: dá para entender depois por que um disparo saiu com 0
        detalhes = f"{r['enviados']} enviadas" + (f"; não saíram: {motivos}" if motivos else "") \
            + (f"; parou: {r['parou']}" if r["parou"] else "")
        registrar_log(db, usuario, f"disparou_campanha_{canal}", "campanha", cid, detalhes[:1000], request)
        avisar(request, ". ".join(partes) + ".", "ok" if r["enviados"] and not (r["parou"] or r["erros"]) else "alerta")
        db.commit()
        return voltar(f"/campanhas/{cid}#disparar")
    elif acao == "numero":
        if not autorizacao.pode(usuario, "campanhas.escolher_numero"):
            avisar(request, "Só o administrador escolhe o número da campanha.", "erro")
        else:
            camp.conexao_id = _numero_escolhido(db, usuario, form)
            avisar(request, "Número da campanha atualizado.")
    elif acao == "whatsapp-sozinho":
        if not autorizacao.pode(usuario, "campanhas.whatsapp_sozinho"):
            avisar(request, "Só o administrador liga ou desliga o WhatsApp automático da campanha.", "erro")
        elif camp.tipo in campanhas.TIPOS_QUE_SAEM_SOZINHOS:
            avisar(request, "Nas campanhas de Empresas novas o WhatsApp já sai sozinho depois da aprovação.", "alerta")
        else:
            ligar = form.get("ligar") == "1"
            camp.whatsapp_sozinho = ligar
            registrar_log(db, usuario, "ligou_whatsapp_sozinho" if ligar else "desligou_whatsapp_sozinho", "campanha",
                          cid, "WhatsApp sai sozinho depois da aprovação, também para contato frio" if ligar
                          else "Contato frio volta a esperar o clique", request)
            if not ligar:
                avisar(request, "WhatsApp automático desligado: quem nunca conversou com a MS volta a esperar o seu clique.")
            elif camp.status == "ativa" and camp.aprovado_em:
                avisar(request, "WhatsApp automático ligado: as mensagens desta campanha saem sozinhas, uma a cada "
                                "3 minutos, no horário de envio e com os limites do número.")
            else:
                avisar(request, "WhatsApp automático ligado: começa quando a campanha for aprovada.")
        db.commit()
        return voltar(f"/campanhas/{cid}#whatsapp-sozinho")
    elif acao == "remover-lead":
        lead_id = util.para_int(form.get("lead_id"))
        motivo = str(form.get("motivo", ""))
        if motivo not in config.MOTIVOS_RETIRADA:
            avisar(request, "Escolha o motivo para tirar a empresa da campanha.", "erro")
            return voltar(f"/campanhas/{cid}")
        from ..leads_servico import historico as registrar_historico

        registrar_historico(db, lead_id, "campanha", f"Tirada da campanha \"{camp.nome}\". Motivo: {motivo}", usuario)
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid, Tarefa.lead_id == lead_id,
                                                 Tarefa.status.in_(["rascunho", "pendente"]))).scalars():
            t.status, t.concluida_em, t.resultado = "cancelada", agora(), f"Removido da campanha: {motivo}"
            if t.lead and t.lead.status == "Abordagem criada":
                t.lead.status = "Pesquisando" if t.lead.pesquisado_em else "Novo"
        avisar(request, "Empresa removida da campanha.")
    db.commit()
    return voltar(f"/campanhas/{cid}")


# ---------------------------------------------------------------- Inteligência de Prospecção

@rotas.get("/inteligencia")
def inteligencia(request: Request, periodo: str = "90d", uf: str = "", cidade: str = "",
                 usuario: Usuario = Depends(exige("inteligencia.ver")), db: Session = Depends(obter_db)):
    p = metricas.periodo(periodo)
    return tela(request, "inteligencia.html", {
        "p": p, "periodo": periodo, "uf": uf, "cidade": cidade, **metricas.inteligencia(db, usuario, p),
        "oportunidades": metricas.oportunidades_de_parceria(db, uf, cidade),
        "ia_ligada": ia.disponivel(), "sugestoes_ia": request.session.pop("sugestoes_categorias", None),
    })


ESQUEMA_CATEGORIAS = {
    "type": "object",
    "properties": {"sugestoes": {"type": "array", "items": {"type": "object", "properties": {
        "nome": {"type": "string"}, "motivo": {"type": "string"}, "potencial": {"type": "string",
                                                                              "enum": ["Alto", "Médio", "Baixo"]},
        "palavras_chave": {"type": "string"}, "estrategia": {"type": "string"}},
        "required": ["nome", "motivo", "potencial", "palavras_chave", "estrategia"], "additionalProperties": False}}},
    "required": ["sugestoes"], "additionalProperties": False,
}


@rotas.post("/inteligencia/sugerir-categorias", dependencies=[Depends(verificar_csrf)])
def sugerir_categorias(request: Request, usuario: Usuario = Depends(exige("categorias.sugerir")), db: Session = Depends(obter_db)):
    if not ia.disponivel():
        avisar(request, "Para a IA sugerir novas categorias, configure ANTHROPIC_API_KEY no .env.", "alerta")
        return voltar("/inteligencia")
    dados = metricas.inteligencia(db, usuario, metricas.periodo("tudo"))
    atuais = [c.nome for c in db.execute(select(Categoria)).scalars()]
    numeros = [f"{s['nome']}: {s['contatados']} contatados, resposta {s['taxa_resposta']}%, {s['parceiros']} parceiros"
               for s in dados["segmentos"]]
    pedido = ("Sugira até 5 NOVAS categorias de empresas que poderiam ser parceiras comerciais da MS Certificação "
              "Digital (indicando certificados digitais aos próprios clientes). Não repita as atuais: "
              f"{', '.join(atuais)}.\nResultados até agora: {'; '.join(numeros) or 'ainda sem dados'}.\n"
              "Para cada uma: motivo (por que os clientes dela precisam de certificado), potencial, palavras_chave "
              "para achar no nome da empresa (separadas por vírgula) e estratégia de abordagem.")
    try:
        request.session["sugestoes_categorias"] = ia.perguntar(db, pedido, ESQUEMA_CATEGORIAS, 2500)["sugestoes"]
    except ia.ErroDaIA as erro:
        avisar(request, str(erro), "erro")
    return voltar("/inteligencia#sugestoes")


# ---------------------------------------------------------------- Categorias e base de conhecimento

@rotas.get("/categorias")
def categorias(request: Request, usuario: Usuario = Depends(exige("categorias.ver")), db: Session = Depends(obter_db)):
    from .. import base_receita

    return tela(request, "categorias.html", {
        "categorias": db.execute(select(Categoria).order_by(Categoria.prioridade)).scalars().all(),
        "contagem": base_receita.contar(db), "nova": request.query_params.get("nova", ""),
        "motivo_novo": request.query_params.get("motivo", ""), "palavras_novas": request.query_params.get("palavras", ""),
        "estrategia_nova": request.query_params.get("estrategia", ""),
    })


@rotas.post("/categorias/{cid:int}", dependencies=[Depends(verificar_csrf)])
async def salvar_categoria(request: Request, cid: int, usuario: Usuario = Depends(exige("categorias.editar")), db: Session = Depends(obter_db)):
    form = await request.form()
    c = Categoria() if cid == 0 else db.get(Categoria, cid)
    if c is None:
        raise HTTPException(404)
    nome = str(form.get("nome", "")).strip()
    if not nome:
        avisar(request, "Informe o nome da categoria.", "erro")
        return voltar("/categorias")
    if cid == 0:
        c.codigo = util.chave_texto(nome).replace(" ", "_")[:40]
        if db.execute(select(Categoria.id).where(Categoria.codigo == c.codigo)).first():
            c.codigo = f"{c.codigo[:34]}_{agora():%H%M%S}"
        c.sugerida_pela_ia = form.get("sugerida") == "1"
    cnaes = [x for x in re.split(r"[^\d]+", str(form.get("cnaes", ""))) if x]
    cnaes_palavra = [x for x in re.split(r"[^\d]+", str(form.get("cnaes_com_palavra", ""))) if x]
    invalidos = [x for x in cnaes + cnaes_palavra if len(x) != 7]
    if invalidos:
        avisar(request, f"CNAE deve ter 7 números (ex.: 6920601). Confira: {', '.join(invalidos)}.", "erro")
        return voltar("/categorias")
    c.nome, c.cnaes, c.cnaes_com_palavra = nome[:120], ",".join(cnaes), ",".join(cnaes_palavra)
    c.palavras_chave = str(form.get("palavras_chave", ""))[:500]
    c.prioridade = util.para_int(form.get("prioridade")) or 50
    c.aderencia = max(0, min(util.para_int(form.get("aderencia")) or 0, 25))
    c.recorrente = form.get("recorrente") == "on"
    c.ativa = form.get("ativa") == "on"
    for campo in ("motivo", "estrategia", "abertura", "gancho"):
        setattr(c, campo, str(form.get(campo, "")).strip())
    if cid == 0:
        db.add(c)
    registrar_log(db, usuario, "salvou_categoria", "categoria", c.id, c.nome, request)
    db.commit()
    avisar(request, "Categoria salva." + (" Para buscar empresas com os CNAEs novos, importe a base da Receita de novo "
                                          "(Configurações > Integrações)." if cnaes or cnaes_palavra else ""))
    return voltar("/categorias")


@rotas.get("/conhecimento")
def conhecimento(request: Request, usuario: Usuario = Depends(exige("conhecimento.ver")), db: Session = Depends(obter_db)):
    return tela(request, "conhecimento.html", {"itens": db.execute(select(Conhecimento).order_by(Conhecimento.id)).scalars().all()})


@rotas.post("/conhecimento/{kid:int}", dependencies=[Depends(verificar_csrf)])
def salvar_conhecimento(request: Request, kid: int, pergunta: str = Form(...), resposta: str = Form(...),
                        ativa: str = Form(""), excluir: str = Form(""), usuario: Usuario = Depends(exige("conhecimento.editar")),
                        db: Session = Depends(obter_db)):
    item = Conhecimento() if kid == 0 else db.get(Conhecimento, kid)
    if item is None:
        raise HTTPException(404)
    if excluir and kid:
        db.delete(item)
        db.commit()
        avisar(request, "Item excluído.")
        return voltar("/conhecimento")
    if not sdr.texto_seguro(resposta):
        avisar(request, "A resposta não pode ter valores, percentuais, desconto, exclusividade ou contrato: esses "
                        "assuntos são sempre do time humano.", "erro")
        return voltar("/conhecimento")
    item.pergunta, item.resposta, item.ativa = pergunta.strip()[:250], resposta.strip(), ativa == "on" or kid == 0
    if kid == 0:
        db.add(item)
    db.commit()
    avisar(request, "Base de conhecimento atualizada.")
    return voltar("/conhecimento")


@rotas.get("/notificacoes")
def notificacoes(request: Request, usuario: Usuario = Depends(exige("painel.ver")), db: Session = Depends(obter_db)):
    lista = db.execute(select(Notificacao).where(Notificacao.usuario_id == usuario.id)
                       .order_by(Notificacao.criado_em.desc()).limit(100)).scalars().all()
    for n in lista:
        n.lida = True
    db.commit()
    return tela(request, "notificacoes.html", {"lista": lista})

