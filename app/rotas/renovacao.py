"""Tela Renovação: avisos de vencimento do certificado para os clientes da AR (planilha de renovação, app/renovacao.py)."""

import json
import re
from collections import Counter
from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import autorizacao, marca, renovacao, util
from .. import visual as _visual
from ..banco import gravar_config, gravar_config_da_ar, ler_config_int, obter_db, usar_config_da_ar
from ..modelos import Certificado, Tarefa, Usuario
from ..seguranca import diferencas, exige, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()

FILTROS = {"avisar": "Vencem em 30 dias", "campanha": "Em campanha", "sem_contato": "Sem WhatsApp e e-mail",
           "proximos": "Todos a vencer", "encerrados": "Renovados e não vão renovar",
           "cancelados": "Avisos cancelados", "vencidos": "Vencidos"}
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
    if ver == "cancelados":
        return c.status == "Avisos cancelados"
    return c.status == "Vencido" or (c.status == "Ativo" and c.data_vencimento < hoje)


def _na_busca(c: Certificado, busca: str) -> bool:
    """Campo de pesquisa da lista de certificados (pedido da Maria em 16/11/2026: o time achar a empresa rápido), em
    todas as abas. Só números (CNPJ, CPF, telefone, protocolo; com ou sem pontos e traços, 3 ou mais): procura nos
    números. Com letras: cada palavra, sem acento e sem diferença de maiúscula, em algum campo (cliente, responsável,
    e-mail, certificado, parceiro, protocolo, CNPJ/CPF)."""
    digitos = util.so_digitos(busca)
    if digitos and not re.search(r"[^\d\s().+/-]", busca):
        return len(digitos) >= 3 and any(digitos in util.so_digitos(x) for x in (c.cnpj, c.whatsapp, c.telefone,
                                                                                 c.protocolo))
    texto = util.chave_texto(" ".join(x or "" for x in (c.cliente_nome, c.responsavel, c.email, c.tipo,
                                                        c.parceiro_nome, c.protocolo, c.cnpj)))
    return all(p in texto for p in util.chave_texto(busca).split())


def _endereco_da_lista(ver: str, busca: str = "") -> str:
    """Volta para a lista de certificados na mesma aba e com a mesma pesquisa."""
    params = {"ver": ver} if ver in FILTROS else {}
    if busca:
        params["q"] = busca
    return "/renovacao" + (f"?{urlencode(params)}" if params else "") + "#certificados"


@rotas.get("/renovacao")
def tela_renovacao(request: Request, ver: str = "avisar", q: str = "", usuario: Usuario = Depends(exige("campanhas.configurar")),
                   db: Session = Depends(obter_db)):
    _na_ar_da_renovacao(db, request, usuario)
    hoje = date.today()
    ver = ver if ver in FILTROS else "avisar"
    busca = q.strip()[:80]
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
    no_filtro = (lambda c: _na_busca(c, busca)) if busca else (lambda c: _no_filtro(ver, c, hoje))
    lista = sorted((c for c in todos if no_filtro(c)), key=lambda c: (c.data_vencimento, c.cliente_nome))
    por_contato = Counter(renovacao.chave_do_contato(c) for c in abertos)
    # as campanhas seguem a hierarquia: as da pessoa e as de quem está abaixo (o administrador vê todas)
    campanhas = [c for c in renovacao.campanhas_recentes(db) if autorizacao.pode(usuario, "campanhas.ver", c)]
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
        "kpis": kpis, "fora": fora, "filtros": filtros, "ver": ver, "busca": busca, "lista": lista[:LIMITE_LISTA],
        "total_lista": len(lista), "por_contato": por_contato, "hoje": hoje, "campanhas": campanhas,
        "contatos_por_campanha": contagem, "usuarios": usuarios, "dono": renovacao.dono(db),
        "limite_frios": ler_config_int(db, "limite_frios_whatsapp", 0), "situacoes": renovacao.SITUACOES,
        "situacao": lambda c, h: renovacao.situacao_na_tela(c, h, janela),
        "chave_do_contato": renovacao.chave_do_contato,
        "tipo_curto": renovacao.tipo_curto,
        **_arte_da_marca(db, request, usuario),
        "artes": renovacao.situacao_das_artes(db),
        "exemplos": renovacao.exemplos_para_teste(db), "avisos_teste": renovacao.avisos_teste(db),
        "remetente": renovacao.dono(db) or usuario, "numeros": numeros,
        "numeros_disparo": renovacao.numeros_para_escolher(db, renovacao.dono(db) or usuario),
        "numero_auto": numero_auto, "pode_escolher_numero": autorizacao.pode(usuario, "campanhas.escolher_numero"),
        **_api_oficial(db, request, usuario),
        "aprovaveis": {c.id for c in campanhas if autorizacao.pode(usuario, "campanhas.gerenciar", c)},
        "email_html_liberado": _visual.html_da_marca_ligado(db),
        "proximos_feriados": renovacao.proximos_feriados(db),
    })


@rotas.post("/renovacao/importar", dependencies=[Depends(verificar_csrf)])
async def importar(request: Request, arquivo: UploadFile = File(...), usuario: Usuario = Depends(exige("campanhas.configurar")),
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
async def montar(request: Request, usuario: Usuario = Depends(exige("campanhas.configurar")),
                 db: Session = Depends(obter_db)):
    form = await request.form()
    _na_ar_da_renovacao(db, request, usuario)
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


def _ar_da_renovacao(db, request: Request, usuario: Usuario):
    """A AR da tela (o Admin Master fora de uma AR fala pela AR MS, dona da Renovação)."""
    return marca.ar_da_tela(request, usuario) or marca.ar_padrao(db)


def _na_ar_da_renovacao(db, request: Request, usuario: Usuario) -> int | None:
    """As configurações de cada AR (dono, número, API oficial, calendário, arte) lidas e gravadas na AR da tela: o Admin
    Master fora das ARs mexe nas da AR MS (como a rodada diária, renovacao.rodada_diaria), nunca nas da plataforma."""
    ar = _ar_da_renovacao(db, request, usuario)
    usar_config_da_ar(db, ar)
    return ar


def _arte_da_marca(db, request: Request, usuario: Usuario) -> dict:
    """Para os quadros 1 e 4: a página da arte do aviso da marca da tela (vazio: a marca não tem e sai só o texto)."""
    ar = _ar_da_renovacao(db, request, usuario)
    m = marca.da_ar(db, ar)
    return {"url_da_arte": renovacao.url_da_arte(db, ar), "nome_da_marca_renov": m["nome"],
            "arte_padrao": renovacao.URL_DA_ARTE if m["e_ms"] else "", "marca_principal": m["e_ms"]}


def _api_oficial(db, request: Request, usuario: Usuario) -> dict:
    """Para o quadro 4: o que falta para os avisos saírem pela API oficial da Meta e o número oficial."""
    from .. import whatsapp_oficial

    ar = _ar_da_renovacao(db, request, usuario)
    conta = whatsapp_oficial.conta_da_ar(db, ar)
    return {"falta_oficial": whatsapp_oficial.falta_para_renovacao(db, ar),
            "numero_oficial": (conta.numero or conta.nome) if conta is not None else "",
            "calendario_pronto": bool(conta is not None and conta.flow_agenda_id)}


@rotas.post("/renovacao/configurar", dependencies=[Depends(verificar_csrf)])
async def configurar(request: Request, usuario: Usuario = Depends(exige("campanhas.configurar")),
                     db: Session = Depends(obter_db)):
    form = await request.form()
    _na_ar_da_renovacao(db, request, usuario)
    canais = ",".join(c for c in ("whatsapp", "email") if form.get(f"canal_{c}"))
    if not canais:
        avisar(request, "Escolha pelo menos um canal (WhatsApp ou e-mail).", "erro")
        return voltar("/renovacao#configurar")
    maximo = max(1, min(300, util.para_int(form.get("maximo_dia")) or 40))
    # a página do site que desenha a arte do aviso desta marca (pedido da Maria em 23/11/2026: "coloque um campo
    # editável"). Só o Admin Master troca: quem abre a página, com os dados do cliente, é o servidor
    aviso_da_arte = ""
    if autorizacao.e_master(usuario) and form.get("arte_url") is not None:
        ar_arte = _ar_da_renovacao(db, request, usuario)
        novo, antes = str(form.get("arte_url") or "").strip(), renovacao.url_da_arte(db, ar_arte)
        if novo != antes:
            final, problema = renovacao.conferir_endereco_da_arte(db, ar_arte, novo) if novo else ("", "")
            if problema:
                avisar(request, f"O endereço da arte não foi salvo: {problema}.", "erro")
                return voltar("/renovacao#arte-url")
            gravar_config_da_ar(db, ar_arte, renovacao.CHAVE_URL_DA_ARTE, final)
            depois, m = renovacao.url_da_arte(db, ar_arte), marca.da_ar(db, ar_arte)
            registrar_log(db, usuario, "renovacao_endereco_da_arte", "tenant", ar_arte,
                          f"{m['nome']}: {depois or 'sem arte'}", request, modulo="Renovação",
                          mudancas=diferencas({"endereço da arte": antes}, {"endereço da arte": depois}))
            de_quem = marca.frase(m, "de", nome=True)
            aviso_da_arte = (f" Os avisos {de_quem} passam a sair com a arte de {depois}." if depois else
                             f" Sem endereço da arte: os avisos {de_quem} saem só com o texto.")
            if final and final != novo:  # a página do site traz a ferramenta numa moldura (Wix)
                aviso_da_arte += (" A ferramenta da arte fica numa moldura dentro da página do site: o sistema achou "
                                  "e guardou o endereço dela.")
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
    # até que horas (pedido da Maria em 13/11/2026: segunda a sexta, das 10:00 às 18:00; vazio = 18:00)
    hora_fim = str(form.get("hora_fim", "") or "")[:5]
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora_fim):
        hora_fim = ""
    if hora_fim and hora_fim <= (hora_inicio or "00:00"):
        avisar(request, "O horário final dos avisos precisa ser depois do inicial (ex.: das 10:00 às 18:00).", "erro")
        return voltar("/renovacao#configurar")
    # outros feriados sem avisos, além dos nacionais (pedido da Maria em 13/11/2026: "pular feriados")
    mudou_feriados = False
    if form.get("feriados") is not None:
        validos, invalidos = renovacao.feriados_extras(str(form.get("feriados")))
        if invalidos:
            avisar(request, "Não entendi estes feriados: " + ", ".join(invalidos[:5]) + ". Escreva como 08/12 (todo ano) "
                            "ou 08/12/2026 (só naquele ano), separados por vírgula.", "erro")
            return voltar("/renovacao#configurar")
        mudou_feriados = ", ".join(validos) != renovacao.cfg(db, "renov_feriados")
        gravar_config(db, "renov_feriados", ", ".join(validos))
    desde = util.para_data(form.get("ativo_desde"))
    gravar_config(db, "renov_hora_inicio", hora_inicio)
    gravar_config(db, "renov_hora_fim", hora_fim)
    gravar_config(db, "renov_ativo_desde", desde.isoformat() if desde else "")
    hora = str(form.get("hora", "07:45"))[:5] or "07:45"
    dono_id = util.para_int(form.get("dono_id"))
    if dono_id and not db.get(Usuario, dono_id):
        dono_id = None
    if autorizacao.pode(usuario, "campanhas.escolher_numero"):  # só quem pode escolher o número (administrador)
        from ..modelos import ConexaoWhatsApp

        from .. import conexoes as _conexoes

        conexao = str(form.get("conexao") or "")
        c = db.get(ConexaoWhatsApp, conexao) if conexao else None
        quem_assina = db.get(Usuario, dono_id) if dono_id else usuario
        if c is not None and not _conexoes.pode_disparar(quem_assina, c):  # regra da Maria em 13/11/2026
            avisar(request, f"O número {c.nome} não é de {quem_assina.nome} nem está compartilhado com ele: pela regra "
                            "do sistema, os disparos de cada pessoa saem só pelo WhatsApp dela (ou um compartilhado com ela).",
                   "erro")
            return voltar("/renovacao#configurar")
        gravar_config(db, "renov_conexao", conexao if c is not None else "")
        # WhatsApp dos avisos pela API oficial da Meta (etapa 2, pedido da Maria em 16/11/2026)
        from .. import whatsapp_oficial

        oficial, antes = bool(form.get("oficial")), renovacao.cfg(db, "renov_envio_oficial") == "1"
        if oficial and not antes:
            falta = whatsapp_oficial.falta_para_renovacao(db, _ar_da_renovacao(db, request, usuario))
            if falta:
                avisar(request, f"Ainda não dá para enviar pela API oficial da Meta: {falta}.", "erro")
                return voltar("/renovacao#configurar")
        if oficial != antes:
            gravar_config(db, "renov_envio_oficial", "1" if oficial else "0")
            mudaram = renovacao.aplicar_envio_oficial(db, oficial)
            registrar_log(db, usuario, "renovacao_api_oficial", "configuracao", None,
                          ("ligou" if oficial else "desligou") + f" o envio pela API oficial ({mudaram} campanha(s) em "
                          "andamento)", request)
            avisar(request, ("Os avisos de WhatsApp passam a sair pela API oficial da Meta" if oficial else
                             "Os avisos de WhatsApp voltam a sair pelo número do QR code")
                   + (f", também nas {mudaram} campanha(s) em andamento." if mudaram else "."))
        # o calendário para quem toca em "Quero renovar" (pedido da Maria em 23/11/2026)
        ar = _ar_da_renovacao(db, request, usuario)
        agenda, agenda_antes = bool(form.get("agenda")), renovacao.cfg(db, "renov_agenda") == "1"
        pessoa = db.get(Usuario, util.para_int(form.get("agenda_usuario_id")) or 0)
        if pessoa is not None and (not pessoa.ativo or pessoa.perfil == "parceiro"
                                   or (pessoa.tenant_id != ar and not pessoa.master)):
            pessoa = None
        if str(pessoa.id if pessoa else "") != renovacao.cfg(db, "renov_agenda_usuario_id"):
            gravar_config(db, "renov_agenda_usuario_id", str(pessoa.id) if pessoa else "")
        if agenda and not agenda_antes:
            problema = whatsapp_oficial.garantir_flow_agenda(db, whatsapp_oficial.conta_da_ar(db, ar))
            if problema:
                avisar(request, f"O calendário não foi ligado: {problema}.", "erro")
                return voltar("/renovacao#configurar")
        if agenda != agenda_antes:
            gravar_config(db, "renov_agenda", "1" if agenda else "0")
            registrar_log(db, usuario, "renovacao_calendario", "configuracao", None,
                          ("ligou" if agenda else "desligou") + " o calendário do \"Quero renovar\"", request)
            avisar(request, "Quem tocar em \"Quero renovar\" passa a receber o calendário para escolher o dia e o horário."
                   if agenda else "O calendário do \"Quero renovar\" foi desligado: a equipe combina o horário.")
    if _visual.html_da_marca_ligado(db):  # o botão "E-mail em HTML com a marca" só aparece com o módulo liberado
        email_html = bool(form.get("email_html"))
        if email_html != (renovacao.cfg(db, "renov_email_html") != "0"):
            gravar_config(db, "renov_email_html", "1" if email_html else "0")
            renovacao.aplicar_email_html(db, email_html)  # também nas campanhas em andamento
    for chave, valor in [("renov_ativo", "1" if form.get("ativo") else "0"), ("renov_canais", canais),
                         ("renov_arte", "1" if form.get("arte") else "0"),
                         ("renov_maximo_dia", str(maximo)), ("renov_hora", hora), ("renov_dono_id", str(dono_id or ""))]:
        gravar_config(db, chave, valor)
    registrar_log(db, usuario, "configurou_renovacao", "configuracao", None, request=request)
    db.commit()
    remarcados = ""
    if mudou_feriados:  # feriado novo: os avisos já marcados para ele mudam de dia
        r = renovacao.remarcar_feriados(db)
        db.commit()
        if r["remarcados"] or r["cancelados"]:
            remarcados = (f" {r['remarcados']} aviso(s) que caíam em feriado mudaram de dia"
                          + (f" e {r['cancelados']} não couberam em outro dia antes do vencimento" if r["cancelados"] else "")
                          + ".")
    if form.get("ativo") and not dono_id:
        avisar(request, "Configuração salva, mas escolha quem é o dono das campanhas de renovação." + remarcados
               + aviso_da_arte, "erro")
    else:
        avisar(request, "Configuração salva." + (
            f" A campanha automática roda todo dia às {hora}" + (f", a partir de {desde:%d/%m/%Y}" if desde else "") + "."
            if form.get("ativo") else "") + remarcados + aviso_da_arte)
    return voltar("/renovacao#configurar")


@rotas.post("/renovacao/mensagens", dependencies=[Depends(verificar_csrf)])
async def salvar_mensagens(request: Request, usuario: Usuario = Depends(exige("campanhas.configurar")),
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
def restaurar_mensagens(request: Request, usuario: Usuario = Depends(exige("campanhas.configurar")),
                        db: Session = Depends(obter_db)):
    gravar_config(db, "renov_mensagens", "")
    registrar_log(db, usuario, "restaurou_mensagens_renovacao", "configuracao", None, request=request)
    db.commit()
    avisar(request, "Mensagens voltaram ao texto inicial.")
    return voltar("/renovacao#mensagens")


@rotas.post("/renovacao/testar", dependencies=[Depends(verificar_csrf)])
async def testar(request: Request, usuario: Usuario = Depends(exige("campanhas.configurar")),
                 db: Session = Depends(obter_db)):
    """Área de teste (como a da IA SDR): os avisos chegam no WhatsApp ou no e-mail de quem testa, com "[TESTE]"."""
    form = await request.form()
    _na_ar_da_renovacao(db, request, usuario)
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
                                   com_arte=bool(form.get("com_arte")), conexao=conexao,
                                   ar=_ar_da_renovacao(db, request, usuario))
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
async def mudar_situacao(request: Request, cid: int, usuario: Usuario = Depends(exige("campanhas.configurar")),
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
    return voltar(_endereco_da_lista(str(form.get("ver", "")), str(form.get("q", "")).strip()[:80]))
