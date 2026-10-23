"""Cadências, templates de mensagem, campanhas e a agenda de prospecção ("Minha agenda")."""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import cadencias, config, ia, leads_servico, mensagens, util
from ..banco import agora, ler_config, obter_db, sessao
from ..leads_servico import historico, pode_ver
from ..modelos import Cadencia, Campanha, Lead, PassoCadencia, Tarefa, Template, Usuario
from ..seguranca import equipe, ferramentas, gestao, registrar_log, ve_tudo, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------- Cadências

@rotas.get("/cadencias")
def lista_cadencias(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lista = db.execute(select(Cadencia).order_by(Cadencia.id)).scalars().all()
    templates = db.execute(select(Template).order_by(Template.canal, Template.nome)).scalars().all()
    campanhas = db.execute(select(Campanha).order_by(Campanha.criado_em.desc()).limit(20)).scalars().all()
    resumo = {}
    for c in campanhas:
        tarefas = db.execute(select(Tarefa.status, Tarefa.lead_id).where(Tarefa.campanha_id == c.id)).all()
        leads_ids = {t.lead_id for t in tarefas}
        respondeu = db.execute(select(func.count(Lead.id)).where(Lead.id.in_(leads_ids), Lead.respondeu_em.is_not(None))).scalar() if leads_ids else 0
        interessados = db.execute(select(func.count(Lead.id)).where(Lead.id.in_(leads_ids), Lead.interessado_em.is_not(None))).scalar() if leads_ids else 0
        resumo[c.id] = {"leads": len(leads_ids), "feitas": sum(1 for t in tarefas if t.status == "feita"),
                        "pendentes": sum(1 for t in tarefas if t.status == "pendente"),
                        "responderam": respondeu, "interessados": interessados}
    return tela(request, "cadencias.html", {"cadencias": lista, "templates": templates, "campanhas": campanhas,
                                            "resumo": resumo, "variaveis": mensagens.VARIAVEIS, "ia_ligada": ia.disponivel()})


@rotas.get("/cadencias/{cad_id:int}")
def editar_cadencia_tela(request: Request, cad_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    cad = db.get(Cadencia, cad_id) if cad_id else Cadencia(nome="", descricao="", ativa=True)
    if cad is None:
        raise HTTPException(404)
    templates = db.execute(select(Template).where(Template.ativo.is_(True)).order_by(Template.canal, Template.nome)).scalars().all()
    return tela(request, "cadencia_form.html", {"cad": cad, "templates": templates})


@rotas.post("/cadencias/{cad_id:int}", dependencies=[Depends(verificar_csrf)])
async def salvar_cadencia(request: Request, cad_id: int, usuario: Usuario = Depends(ferramentas), db: Session = Depends(obter_db)):
    form = await request.form()
    cad = db.get(Cadencia, cad_id) if cad_id else Cadencia()
    if cad is None:
        raise HTTPException(404)
    cad.nome = str(form.get("nome", "")).strip() or "Cadência sem nome"
    cad.descricao = str(form.get("descricao", ""))
    cad.ativa = form.get("ativa") == "on"
    dias, canais, acoes, tmpls, horas = (form.getlist(n) for n in ("dia", "canal", "acao", "template_id", "hora"))
    novos = []
    for dia, canal, acao, tid, hora in zip(dias, canais, acoes, tmpls, horas):
        if not str(dia).strip():
            continue
        novos.append(PassoCadencia(dia=max(1, util.para_int(dia) or 1), canal=canal if canal in config.CANAIS else "whatsapp",
                                   acao=str(acao).strip(), template_id=util.para_int(tid), hora=str(hora or "09:00")[:5]))
    if not novos:
        avisar(request, "Adicione pelo menos um passo à cadência.", "erro")
        return voltar(f"/cadencias/{cad_id}")
    # Tarefas já criadas continuam valendo; só os passos da cadência são trocados.
    for p in list(cad.passos):
        for t in db.execute(select(Tarefa).where(Tarefa.passo_id == p.id)).scalars():
            t.passo_id = None
    cad.passos = sorted(novos, key=lambda p: p.dia)
    if not cad_id:
        db.add(cad)
    registrar_log(db, usuario, "salvou_cadencia", "cadencia", cad.id, cad.nome, request)
    db.commit()
    avisar(request, "Cadência salva.")
    return voltar("/cadencias")


# ---------------------------------------------------------------- Templates

@rotas.get("/templates/{tid:int}")
def template_tela(request: Request, tid: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    t = db.get(Template, tid) if tid else Template(nome="", canal="whatsapp", assunto="", corpo="", ativo=True, nome_meta="")
    if t is None:
        raise HTTPException(404)
    exemplo = Lead(empresa="Contabilidade Exemplo", responsavel="João Silva", cidade="São Paulo", estado="SP",
                   especialidade="Contabilidade empresarial")
    previa = mensagens.montar(db, t, exemplo, usuario) if tid else ("", "")
    return tela(request, "template_form.html", {"t": t, "variaveis": mensagens.VARIAVEIS, "previa": previa,
                                                "ia_ligada": ia.disponivel()})


@rotas.post("/templates/{tid:int}", dependencies=[Depends(verificar_csrf)])
def salvar_template(request: Request, tid: int, nome: str = Form(...), canal: str = Form(...), assunto: str = Form(""),
                    corpo: str = Form(...), nome_meta: str = Form(""), ativo: str = Form(""),
                    usuario: Usuario = Depends(ferramentas), db: Session = Depends(obter_db)):
    t = db.get(Template, tid) if tid else Template()
    if t is None:
        raise HTTPException(404)
    t.nome, t.canal, t.assunto, t.corpo = nome.strip(), canal, assunto.strip(), corpo.strip()
    t.nome_meta, t.ativo = nome_meta.strip(), ativo == "on"
    if not tid:
        db.add(t)
    db.flush()
    registrar_log(db, usuario, "salvou_template", "template", t.id, t.nome, request)
    db.commit()
    avisar(request, "Template salvo.")
    return voltar(f"/templates/{t.id}")


@rotas.post("/templates/criar-com-ia", dependencies=[Depends(verificar_csrf)])
def template_ia(request: Request, canal: str = Form(...), objetivo: str = Form(...), usuario: Usuario = Depends(ferramentas),
                db: Session = Depends(obter_db)):
    try:
        dados = ia.criar_template(db, canal, objetivo)
    except ia.ErroDaIA as erro:
        avisar(request, str(erro), "erro")
        return voltar("/cadencias#templates")
    t = Template(nome=dados["nome"][:120], canal=canal, assunto=dados.get("assunto", "")[:200], corpo=dados["corpo"], ativo=False)
    db.add(t)
    db.commit()
    avisar(request, "Template criado pela IA (ainda desativado). Revise o texto, marque \"Ativo\" e salve.")
    return voltar(f"/templates/{t.id}")


# ---------------------------------------------------------------- Agenda

def _consulta_agenda(usuario: Usuario, filtro_usuario: int | None):
    consulta = select(Tarefa)
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where(Tarefa.usuario_id == usuario.id)
    elif filtro_usuario:
        consulta = consulta.where(Tarefa.usuario_id == filtro_usuario)
    return consulta


@rotas.get("/agenda")
def agenda(request: Request, ver: str = "hoje", canal: str = "", tipo: str = "", responsavel: int | None = None,
           usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    hoje = date.today()
    consulta = _consulta_agenda(usuario, responsavel)
    if ver == "hoje":
        consulta = consulta.where(Tarefa.status == "pendente", Tarefa.data <= hoje)
    elif ver == "semana":
        consulta = consulta.where(Tarefa.status == "pendente", Tarefa.data <= hoje + timedelta(days=7))
    elif ver == "proximas":
        consulta = consulta.where(Tarefa.status == "pendente", Tarefa.data > hoje)
    elif ver == "feitas":
        consulta = consulta.where(Tarefa.status.in_(["feita", "pulada", "cancelada"]))
    if canal:
        consulta = consulta.where(Tarefa.canal == canal)
    if tipo:
        consulta = consulta.where(Tarefa.tipo == tipo)
    ordem = [Tarefa.concluida_em.desc()] if ver == "feitas" else [Tarefa.data, Tarefa.hora, Tarefa.id]
    tarefas = db.execute(consulta.order_by(*ordem).limit(300)).scalars().all()
    pendentes_hoje = db.execute(_consulta_agenda(usuario, responsavel).with_only_columns(func.count(Tarefa.id))
                                .where(Tarefa.status == "pendente", Tarefa.data <= hoje)).scalar()
    usuarios = db.execute(select(Usuario).where(Usuario.perfil != "parceiro", Usuario.ativo.is_(True))).scalars().all()
    bloqueios = {t.id: mensagens.bloqueio_de_envio(db, t.lead, t.canal) for t in tarefas
                 if t.status == "pendente" and t.lead and t.canal in ("whatsapp", "email")}
    from ..campanhas import whatsapp_liberado

    # Passos de WhatsApp de campanha que a IA SDR manda sozinha (contato que já conversou com a MS)
    automaticas = {t.id for t in tarefas if t.status == "pendente" and t.canal == "whatsapp" and t.lead and t.campanha_id
                   and ler_config(db, "enviar_whatsapp_automatico") == "1" and whatsapp_liberado(db, t.lead)}
    return tela(request, "agenda.html", {
        "tarefas": tarefas, "automaticas": automaticas, "ver": ver, "canal": canal, "tipo": tipo, "pendentes_hoje": pendentes_hoje,
        "usuarios": usuarios if ve_tudo(usuario) else [], "responsavel": responsavel, "bloqueios": bloqueios,
        "limites": {c: (mensagens.enviadas_hoje(db, c), mensagens.limite_diario(db, c)) for c in ("whatsapp", "email")},
    })


def _tarefa(db: Session, tarefa_id: int, usuario: Usuario) -> Tarefa:
    t = db.get(Tarefa, tarefa_id)
    if not t or (usuario.perfil in config.PERFIS_SO_PROPRIOS and t.usuario_id != usuario.id
                 and not (t.lead and pode_ver(usuario, t.lead))):
        raise HTTPException(404)
    return t


@rotas.post("/agenda/{tarefa_id:int}/{acao}", dependencies=[Depends(verificar_csrf)])
def acao_tarefa(request: Request, tarefa_id: int, acao: str, resultado: str = Form(""), data: str = Form(""),
                hora: str = Form(""), voltar_para: str = Form("/agenda"), usuario: Usuario = Depends(equipe),
                db: Session = Depends(obter_db)):
    t = _tarefa(db, tarefa_id, usuario)
    lead = t.lead
    if not voltar_para.startswith("/"):
        voltar_para = "/agenda"
    if acao == "feita":
        t.status, t.concluida_em, t.resultado = "feita", agora(), resultado
        if lead:
            texto = f"{t.acao}" + (f" – {resultado}" if resultado else "")
            if t.tipo == "reuniao":
                historico(db, lead.id, "reuniao", f"Reunião realizada. {resultado}", usuario)
                lead.ultimo_contato = agora()
            else:
                leads_servico.registrar_contato(db, lead, t.canal, texto, usuario)
        if t.parceiro:
            t.parceiro.ultimo_contato = agora()
        avisar(request, "Tarefa concluída.")
    elif acao == "respondeu" and lead:
        t.status, t.concluida_em, t.resultado = "feita", agora(), "O lead respondeu"
        if resultado.strip():
            from .. import sdr

            analise = sdr.processar_resposta(db, lead, resultado, t.canal, usuario)
            request.session["analise_resposta"] = {k: v for k, v in analise.items() if k != "oportunidade_id"}
            avisar(request, f"Resposta classificada como {analise['classe']}."
                   + (" A automação parou e o lead virou OPORTUNIDADE para o time humano."
                      if analise["classe"] in config.CLASSES_QUENTES else ""))
            voltar_para = f"/leads/{lead.id}#resposta"
        else:
            leads_servico.registrar_resposta(db, lead, t.canal, "", usuario)
            avisar(request, "Resposta registrada! As próximas tentativas da cadência foram canceladas.")
    elif acao == "enviar-whatsapp":
        from .. import sdr

        telefone = (t.cliente.telefone if t.cliente else "") if not lead else ""
        try:
            sdr.enviar_whatsapp_conectado(db, t.mensagem, usuario, lead=lead, telefone=telefone,
                                          nome=t.cliente.contato or t.cliente.nome if t.cliente else "", tarefa=t)
            avisar(request, "Mensagem colocada na fila do WhatsApp conectado (sai respeitando as pausas e o horário).")
        except sdr.EnvioRecusado as erro:
            avisar(request, str(erro), "erro")
            return voltar(voltar_para)
    elif acao == "pular":
        t.status, t.concluida_em, t.resultado = "pulada", agora(), resultado or "Pulada"
    elif acao == "remarcar":
        nova = util.para_data(data)
        if nova:
            t.data = nova
            t.hora = (hora or t.hora)[:5]
            avisar(request, f"Remarcada para {nova:%d/%m/%Y}.")
    elif acao == "invalido" and lead:
        t.status, t.concluida_em, t.resultado = "feita", agora(), "Contato inválido"
        leads_servico.mudar_status(db, lead, "Perdido", usuario, "Contato inválido")
    elif acao == "opt-out" and lead:
        t.status, t.concluida_em = "cancelada", agora()
        leads_servico.registrar_opt_out(db, lead, usuario, "pedido do contato registrado na agenda")
        avisar(request, "Opt-out registrado.")
    else:
        raise HTTPException(400)
    if lead:
        cadencias.atualizar_proximo_contato(db, lead)
    db.commit()
    return voltar(voltar_para)


# ---------------------------------------------------------------- Campanha personalizada pela IA

def personalizar_campanha_em_segundo_plano(campanha_id: int, usuario_id: int) -> None:
    """Troca a mensagem do PRIMEIRO passo de cada lead da campanha por uma mensagem escrita pela IA."""
    from ..campanhas import personalizar

    personalizar(campanha_id, usuario_id)
