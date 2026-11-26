"""Configurações (administrador): regras do negócio, pesos do score, usuários, LGPD e logs."""

import logging
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import (alertas, autorizacao, base_receita, bases_importadas, config, ia, leads_servico, marca, prospeccao,
               relogio, score, util)
from ..banco import CHAVES_DA_AR, CHAVES_SO_MASTER, gravar_config, ler_config, ler_config_json, obter_db
from ..integracoes import dns_email, email_imap, email_smtp, whatsapp_cloud, whatsapp_leads
from ..modelos import Equipe, Lead, LogAuditoria, MarcaAR, Papel, Parceiro, Tenant, Usuario
from ..seguranca import diferencas, exige, problema_na_senha, registrar_log, resumir_senha, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()
log = logging.getLogger(__name__)

HORARIOS_DE_ENVIO = ("horario_envio_inicio", "horario_envio_fim")  # gravados sempre como HH:MM
VAZIO_E_PADRAO = ("horas_entre_contatos_whatsapp", "horas_entre_contatos_email")  # em branco = o intervalo geral (20 h)
# Configurações > Geral em grupos (pedido da Maria em 19/11/2026: "está muito confuso e feio"). Cada campo:
# (chave, rótulo, tipo, unidade, ajuda). Tipos: sim_nao (chave liga/desliga; grava 1 ou 0), hora (HH:MM), numero,
# texto e area. A ordem é a da tela. CAMPOS_GERAIS (a lista que o salvar usa) sai daqui.
SECOES_GERAIS = [
    {"id": "horario", "titulo": "Horário de envio", "descricao": "Quando as mensagens automáticas podem sair, nos dias úteis.",
     "campos": [
         ("horario_envio_inicio", "Começa às", "hora", "", ""),
         ("horario_envio_fim", "Termina às", "hora", "", ""),
         ("pular_fim_de_semana", "Cadências pulam sábado e domingo", "sim_nao", "",
          "Os toques que cairiam no fim de semana passam para segunda-feira."),
     ]},
    {"id": "whatsapp", "titulo": "WhatsApp",
     "descricao": "Ritmo e limites dos envios. Valem para cada número conectado e protegem o número contra bloqueio.",
     "campos": [
         ("enviar_whatsapp_automatico", "A fila manda o WhatsApp sozinha", "sim_nao", "",
          "Com o celular conectado: para quem já conversou ou autorizou e, nas campanhas com o WhatsApp automático "
          "ligado, também para contato frio."),
         ("whatsapp_sozinho_padrao", "Campanha nova já vem com o WhatsApp automático ligado", "sim_nao", "",
          "Depois da aprovação, sai sozinho também para contato frio. O administrador desliga em cada campanha."),
         ("intervalo_whatsapp_min", "Tempo mínimo entre duas mensagens", "numero", "minutos",
          "A fila sorteia um tempo entre o mínimo e o máximo."),
         ("intervalo_whatsapp_max", "Tempo máximo entre duas mensagens", "numero", "minutos", ""),
         ("limite_hora_whatsapp", "Limite por hora", "numero", "por hora", ""),
         ("limite_diario_whatsapp", "Limite por dia", "numero", "por dia", "0 = sem limite."),
         ("limite_frios_whatsapp", "Contatos frios por dia", "numero", "por dia",
          "Quem nunca conversou com a empresa. 0 = sem teto."),
         ("pausa_frios_sair", "Pausar os contatos frios depois de", "numero", "pedidos de SAIR no dia",
          "O número volta no dia seguinte. 0 = não pausa."),
         ("horas_entre_contatos_whatsapp", "Intervalo para a mesma empresa (envio por clique)", "numero", "horas",
          "Em branco = 20 horas. A fila automática sempre espera pelo menos 20 horas."),
         ("whatsapp_convite", "WhatsApp dos convites por e-mail", "texto", "",
          "Com DDD, ex.: 81999998888. Quem clicar no convite abre a conversa com este número; em branco, o convite "
          "pede para responder o e-mail."),
     ]},
    {"id": "email", "titulo": "E-mail", "descricao": "Ritmo e limites dos e-mails.",
     "campos": [
         ("enviar_email_automatico", "A fila manda os e-mails sozinha depois da aprovação", "sim_nao", "", ""),
         ("limite_hora_email", "Limite por hora", "numero", "por hora", ""),
         ("limite_diario_email", "Limite por dia", "numero", "por dia", ""),
         ("limite_diario_dominio", "Limite para o mesmo domínio", "numero", "por dia",
          "Vários e-mails para a mesma empresa (o mesmo @domínio) no mesmo dia."),
         ("horas_entre_contatos_email", "Intervalo para a mesma empresa (envio por clique)", "numero", "horas",
          "Em branco = 20 horas. A fila automática sempre espera pelo menos 20 horas."),
     ]},
    {"id": "campanhas", "titulo": "Campanhas e IA SDR", "descricao": "Como as campanhas andam e o que a IA faz sozinha.",
     "campos": [
         ("aprovacao_obrigatoria", "Campanha só começa com aprovação", "sim_nao", "", ""),
         ("sdr_resposta_automatica", "A IA responde \"vou passar para o time\" quando o canal permite", "sim_nao", "", ""),
         ("notificar_por_email", "Avisar o responsável por e-mail quando surgir uma oportunidade", "sim_nao", "", ""),
         ("limite_diario_campanha", "Limite de mensagens por campanha", "numero", "por dia", ""),
         ("dias_sem_resposta", "Marcar SEM RESPOSTA depois de", "numero", "dias", "Contados do último toque."),
         ("prioridade_canais", "Ordem dos canais", "texto", "", "Ex.: whatsapp,email,linkedin"),
     ]},
    {"id": "parceria", "titulo": "Parceria", "descricao": "Textos que entram nas mensagens para os escritórios parceiros.",
     "campos": [
         ("link_parceria", "Link da página de parceria", "texto", "", "Entra no lugar de {{link_parceria}}."),
         ("texto_comissao", "Texto da comissão", "texto", "", "Entra no lugar de {{comissao}}."),
         ("programa_parceria", "Como funciona o programa de parceria", "area", "",
          "A IA usa este texto para explicar a parceria."),
     ]},
    {"id": "acompanhamento", "titulo": "Acompanhamento", "descricao": "Quando o sistema avisa que algo parou.",
     "campos": [
         ("dias_lead_parado", "Lead parado depois de", "numero", "dias sem movimento", ""),
         ("dias_parceiro_parado", "Parceiro parado depois de", "numero", "dias sem venda", ""),
         ("alertas_vencimento", "Alertas de vencimento", "texto", "",
          "Dias antes do vencimento, separados por vírgula. Ex.: 90,60,30,15,7"),
         ("custo_mensal_prospeccao", "Custo mensal da prospecção", "numero", "R$ por mês",
          "Salários e ferramentas: entra nos relatórios."),
     ]},
    {"id": "menu", "titulo": "Menu", "descricao": "O que aparece no menu e no Dashboard.",
     "campos": [
         ("mostrar_vendas", "Mostrar Vendas, Vencimentos e Comissões", "sim_nao", "", ""),
         ("mostrar_agenda", "Mostrar a Agenda de prospecção (follow-ups)", "sim_nao", "", ""),
     ]},
    {"id": "avisos", "titulo": "Avisos e LGPD",
     "descricao": "Avisos de problema do sistema e quanto tempo os dados ficam guardados.",
     "campos": [
         ("alertas_emails", "Quem recebe os avisos de problema", "texto", "",
          "E-mails separados por vírgula. Em branco = os administradores."),
         ("limite_banco_mb", "Tamanho do banco contratado", "numero", "MB", "O aviso sai quando chega em 80%."),
         ("dias_retencao_perdidos", "Anonimizar leads encerrados ou com SAIR depois de", "numero", "dias", ""),
         ("guarda_conversas_meses", "Guardar a cópia das conversas do WhatsApp por", "numero", "meses",
          "0 = sem prazo. As originais continuam nos celulares e no WhatsApp Leads."),
     ]},
]
CAMPOS_GERAIS = [(c, rotulo, tipo) for secao in SECOES_GERAIS for c, rotulo, tipo, _, _ in secao["campos"]]


def _secoes_gerais(db: Session, usuario: Usuario) -> tuple[list[dict], bool]:
    """As seções da tela Geral com os valores de agora. Quem é de uma AR vê só o que pode mudar (o resto é da
    plataforma). Devolve (seções, se ficou alguma da plataforma de fora)."""
    master = autorizacao.e_master(usuario)
    secoes, de_fora = [], False
    for secao in SECOES_GERAIS:
        campos = []
        for chave, rotulo, tipo, unidade, ajuda in secao["campos"]:
            if not (master or (chave in CHAVES_DA_AR and chave not in CHAVES_SO_MASTER)):
                de_fora = True
                continue
            valor = ler_config(db, chave)
            if tipo == "hora":
                valor = util.hora_hhmm(valor)
            campos.append({"chave": chave, "rotulo": rotulo, "tipo": tipo, "unidade": unidade, "ajuda": ajuda,
                           "valor": valor, "ligado": str(valor or "").strip().lower() in ("1", "1.0", "sim", "true")})
        if campos:
            secoes.append({**secao, "campos": campos})
    return secoes, de_fora


def _cadastro_no_registro(u: Usuario) -> dict:
    """O que o registro de atividades guarda de uma mudança no cadastro de uma pessoa (sem senha nem 2 etapas)."""
    return {"nome": u.nome, "email": u.email, "papel": u.perfil if not u.papel_id else f"papel {u.papel_id}",
            "ativo": "sim" if u.ativo else "não", "equipe": u.equipe_id or "", "parceiro": u.parceiro_id or "",
            "expediente": u.expediente or "", "cidade": f"{u.cidade or ''} ({u.uf})" if u.uf else ""}


def _marca_no_registro(db: Session, ar: int) -> dict:
    """O que o registro de atividades guarda da marca de uma AR (o logo só como "tem" ou "não tem")."""
    linha = db.get(MarcaAR, ar)
    campos = ("nome", "curto", "artigo", "site", "descricao", "dominio_email", "cor", "cor_detalhe", "cor_fundo", "fonte",
              "uf", "cidade")
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


def _grupos_de_usuarios(db: Session, request: Request, usuario: Usuario) -> list[dict]:
    """Configurações > Usuários separados por marca (AR). O Admin Master fora das ARs vê todas (e a plataforma, onde fica
    ele); quem é de uma AR (e o master dentro dela) vê só a sua. Equipes, parceiros e papéis de cada quadro são os
    daquela AR (ou os da plataforma)."""
    pessoas = db.execute(select(Usuario).order_by(Usuario.ativo.desc(), Usuario.nome)).scalars().all()
    equipes = db.execute(select(Equipe).order_by(Equipe.nome)).scalars().all()
    parceiros = db.execute(select(Parceiro).order_by(Parceiro.escritorio)).scalars().all()
    papeis = _papeis(db)
    ar_tela = marca.ar_da_tela(request, usuario)
    consulta = select(Tenant.id, Tenant.nome).order_by(Tenant.id)
    ars = db.execute(consulta.where(Tenant.id == ar_tela) if ar_tela else consulta).all()
    grupos = [{"ar": ar, "nome": nome, "pode_criar": True,
               "pessoas": [u for u in pessoas if u.tenant_id == ar],
               "equipes": [e for e in equipes if e.tenant_id in (ar, None)],
               "parceiros": [p for p in parceiros if p.tenant_id == ar],
               "papeis": [p for p in papeis if p.tenant_id in (ar, None)]} for ar, nome in ars]
    da_plataforma = [u for u in pessoas if u.tenant_id is None] if not ar_tela else []
    if da_plataforma:
        grupos.append({"ar": None, "nome": "Plataforma", "pode_criar": False, "pessoas": da_plataforma,
                       "equipes": [e for e in equipes if e.tenant_id is None], "parceiros": [],
                       "papeis": [p for p in papeis if p.tenant_id is None]})
    return grupos


@rotas.get("/configuracoes")
def configuracoes(request: Request, aba: str = "geral", usuario: Usuario = Depends(exige("configuracoes.ver")), db: Session = Depends(obter_db)):
    from .. import feriados

    wl = whatsapp_leads.status(False)  # uma consulta só (antes eram duas a cada abertura da tela)
    from .assertiva import painel as painel_assertiva

    # Assertiva: as credenciais são de cada marca (a da tela); o quadro e a linha do resumo só na aba Integrações
    assertiva_painel = painel_assertiva(request, usuario, db) if aba == "integracoes" else None
    ar_tela = marca.ar_da_tela(request, usuario)
    dominio_dns = (marca.da_ar(db, ar_tela)["dominio_email"] if ar_tela else config.EMAIL_DOMINIO) if aba == "email" else ""
    return tela(request, "configuracoes.html", {
        # white label: quem é de uma AR muda só as configurações da AR (o resto é da plataforma: Admin Master)
        "aba": aba, "secao": aba, "ufs": feriados.UFS,
        "feriados": feriados.painel(db, request.query_params.get("uf", ""), request.query_params.get("cidade", ""),
                                    ar=marca.ar_da_tela(request, usuario))
        if aba == "feriados" else None,
        "grupos_usuarios": _grupos_de_usuarios(db, request, usuario) if aba == "usuarios" else [],
        **(dict(zip(("secoes_gerais", "configs_da_plataforma"), _secoes_gerais(db, usuario))) if aba == "geral" else {}),
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
            ("Assertiva (consultas, desta marca)", bool(assertiva_painel and assertiva_painel["configurada"]),
             "Client ID e Client Secret da marca: no quadro Assertiva abaixo"),
            ("Google Places", bool(config.GOOGLE_PLACES_API_KEY), "GOOGLE_PLACES_API_KEY no .env"),
            ("OpenStreetMap", True, "Gratuito, já funciona"),
            ("BrasilAPI (CNPJ)", True, "Gratuito, já funciona"),
            ("Banco de dados", True, "PostgreSQL" if "postgres" in config.DATABASE_URL else "SQLite (arquivo local em dados/)"),
        ],
        "fontes": prospeccao.fontes_disponiveis(db), "receita": base_receita.resumo(db),
        "listas": bases_importadas.listas(db) if aba == "integracoes" else [],
        "receita_oculta": bases_importadas.receita_oculta(db),
        "tem_chave_cnpja": bool(_chave_cnpja()) if aba == "integracoes" else False,
        "assertiva": assertiva_painel,
        "painel_avisos": {"ativos": alertas.ativos(db, ar_tela), "para": alertas.destinatarios(db), "ligado": alertas.ligado(),
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
    from .. import feriados

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
    campos = ("nome", "curto", "artigo", "site", "descricao", "dominio_email", "cor", "cor_detalhe", "cor_fundo", "fonte",
              "uf", "cidade")
    antes = _marca_no_registro(db, ar)
    tirar_fundo = form.get("tirar_fundo") == "1"
    problemas = marca.salvar(db, ar, {c: str(form.get(c) or "") for c in campos if c in form}, novo_logo,
                             tirar_logo=form.get("tirar_logo") == "1", tirar_fundo=tirar_fundo)
    db.flush()
    feito = (["logo novo"] if novo_logo else []) + (["tirou o fundo do logo"] if tirar_fundo else [])
    depois = _marca_no_registro(db, ar)
    registrar_log(db, usuario, "salvou_marca", "tenant", ar, "; ".join(feito + problemas)[:250], request,
                  modulo="Marca", mudancas=diferencas(antes, depois))
    marca.esquecer(ar)
    movidos = 0
    if (antes.get("uf"), antes.get("cidade")) != (depois.get("uf"), depois.get("cidade")):
        # quem está sem cidade no cadastro segue a da marca: os toques num feriado dela mudam de dia
        sem_local = {u.id for u in db.execute(select(Usuario).where(Usuario.tenant_id == ar)
                                              .execution_options(sem_filtro_de_ar=True)).scalars()
                     if not feriados.normalizar_uf(u.uf)}
        if sem_local:
            movidos = _remarcar_feriados(db, sem_local)
    db.commit()
    if movidos:
        avisar(request, f"{movidos} toque(s) que caíam num feriado da cidade da marca mudaram de dia.")
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
    for chave, rotulo, tipo in CAMPOS_GERAIS:
        if chave in form and (master or (chave in CHAVES_DA_AR and chave not in CHAVES_SO_MASTER)):  # da plataforma: master
            valor = str(form.get(chave)).strip()  # chave liga/desliga: vem "0" (escondido) e "1" (marcado); vale o último
            if tipo == "sim_nao":
                valor = "1" if valor.lower() in ("1", "on", "sim", "true") else "0"
            elif tipo == "numero" and not (valor == "" and chave in VAZIO_E_PADRAO):
                valor = str(util.para_float(valor)).removesuffix(".0")
            if chave in HORARIOS_DE_ENVIO and valor:  # sempre HH:MM, com o zero (o "8:12" parou a fila em 19/11/2026)
                normal = util.hora_hhmm(valor)
                if not normal:
                    db.rollback()
                    avisar(request, f"Horário inválido em \"{rotulo}\": escreva como 08:30.", "erro")
                    return voltar("/configuracoes")
                valor = normal
            gravar_config(db, chave, valor)
    inicio, fim = (util.hora_hhmm(ler_config(db, c)) for c in HORARIOS_DE_ENVIO)
    if inicio and fim and inicio >= fim:
        db.rollback()
        avisar(request, "O horário de envio precisa terminar depois de começar (ex.: das 08:30 às 18:00).", "erro")
        return voltar("/configuracoes")
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
                   ar: str = Form(""), cidade: str = Form("manter"), uf: str = Form("manter"),
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
        from ..agenda_horarios import faixas_por_dia

        if not faixas_por_dia(expediente):
            avisar(request, "Expediente inválido. Use o formato: seg-sex 09:00-12:00,14:00-18:00 (com um dia diferente, "
                            "separe por ponto e vírgula: seg-qui 08:00-18:00; sex 08:00-17:30)", "erro")
            return voltar(destino)
        u.expediente = expediente.strip()
    u.duracao_reuniao = util.para_int(duracao_reuniao) or u.duracao_reuniao or 30
    from .. import feriados  # onde a pessoa trabalha: os feriados do estado e da cidade dela (18/11/2026)

    local_antes = (u.cidade or "", u.uf or "")
    if uf != "manter":
        u.uf = feriados.normalizar_uf(uf)
    aviso_cidade = ""
    if cidade != "manter":  # o nome como o IBGE escreve (a base de feriados é por município)
        u.cidade, aviso_cidade = feriados.conferir_cidade(u.uf, cidade)
    mudou_local = bool(uid) and (u.cidade or "", u.uf or "") != local_antes
    # white label: a marca da pessoa. Nova pessoa criada pelo Admin Master fora das ARs vai para a marca do quadro em
    # que ele clicou; quem é de uma AR (ou o master dentro dela) cria na própria (isolamento._ar_nas_novas)
    ar_da_tela = marca.ar_da_tela(request, usuario)
    if uid == 0 and not ar_da_tela and autorizacao.e_master(usuario):
        escolhida = util.para_int(ar)
        if not escolhida or db.get(Tenant, escolhida) is None:
            avisar(request, "Escolha em qual marca a pessoa nova trabalha (o botão \"+ Nova pessoa\" do quadro dela).",
                   "erro")
            return voltar(destino)
        u.tenant_id = escolhida
    ar_da_pessoa = u.tenant_id if u.tenant_id else ar_da_tela
    if ar_da_pessoa:  # equipe, parceiro e papel da mesma marca da pessoa (ou da plataforma)
        de_outra = [nome for nome, obj in (("A equipe", db.get(Equipe, u.equipe_id) if u.equipe_id else None),
                                           ("O parceiro", db.get(Parceiro, u.parceiro_id) if u.parceiro_id else None),
                                           ("O papel", papel))
                    if obj is not None and obj.tenant_id not in (None, ar_da_pessoa)]
        if de_outra:
            db.rollback()
            avisar(request, f"{de_outra[0]} escolhido é de outra marca. Escolha um da mesma marca da pessoa.", "erro")
            return voltar(destino)
    if uid == 0:
        db.add(u)
    db.flush()
    registrar_log(db, usuario, "salvou_usuario", "usuario", u.id, f"{u.email} ({papel.nome})", request,
                  mudancas=diferencas(antes, _cadastro_no_registro(u)))
    movidos = _remarcar_feriados(db, {u.id}) if mudou_local else 0
    db.commit()
    avisar(request, "Usuário salvo." + (" Envie a senha para a pessoa por um canal seguro." if uid == 0 else "")
           + (f" {movidos} toque(s) que caíam num feriado da cidade dela mudaram de dia." if movidos else ""))
    if aviso_cidade:
        avisar(request, aviso_cidade, "alerta")
    return voltar(destino)


def _remarcar_feriados(db: Session, pessoas: set[int] | None = None) -> int:
    """Depois de mudar a cidade de alguém ou os feriados: os toques marcados num feriado de quem envia mudam de dia
    (campanhas e cadências: feriados.remarcar; Renovação: renovacao.remarcar_feriados, com as regras do vencimento)."""
    from .. import feriados, renovacao

    db.flush()
    movidos = feriados.remarcar(db, pessoas=pessoas)
    try:
        movidos += renovacao.remarcar_feriados(db)["remarcados"]
    except Exception:  # noqa: BLE001 - a Renovação não pode impedir de salvar (a rotina de hora em hora tenta de novo)
        log.exception("Feriados: não deu para remarcar os avisos da Renovação")
    return movidos


@rotas.post("/configuracoes/feriados", dependencies=[Depends(verificar_csrf)])
async def salvar_feriados(request: Request, usuario: Usuario = Depends(exige("configuracoes.alterar")),
                          db: Session = Depends(obter_db)):
    """Configurações > Feriados: os feriados do estado e da cidade (de cada marca; os nacionais são automáticos)."""
    from .. import feriados

    destino = "/configuracoes?aba=feriados"
    form = await request.form()
    antes = feriados.locais(db)
    listas = dict(antes)
    invalidas: list[str] = []
    for campo, valor in form.multi_items():
        if not campo.startswith("local__"):
            continue
        chave = campo.removeprefix("local__")
        uf_, _, cidade_ = chave.partition("/")
        if feriados.chave_do_local(uf_, cidade_) != chave:
            continue
        itens, ruins = feriados.ler_lista(str(valor))
        invalidas += ruins
        listas[chave] = feriados.texto_da_lista(itens)
    if str(form.get("nova_lista") or "").strip():
        nova = feriados.chave_do_local(str(form.get("nova_uf") or ""), str(form.get("nova_cidade") or ""))
        if not nova:
            avisar(request, "Escolha a UF da cidade (ou do estado) dos feriados novos.", "erro")
            return voltar(destino)
        itens, ruins = feriados.ler_lista(str(form.get("nova_lista")))
        invalidas += ruins
        ja = feriados.ler_lista(listas.get(nova, ""))[0]
        listas[nova] = feriados.texto_da_lista(ja + [i for i in itens if i[:3] not in {j[:3] for j in ja}])
    if invalidas:
        avisar(request, "Não entendi: " + "; ".join(invalidas[:5]) + ". Escreva uma data por linha, como "
               "\"16/07 Nossa Senhora do Carmo\" (todo ano) ou \"20/11/2026 Ponto facultativo\" (só naquele ano). "
               "Nada foi salvo.", "erro")
        return voltar(destino)
    feriados.gravar_locais(db, listas)
    movidos = _remarcar_feriados(db)
    registrar_log(db, usuario, "salvou_feriados", "configuracao", None, request=request,
                  mudancas=diferencas(antes, feriados.locais(db)))
    db.commit()
    avisar(request, "Feriados salvos." + (f" {movidos} toque(s) que caíam num feriado mudaram de dia." if movidos else ""))
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
