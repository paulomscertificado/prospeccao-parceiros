"""Configurações (administrador): regras do negócio, pesos do score, usuários, LGPD e logs."""

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import base_receita, config, ia, leads_servico, prospeccao, score, util
from ..banco import gravar_config, ler_config, obter_db
from ..integracoes import dns_email, email_imap, email_smtp, whatsapp_cloud, whatsapp_leads
from ..modelos import Lead, LogAuditoria, Parceiro, Usuario
from ..seguranca import admin, problema_na_senha, registrar_log, resumir_senha, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()

CAMPOS_GERAIS = [
    ("mostrar_vendas", "Mostrar Vendas, Vencimentos e Comissões no menu e no Dashboard (1 = sim, 0 = não)", "numero"),
    ("mostrar_agenda", "Mostrar a Agenda de prospecção (follow-ups) no menu e no Dashboard (1 = sim, 0 = não)", "numero"),
    ("empresa_nome", "Nome da empresa", "texto"),
    ("link_parceria", "Link da página de parceria ({{link_parceria}})", "texto"),
    ("texto_comissao", "Texto da comissão nas mensagens ({{comissao}})", "texto"),
    ("programa_parceria", "Descrição do programa de parceria (usada pela IA)", "area"),
    ("limite_diario_whatsapp", "Limite diário de mensagens de WhatsApp", "numero"),
    ("limite_diario_email", "Limite diário de e-mails", "numero"),
    ("horas_entre_contatos", "Intervalo mínimo entre mensagens para o mesmo lead (horas)", "numero"),
    ("pular_fim_de_semana", "Cadências pulam sábado e domingo (1 = sim, 0 = não)", "numero"),
    ("alertas_vencimento", "Alertas de vencimento (dias antes, separados por vírgula)", "texto"),
    ("dias_parceiro_parado", "Parceiro parado: dias sem venda", "numero"),
    ("dias_lead_parado", "Lead parado: dias sem movimento", "numero"),
    ("dias_retencao_perdidos", "Retenção: anonimizar leads encerrados/opt-out após (dias)", "numero"),
    ("custo_mensal_prospeccao", "Custo mensal da prospecção em R$ (salários, ferramentas)", "numero"),
    # IA SDR
    ("prioridade_canais", "IA SDR · prioridade dos canais (ex.: whatsapp,email,linkedin)", "texto"),
    ("limite_hora_email", "IA SDR · limite de e-mails por hora", "numero"),
    ("limite_hora_whatsapp", "IA SDR · limite de WhatsApp por hora", "numero"),
    ("limite_diario_campanha", "IA SDR · limite diário de mensagens por campanha", "numero"),
    ("limite_diario_dominio", "IA SDR · limite diário de e-mails para o mesmo domínio", "numero"),
    ("horario_envio_inicio", "IA SDR · envio automático a partir de (HH:MM, dias úteis)", "texto"),
    ("horario_envio_fim", "IA SDR · envio automático até (HH:MM)", "texto"),
    ("enviar_email_automatico", "IA SDR · fila envia e-mails sozinha depois da aprovação (1 = sim, 0 = não)", "numero"),
    ("sdr_resposta_automatica", "IA SDR · responde \"vou passar para o time\" quando o canal permite (1 = sim, 0 = não)", "numero"),
    ("dias_sem_resposta", "IA SDR · dias depois do último toque para marcar SEM RESPOSTA", "numero"),
    ("enviar_whatsapp_automatico", "IA SDR · com o celular conectado, manda sozinha o WhatsApp para quem já conversou "
     "ou autorizou (1 = sim, 0 = não). Primeiro contato frio: sempre 1 clique", "numero"),
    ("aprovacao_obrigatoria", "IA SDR · campanha só começa com aprovação (1 = sim, 0 = não)", "numero"),
    ("notificar_por_email", "IA SDR · avisar o responsável por e-mail quando surgir oportunidade (1 = sim)", "numero"),
]


@rotas.get("/configuracoes")
def configuracoes(request: Request, aba: str = "geral", usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    return tela(request, "configuracoes.html", {
        "aba": aba, "campos": [(c, n, t, ler_config(db, c)) for c, n, t in CAMPOS_GERAIS],
        "criterios": score.CRITERIOS, "pesos": score.pesos(db), "faixas": score.faixas(db),
        "usuarios": db.execute(select(Usuario).order_by(Usuario.perfil, Usuario.nome)).scalars().all(),
        "parceiros": db.execute(select(Parceiro).order_by(Parceiro.escritorio)).scalars().all(),
        "logs": db.execute(select(LogAuditoria).order_by(LogAuditoria.id.desc()).limit(300)).scalars().all() if aba == "logs" else [],
        "integracoes": [
            ("IA (Claude)", ia.disponivel(), f"Modelo: {config.IA_MODELO}" if ia.disponivel() else "ANTHROPIC_API_KEY no .env"),
            ("WhatsApp conectado (WhatsApp Leads)", whatsapp_leads.status(False).get("conectado", False),
             (lambda s: f"{s.get('estado', '')} · {s.get('enviadas_hoje', 0)} de {s.get('limite_diario', 0)} hoje"
              if s.get("disponivel") else s.get("erro", ""))(whatsapp_leads.status(False))),
            ("WhatsApp Cloud API (oficial)", whatsapp_cloud.configurado(), "WHATSAPP_TOKEN e WHATSAPP_PHONE_NUMBER_ID no .env"),
            ("E-mail (SMTP)", email_smtp.configurado(), "SMTP_HOST, SMTP_USUARIO, SMTP_SENHA e SMTP_REMETENTE no .env"),
            ("Respostas por e-mail (IMAP)", email_imap.configurado(), "IMAP_HOST, IMAP_USUARIO e IMAP_SENHA no .env"),
            ("Google Places", bool(config.GOOGLE_PLACES_API_KEY), "GOOGLE_PLACES_API_KEY no .env"),
            ("OpenStreetMap", True, "Gratuito, já funciona"),
            ("BrasilAPI (CNPJ)", True, "Gratuito, já funciona"),
            ("Banco de dados", True, "PostgreSQL" if "postgres" in config.DATABASE_URL else "SQLite (arquivo local em dados/)"),
        ],
        "fontes": prospeccao.fontes_disponiveis(db), "receita": base_receita.resumo(db),
        "demo": db.execute(select(Lead.id).where(Lead.origem == "Demonstração").limit(1)).first() is not None,
        "email": _email_atual() if aba == "email" else None,
        "dns": dns_email.verificar(config.EMAIL_DOMINIO)
        if aba == "email" and config.EMAIL_DOMINIO else None,
    })


@rotas.post("/configuracoes/geral", dependencies=[Depends(verificar_csrf)])
async def salvar_geral(request: Request, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    form = await request.form()
    for chave, _, tipo in CAMPOS_GERAIS:
        if chave in form:
            valor = str(form.get(chave)).strip()
            if tipo == "numero":
                valor = str(util.para_float(valor)).removesuffix(".0")
            gravar_config(db, chave, valor)
    registrar_log(db, usuario, "salvou_configuracoes", "configuracao", None, request=request)
    db.commit()
    avisar(request, "Configurações salvas.")
    return voltar("/configuracoes")


@rotas.post("/configuracoes/score", dependencies=[Depends(verificar_csrf)])
async def salvar_score(request: Request, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    form = await request.form()
    gravar_config(db, "score_pesos", {c: int(util.para_float(form.get(f"peso_{c}", p))) for c, _, p in score.CRITERIOS})
    gravar_config(db, "score_faixas", {k: int(util.para_float(form.get(f"faixa_{k}", v))) for k, v in score.FAIXAS_PADRAO.items()})
    db.flush()
    total = score.recalcular_todos(db)
    registrar_log(db, usuario, "alterou_score", "configuracao", None, request=request)
    db.commit()
    avisar(request, f"Pesos salvos e score recalculado em {total} leads.")
    return voltar("/configuracoes?aba=score")


# ---------------------------------------------------------------- E-mail de envio das campanhas

def _email_atual() -> dict:
    from email.utils import parseaddr

    nome, endereco = parseaddr(config.SMTP_REMETENTE or "") if config.SMTP_HOST else ("", "")  # vazio até configurar
    return {"nome": nome, "endereco": endereco or (config.SMTP_USUARIO if config.SMTP_HOST else ""), "host": config.SMTP_HOST,
            "porta": config.SMTP_PORTA, "tls": config.SMTP_TLS, "tem_senha": bool(config.SMTP_SENHA),
            "responder_para": config.SMTP_RESPONDER_PARA, "imap": bool(config.IMAP_HOST),
            "imap_host": config.IMAP_HOST, "dominio": config.EMAIL_DOMINIO,
            "usuario_login": config.SMTP_USUARIO if config.SMTP_HOST and config.SMTP_USUARIO != endereco else ""}


@rotas.post("/configuracoes/email", dependencies=[Depends(verificar_csrf)])
def salvar_email(request: Request, endereco: str = Form(...), nome: str = Form("MS Certificação Digital"),
                 senha: str = Form(""), provedor: str = Form("google"), host: str = Form(""), porta: str = Form("587"),
                 responder_para: str = Form(""), ler_respostas: str = Form(""), imap_host: str = Form(""),
                 usuario_login: str = Form(""), usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    from .. import arquivo_env

    destino = "/configuracoes?aba=email"
    endereco = endereco.strip().lower()
    login = usuario_login.strip().lower() or endereco  # apelido (alias): entra com a conta dona dele
    if login != endereco and not util.email_valido(login):
        avisar(request, "A conta que faz o login precisa ser um e-mail válido.", "erro")
        return voltar("/configuracoes?aba=email")
    if not util.email_valido(endereco):
        avisar(request, "Digite um e-mail válido.", "erro")
        return voltar(destino)
    if config.EMAIL_DOMINIO and not endereco.endswith("@" + config.EMAIL_DOMINIO):
        avisar(request, f"O e-mail de envio precisa ser do domínio @{config.EMAIL_DOMINIO}.", "erro")
        return voltar(destino)
    if responder_para.strip() and not util.email_valido(responder_para.strip()):
        avisar(request, "O e-mail de \"responder para\" não é válido.", "erro")
        return voltar(destino)
    digitada = senha.replace(" ", "").strip()
    if digitada and provedor == "google" and not re.fullmatch(r"[A-Za-z]{16}", digitada):
        avisar(request, f"A senha de app do Google tem 16 letras (ex.: abcd efgh ijkl mnop), e você digitou "
                        f"{len(digitada)} caracteres — parece a senha normal da conta, que não funciona aqui. "
                        "Crie a senha de app em myaccount.google.com/apppasswords (veja o passo a passo ao lado).", "erro")
        return voltar(destino)
    senha = digitada or config.SMTP_SENHA  # vazio = mantém a senha atual
    if not senha:
        avisar(request, "Informe a senha de app do e-mail.", "erro")
        return voltar(destino)
    if provedor == "google":
        host, porta_n, tls, imap = "smtp.gmail.com", 587, "1", "imap.gmail.com"
    else:
        porta_n = util.para_int(porta) or 587
        tls, imap = ("0" if porta_n == 465 else "1"), imap_host.strip()
        if not host.strip():
            avisar(request, "Informe o servidor de envio (SMTP).", "erro")
            return voltar(destino)
    nome = nome.strip().replace('"', "") or "MS Certificação Digital"
    valores = {"SMTP_HOST": host.strip(), "SMTP_PORTA": str(porta_n), "SMTP_TLS": tls, "SMTP_USUARIO": login,
               "SMTP_SENHA": senha, "SMTP_REMETENTE": f"{nome} <{endereco}>",
               "SMTP_RESPONDER_PARA": responder_para.strip()}
    if ler_respostas == "on" and imap:
        valores.update({"IMAP_HOST": imap, "IMAP_PORTA": "993", "IMAP_USUARIO": login, "IMAP_SENHA": senha})
    else:
        valores.update({"IMAP_HOST": "", "IMAP_USUARIO": "", "IMAP_SENHA": ""})
    arquivo_env.gravar(valores)
    registrar_log(db, usuario, "configurou_email", "configuracao", None, f"remetente {endereco} via {host}", request)
    db.commit()
    avisar(request, f"E-mail de envio salvo: {endereco}. Agora clique em \"Enviar e-mail de teste\".")
    return voltar(destino)


@rotas.post("/configuracoes/email/testar", dependencies=[Depends(verificar_csrf)])
def testar_email(request: Request, para: str = Form(""), usuario: Usuario = Depends(admin),
                 db: Session = Depends(obter_db)):
    para = para.strip() or usuario.email
    try:
        email_smtp.enviar(para, "Teste – e-mail das campanhas da MS Certificação Digital",
                          "Este é um e-mail de teste do sistema de Prospecção de Parceiros.\n\nSe ele chegou na caixa "
                          "de entrada (e não no spam), o envio das campanhas está funcionando.", com_rodape=False)
        registrar_log(db, usuario, "testou_email", "configuracao", None, f"para {para}", request)
        db.commit()
        avisar(request, f"E-mail de teste enviado para {para}. Confira se chegou na caixa de entrada (e não no spam).")
    except email_smtp.ErroEmail as erro:
        registrar_log(db, usuario, "erro_email_teste", "configuracao", None, str(erro)[:250], request)
        db.commit()
        avisar(request, str(erro), "erro")
    return voltar("/configuracoes?aba=email")


@rotas.post("/configuracoes/email/testar-leitura", dependencies=[Depends(verificar_csrf)])
def testar_leitura(request: Request, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    try:
        avisar(request, email_imap.testar())
    except email_imap.ErroImap as erro:
        registrar_log(db, usuario, "erro_email_leitura", "configuracao", None, str(erro)[:250], request)
        db.commit()
        avisar(request, str(erro), "erro")
    return voltar("/configuracoes?aba=email")


# ---------------------------------------------------------------- Usuários

@rotas.post("/configuracoes/usuarios/{uid:int}", dependencies=[Depends(verificar_csrf)])
def salvar_usuario(request: Request, uid: int, nome: str = Form(...), email: str = Form(...), perfil: str = Form(...),
                   senha: str = Form(""), parceiro_id: str = Form(""), ativo: str = Form(""),
                   expediente: str = Form(""), duracao_reuniao: str = Form(""),
                   usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    destino = "/configuracoes?aba=usuarios"
    u = Usuario() if uid == 0 else db.get(Usuario, uid)
    if u is None:
        raise HTTPException(404)
    email = email.strip().lower()
    if perfil not in config.PERFIS or not nome.strip() or not util.email_valido(email):
        avisar(request, "Preencha nome, e-mail válido e perfil.", "erro")
        return voltar(destino)
    outro = db.execute(select(Usuario).where(Usuario.email == email, Usuario.id != (u.id or 0))).scalars().first()
    if outro:
        avisar(request, "Já existe um usuário com esse e-mail.", "erro")
        return voltar(destino)
    if perfil == "parceiro" and not util.para_int(parceiro_id):
        avisar(request, "Usuário do tipo Parceiro precisa estar ligado a um parceiro cadastrado.", "erro")
        return voltar(destino)
    if uid == usuario.id and (perfil != "admin" or ativo != "on"):
        avisar(request, "Você não pode tirar o seu próprio acesso de administrador.", "erro")
        return voltar(destino)
    if uid == 0 or senha:
        if problema := problema_na_senha(senha):
            avisar(request, problema, "erro")
            return voltar(destino)
        u.senha_hash = resumir_senha(senha)
        u.versao_sessao = (u.versao_sessao or 1) + 1
    u.nome, u.email, u.perfil, u.ativo = nome.strip(), email, perfil, ativo == "on"
    u.parceiro_id = util.para_int(parceiro_id) if perfil == "parceiro" else None
    if expediente.strip():
        from ..agenda_horarios import ler_expediente

        if not ler_expediente(expediente)[0]:
            avisar(request, "Expediente inválido. Use o formato: seg-sex 09:00-12:00,14:00-18:00", "erro")
            return voltar(destino)
        u.expediente = expediente.strip()
    u.duracao_reuniao = util.para_int(duracao_reuniao) or u.duracao_reuniao or 30
    if uid == 0:
        db.add(u)
    db.flush()
    registrar_log(db, usuario, "salvou_usuario", "usuario", u.id, f"{u.email} ({u.perfil})", request)
    db.commit()
    avisar(request, "Usuário salvo." + (" Envie a senha para a pessoa por um canal seguro." if uid == 0 else ""))
    return voltar(destino)


@rotas.post("/configuracoes/receita", dependencies=[Depends(verificar_csrf)])
def importar_receita(request: Request, pasta: str = Form(...), usuario: Usuario = Depends(admin),
                     db: Session = Depends(obter_db)):
    if config.NA_NUVEM:
        avisar(request, "Na nuvem a base é importada pelo seu computador: dois cliques em importar_receita_nuvem.bat "
                        "(veja docs/deploy-vercel.md).", "alerta")
    elif base_receita.resumo(db)["status"].startswith("Lendo"):
        avisar(request, "A importação já está em andamento.", "alerta")
    else:
        base_receita.importar_em_segundo_plano(pasta)
        registrar_log(db, usuario, "importou_base_receita", "", None, pasta, request)
        db.commit()
        avisar(request, "Importação iniciada. Leva uns 3 a 5 minutos; acompanhe nesta tela.")
    return voltar("/configuracoes?aba=integracoes")


# ---------------------------------------------------------------- LGPD e manutenção

@rotas.post("/configuracoes/retencao", dependencies=[Depends(verificar_csrf)])
def aplicar_retencao(request: Request, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    total = leads_servico.aplicar_retencao(db)
    registrar_log(db, usuario, "aplicou_retencao", "lead", None, f"{total} anonimizados", request)
    db.commit()
    avisar(request, f"Política de retenção aplicada: {total} leads anonimizados.")
    return voltar("/configuracoes?aba=lgpd")


@rotas.post("/configuracoes/apagar-demo", dependencies=[Depends(verificar_csrf)])
def apagar_demo(request: Request, usuario: Usuario = Depends(admin), db: Session = Depends(obter_db)):
    from ..seed import apagar_demonstracao

    total = apagar_demonstracao(db)
    registrar_log(db, usuario, "apagou_demo", "", None, f"{total} registros", request)
    db.commit()
    avisar(request, "Dados de demonstração apagados.")
    return voltar("/configuracoes")
