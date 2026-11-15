"""Configurações (administrador): regras do negócio, pesos do score, usuários, LGPD e logs."""

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import (alertas, autorizacao, base_receita, bases_importadas, config, ia, leads_servico, marca, prospeccao,
               relogio, score, util)
from ..banco import CHAVES_DA_AR, CHAVES_SO_MASTER, gravar_config, ler_config, ler_config_json, obter_db
from ..integracoes import dns_email, email_imap, email_smtp, whatsapp_cloud, whatsapp_leads
from ..modelos import Equipe, Lead, LogAuditoria, MarcaAR, Papel, Parceiro, Usuario
from ..seguranca import diferencas, exige, problema_na_senha, registrar_log, resumir_senha, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()

CAMPOS_GERAIS = [
    ("mostrar_vendas", "Mostrar Vendas, Vencimentos e Comissões no menu e no Dashboard (1 = sim, 0 = não)", "numero"),
    ("mostrar_agenda", "Mostrar a Agenda de prospecção (follow-ups) no menu e no Dashboard (1 = sim, 0 = não)", "numero"),
    ("link_parceria", "Link da página de parceria ({{link_parceria}})", "texto"),
    ("texto_comissao", "Texto da comissão nas mensagens ({{comissao}})", "texto"),
    ("programa_parceria", "Descrição do programa de parceria (usada pela IA)", "area"),
    ("limite_diario_whatsapp", "Limite diário de mensagens de WhatsApp", "numero"),
    ("limite_diario_email", "Limite diário de e-mails", "numero"),
    ("horas_entre_contatos_whatsapp", "WhatsApp: intervalo mínimo entre mensagens para o mesmo lead (horas; vazio = 20)", "numero"),
    ("horas_entre_contatos_email", "E-mail: intervalo mínimo entre e-mails para o mesmo lead (horas; vazio = 20)", "numero"),
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
    ("limite_frios_whatsapp", "WhatsApp · contatos frios por número por dia (quem nunca conversou com a empresa; "
     "protege o número contra bloqueio; 0 = sem teto)", "numero"),
    ("pausa_frios_sair", "WhatsApp · pedidos de SAIR no mesmo dia que pausam os contatos frios do número até amanhã "
     "(0 = não pausa)", "numero"),
    ("limite_diario_campanha", "IA SDR · limite diário de mensagens por campanha", "numero"),
    ("limite_diario_dominio", "IA SDR · limite diário de e-mails para o mesmo domínio", "numero"),
    ("horario_envio_inicio", "IA SDR · envio automático a partir de (HH:MM, dias úteis)", "texto"),
    ("horario_envio_fim", "IA SDR · envio automático até (HH:MM)", "texto"),
    ("enviar_email_automatico", "IA SDR · fila envia e-mails sozinha depois da aprovação (1 = sim, 0 = não)", "numero"),
    ("sdr_resposta_automatica", "IA SDR · responde \"vou passar para o time\" quando o canal permite (1 = sim, 0 = não)", "numero"),
    ("dias_sem_resposta", "IA SDR · dias depois do último toque para marcar SEM RESPOSTA", "numero"),
    ("enviar_whatsapp_automatico", "IA SDR · com o celular conectado, a fila manda o WhatsApp sozinha (1 = sim, 0 = não): "
     "para quem já conversou ou autorizou e, nas campanhas com o WhatsApp automático ligado, também para contato frio",
     "numero"),
    ("whatsapp_sozinho_padrao", "IA SDR · campanha nova já vem com o WhatsApp automático ligado: depois da aprovação, "
     "sai sozinho também para contato frio (1 = sim, 0 = não; o administrador desliga em cada campanha)", "numero"),
    ("aprovacao_obrigatoria", "IA SDR · campanha só começa com aprovação (1 = sim, 0 = não)", "numero"),
    ("whatsapp_convite", "IA SDR · WhatsApp da empresa para os convites por e-mail (com DDD, ex.: 81999998888). Quem "
     "clicar abre a conversa com este número; vazio = o convite pede para responder o e-mail", "texto"),
    ("notificar_por_email", "IA SDR · avisar o responsável por e-mail quando surgir oportunidade (1 = sim)", "numero"),
    ("alertas_emails", "Avisos de problema · e-mails que recebem (separados por vírgula; vazio = os administradores)",
     "texto"),
    ("limite_banco_mb", "Avisos de problema · tamanho do banco contratado em MB (o aviso sai em 80%)", "numero"),
    ("guarda_conversas_meses", "LGPD · meses que a cópia das conversas do WhatsApp fica na nuvem (0 = sem prazo; as "
     "originais continuam nos celulares e no WhatsApp Leads)", "numero"),
]


def _cadastro_no_registro(u: Usuario) -> dict:
    """O que o registro de atividades guarda de uma mudança no cadastro de uma pessoa (sem senha nem 2 etapas)."""
    return {"nome": u.nome, "email": u.email, "papel": u.perfil if not u.papel_id else f"papel {u.papel_id}",
            "ativo": "sim" if u.ativo else "não", "equipe": u.equipe_id or "", "parceiro": u.parceiro_id or "",
            "expediente": u.expediente or ""}


def _marca_no_registro(db: Session, ar: int) -> dict:
    """O que o registro de atividades guarda da marca de uma AR (o logo só como "tem" ou "não tem")."""
    linha = db.get(MarcaAR, ar)
    campos = ("nome", "curto", "artigo", "site", "descricao", "dominio_email", "cor", "cor_detalhe", "cor_fundo", "fonte")
    dados = {c: (getattr(linha, c) or "") if linha is not None else "" for c in campos}
    dados["logo"] = "tem" if linha is not None and linha.logo_tipo else "não tem"
    return dados


def _so_da_plataforma(request: Request, destino: str):
    """O que é da plataforma (e-mail principal, chaves, base da Receita, listas da CNPJá) vale para todas as ARs: só o
    Admin Master muda (white label, Fase 5)."""
    avisar(request, "Isto é da plataforma e vale para todas as empresas: só o Admin Master muda.", "erro")
    return voltar(destino)


def _papeis(db: Session) -> list[Papel]:
    ordem = {c: i for i, c in enumerate(autorizacao.PERFIS_BASE)}
    return sorted(db.execute(select(Papel)).scalars(), key=lambda p: (ordem.get(p.codigo, 9), p.nome))


@rotas.get("/configuracoes")
def configuracoes(request: Request, aba: str = "geral", usuario: Usuario = Depends(exige("configuracoes.ver")), db: Session = Depends(obter_db)):
    wl = whatsapp_leads.status(False)  # uma consulta só (antes eram duas a cada abertura da tela)
    ar_tela = marca.ar_da_tela(request, usuario)
    dominio_dns = (marca.da_ar(db, ar_tela)["dominio_email"] if ar_tela else config.EMAIL_DOMINIO) if aba == "email" else ""
    return tela(request, "configuracoes.html", {
        # white label: quem é de uma AR muda só as configurações da AR (o resto é da plataforma: Admin Master)
        "aba": aba, "campos": [(c, n, t, ler_config(db, c), autorizacao.e_master(usuario)
                                or (c in CHAVES_DA_AR and c not in CHAVES_SO_MASTER)) for c, n, t in CAMPOS_GERAIS],
        "criterios": score.CRITERIOS, "pesos": score.pesos(db), "faixas": score.faixas(db),
        "usuarios": db.execute(select(Usuario).order_by(Usuario.perfil, Usuario.nome)).scalars().all(),
        "papeis": _papeis(db), "equipes": db.execute(select(Equipe).order_by(Equipe.nome)).scalars().all(),
        "sou_master": autorizacao.e_master(usuario),
        "papeis_de_admin": {p.codigo for p in _papeis(db) if autorizacao.papel_da_poder_de_admin(db, p)},
        "parceiros": db.execute(select(Parceiro).order_by(Parceiro.escritorio)).scalars().all(),
        "logs": db.execute(select(LogAuditoria).order_by(LogAuditoria.id.desc()).limit(300)).scalars().all() if aba == "logs" else [],
        "integracoes": [
            ("IA (Claude)", ia.disponivel(), f"Modelo: {config.IA_MODELO}" if ia.disponivel() else "ANTHROPIC_API_KEY no .env"),
            ("WhatsApp conectado (WhatsApp Leads)", wl.get("conectado", False),
             f"{wl.get('estado', '')} · {wl.get('enviadas_hoje', 0)} de {wl.get('limite_diario', 0)} hoje"
             if wl.get("disponivel") else wl.get("erro", "")),
            ("WhatsApp Cloud API (oficial)", whatsapp_cloud.configurado(), "WHATSAPP_TOKEN e WHATSAPP_PHONE_NUMBER_ID no .env"),
            ("E-mail (SMTP)", email_smtp.configurado(), "SMTP_HOST, SMTP_USUARIO, SMTP_SENHA e SMTP_REMETENTE no .env"),
            ("Respostas por e-mail (IMAP)", email_imap.configurado(), "IMAP_HOST, IMAP_USUARIO e IMAP_SENHA no .env"),
            ("CNPJá (Empresas novas)", bool(_chave_cnpja()), "Chave da API: no quadro CNPJá abaixo"),
            ("Google Places", bool(config.GOOGLE_PLACES_API_KEY), "GOOGLE_PLACES_API_KEY no .env"),
            ("OpenStreetMap", True, "Gratuito, já funciona"),
            ("BrasilAPI (CNPJ)", True, "Gratuito, já funciona"),
            ("Banco de dados", True, "PostgreSQL" if "postgres" in config.DATABASE_URL else "SQLite (arquivo local em dados/)"),
        ],
        "fontes": prospeccao.fontes_disponiveis(db), "receita": base_receita.resumo(db),
        "listas": bases_importadas.listas(db) if aba == "integracoes" else [],
        "receita_oculta": bases_importadas.receita_oculta(db),
        "tem_chave_cnpja": bool(_chave_cnpja()) if aba == "integracoes" else False,
        "painel_avisos": {"ativos": alertas.ativos(db), "para": alertas.destinatarios(db), "ligado": alertas.ligado(),
                   "email_ok": email_smtp.configurado(), "banco_mb": alertas.tamanho_do_banco_mb(db),
                   "banco_limite": int(float(ler_config(db, "limite_banco_mb") or 0) or 0),
                   "backup": ler_config_json(db, "backup_ultimo", {}) or {}, "relogio": relogio.resumo(db)}
        if aba == "integracoes" else None,
        "demo": db.execute(select(Lead.id).where(Lead.origem == "Demonstração").limit(1)).first() is not None,
        "email": _email_atual() if aba == "email" else None,
        # white label: o domínio da AR de quem vê (Configurações > Marca); fora das ARs, o do e-mail principal
        "dns": dns_email.verificar(dominio_dns) if aba == "email" and dominio_dns else None, "dominio_dns": dominio_dns,
        "marca_ar": marca.da_ar(db, ar_tela) if aba == "marca" else None,
        "marca_linha": db.get(MarcaAR, ar_tela) if aba == "marca" and ar_tela else None,
        "fontes": marca.FONTES, "tipos_logo": ", ".join(marca.TIPOS_LOGO.values()),
    })


@rotas.post("/configuracoes/marca", dependencies=[Depends(verificar_csrf)])
async def salvar_marca(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")),
                       db: Session = Depends(obter_db)):
    """Marca da AR de quem salva (white label, Fase 5; o Admin Master: a da AR em que entrou). Fora das ARs, o Admin
    Master muda o nome neutro da plataforma (tela de entrada)."""
    form = await request.form()
    destino = "/configuracoes?aba=marca"
    ar = marca.ar_da_tela(request, usuario)
    if ar is None:
        if not autorizacao.e_master(usuario):
            return _so_da_plataforma(request, destino)
        nome = re.sub(r"\s+", " ", str(form.get("plataforma_nome") or "")).strip()[:60]
        antes = {"plataforma_nome": ler_config(db, "plataforma_nome")}
        gravar_config(db, "plataforma_nome", nome or marca.PLATAFORMA)
        registrar_log(db, usuario, "salvou_nome_da_plataforma", "configuracao", None, nome, request,
                      mudancas=diferencas(antes, {"plataforma_nome": nome or marca.PLATAFORMA}))
        db.commit()
        marca.esquecer()
        avisar(request, "Nome da plataforma salvo.")
        return voltar(destino)
    arquivo = form.get("logo")
    novo_logo = await arquivo.read() if arquivo is not None and getattr(arquivo, "filename", "") else None
    campos = ("nome", "curto", "artigo", "site", "descricao", "dominio_email", "cor", "cor_detalhe", "cor_fundo", "fonte")
    antes = _marca_no_registro(db, ar)
    problemas = marca.salvar(db, ar, {c: str(form.get(c) or "") for c in campos if c in form}, novo_logo,
                             tirar_logo=form.get("tirar_logo") == "1")
    db.flush()
    registrar_log(db, usuario, "salvou_marca", "tenant", ar, "; ".join(problemas)[:250], request, modulo="Marca",
                  mudancas=diferencas(antes, _marca_no_registro(db, ar)))
    db.commit()
    marca.esquecer(ar)
    for problema in problemas:
        avisar(request, problema, "erro")
    if not problemas:
        avisar(request, "Marca salva. As telas e as próximas mensagens já saem com ela.")
    return voltar(destino)


@rotas.get("/marca/logo/{ar:int}/{assinatura}")
def logo_da_marca(ar: int, assinatura: str, db: Session = Depends(obter_db)):
    """O logo de uma AR (aberto: aparece nas telas e na página de descadastro). O endereço leva uma assinatura e a
    versão (muda quando o logo muda), então o navegador guarda a imagem por uma semana."""
    if not marca.logo_confere(ar, assinatura):
        raise HTTPException(404)
    achado = marca.logo(db, ar)
    if achado is None:
        raise HTTPException(404)
    dados, tipo = achado
    return Response(dados, media_type=tipo, headers={"Cache-Control": "public, max-age=604800, immutable",
                                                     "X-Content-Type-Options": "nosniff"})


@rotas.post("/configuracoes/geral", dependencies=[Depends(verificar_csrf)])
async def salvar_geral(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")), db: Session = Depends(obter_db)):
    form = await request.form()
    master = autorizacao.e_master(usuario)
    alteraveis = [c for c, _, _ in CAMPOS_GERAIS
                  if c in form and (master or (c in CHAVES_DA_AR and c not in CHAVES_SO_MASTER))]
    antes = {c: ler_config(db, c) for c in alteraveis}  # registro de atividades: o antes e o depois
    for chave, _, tipo in CAMPOS_GERAIS:
        if chave in form and (master or (chave in CHAVES_DA_AR and chave not in CHAVES_SO_MASTER)):  # da plataforma: master
            valor = str(form.get(chave)).strip()
            if tipo == "numero":
                valor = str(util.para_float(valor)).removesuffix(".0")
            gravar_config(db, chave, valor)
    registrar_log(db, usuario, "salvou_configuracoes", "configuracao", None, request=request,
                  mudancas=diferencas(antes, {c: ler_config(db, c) for c in alteraveis}))
    db.commit()
    avisar(request, "Configurações salvas.")
    return voltar("/configuracoes")


@rotas.post("/configuracoes/score", dependencies=[Depends(verificar_csrf)])
async def salvar_score(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")), db: Session = Depends(obter_db)):
    form = await request.form()
    antes = {c: ler_config(db, c) for c in ("score_pesos", "score_faixas")}
    gravar_config(db, "score_pesos", {c: int(util.para_float(form.get(f"peso_{c}", p))) for c, _, p in score.CRITERIOS})
    gravar_config(db, "score_faixas", {k: int(util.para_float(form.get(f"faixa_{k}", v))) for k, v in score.FAIXAS_PADRAO.items()})
    db.flush()
    total = score.recalcular_todos(db)
    registrar_log(db, usuario, "alterou_score", "configuracao", None, request=request,
                  mudancas=diferencas(antes, {c: ler_config(db, c) for c in ("score_pesos", "score_faixas")}))
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
def salvar_email(request: Request, endereco: str = Form(...), nome: str = Form(""),
                 senha: str = Form(""), provedor: str = Form("google"), host: str = Form(""), porta: str = Form("587"),
                 responder_para: str = Form(""), ler_respostas: str = Form(""), imap_host: str = Form(""),
                 usuario_login: str = Form(""), usuario: Usuario = Depends(exige("configuracoes.alterar")), db: Session = Depends(obter_db)):
    if not autorizacao.e_master(usuario):  # white label: é da plataforma (vale para todas as ARs)
        return _so_da_plataforma(request, "/configuracoes?aba=email")
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
    nome = nome.strip().replace('"', "") or "Prospecção de Parceiros"
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
def testar_email(request: Request, para: str = Form(""), usuario: Usuario = Depends(exige("configuracoes.alterar")),
                 db: Session = Depends(obter_db)):
    if not autorizacao.e_master(usuario):  # white label: é da plataforma (vale para todas as ARs)
        return _so_da_plataforma(request, "/configuracoes?aba=email")
    para = para.strip() or usuario.email
    try:
        email_smtp.enviar(para, "Teste – e-mail principal das campanhas",
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
def testar_leitura(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")), db: Session = Depends(obter_db)):
    if not autorizacao.e_master(usuario):  # white label: é da plataforma (vale para todas as ARs)
        return _so_da_plataforma(request, "/configuracoes?aba=email")
    try:
        avisar(request, email_imap.testar())
    except email_imap.ErroImap as erro:
        registrar_log(db, usuario, "erro_email_leitura", "configuracao", None, str(erro)[:250], request)
        db.commit()
        avisar(request, str(erro), "erro")
    return voltar("/configuracoes?aba=email")


# ---------------------------------------------------------------- Usuários

@rotas.post("/configuracoes/usuarios/{uid:int}/zerar-2fa", dependencies=[Depends(verificar_csrf)])
def zerar_2fa(request: Request, uid: int, usuario: Usuario = Depends(exige("usuarios.gerenciar")), db: Session = Depends(obter_db)):
    """Celular perdido: desliga a verificação em 2 etapas da pessoa; no próximo login ela configura de novo."""
    from .. import dois_fatores

    u = db.get(Usuario, uid)
    if u is None:
        raise HTTPException(404)
    if motivo := autorizacao.motivo_para_nao_alterar(db, usuario, u):  # o 2FA do master/admin: só o master
        avisar(request, motivo, "erro")
        return voltar("/configuracoes?aba=usuarios")
    dois_fatores.zerar(u)
    registrar_log(db, usuario, "zerou_2fa", "usuario", u.id, u.email, request)
    db.commit()
    if u.id == usuario.id:
        request.session.clear()
        avisar(request, "Sua verificação em 2 etapas foi zerada. Entre de novo e configure o app no celular.", "alerta")
        return voltar("/login")
    avisar(request, f"Verificação em 2 etapas de {u.nome} zerada. No próximo login, a pessoa lê um QR code novo.")
    return voltar("/configuracoes?aba=usuarios")


@rotas.post("/configuracoes/usuarios/{uid:int}", dependencies=[Depends(verificar_csrf)])
def salvar_usuario(request: Request, uid: int, nome: str = Form(...), email: str = Form(...), perfil: str = Form(...),
                   senha: str = Form(""), parceiro_id: str = Form(""), ativo: str = Form(""),
                   expediente: str = Form(""), duracao_reuniao: str = Form(""), equipe_id: str = Form("manter"),
                   usuario: Usuario = Depends(exige("usuarios.gerenciar")), db: Session = Depends(obter_db)):
    destino = "/configuracoes?aba=usuarios"
    u = Usuario() if uid == 0 else db.get(Usuario, uid)
    if u is None:
        raise HTTPException(404)
    antes = _cadastro_no_registro(u) if uid else {}  # registro de atividades: o antes e o depois
    email = email.strip().lower()
    # "perfil" no formulário = código do papel (os 5 do sistema têm o código do perfil; os criados, "p_...")
    papel = db.execute(select(Papel).where(Papel.codigo == perfil)).scalars().first()
    if papel is None or not nome.strip() or not util.email_valido(email):
        avisar(request, "Preencha nome, e-mail válido e papel.", "erro")
        return voltar(destino)
    perfil = papel.base
    # travas contra escalada (pedido da Maria em 13/11/2026): o master e os administradores só o master altera; só o
    # master dá o papel de administrador; ninguém muda o próprio papel, a própria equipe nem se desativa
    if uid and (motivo := autorizacao.motivo_para_nao_alterar(db, usuario, u)):
        avisar(request, motivo, "erro")
        return voltar(destino)
    papel_atual = autorizacao.papel_de(db, u) if uid else None
    if (papel_atual is None or papel_atual.id != papel.id) and (
            motivo := autorizacao.motivo_para_nao_dar_papel(db, usuario, papel)):
        avisar(request, motivo, "erro")
        return voltar(destino)
    if uid == usuario.id:
        if papel_atual is not None and papel_atual.id != papel.id:
            avisar(request, "Você não pode mudar o próprio papel. Peça a quem administra o sistema.", "erro")
            return voltar(destino)
        if ativo != "on":
            avisar(request, "Você não pode desativar o próprio acesso.", "erro")
            return voltar(destino)
        if equipe_id != "manter" and (util.para_int(equipe_id) or None) != u.equipe_id \
                and not autorizacao.e_master(usuario):
            avisar(request, "Você não pode mudar a própria equipe. Peça a quem administra o sistema.", "erro")
            return voltar(destino)
    outro = db.execute(select(Usuario).where(Usuario.email == email, Usuario.id != (u.id or 0))).scalars().first()
    if outro:
        avisar(request, "Já existe um usuário com esse e-mail.", "erro")
        return voltar(destino)
    if perfil == "parceiro" and not util.para_int(parceiro_id):
        avisar(request, "Usuário do tipo Parceiro precisa estar ligado a um parceiro cadastrado.", "erro")
        return voltar(destino)
    if uid == 0 or senha:
        if problema := problema_na_senha(senha):
            avisar(request, problema, "erro")
            return voltar(destino)
        u.senha_hash = resumir_senha(senha)
        u.versao_sessao = (u.versao_sessao or 1) + 1
    u.nome, u.email, u.perfil, u.ativo = nome.strip(), email, perfil, ativo == "on"
    u.papel_id = None if papel.sistema else papel.id
    if equipe_id != "manter":
        u.equipe_id = util.para_int(equipe_id) if equipe_id and db.get(Equipe, util.para_int(equipe_id) or 0) else None
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
    registrar_log(db, usuario, "salvou_usuario", "usuario", u.id, f"{u.email} ({papel.nome})", request,
                  mudancas=diferencas(antes, _cadastro_no_registro(u)))
    db.commit()
    avisar(request, "Usuário salvo." + (" Envie a senha para a pessoa por um canal seguro." if uid == 0 else ""))
    return voltar(destino)


@rotas.post("/configuracoes/receita", dependencies=[Depends(verificar_csrf)])
def importar_receita(request: Request, pasta: str = Form(...), usuario: Usuario = Depends(exige("configuracoes.alterar")),
                     db: Session = Depends(obter_db)):
    if not autorizacao.e_master(usuario):  # white label: é da plataforma (vale para todas as ARs)
        return _so_da_plataforma(request, "/configuracoes?aba=integracoes")
    if config.NA_NUVEM:
        avisar(request, "Na nuvem a base da Receita não é importada por esta tela: o banco grátis tem só 500 MB e uma "
                        "importação inteira não cabe junto com o que já está lá. Para acrescentar um ramo ou uma "
                        "região, peça para quem cuida do sistema (veja docs/deploy-vercel.md).", "alerta")
    elif base_receita.resumo(db)["status"].startswith("Lendo"):
        avisar(request, "A importação já está em andamento.", "alerta")
    else:
        base_receita.importar_em_segundo_plano(pasta)
        registrar_log(db, usuario, "importou_base_receita", "", None, pasta, request)
        db.commit()
        avisar(request, "Importação iniciada. Leva uns 3 a 5 minutos; acompanhe nesta tela.")
    return voltar("/configuracoes?aba=integracoes")


def _chave_cnpja() -> str:
    from .. import empresas_novas

    return empresas_novas.chave_api()


@rotas.post("/configuracoes/cnpja", dependencies=[Depends(verificar_csrf)])
def salvar_chave_cnpja(request: Request, chave: str = Form(""), usuario: Usuario = Depends(exige("configuracoes.alterar")),
                       db: Session = Depends(obter_db)):
    """Chave da API da CNPJá (usada em Empresas novas). Fica no .env (na nuvem: no banco, criptografada)."""
    if not autorizacao.e_master(usuario):  # white label: é da plataforma (vale para todas as ARs)
        return _so_da_plataforma(request, "/configuracoes?aba=integracoes#cnpja")
    from .. import arquivo_env

    chave = chave.strip()
    if len(chave) < 20 or " " in chave:
        avisar(request, "Cole a chave inteira da API da CNPJá (cnpja.com > Chave de API).", "erro")
        return voltar("/configuracoes?aba=integracoes#cnpja")
    arquivo_env.gravar({"CNPJA_API_KEY": chave})
    registrar_log(db, usuario, "salvou_chave_cnpja", "configuracao", None, request=request)  # a chave não vai no log
    db.commit()
    avisar(request, "Chave da CNPJá salva. Clique em \"Testar a chave\" para conferir o saldo.")
    return voltar("/configuracoes?aba=integracoes#cnpja")


@rotas.post("/configuracoes/alertas/teste", dependencies=[Depends(verificar_csrf)])
def testar_alertas(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")),
                   db: Session = Depends(obter_db)):
    """Manda um aviso de teste para quem recebe os avisos de problema (para conferir que o e-mail chega)."""
    para = alertas.destinatarios(db)
    if not email_smtp.configurado():
        avisar(request, "O e-mail de envio ainda não foi configurado (Configurações > E-mail): os avisos aparecem só "
                        "no sino do sistema.", "erro")
        return voltar("/configuracoes?aba=integracoes#avisos")
    try:
        for destino in para:
            email_smtp.enviar(destino, "[Prospecção] Teste dos avisos de problema",
                              f"Este é um teste pedido por {usuario.nome}. Quando algo parar no sistema (WhatsApp, "
                              "e-mails, banco, agendador), o aviso chega assim, neste endereço.\n\n"
                              f"Abrir o sistema: {config.URL_PUBLICA}/configuracoes?aba=integracoes", com_rodape=False)
    except email_smtp.ErroEmail as erro:
        avisar(request, f"O e-mail de teste não saiu: {erro}", "erro")
        return voltar("/configuracoes?aba=integracoes#avisos")
    registrar_log(db, usuario, "testou_alertas", "configuracao", None, ", ".join(para), request)
    db.commit()
    avisar(request, f"E-mail de teste enviado para {', '.join(para) or 'ninguém (cadastre um e-mail)'}. Confira a caixa de "
                    "entrada (e o spam).")
    return voltar("/configuracoes?aba=integracoes#avisos")


@rotas.post("/configuracoes/cnpja/saldo", dependencies=[Depends(verificar_csrf)])
def saldo_cnpja(request: Request, usuario: Usuario = Depends(exige("configuracoes.ver"))):
    from .. import empresas_novas

    try:
        s = empresas_novas.saldo()
    except empresas_novas.ErroCnpja as erro:
        texto = str(erro)
        avisar(request, f"{texto[:1].upper()}{texto[1:]}.", "erro")
        return voltar("/configuracoes?aba=integracoes#cnpja")
    total = (s.get("perpetual") or 0) + (s.get("transient") or 0)
    avisar(request, f"A chave da CNPJá funciona. Saldo: {total} créditos ({s.get('transient', 0)} do mês e "
                    f"{s.get('perpetual', 0)} acumulados).")
    return voltar("/configuracoes?aba=integracoes#cnpja")


MAXIMO_UPLOAD_NUVEM = 4 * 1024 * 1024  # a Vercel recusa pedidos maiores que 4,5 MB


@rotas.post("/configuracoes/listas/importar", dependencies=[Depends(verificar_csrf)])
async def importar_lista(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")),
                         db: Session = Depends(obter_db)):
    """Lista de empresas exportada da CNPJá (.xlsx) → base separada da Receita (ver app/bases_importadas.py)."""
    if not autorizacao.e_master(usuario):  # white label: é da plataforma (vale para todas as ARs)
        return _so_da_plataforma(request, "/configuracoes?aba=integracoes#listas")
    form = await request.form()
    arquivo = form.get("arquivo")
    nome = str(form.get("nome") or "").strip()
    if arquivo is None or not getattr(arquivo, "filename", ""):
        avisar(request, "Escolha o arquivo .xlsx exportado da CNPJá.", "erro")
        return voltar("/configuracoes?aba=integracoes#listas")
    conteudo = await arquivo.read()
    if config.NA_NUVEM and len(conteudo) > MAXIMO_UPLOAD_NUVEM:
        avisar(request, "Arquivo grande demais para enviar pela internet. No computador da plataforma, dê dois cliques em "
                        "importar_lista.bat e escolha o arquivo.", "alerta")
        return voltar("/configuracoes?aba=integracoes#listas")
    try:
        resumo = bases_importadas.importar(db, nome or arquivo.filename.rsplit(".", 1)[0], conteudo,
                                           arquivo.filename, usuario.id)
    except bases_importadas.ErroImportacao as erro:
        avisar(request, str(erro), "erro")
        return voltar("/configuracoes?aba=integracoes#listas")
    registrar_log(db, usuario, "importou_lista", "base", resumo["base_id"],
                  f"{resumo['nome']}: {resumo['importadas']} empresas ({arquivo.filename})", request)
    db.commit()
    avisar(request, f"Lista \"{resumo['nome']}\" importada: {resumo['importadas']} empresas ativas"
                    + (f" ({resumo['inativas']} inativas ficaram de fora)" if resumo["inativas"] else "") + ".")
    return voltar("/configuracoes?aba=integracoes#listas")


@rotas.post("/configuracoes/listas/{lista_id:int}/apagar", dependencies=[Depends(verificar_csrf)])
def apagar_lista(request: Request, lista_id: int, usuario: Usuario = Depends(exige("configuracoes.alterar")),
                 db: Session = Depends(obter_db)):
    if not autorizacao.e_master(usuario):  # white label: é da plataforma (vale para todas as ARs)
        return _so_da_plataforma(request, "/configuracoes?aba=integracoes#listas")
    nome = bases_importadas.apagar(db, lista_id)
    if nome:
        registrar_log(db, usuario, "apagou_lista", "base", lista_id, nome, request)
        db.commit()
        avisar(request, f"Lista \"{nome}\" apagada. Os leads que já foram criados a partir dela continuam no sistema.")
    return voltar("/configuracoes?aba=integracoes#listas")


@rotas.post("/configuracoes/listas/receita", dependencies=[Depends(verificar_csrf)])
def ocultar_receita(request: Request, ocultar: str = Form(""), usuario: Usuario = Depends(exige("configuracoes.alterar")),
                    db: Session = Depends(obter_db)):
    esconder = ocultar == "1"
    if esconder and not bases_importadas.listas(db):
        avisar(request, "Importe uma lista antes de esconder a base da Receita.", "erro")
        return voltar("/configuracoes?aba=integracoes#listas")
    bases_importadas.esconder_receita(db, esconder)
    registrar_log(db, usuario, "base_receita_" + ("oculta" if esconder else "visivel"), "", None, request=request)
    db.commit()
    avisar(request, "A base da Receita foi escondida: os usuários só veem as listas importadas." if esconder
           else "A base da Receita voltou a aparecer para os usuários.")
    return voltar("/configuracoes?aba=integracoes#listas")


# ---------------------------------------------------------------- LGPD e manutenção

@rotas.post("/configuracoes/retencao", dependencies=[Depends(verificar_csrf)])
def aplicar_retencao(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")), db: Session = Depends(obter_db)):
    total = leads_servico.aplicar_retencao(db)
    registrar_log(db, usuario, "aplicou_retencao", "lead", None, f"{total} anonimizados", request)
    db.commit()
    avisar(request, f"Política de retenção aplicada: {total} leads anonimizados.")
    return voltar("/configuracoes?aba=lgpd")


@rotas.post("/configuracoes/apagar-demo", dependencies=[Depends(verificar_csrf)])
def apagar_demo(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")), db: Session = Depends(obter_db)):
    from ..seed import apagar_demonstracao

    total = apagar_demonstracao(db)
    registrar_log(db, usuario, "apagou_demo", "", None, f"{total} registros", request)
    db.commit()
    avisar(request, "Dados de demonstração apagados.")
    return voltar("/configuracoes")
