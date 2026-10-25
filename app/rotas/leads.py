"""Leads (banco de leads), pipeline Kanban, prospecção automática e importação."""

import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import cadencias, config, ia, leads_servico, mensagens, planilhas, prospeccao, score, sdr, util
from ..banco import agora, obter_db
from ..integracoes import email_smtp, whatsapp_cloud
from ..leads_servico import filtrar_por_usuario, historico, pode_ver
from ..modelos import Busca, Cadencia, Campanha, Categoria, Historico, Lead, Mensagem, Tarefa, Template, Usuario
from ..seguranca import equipe, gestao, registrar_log, ve_tudo, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()
POR_PAGINA = 50


def _lead(db: Session, lead_id: int, usuario: Usuario) -> Lead:
    lead = db.get(Lead, lead_id)
    if not lead or not pode_ver(usuario, lead):
        raise HTTPException(404)
    return lead


def _vendedores(db: Session):
    return list(db.execute(select(Usuario).where(Usuario.perfil.in_(["vendedor", "gestor", "admin"]),
                                                 Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars())


def _dados_do_form(form) -> dict:
    dados = {c: form.get(c, "") for c in leads_servico.CAMPOS_TEXTO + leads_servico.CAMPOS_NUMERO if c in form}
    if "empresa" in form:  # formulário completo: caixa desmarcada = False
        for c in leads_servico.CAMPOS_MARCA:
            dados[c] = form.get(c) == "on"
    if "vendedor_id" in form:
        dados["vendedor_id"] = util.para_int(form.get("vendedor_id"))
    if "categoria_id" in form:
        dados["categoria_id"] = util.para_int(form.get("categoria_id"))
    if "proximo_contato" in form:
        dados["proximo_contato"] = form.get("proximo_contato")
    return dados


# ---------------------------------------------------------------- Lista

@rotas.get("/leads")
def lista(request: Request, q: str = "", status: str = "", potencial: str = "", uf: str = "", cidade: str = "",
          vendedor: str = "", origem: str = "", ordem: str = "score", pagina: int = 1,
          usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    consulta = filtrar_por_usuario(select(Lead).where(Lead.anonimizado.is_(False)), usuario)
    if q:
        termo = f"%{q.strip()}%"
        digitos = util.so_digitos(q)
        condicoes = [Lead.empresa.ilike(termo), Lead.responsavel.ilike(termo), Lead.email.ilike(termo),
                     Lead.cidade.ilike(termo)]
        if len(digitos) >= 4:
            condicoes += [Lead.chave_cnpj.contains(digitos), Lead.chave_telefone.contains(digitos),
                          Lead.chave_whatsapp.contains(digitos)]
        consulta = consulta.where(or_(*condicoes))
    if status == "abertos":
        consulta = consulta.where(Lead.status.not_in(config.STATUS_PERDIDO))
    elif status:
        consulta = consulta.where(Lead.status == status)
    if potencial:
        consulta = consulta.where(Lead.potencial == potencial)
    if uf:
        consulta = consulta.where(Lead.estado == uf)
    if cidade:
        consulta = consulta.where(Lead.cidade.ilike(f"%{cidade}%"))
    if vendedor == "sem" and ve_tudo(usuario):
        consulta = consulta.where(Lead.vendedor_id.is_(None))
    elif vendedor and ve_tudo(usuario):
        consulta = consulta.where(Lead.vendedor_id == util.para_int(vendedor))
    if origem:
        consulta = consulta.where(Lead.origem == origem)
    total = db.execute(select(func.count()).select_from(consulta.subquery())).scalar()
    ordens = {"score": [Lead.score.desc(), Lead.id.desc()], "recentes": [Lead.criado_em.desc()],
              "nome": [Lead.empresa], "proximo": [Lead.proximo_contato.is_(None), Lead.proximo_contato]}
    leads = db.execute(consulta.order_by(*ordens.get(ordem, ordens["score"]))
                       .offset((max(pagina, 1) - 1) * POR_PAGINA).limit(POR_PAGINA)).scalars().all()
    origens = [o for (o,) in db.execute(select(Lead.origem).distinct().order_by(Lead.origem))]
    return tela(request, "leads.html", {
        "leads": leads, "total": total, "pagina": pagina, "paginas": max(1, -(-total // POR_PAGINA)),
        "filtros": {"q": q, "status": status, "potencial": potencial, "uf": uf, "cidade": cidade,
                    "vendedor": vendedor, "origem": origem, "ordem": ordem},
        "origens": origens, "vendedores": _vendedores(db), "potenciais": score.NOMES_POTENCIAL,
        "cadencias": db.execute(select(Cadencia).where(Cadencia.ativa.is_(True))).scalars().all(),
    })


@rotas.post("/leads/acoes", dependencies=[Depends(verificar_csrf)])
async def acoes_em_lote(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    acao = form.get("acao", "")
    leads = [l for l in db.execute(select(Lead).where(Lead.id.in_(ids))).scalars() if pode_ver(usuario, l)]
    voltar_para = form.get("voltar") or "/leads"
    if not leads:
        avisar(request, "Marque pelo menos um lead na lista.", "alerta")
        return voltar(voltar_para)
    if acao == "cadencia":
        cad = db.get(Cadencia, util.para_int(form.get("cadencia_id")) or 0)
        if not cad:
            avisar(request, "Escolha uma cadência.", "alerta")
            return voltar(voltar_para)
        campanha = Campanha(nome=form.get("campanha") or f"{cad.nome} – {date.today():%d/%m/%Y}",
                            cadencia_id=cad.id, usuario_id=usuario.id,
                            busca_id=util.para_int(form.get("busca_id")),
                            personalizar_ia=form.get("personalizar_ia") == "on" and ia.disponivel())
        db.add(campanha)
        db.flush()
        r = cadencias.aplicar(db, cad, leads, usuario, util.para_data(form.get("inicio")) or date.today(), campanha.id)
        registrar_log(db, usuario, "iniciou_campanha", "campanha", campanha.id, f"{r['leads']} leads", request)
        db.commit()
        texto = f"Campanha criada: {r['leads']} leads e {r['tarefas']} tarefas na agenda."
        if r["pulados"]:
            texto += f" {len(r['pulados'])} pulados (opt-out, já em cadência ou encerrados)."
        avisar(request, texto)
        if campanha.personalizar_ia and r["leads"]:
            from .agenda import personalizar_campanha_em_segundo_plano

            personalizar_campanha_em_segundo_plano(campanha.id, usuario.id)
            avisar(request, "A IA está personalizando a primeira mensagem de cada lead. Atualize a agenda em alguns minutos.")
        return voltar("/agenda")
    if acao == "vendedor" and ve_tudo(usuario):
        vid = util.para_int(form.get("vendedor_id"))
        for l in leads:
            l.vendedor_id = vid
            historico(db, l.id, "sistema", "Vendedor responsável alterado.", usuario)
        db.commit()
        avisar(request, f"{len(leads)} leads atribuídos.")
    elif acao == "status" and form.get("status") in config.STATUS_LEAD:
        for l in leads:
            leads_servico.mudar_status(db, l, form.get("status"), usuario)
        db.commit()
        avisar(request, f"Status de {len(leads)} leads alterado.")
    elif acao == "recalcular":
        for l in leads:
            score.atualizar(db, l)
        db.commit()
        avisar(request, "Score recalculado.")
    return voltar(voltar_para)


# ---------------------------------------------------------------- Pipeline (Kanban)

@rotas.get("/leads/pipeline")
def pipeline(request: Request, vendedor: str = "", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    consulta = filtrar_por_usuario(select(Lead).where(Lead.anonimizado.is_(False)), usuario)
    if ve_tudo(usuario) and vendedor != "todos":
        vendedor = vendedor or str(usuario.id)  # padrão: os leads de quem está usando a conta
        consulta = consulta.where(Lead.vendedor_id == util.para_int(vendedor))
    colunas = []
    for codigo, nome, lista_status in config.COLUNAS_PIPELINE:
        q = consulta.where(Lead.status.in_(lista_status))
        total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
        itens = db.execute(q.order_by(Lead.score.desc()).limit(60)).scalars().all()
        colunas.append({"codigo": codigo, "nome": nome, "status": lista_status, "leads": itens, "total": total})
    return tela(request, "pipeline.html", {"colunas": colunas, "vendedores": _vendedores(db), "vendedor": vendedor})


@rotas.post("/api/leads/{lead_id}/status", dependencies=[Depends(verificar_csrf)])
async def api_mudar_status(lead_id: int, request: Request, usuario: Usuario = Depends(equipe),
                           db: Session = Depends(obter_db)):
    corpo = await request.json()
    lead = _lead(db, lead_id, usuario)
    novo = corpo.get("status", "")
    if novo not in config.STATUS_LEAD:
        return JSONResponse({"erro": "Status inválido."}, status_code=400)
    leads_servico.mudar_status(db, lead, novo, usuario, corpo.get("motivo", ""))
    db.commit()
    return {"ok": True, "status": lead.status, "score": lead.score, "potencial": lead.potencial}


# ---------------------------------------------------------------- Cadastro e ficha do lead

@rotas.get("/leads/novo")
def novo_tela(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    return tela(request, "lead_form.html", {"lead": Lead(status="Novo", estado="", origem="Cadastro manual"),
                                            "vendedores": _vendedores(db), "novo": True})


@rotas.post("/leads/novo", dependencies=[Depends(verificar_csrf)])
async def novo(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    form = await request.form()
    dados = _dados_do_form(form)
    problemas = planilhas.validar_lead(dados)
    if problemas:
        avisar(request, "Corrija: " + "; ".join(problemas) + ".", "erro")
        return tela(request, "lead_form.html", {"lead": Lead(**{k: v for k, v in dados.items() if hasattr(Lead, k)}),
                                                "vendedores": _vendedores(db), "novo": True})
    lead, motivo = leads_servico.criar_lead(db, dados, usuario, origem=dados.get("origem") or "Cadastro manual")
    if motivo:
        avisar(request, f"Este escritório já está cadastrado (mesmo {motivo}). Abrimos o cadastro existente.", "alerta")
        return voltar(f"/leads/{lead.id}")
    registrar_log(db, usuario, "criou", "lead", lead.id, request=request)
    db.commit()
    avisar(request, "Lead cadastrado.")
    return voltar(f"/leads/{lead.id}")


def _contexto_lead(db: Session, lead: Lead, usuario: Usuario) -> dict:
    total, potencial, detalhes = score.calcular(db, lead)
    templates = db.execute(select(Template).where(Template.ativo.is_(True)).order_by(Template.canal, Template.id)).scalars().all()
    prontas = []
    for t in templates:
        assunto, corpo = mensagens.montar(db, t, lead, usuario)
        prontas.append({"id": t.id, "nome": t.nome, "canal": t.canal, "assunto": assunto, "corpo": corpo,
                        "nome_meta": t.nome_meta})
    itens = db.execute(select(Historico).where(Historico.lead_id == lead.id).order_by(Historico.criado_em.desc(),
                                                                                        Historico.id.desc())).scalars().all()
    tarefas = db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id).order_by(Tarefa.data, Tarefa.hora)).scalars().all()
    return {
        "lead": lead, "detalhes_score": detalhes, "historico": itens, "tarefas": tarefas, "mensagens": prontas,
        "qualificacao": json.loads(lead.qualificacao) if lead.qualificacao else None,
        "vendedores": _vendedores(db), "bloqueio_whatsapp": mensagens.bloqueio_de_envio(db, lead, "whatsapp"),
        "bloqueio_email": mensagens.bloqueio_de_envio(db, lead, "email"),
        "cadencias": db.execute(select(Cadencia).where(Cadencia.ativa.is_(True))).scalars().all(),
        "ia_ligada": ia.disponivel(), "whatsapp_api": whatsapp_cloud.configurado(), "email_api": email_smtp.configurado(),
        "enviadas": db.execute(select(Mensagem).where(Mensagem.lead_id == lead.id).order_by(Mensagem.criado_em.desc()).limit(20)).scalars().all(),
        "perfil": score.perfil_de(lead),
        "categorias": db.execute(select(Categoria).order_by(Categoria.prioridade)).scalars().all(),
        "sdr_msgs": (json.loads(lead.qualificacao).get("sdr") if lead.qualificacao else None),
        "handoff": sdr.resumo_handoff(db, lead) if (lead.automacao_pausada or lead.humano_id) else None,
    }


@rotas.get("/leads/{lead_id:int}")
def ficha(request: Request, lead_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    return tela(request, "lead.html", _contexto_lead(db, lead, usuario))


@rotas.post("/leads/{lead_id:int}", dependencies=[Depends(verificar_csrf)])
async def salvar(request: Request, lead_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    form = await request.form()
    if "empresa" not in form:  # só mudança de status (ex.: botão "Mudar status para...")
        if form.get("status") in config.STATUS_LEAD:
            leads_servico.mudar_status(db, lead, form.get("status"), usuario, form.get("motivo_perda", ""))
            db.commit()
            avisar(request, f"Status alterado para {lead.status}.")
        return voltar(f"/leads/{lead_id}")
    dados = _dados_do_form(form)
    if not ve_tudo(usuario):
        dados.pop("vendedor_id", None)
    problemas = planilhas.validar_lead(dados)
    if problemas:
        avisar(request, "Não salvei. Corrija: " + "; ".join(problemas) + ".", "erro")
        return voltar(f"/leads/{lead_id}")
    alterados = leads_servico.preencher(lead, dados)
    if "categoria_id" in dados and dados["categoria_id"] != lead.categoria_id:
        lead.categoria = db.get(Categoria, dados["categoria_id"]) if dados["categoria_id"] else None
        alterados.append("categoria")
    leads_servico.limpar_campos(lead)
    duplicado, motivo = leads_servico.achar_duplicado(db, lead, ignorar_id=lead.id)
    if duplicado:
        db.rollback()
        avisar(request, f"Não salvei: o lead \"{duplicado.empresa}\" (nº {duplicado.id}) já usa o mesmo {motivo}.", "erro")
        return voltar(f"/leads/{lead_id}")
    novo_status = form.get("status")
    if novo_status and novo_status != lead.status:
        leads_servico.mudar_status(db, lead, novo_status, usuario, form.get("motivo_perda", ""))
    score.atualizar(db, lead)
    if alterados:
        historico(db, lead.id, "sistema", "Dados alterados: " + ", ".join(alterados) + ".", usuario)
    db.commit()
    avisar(request, "Lead salvo.")
    return voltar(f"/leads/{lead_id}")


@rotas.post("/leads/{lead_id:int}/qualificar", dependencies=[Depends(verificar_csrf)])
def qualificar(request: Request, lead_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    score.atualizar(db, lead)
    try:
        resultado = ia.gerar_abordagem(db, lead, usuario)
    except ia.ErroDaIA as erro:
        avisar(request, f"{erro} Usei as regras do sistema.", "alerta")
        resultado = ia.abordagem_por_regras(db, lead, usuario)
    resultado.update({"score": lead.score, "potencial": lead.potencial, "em": agora().strftime("%d/%m/%Y %H:%M")})
    lead.qualificacao = json.dumps(resultado, ensure_ascii=False)
    historico(db, lead.id, "ia", f"Lead qualificado: score {lead.score} ({lead.potencial}). "
                                 f"Abordagem: {resultado.get('melhor_abordagem', '')}", usuario)
    db.commit()
    return voltar(f"/leads/{lead_id}#qualificacao")


@rotas.post("/leads/{lead_id:int}/proximo-passo", dependencies=[Depends(verificar_csrf)])
def proximo_passo(request: Request, lead_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    itens = list(reversed(db.execute(select(Historico).where(Historico.lead_id == lead.id)
                                     .order_by(Historico.criado_em.desc()).limit(40)).scalars().all()))
    try:
        r = ia.proximo_passo(db, lead, itens)
    except ia.ErroDaIA as erro:
        avisar(request, str(erro), "erro")
        return voltar(f"/leads/{lead_id}")
    texto = (f"Próximo passo: {r['proximo_passo']} · Canal: {config.CANAIS.get(r['canal'], r['canal'])} · "
             f"Quando: {r['quando']} · Temperatura: {r['temperatura']}. {r['justificativa']}")
    if r.get("resumo_historico"):
        texto += f"\nResumo: {r['resumo_historico']}"
    if r.get("mensagem_sugerida"):
        texto += f"\nMensagem sugerida: {r['mensagem_sugerida']}"
    historico(db, lead.id, "ia", texto, usuario)
    db.commit()
    avisar(request, texto)
    return voltar(f"/leads/{lead_id}")


@rotas.post("/leads/{lead_id:int}/enriquecer", dependencies=[Depends(verificar_csrf)])
def enriquecer(request: Request, lead_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    if not lead.site and not lead.cnpj:
        avisar(request, "Informe o site ou o CNPJ do escritório para buscar dados públicos.", "alerta")
        return voltar(f"/leads/{lead_id}")
    alterados = prospeccao.enriquecer_lead(db, lead, usuario)
    db.commit()
    avisar(request, ("Encontrei: " + ", ".join(sorted(set(alterados))) + ".") if alterados
           else "Não encontrei dados novos no site/CNPJ (os campos já preenchidos nunca são trocados).",
           "ok" if alterados else "alerta")
    return voltar(f"/leads/{lead_id}")


@rotas.post("/leads/{lead_id:int}/contato", dependencies=[Depends(verificar_csrf)])
def contato(request: Request, lead_id: int, canal: str = Form(...), descricao: str = Form(""),
            usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    leads_servico.registrar_contato(db, lead, canal, descricao or f"Contato por {config.CANAIS.get(canal, canal)}.", usuario)
    db.commit()
    avisar(request, "Contato registrado.")
    return voltar(f"/leads/{lead_id}")


@rotas.post("/leads/{lead_id:int}/resposta", dependencies=[Depends(verificar_csrf)])
def resposta(request: Request, lead_id: int, canal: str = Form("whatsapp"), texto: str = Form(""),
             usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    if not texto.strip():
        leads_servico.registrar_resposta(db, lead, canal, "", usuario)
        db.commit()
        avisar(request, "Resposta registrada. As tentativas pendentes da cadência foram canceladas.")
        return voltar(f"/leads/{lead_id}")
    from .. import sdr

    analise = sdr.processar_resposta(db, lead, texto, canal, usuario)
    request.session["analise_resposta"] = {k: v for k, v in analise.items() if k != "oportunidade_id"}
    db.commit()
    if analise["classe"] in config.CLASSES_QUENTES:
        avisar(request, f"{analise['classe']}: a automação parou e o lead virou OPORTUNIDADE para o time humano.")
    else:
        avisar(request, f"Resposta classificada como {analise['classe']}.")
    return voltar(f"/leads/{lead_id}#resposta")


@rotas.post("/leads/{lead_id:int}/nota", dependencies=[Depends(verificar_csrf)])
def nota(request: Request, lead_id: int, texto: str = Form(...), usuario: Usuario = Depends(equipe),
         db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    if texto.strip():
        historico(db, lead.id, "nota", texto.strip()[:3000], usuario)
        db.commit()
    return voltar(f"/leads/{lead_id}#historico")


@rotas.post("/leads/{lead_id:int}/tarefa", dependencies=[Depends(verificar_csrf)])
def nova_tarefa(request: Request, lead_id: int, tipo: str = Form("followup"), canal: str = Form("whatsapp"),
                data: str = Form(...), hora: str = Form("09:00"), acao: str = Form(""), mensagem: str = Form(""),
                usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    dia = util.para_data(data) or date.today()
    tipo = "reuniao" if tipo == "reuniao" else "followup"
    db.add(Tarefa(tipo=tipo, lead_id=lead.id, usuario_id=lead.vendedor_id or usuario.id, canal=canal, data=dia,
                  hora=hora or "09:00", acao=acao or ("Reunião de apresentação da parceria" if tipo == "reuniao" else "Follow-up"),
                  mensagem=mensagem))
    if tipo == "reuniao":
        if lead.etapa < 5:
            leads_servico.mudar_status(db, lead, "Reunião", usuario)
        historico(db, lead.id, "reuniao", f"Reunião agendada para {dia:%d/%m/%Y} às {hora}. {acao}", usuario)
    if not lead.proximo_contato or dia < lead.proximo_contato:
        lead.proximo_contato = dia
    db.commit()
    avisar(request, "Reunião agendada." if tipo == "reuniao" else "Follow-up agendado.")
    return voltar(f"/leads/{lead_id}")


@rotas.post("/leads/{lead_id:int}/converter", dependencies=[Depends(verificar_csrf)])
def converter(request: Request, lead_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    if lead.etapa < 7:
        leads_servico.mudar_status(db, lead, "Parceiro", usuario, "convertido pelo vendedor")
    parceiro = leads_servico.converter_em_parceiro(db, lead, usuario)
    registrar_log(db, usuario, "converteu", "lead", lead.id, f"parceiro {parceiro.id}", request)
    db.commit()
    avisar(request, "Lead convertido em parceiro! Complete o cadastro (comissão, chave Pix) abaixo.")
    return voltar(f"/parceiros/{parceiro.id}")


@rotas.post("/leads/{lead_id:int}/opt-out", dependencies=[Depends(verificar_csrf)])
def opt_out(request: Request, lead_id: int, desfazer: str = Form(""), usuario: Usuario = Depends(equipe),
            db: Session = Depends(obter_db)):
    lead = _lead(db, lead_id, usuario)
    if desfazer and ve_tudo(usuario):
        lead.opt_out, lead.opt_out_em = False, None
        historico(db, lead.id, "lgpd", "Opt-out desfeito (o contato autorizou novamente).", usuario)
        avisar(request, "Opt-out desfeito.")
    else:
        leads_servico.registrar_opt_out(db, lead, usuario, "registrado pelo vendedor")
        avisar(request, "Opt-out registrado: este lead não receberá mais contatos.")
    registrar_log(db, usuario, "opt_out" if not desfazer else "opt_out_desfeito", "lead", lead.id, request=request)
    db.commit()
    return voltar(f"/leads/{lead_id}")


@rotas.post("/leads/{lead_id:int}/excluir", dependencies=[Depends(verificar_csrf)])
def excluir(request: Request, lead_id: int, usuario: Usuario = Depends(gestao), db: Session = Depends(obter_db)):
    """Atende pedido de exclusão (LGPD): anonimiza e guarda só o necessário para não contatar de novo."""
    lead = _lead(db, lead_id, usuario)
    leads_servico.registrar_opt_out(db, lead, usuario, "pedido de exclusão de dados")
    leads_servico.anonimizar(lead, manter_bloqueio=True)
    historico(db, lead.id, "lgpd", "Dados pessoais excluídos a pedido (LGPD).", usuario)
    registrar_log(db, usuario, "excluiu_dados", "lead", lead.id, request=request)
    db.commit()
    avisar(request, "Dados do lead excluídos. Fica só o registro mínimo para não contatá-lo de novo.")
    return voltar("/leads")


# ---------------------------------------------------------------- Mensagens (copiar / enviar)

@rotas.post("/api/mensagens/registrar", dependencies=[Depends(verificar_csrf)])
async def registrar_mensagem(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    """Chamado ao clicar em "Copiar mensagem" ou "Abrir no WhatsApp": aplica as regras e guarda no histórico."""
    corpo = await request.json()
    lead = _lead(db, int(corpo.get("lead_id") or 0), usuario) if corpo.get("lead_id") else None
    canal = corpo.get("canal", "whatsapp")
    bloqueio = mensagens.bloqueio_de_envio(db, lead, canal) if lead else ""
    if bloqueio and lead and lead.opt_out:
        return JSONResponse({"erro": bloqueio}, status_code=409)
    texto = str(corpo.get("corpo", ""))[:5000]
    mensagens.registrar(db, lead.id if lead else None, canal, texto, usuario, status="copiada",
                        assunto=str(corpo.get("assunto", ""))[:200], tarefa_id=util.para_int(corpo.get("tarefa_id")))
    if lead:
        historico(db, lead.id, "contato", f"Mensagem de {config.CANAIS.get(canal, canal)} copiada para envio manual.",
                  usuario, canal)
    db.commit()
    return {"ok": True, "aviso": bloqueio}


@rotas.post("/leads/{lead_id:int}/enviar", dependencies=[Depends(verificar_csrf)])
def enviar_api(request: Request, lead_id: int, canal: str = Form(...), template_id: int = Form(...),
               usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    """Envio de UMA mensagem pela integração oficial (WhatsApp Cloud API ou SMTP)."""
    lead = _lead(db, lead_id, usuario)
    template = db.get(Template, template_id)
    bloqueio = mensagens.bloqueio_de_envio(db, lead, canal)
    if bloqueio:
        avisar(request, bloqueio, "erro")
        return voltar(f"/leads/{lead_id}")
    assunto, corpo = mensagens.montar(db, template, lead, usuario)
    try:
        if canal == "whatsapp":
            valores = mensagens.valores_variaveis(db, lead, usuario)
            id_externo = whatsapp_cloud.enviar_template(lead.whatsapp, template.nome_meta,
                                                        [valores["nome"] or "tudo bem", valores["empresa"], valores["vendedor"]])
        elif canal == "email":
            if not lead.email:
                raise email_smtp.ErroEmail("Este lead não tem e-mail.")
            id_externo = email_smtp.enviar(lead.email, assunto, corpo, lead_id=lead.id)
        else:
            raise HTTPException(400)
    except (whatsapp_cloud.ErroWhatsApp, email_smtp.ErroEmail) as erro:
        mensagens.registrar(db, lead.id, canal, corpo, usuario, modo="api", status="falhou", assunto=assunto, erro=str(erro))
        db.commit()
        avisar(request, str(erro), "erro")
        return voltar(f"/leads/{lead_id}")
    mensagens.registrar(db, lead.id, canal, corpo, usuario, modo="api", status="enviada", assunto=assunto, id_externo=id_externo)
    leads_servico.registrar_contato(db, lead, canal, f"Mensagem enviada pela API ({template.nome}).", usuario)
    db.commit()
    avisar(request, "Mensagem enviada.")
    return voltar(f"/leads/{lead_id}")


# ---------------------------------------------------------------- Importação

@rotas.get("/leads/importar")
def importar_tela(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    return tela(request, "importar.html", {"vendedores": _vendedores(db), "resultado": None})


@rotas.post("/leads/importar", dependencies=[Depends(verificar_csrf)])
async def importar(request: Request, arquivo: UploadFile = File(...), vendedor_id: str = Form(""),
                   origem: str = Form(""), base_legal: str = Form("Legítimo interesse (contato B2B)"),
                   usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    conteudo = await arquivo.read()
    if len(conteudo) > 10 * 1024 * 1024:
        avisar(request, "Arquivo grande demais (máximo 10 MB). Divida em partes.", "erro")
        return voltar("/leads/importar")
    try:
        linhas = planilhas.ler_linhas(arquivo.filename, conteudo)
    except planilhas.ErroPlanilha as erro:
        avisar(request, str(erro), "erro")
        return voltar("/leads/importar")
    origem = origem.strip() or f"Importação: {arquivo.filename}"
    vendedor = util.para_int(vendedor_id) if ve_tudo(usuario) else usuario.id
    resultado = {"importados": 0, "duplicados": [], "invalidos": [], "total": len(linhas), "colunas_ignoradas": []}
    if linhas:
        resultado["colunas_ignoradas"] = [c for c in linhas[0].keys()
                                          if c and util.chave_texto(str(c)) not in planilhas.SINONIMOS_LEAD]
    for numero, linha in enumerate(linhas, start=2):
        dados = planilhas.mapear(linha, planilhas.SINONIMOS_LEAD)
        problemas = planilhas.validar_lead(dados)
        if problemas:
            resultado["invalidos"].append((numero, dados.get("empresa", "-"), "; ".join(problemas)))
            continue
        dados["vendedor_id"] = vendedor
        dados["base_legal"] = base_legal
        lead, motivo = leads_servico.criar_lead(db, dados, usuario, origem=origem)
        if motivo:
            resultado["duplicados"].append((numero, dados.get("empresa", "-"), f"mesmo {motivo} de \"{lead.empresa}\"" if lead else motivo))
            continue
        resultado["importados"] += 1
    registrar_log(db, usuario, "importou_leads", "lead", None,
                  f"{arquivo.filename}: {resultado['importados']} importados, {len(resultado['duplicados'])} duplicados, "
                  f"{len(resultado['invalidos'])} inválidos", request)
    db.commit()
    return tela(request, "importar.html", {"vendedores": _vendedores(db), "resultado": resultado})


# ---------------------------------------------------------------- Prospecção ("Encontrar novos parceiros")

@rotas.get("/prospeccao")
def prospeccao_tela(request: Request, pedido: str = "", usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    preenchido = prospeccao.interpretar_pedido(pedido) if pedido else {}
    buscas = db.execute(select(Busca).order_by(Busca.criado_em.desc()).limit(15)).scalars().all()
    return tela(request, "prospeccao.html", {"fontes": prospeccao.fontes_disponiveis(db), "buscas": buscas,
                                             "categorias": db.execute(select(Categoria).where(Categoria.ativa.is_(True))
                                                                      .order_by(Categoria.prioridade)).scalars().all(),
                                             "pre": preenchido, "pedido": pedido})


@rotas.post("/prospeccao/buscar", dependencies=[Depends(verificar_csrf)])
async def prospeccao_buscar(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    form = await request.form()
    cidade, uf = str(form.get("cidade", "")).strip(), str(form.get("estado", "")).strip().upper()
    fontes = [f for f in form.getlist("fontes") if f in ("receita", "osm", "google")]
    if not cidade or uf not in config.UFS:
        avisar(request, "Informe a cidade e escolha o estado.", "erro")
        return voltar("/prospeccao")
    if not fontes:
        avisar(request, "Escolha pelo menos uma fonte de dados.", "erro")
        return voltar("/prospeccao")
    em_andamento = db.execute(select(Busca.id).where(Busca.status.in_(["na fila", "buscando", "enriquecendo"]),
                                                    Busca.usuario_id == usuario.id)).first()
    if em_andamento:
        avisar(request, "Você já tem uma busca em andamento. Espere ela terminar.", "alerta")
        return voltar(f"/prospeccao/busca/{em_andamento[0]}")
    busca = Busca(usuario_id=usuario.id, cidade=cidade, estado=uf,
                  raio_km=max(1, min(util.para_int(form.get("raio_km")) or 10, 50)),
                  quantidade=max(1, min(util.para_int(form.get("quantidade")) or 100, 500)),
                  categoria=str(form.get("categoria") or "contabil")[:40],
                  tipo_empresa=(db.execute(select(Categoria.nome).where(Categoria.codigo == form.get("categoria")))
                                .scalar() or config.TIPOS_EMPRESA[0]),
                  tamanho_min=util.para_int(form.get("tamanho_min")), tamanho_max=util.para_int(form.get("tamanho_max")),
                  fontes=",".join(fontes), enriquecer=form.get("enriquecer") == "on")
    db.add(busca)
    registrar_log(db, usuario, "prospeccao", "busca", None, f"{cidade}/{uf} {busca.quantidade}", request)
    db.commit()
    prospeccao.iniciar_busca_em_segundo_plano(busca.id)
    return voltar(f"/prospeccao/busca/{busca.id}")


@rotas.get("/prospeccao/busca/{busca_id}")
def prospeccao_resultado(request: Request, busca_id: int, potencial: str = "", usuario: Usuario = Depends(equipe),
                         db: Session = Depends(obter_db)):
    busca = db.get(Busca, busca_id)
    if not busca:
        raise HTTPException(404)
    leads = [l for l in prospeccao.leads_da_busca(db, busca_id) if pode_ver(usuario, l)]
    if potencial:
        leads = [l for l in leads if l.potencial == potencial]
    return tela(request, "busca.html", {
        "busca": busca, "leads": leads[: busca.quantidade], "potencial": potencial,
        "cadencias": db.execute(select(Cadencia).where(Cadencia.ativa.is_(True))).scalars().all(),
        "potenciais": score.NOMES_POTENCIAL, "ia_ligada": ia.disponivel(),
        "rodando": busca.status in ("na fila", "buscando", "enriquecendo"),
    })
