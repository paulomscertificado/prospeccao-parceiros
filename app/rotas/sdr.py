"""Telas da IA SDR: Novas oportunidades (handoff), Campanhas (com aprovação), Inteligência de Prospecção,
Categorias de parceiros, Base de conhecimento e avisos."""

import json
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import agenda_horarios, campanhas, config, ia, metricas, sdr, util
from ..banco import agora, obter_db
from ..leads_servico import historico, pode_ver
from ..modelos import (Cadencia, Campanha, Categoria, Conhecimento, Lead, Notificacao, Oportunidade, Tarefa,
                       Usuario)
from ..seguranca import admin, equipe, ferramentas, gestao, registrar_log, ve_tudo, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()


def _lead(db: Session, lead_id: int, usuario: Usuario) -> Lead:
    lead = db.get(Lead, lead_id)
    if not lead or not pode_ver(usuario, lead):
        raise HTTPException(404)
    return lead


def _equipe(db: Session):
    return list(db.execute(select(Usuario).where(Usuario.perfil.in_(["vendedor", "gestor", "admin"]),
                                                 Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars())


# ---------------------------------------------------------------- Novas oportunidades (handoff)

@rotas.get("/oportunidades")
def oportunidades(request: Request, ver: str = "novas", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    consulta = select(Oportunidade).join(Lead, Oportunidade.lead_id == Lead.id)
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where((Lead.vendedor_id == usuario.id) | (Lead.vendedor_id.is_(None)))
    consulta = consulta.where(Oportunidade.status == "nova") if ver == "novas" else consulta.where(
        Oportunidade.status != "nova")
    lista = db.execute(consulta.order_by(Oportunidade.temperatura, Oportunidade.criado_em.desc()).limit(200)).scalars().all()
    # Avisos sobre oportunidades contam como lidos ao abrir a tela.
    for n in db.execute(select(Notificacao).where(Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False),
                                                  Notificacao.link.like("/oportunidades%"))).scalars():
        n.lida = True
    db.commit()
    return tela(request, "oportunidades.html", {
        "oportunidades": lista, "ver": ver,
        "resumos": {o.id: sdr.resumo_handoff(db, o.lead) for o in lista},
    })


@rotas.post("/oportunidades/{oid:int}/descartar", dependencies=[Depends(verificar_csrf)])
def descartar(request: Request, oid: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    op = db.get(Oportunidade, oid)
    if not op or (usuario.perfil in config.PERFIS_SO_PROPRIOS and op.lead.vendedor_id not in (None, usuario.id)):
        raise HTTPException(404)
    op.status, op.responsavel_id, op.assumida_em = "descartada", usuario.id, agora()
    historico(db, op.lead_id, "sistema", f"Oportunidade descartada por {usuario.nome}.", usuario)
    db.commit()
    return voltar("/oportunidades")


@rotas.post("/leads/{lead_id:int}/assumir", dependencies=[Depends(verificar_csrf)])
def assumir(request: Request, lead_id: int, voltar_para: str = Form(""), usuario: Usuario = Depends(equipe),
            db: Session = Depends(obter_db)):
    lead = db.get(Lead, lead_id)
    if not lead or (usuario.perfil in config.PERFIS_SO_PROPRIOS and lead.vendedor_id not in (None, usuario.id)):
        raise HTTPException(404)
    sdr.assumir_lead(db, lead, usuario)
    registrar_log(db, usuario, "assumiu_lead", "lead", lead.id, request=request)
    db.commit()
    avisar(request, f"Você assumiu {lead.empresa}. A automação deste lead foi parada.")
    return voltar(voltar_para if voltar_para.startswith("/") else f"/leads/{lead_id}#handoff")


@rotas.get("/leads/{lead_id:int}/agendar")
def agendar_tela(request: Request, lead_id: int, responsavel: int | None = None, usuario: Usuario = Depends(equipe),
                 db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario) if usuario.perfil in config.PERFIS_SO_PROPRIOS else db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404)
    resp = db.get(Usuario, responsavel or lead.humano_id or lead.vendedor_id or usuario.id) or usuario
    return tela(request, "agendar.html", {"lead": lead, "responsavel": resp, "equipe": _equipe(db),
                                          "horarios": agenda_horarios.horarios_livres(db, resp, dias=10, quantidade=30),
                                          "nomes_dia": agenda_horarios.NOMES_DIA})


@rotas.post("/leads/{lead_id:int}/agendar", dependencies=[Depends(verificar_csrf)])
def agendar(request: Request, lead_id: int, responsavel_id: int = Form(...), quando: str = Form(...),
            canal: str = Form("video"), pauta: str = Form(""), usuario: Usuario = Depends(equipe),
            db: Session = Depends(obter_db)):
    lead = db.get(Lead, lead_id)
    resp = db.get(Usuario, responsavel_id)
    if not lead or not resp:
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
                    usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
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
def pesquisar(request: Request, lead_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    from ..pesquisa import pesquisar_lead

    lead = _lead(db, lead_id, usuario)
    pesquisar_lead(db, lead, usuario)
    db.commit()
    avisar(request, f"Pesquisa concluída: {lead.fit}, score {lead.score}.")
    return voltar(f"/leads/{lead_id}#perfil")


@rotas.post("/leads/{lead_id:int}/abordagem-sdr", dependencies=[Depends(verificar_csrf)])
def abordagem_sdr(request: Request, lead_id: int, cta: str = Form(""), tom: str = Form("consultivo"),
                  usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
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


def _campanha(db: Session, cid: int, usuario: Usuario) -> Campanha:
    """A campanha, se a pessoa pode vê-la: cada um vê as próprias; administrador e gestor veem todas."""
    camp = db.get(Campanha, cid)
    if not camp or (usuario.perfil in config.PERFIS_SO_PROPRIOS and camp.usuario_id != usuario.id):
        raise HTTPException(404)
    return camp


@rotas.get("/campanhas")
def lista_campanhas(request: Request, ver: str = "todas", de: str = "", usuario: Usuario = Depends(equipe),
                    db: Session = Depends(obter_db)):
    consulta = select(Campanha)
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        consulta = consulta.where(Campanha.usuario_id == usuario.id)  # cada um com as suas campanhas
    elif de == "minhas":
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
    equipe_ = ([] if usuario.perfil in config.PERFIS_SO_PROPRIOS else
               sorted({c.usuario_id for c in db.execute(select(Campanha)).scalars() if c.usuario_id},
                      key=lambda i: pessoas.get(i, "")))
    return tela(request, "campanhas.html", {"campanhas": lista, "contagens": contagens, "ver": ver, "de": de,
                                            "filtros": FILTROS_CAMPANHA, "nomes_cat": nomes_cat, "pessoas": pessoas,
                                            "equipe_campanhas": equipe_})


@rotas.get("/campanhas/nova")
def nova_campanha(request: Request, pedido: str = "", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    from .. import base_receita

    entendido = campanhas.interpretar_pedido(db, pedido) if pedido else None
    contagem = (base_receita.contar(db, entendido["estado"], entendido["cidade"])
                if entendido and entendido.get("cidade") and entendido.get("estado") else {})
    ultima = db.execute(select(Campanha).where(Campanha.cidade != "", Campanha.usuario_id == usuario.id)
                        .order_by(Campanha.criado_em.desc()).limit(1)).scalars().first()
    if not contagem:
        cidade = (entendido or {}).get("cidade") or (ultima.cidade if ultima else "Recife")
        uf = (entendido or {}).get("estado") or (ultima.estado if ultima else "PE")
        contagem = base_receita.contar(db, uf, cidade)
    return tela(request, "campanha_nova.html", {
        "pedido": pedido, "entendido": entendido, "contagem": contagem,
        "ultima_cidade": ultima.cidade if ultima else "", "ultima_uf": ultima.estado if ultima else "",
        "categorias": db.execute(select(Categoria).where(Categoria.ativa.is_(True)).order_by(Categoria.prioridade)).scalars().all(),
        "cadencias": db.execute(select(Cadencia).where(Cadencia.ativa.is_(True))).scalars().all(),
        "cadencia_sdr": campanhas.cadencia_sdr(db), "ia_ligada": ia.disponivel(),
    })


@rotas.get("/api/contagem")
def contagem_cidade(cidade: str = "", uf: str = "", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    """Quantas empresas de cada categoria existem na cidade (para a tela de nova campanha)."""
    from .. import base_receita

    if not cidade.strip() or uf not in config.UFS:
        return {}
    return base_receita.contar(db, uf, cidade)


@rotas.post("/campanhas/nova", dependencies=[Depends(verificar_csrf)])
async def criar_campanha(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    form = await request.form()
    cats = [c for c in form.getlist("categorias") if c]
    cidade, uf = str(form.get("cidade", "")).strip(), str(form.get("estado", "")).strip().upper()
    if not cats or not cidade or uf not in config.UFS:
        avisar(request, "Informe a região (cidade e estado) e pelo menos um segmento.", "erro")
        return voltar("/campanhas/nova?pedido=" + util.chave_texto(str(form.get("pedido", "")))[:200])
    canais = [c for c in form.getlist("canais") if c in ("whatsapp", "email", "linkedin")] or ["whatsapp", "email"]
    cta = str(form.get("cta_livre") or form.get("cta") or "").strip()
    camp = Campanha(
        nome=str(form.get("nome") or _nome_automatico(db, cats, cidade)).strip()[:160],
        pedido=str(form.get("pedido", ""))[:2000], categorias=",".join(cats), cidade=cidade, estado=uf,
        quantidade=max(1, min(util.para_int(form.get("quantidade")) or util.para_int(form.get("quantidade_outra")) or 20, 500)), canais=",".join(canais),
        objetivo=str(form.get("objetivo") or "Encontrar parceiros")[:200], tom=str(form.get("tom") or "consultivo"),
        cta=cta[:200], cadencia_id=util.para_int(form.get("cadencia_id")), usuario_id=usuario.id,
        inicio=util.para_data(form.get("inicio")) or date.today(), status="gerando", personalizar_ia=ia.disponivel(),
    )
    db.add(camp)
    db.flush()
    registrar_log(db, usuario, "criou_campanha", "campanha", camp.id, f"{camp.nome}: {camp.categorias} {cidade}/{uf}", request)
    db.commit()
    campanhas.gerar_em_segundo_plano(camp.id)
    return voltar(f"/campanhas/{camp.id}")


def _nome_automatico(db: Session, cats: list[str], cidade: str) -> str:
    nomes = [n for (n,) in db.execute(select(Categoria.nome).where(Categoria.codigo.in_(cats)))]
    segmento = nomes[0] if len(nomes) == 1 else f"{len(nomes)} segmentos"
    return f"{segmento} – {cidade} – {date.today():%d/%m}"


@rotas.get("/campanhas/{cid:int}")
def ver_campanha(request: Request, cid: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    from .. import conexoes

    camp = _campanha(db, cid, usuario)
    nomes = {c.codigo: c.nome for c in db.execute(select(Categoria)).scalars()}
    whatsapp_hoje = campanhas.whatsapp_de_hoje(db, camp) if camp.status == "ativa" else []
    numero, sem_numero = "", ""
    if whatsapp_hoje:
        try:
            numero_id = conexoes.para_enviar(db, conexoes.responsavel(db, None, usuario))
            numero = (db.get(conexoes.ConexaoWhatsApp, numero_id).nome if db.get(conexoes.ConexaoWhatsApp, numero_id)
                      else numero_id)
        except conexoes.SemNumero as erro:
            sem_numero = str(erro)
    ids_fixo = [int(i) for i in (camp.so_fixo or "").split(",") if i.isdigit()]
    so_fixo = db.execute(select(Lead).where(Lead.id.in_(ids_fixo))).scalars().all() if ids_fixo else []
    testaveis_q = (select(Campanha).where(Campanha.arquivada.is_(False),
                                          Campanha.status.in_(["aguardando_aprovacao", "ativa", "pausada"]))
                   .order_by(Campanha.criado_em.desc()).limit(50))
    if usuario.perfil in config.PERFIS_SO_PROPRIOS:
        testaveis_q = testaveis_q.where(Campanha.usuario_id == usuario.id)
    testaveis = db.execute(testaveis_q).scalars().all()
    if camp not in testaveis:
        testaveis.insert(0, camp)
    contagem = campanhas.mensagens_para_teste(db, [t.id for t in testaveis])
    return tela(request, "campanha.html", {
        "testaveis": [{"id": t.id, "nome": t.nome, **contagem[t.id]} for t in testaveis],
        "so_fixo": so_fixo,
        "andamento": campanhas.andamento(db, camp) if camp.status not in ("gerando", "erro") else [],
        "whatsapp_hoje": whatsapp_hoje, "numero_whatsapp": numero, "sem_numero": sem_numero,
        "pode_gerenciar": ve_tudo(usuario) or camp.usuario_id == usuario.id,
        "dono": db.get(Usuario, camp.usuario_id) if camp.usuario_id else None,
        "c": camp, "resumo": campanhas.resumo_aprovacao(db, camp), "nomes_categorias": nomes,
        "rodando": camp.status == "gerando", "pode_aprovar": ve_tudo(usuario),
        "aprovador": db.get(Usuario, camp.aprovado_por_id) if camp.aprovado_por_id else None,
    })


@rotas.post("/campanhas/{cid:int}/{acao}", dependencies=[Depends(verificar_csrf)])
async def acao_campanha(request: Request, cid: int, acao: str, usuario: Usuario = Depends(equipe),
                        db: Session = Depends(obter_db)):
    camp = _campanha(db, cid, usuario)
    form = await request.form()
    if acao in ("arquivar", "desarquivar", "excluir"):
        if not (ve_tudo(usuario) or camp.usuario_id == usuario.id):
            avisar(request, "Só quem criou a campanha (ou o administrador/gestor) pode arquivar ou excluir.", "erro")
            return voltar(f"/campanhas/{cid}")
        if acao == "excluir":
            if camp.status in ("ativa", "pausada") and not ve_tudo(usuario):
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
    if acao in ("aprovar", "cancelar") and not ve_tudo(usuario):
        avisar(request, "Só administrador ou gestor aprovam ou cancelam campanhas.", "erro")
        return voltar(f"/campanhas/{cid}")
    if acao == "aprovar" and camp.status == "aguardando_aprovacao":
        n = campanhas.aprovar(db, camp, usuario)
        registrar_log(db, usuario, "aprovou_campanha", "campanha", cid, f"{n} tarefas", request)
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
            if not sdr.texto_seguro(novo):
                avisar(request, "A mensagem tem termos que a SDR não pode usar (valores, %, desconto, exclusividade, "
                                "contrato ou frases de spam). Ajuste o texto.", "erro")
            else:
                t.mensagem, t.assunto = novo, str(form.get("assunto", t.assunto))[:200]
                outro = str(form.get("outro_modelo", "")).strip()
                if outro and sdr.texto_seguro(outro):
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
            historico(db, lead.id, "contato", f"WhatsApp encontrado pelo time e cadastrado: {util.formatar_telefone(digitos)}",
                      usuario)
            avisar(request, f"WhatsApp de {lead.empresa} salvo. As mensagens da campanha vão para este número.")
        db.commit()
        return voltar(f"/campanhas/{cid}#ligacoes")
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
    elif acao == "remover-lead":
        lead_id = util.para_int(form.get("lead_id"))
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid, Tarefa.lead_id == lead_id,
                                                 Tarefa.status.in_(["rascunho", "pendente"]))).scalars():
            t.status, t.concluida_em, t.resultado = "cancelada", agora(), "Removido da campanha"
        avisar(request, "Empresa removida da campanha.")
    db.commit()
    return voltar(f"/campanhas/{cid}")


# ---------------------------------------------------------------- Inteligência de Prospecção

@rotas.get("/inteligencia")
def inteligencia(request: Request, periodo: str = "90d", uf: str = "", cidade: str = "",
                 usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
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
def sugerir_categorias(request: Request, usuario: Usuario = Depends(ferramentas), db: Session = Depends(obter_db)):
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
def categorias(request: Request, usuario: Usuario = Depends(ferramentas), db: Session = Depends(obter_db)):
    from .. import base_receita

    return tela(request, "categorias.html", {
        "categorias": db.execute(select(Categoria).order_by(Categoria.prioridade)).scalars().all(),
        "contagem": base_receita.contar(db), "nova": request.query_params.get("nova", ""),
        "motivo_novo": request.query_params.get("motivo", ""), "palavras_novas": request.query_params.get("palavras", ""),
        "estrategia_nova": request.query_params.get("estrategia", ""),
    })


@rotas.post("/categorias/{cid:int}", dependencies=[Depends(verificar_csrf)])
async def salvar_categoria(request: Request, cid: int, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
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
def conhecimento(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    return tela(request, "conhecimento.html", {"itens": db.execute(select(Conhecimento).order_by(Conhecimento.id)).scalars().all()})


@rotas.post("/conhecimento/{kid:int}", dependencies=[Depends(verificar_csrf)])
def salvar_conhecimento(request: Request, kid: int, pergunta: str = Form(...), resposta: str = Form(...),
                        ativa: str = Form(""), excluir: str = Form(""), usuario: Usuario = Depends(ferramentas),
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
def notificacoes(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lista = db.execute(select(Notificacao).where(Notificacao.usuario_id == usuario.id)
                       .order_by(Notificacao.criado_em.desc()).limit(100)).scalars().all()
    for n in lista:
        n.lida = True
    db.commit()
    return tela(request, "notificacoes.html", {"lista": lista})

