"""Tela Renovação: avisos de vencimento do certificado para os clientes da MS (planilha de renovação, app/renovacao.py)."""

import json
from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import autorizacao, renovacao, util
from ..banco import gravar_config, ler_config_int, obter_db
from ..modelos import Certificado, Tarefa, Usuario
from ..seguranca import exige, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()

FILTROS = {"avisar": "Vencem em 30 dias", "campanha": "Em campanha", "sem_contato": "Sem WhatsApp e e-mail",
           "proximos": "Todos a vencer", "encerrados": "Renovados e não vão renovar", "vencidos": "Vencidos"}
LIMITE_LISTA = 500
TAMANHO_MAXIMO = 4_000_000  # bytes (a nuvem recebe até 4,5 MB por envio)


def _n(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def _no_filtro(ver: str, c: Certificado, hoje: date, janela: int = renovacao.JANELA_DIAS) -> bool:
    aberto = c.status == "Ativo" and c.data_vencimento >= hoje
    if ver == "avisar":
        return aberto and c.data_vencimento <= hoje + timedelta(days=janela)
    if ver == "campanha":
        return aberto and bool(c.campanha_id)
    if ver == "sem_contato":
        return aberto and not renovacao.chave_do_contato(c)
    if ver == "proximos":
        return aberto
    if ver == "encerrados":
        return c.status in ("Renovado", "Não renovará")
    return c.status == "Vencido" or (c.status == "Ativo" and c.data_vencimento < hoje)


@rotas.get("/renovacao")
def tela_renovacao(request: Request, ver: str = "avisar", usuario: Usuario = Depends(exige("campanhas.ver")),
                   db: Session = Depends(obter_db)):
    hoje = date.today()
    ver = ver if ver in FILTROS else "avisar"
    dias = renovacao.dias_aviso(db)
    janela = dias[0]
    filtros = {**FILTROS, "avisar": f"Vencem em {janela} dias"}
    todos = db.execute(select(Certificado).where(Certificado.origem == renovacao.ORIGEM)).scalars().all()
    abertos = [c for c in todos if c.status == "Ativo" and c.data_vencimento >= hoje]
    contatos, fora = renovacao.contatos_para_campanha(db, hoje)
    kpis = {
        "base": len(abertos),
        "em_30": sum(1 for c in abertos if c.data_vencimento <= hoje + timedelta(days=janela)),
        "prontos_contatos": len(contatos), "prontos_certificados": sum(len(c.certificados) for c in contatos),
        "em_campanha": sum(1 for c in abertos if c.campanha_id),
        "sem_contato": sum(1 for c in abertos if not renovacao.chave_do_contato(c)),
        "renovados": sum(1 for c in todos if c.status == "Renovado"),
    }
    lista = sorted((c for c in todos if _no_filtro(ver, c, hoje)), key=lambda c: (c.data_vencimento, c.cliente_nome))
    por_contato = Counter(renovacao.chave_do_contato(c) for c in abertos)
    campanhas = renovacao.campanhas_recentes(db)
    contagem = dict(db.execute(select(Tarefa.campanha_id, func.count(func.distinct(Tarefa.lead_id)))
                               .where(Tarefa.campanha_id.in_([c.id for c in campanhas]))
                               .group_by(Tarefa.campanha_id)).all()) if campanhas else {}
    usuarios = db.execute(select(Usuario).where(Usuario.ativo.is_(True), Usuario.perfil != "parceiro")
                          .order_by(Usuario.nome)).scalars().all()
    from .. import conexoes

    numeros = renovacao.numeros_para_escolher(db)
    try:
        auto = renovacao.numero_automatico(db, renovacao.dono(db) or usuario)
        numero_auto = next((f"{n['nome']}{' · ' + n['numero'] if n['numero'] else ''}"
                            + (" · MODO TESTE" if n["teste"] else "") for n in numeros if n["id"] == auto), auto)
    except conexoes.SemNumero:
        numero_auto = "nenhum número conectado"
    return tela(request, "renovacao.html", {
        "cfg": {c: renovacao.cfg(db, c) for c in renovacao.PADRAO}, "mensagens": renovacao.mensagens(db),
        "angulos": renovacao.nomes_dos_avisos(dias), "dias_aviso": dias, "janela": janela,
        "quantidades": renovacao.QUANTIDADES,
        "kpis": kpis, "fora": fora, "filtros": filtros, "ver": ver, "lista": lista[:LIMITE_LISTA],
        "total_lista": len(lista), "por_contato": por_contato, "hoje": hoje, "campanhas": campanhas,
        "contatos_por_campanha": contagem, "usuarios": usuarios, "dono": renovacao.dono(db),
        "limite_frios": ler_config_int(db, "limite_frios_whatsapp", 0), "situacoes": renovacao.SITUACOES,
        "situacao": lambda c, h: renovacao.situacao_na_tela(c, h, janela),
        "chave_do_contato": renovacao.chave_do_contato,
        "tipo_curto": renovacao.tipo_curto, "url_da_arte": renovacao.URL_DA_ARTE,
        "artes": renovacao.situacao_das_artes(db),
        "exemplos": renovacao.exemplos_para_teste(db), "avisos_teste": renovacao.avisos_teste(db),
        "remetente": renovacao.dono(db) or usuario, "numeros": numeros,
        "numero_auto": numero_auto, "pode_escolher_numero": autorizacao.pode(usuario, "campanhas.escolher_numero"),
    })


@rotas.post("/renovacao/importar", dependencies=[Depends(verificar_csrf)])
async def importar(request: Request, arquivo: UploadFile = File(...), usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                   db: Session = Depends(obter_db)):
    conteudo = await arquivo.read()
    if not conteudo:
        avisar(request, "Escolha o arquivo da planilha de renovação (Excel .xlsx ou CSV).", "erro")
        return voltar("/renovacao")
    if len(conteudo) > TAMANHO_MAXIMO:
        avisar(request, "A planilha passou de 4 MB. Salve só a aba do relatório (ou divida em duas) e importe de novo.",
               "erro")
        return voltar("/renovacao")
    try:
        registros, problemas = renovacao.ler_planilha(arquivo.filename or "", conteudo)
    except renovacao.ErroPlanilha as erro:
        avisar(request, str(erro), "erro")
        return voltar("/renovacao")
    if not registros:
        avisar(request, "Não achei nenhum certificado na planilha (as linhas estão sem data de vencimento?).", "erro")
        return voltar("/renovacao")
    r = renovacao.importar(db, registros, usuario, (arquivo.filename or "")[:80])
    registrar_log(db, usuario, "importou_renovacao", "certificado", None,
                  f"{r['novos']} novos, {r['atualizados']} atualizados, {r['linhas']} linhas ({arquivo.filename})", request)
    db.commit()
    texto = (f"Planilha importada: {_n(r['novos'], 'certificado novo', 'certificados novos')} e "
             f"{_n(r['atualizados'], 'atualizado', 'atualizados')} ({r['iguais']} já estavam iguais). "
             f"{_n(r['na_janela'], 'vence', 'vencem')} nos próximos {r['janela']} dias.")
    if r["sem_contato"]:
        texto += f" {r['sem_contato']} estão sem WhatsApp e sem e-mail na planilha (não recebem aviso)."
    if r["vencidos"]:
        texto += f" {r['vencidos']} já venceram (não recebem aviso)."
    if problemas:
        texto += f" {len(problemas)} linhas ficaram de fora: " + "; ".join(problemas[:5]) + ("..." if len(problemas) > 5 else "")
    avisar(request, texto, "alerta" if problemas else "ok")
    return voltar("/renovacao")


@rotas.post("/renovacao/montar", dependencies=[Depends(verificar_csrf)])
async def montar(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                 db: Session = Depends(obter_db)):
    form = await request.form()
    quantidade = util.para_int(form.get("quantidade"))
    if quantidade not in renovacao.QUANTIDADES:
        quantidade = renovacao.QUANTIDADES[0]
    camp = renovacao.criar_campanha(db, renovacao.dono(db) or usuario, quantidade)
    if camp is None:
        avisar(request, "Nenhum cliente para avisar agora: ninguém com certificado vencendo nos próximos 30 dias fora de "
                        "campanha (confira a lista abaixo e importe a planilha mais recente).", "erro")
        return voltar("/renovacao")
    registrar_log(db, usuario, "montou_campanha_renovacao", "campanha", camp.id,
                  f"{camp.quantidade} contatos (pediu {quantidade})", request)
    db.commit()
    avisar(request, f"A campanha está sendo montada com {camp.quantidade} contatos (os que vencem primeiro) e vai pedir "
                    "aprovação (leva alguns minutos).")
    return voltar(f"/campanhas/{camp.id}")


@rotas.post("/renovacao/configurar", dependencies=[Depends(verificar_csrf)])
async def configurar(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                     db: Session = Depends(obter_db)):
    form = await request.form()
    canais = ",".join(c for c in ("whatsapp", "email") if form.get(f"canal_{c}"))
    if not canais:
        avisar(request, "Escolha pelo menos um canal (WhatsApp ou e-mail).", "erro")
        return voltar("/renovacao#configurar")
    maximo = max(1, min(300, util.para_int(form.get("maximo_dia")) or 40))
    # dias dos 4 avisos (ex.: "12, 6, 3, 1"), horário mínimo e o dia em que a campanha automática começa
    import re

    dias_txt = sorted({util.para_int(x) or 0 for x in re.split(r"[,; ]+", str(form.get("dias", ""))) if x.strip()},
                      reverse=True)
    if form.get("dias") is not None:
        if len(dias_txt) != 4 or dias_txt[-1] < 1 or dias_txt[0] > 90:
            avisar(request, "Escreva os 4 dias dos avisos, diferentes, de 1 a 90 (ex.: 12, 6, 3, 1).", "erro")
            return voltar("/renovacao#configurar")
        gravar_config(db, "renov_dias", ",".join(str(d) for d in dias_txt))
    hora_inicio = str(form.get("hora_inicio", "") or "")[:5]
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora_inicio):
        hora_inicio = ""
    desde = util.para_data(form.get("ativo_desde"))
    gravar_config(db, "renov_hora_inicio", hora_inicio)
    gravar_config(db, "renov_ativo_desde", desde.isoformat() if desde else "")
    hora = str(form.get("hora", "07:45"))[:5] or "07:45"
    dono_id = util.para_int(form.get("dono_id"))
    if dono_id and not db.get(Usuario, dono_id):
        dono_id = None
    if autorizacao.pode(usuario, "campanhas.escolher_numero"):  # só quem pode escolher o número (administrador)
        from ..modelos import ConexaoWhatsApp

        conexao = str(form.get("conexao") or "")
        gravar_config(db, "renov_conexao", conexao if conexao and db.get(ConexaoWhatsApp, conexao) else "")
    for chave, valor in [("renov_ativo", "1" if form.get("ativo") else "0"), ("renov_canais", canais),
                         ("renov_arte", "1" if form.get("arte") else "0"),
                         ("renov_maximo_dia", str(maximo)), ("renov_hora", hora), ("renov_dono_id", str(dono_id or ""))]:
        gravar_config(db, chave, valor)
    registrar_log(db, usuario, "configurou_renovacao", "configuracao", None, request=request)
    db.commit()
    if form.get("ativo") and not dono_id:
        avisar(request, "Configuração salva, mas escolha quem é o dono das campanhas de renovação.", "erro")
    else:
        avisar(request, "Configuração salva." + (
            f" A campanha automática roda todo dia às {hora}" + (f", a partir de {desde:%d/%m/%Y}" if desde else "") + "."
            if form.get("ativo") else ""))
    return voltar("/renovacao#configurar")


@rotas.post("/renovacao/mensagens", dependencies=[Depends(verificar_csrf)])
async def salvar_mensagens(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                           db: Session = Depends(obter_db)):
    from .. import sdr

    form = await request.form()
    novas = {}
    for angulo in renovacao.ANGULOS:
        item = {campo: str(form.get(f"{angulo}_{campo}", "")).strip() for campo in ("assunto", "whatsapp", "email")}
        if not all(item.values()):
            avisar(request, "Preencha o assunto, o WhatsApp e o e-mail de todos os avisos.", "erro")
            return voltar("/renovacao#mensagens")
        if "{vencimentos}" not in item["whatsapp"] or "{vencimentos}" not in item["email"]:
            avisar(request, "Deixe o {vencimentos} no WhatsApp e no e-mail de todos os avisos: é onde entram os "
                            "certificados do cliente e as datas.", "erro")
            return voltar("/renovacao#mensagens")
        if not all(sdr.texto_sem_spam(v) for v in item.values()):
            avisar(request, "Tire as frases de spam (\"excelente oportunidade\", \"promoção\", \"não perca\"...).", "erro")
            return voltar("/renovacao#mensagens")
        novas[angulo] = item
    gravar_config(db, "renov_mensagens", json.dumps(novas, ensure_ascii=False))
    registrar_log(db, usuario, "editou_mensagens_renovacao", "configuracao", None, request=request)
    db.commit()
    avisar(request, "Mensagens salvas. Valem para as próximas campanhas de renovação.")
    return voltar("/renovacao#mensagens")


@rotas.post("/renovacao/restaurar-mensagens", dependencies=[Depends(verificar_csrf)])
def restaurar_mensagens(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                        db: Session = Depends(obter_db)):
    gravar_config(db, "renov_mensagens", "")
    registrar_log(db, usuario, "restaurou_mensagens_renovacao", "configuracao", None, request=request)
    db.commit()
    avisar(request, "Mensagens voltaram ao texto inicial.")
    return voltar("/renovacao#mensagens")


@rotas.post("/renovacao/testar", dependencies=[Depends(verificar_csrf)])
async def testar(request: Request, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                 db: Session = Depends(obter_db)):
    """Área de teste (como a da IA SDR): os avisos chegam no WhatsApp ou no e-mail de quem testa, com "[TESTE]"."""
    form = await request.form()
    canal = "email" if form.get("canal") == "email" else "whatsapp"
    if canal == "email":
        destino = str(form.get("email_teste", "")).strip()
        invalido = "" if util.email_valido(destino) else "Digite um e-mail válido para receber o teste."
    else:
        digitos = util.normalizar_telefone(str(form.get("whatsapp_teste", "")))
        destino = "55" + digitos if digitos else ""
        invalido = "" if digitos else "Digite o seu celular com DDD para receber o teste no WhatsApp."
    if invalido:
        avisar(request, invalido, "erro")
        return voltar("/renovacao#testar")
    cert_id = util.para_int(form.get("certificado")) or 0
    try:
        conexao = str(form.get("conexao_teste") or "") if autorizacao.pode(usuario, "campanhas.escolher_numero") else ""
        r = renovacao.enviar_teste(db, usuario, cert_id, canal, destino, str(form.get("avisos", "renov_aviso")),
                                   com_arte=bool(form.get("com_arte")), conexao=conexao)
    except ValueError as erro:
        avisar(request, str(erro), "erro")
        return voltar("/renovacao#testar")
    registrar_log(db, usuario, "testou_renovacao", "certificado", cert_id or None,
                  f"{r['enviadas']} de {canal} para {destino}" + (" com a arte" if r["arte"] else ""), request)
    db.commit()
    if r["enviadas"]:
        para = destino if canal == "email" else util.formatar_telefone(destino[2:])
        texto = (f"Teste enviado: {_n(r['enviadas'], 'mensagem', 'mensagens')} de "
                 f"{'e-mail' if canal == 'email' else 'WhatsApp'} para {para}, assinado por {r['remetente']}"
                 + (f", pelo número {r['numero']}" if r["numero"] else "") + ". Nenhum cliente recebeu nada.")
        if r["modo_teste"]:
            avisar(request, f"Atenção: o número {r['numero']} está em MODO TESTE. O WhatsApp Leads só simula o envio, "
                            "e a mensagem NÃO chega de verdade. Escolha um número conectado por QR code.", "alerta")
        if r["arte"]:
            texto += (" Com a arte: o computador do WhatsApp Leads desenha e manda em até 1 minuto."
                      if canal == "whatsapp" else " Com a arte do teste de WhatsApp deste cliente.")
        elif r["arte_pedida"] and r["certificados"] > 1:
            texto += (f" Sem a arte: este contato tem {r['certificados']} certificados, e no envio de verdade ele recebe "
                      "a lista no texto (a arte é de um certificado só).")
        elif r["arte_pedida"] and canal == "email":
            texto += (" Sem a arte: quem desenha a arte é o computador do WhatsApp Leads. Mande antes o teste no "
                      "WhatsApp deste cliente; em 1 minuto a arte volta e o teste de e-mail já sai com ela.")
        elif r["arte_pedida"]:
            texto += " Sem a arte (o certificado não é A1 nem A3, ou o sistema não está na nuvem)."
        avisar(request, texto)
    for erro in r["erros"]:
        avisar(request, erro, "erro")
    return voltar("/renovacao#testar")


@rotas.post("/renovacao/certificado/{cid:int}/situacao", dependencies=[Depends(verificar_csrf)])
async def mudar_situacao(request: Request, cid: int, usuario: Usuario = Depends(exige("campanhas.gerenciar")),
                         db: Session = Depends(obter_db)):
    form = await request.form()
    cert = db.get(Certificado, cid)
    if cert is None or cert.origem != renovacao.ORIGEM:
        raise HTTPException(404)
    situacao = str(form.get("situacao", ""))
    if situacao not in renovacao.SITUACOES:
        avisar(request, "Situação inválida.", "erro")
        return voltar("/renovacao")
    cancelados = renovacao.mudar_situacao(db, cert, situacao, usuario)
    registrar_log(db, usuario, "situacao_certificado", "certificado", cert.id,
                  f"{renovacao.SITUACOES[situacao]} ({cert.cliente_nome}, vence {cert.data_vencimento:%d/%m/%Y})", request)
    db.commit()
    avisar(request, f"{cert.cliente_nome}: {renovacao.SITUACOES[situacao].lower()}."
                    + (f" {cancelados} avisos que ainda não tinham saído foram cancelados." if cancelados else ""))
    ver = str(form.get("ver", ""))
    return voltar(f"/renovacao?ver={ver}#certificados" if ver in FILTROS else "/renovacao#certificados")
