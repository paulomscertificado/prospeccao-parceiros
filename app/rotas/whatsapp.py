"""Tela WhatsApp: cada pessoa conecta o PRÓPRIO número; o dono (ou o administrador) pode compartilhar.

Os números ficam ligados no computador da MS (WhatsApp Leads, um conector por número; ver app/conexoes.py).
Na nuvem, cada botão vira um pedido (tabela comandos_whatsapp, com o id do número) que o WhatsApp Leads busca
pela ponte; a situação e o QR code de cada número voltam pela ponte. Enquanto esta tela está aberta, a ponte
troca a cada 5 segundos (ver /api/ponte/troca). A tela se atualiza de 3 em 3 s com QR code ou pedido esperando o
computador e de 10 em 10 s no resto do tempo (economia do banco da nuvem, 17/11/2026).
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import autorizacao, config, conexoes, marca, whatsapp_oficial
from ..banco import agora, obter_db
from ..integracoes import whatsapp_cloud, whatsapp_leads
from ..modelos import ComandoWhatsApp, ConexaoWhatsApp, Usuario
from ..seguranca import exige, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()

ACOES = {"conectar": "Conectar", "pausar": "Pausar conexão", "desligar": "Desligar o número",
         "remover": "Remover o número", "salvar_regras": "Salvar regras de envio", "renomear_contato": "Renomear contato"}


def _cartao(db: Session, usuario: Usuario, c: ConexaoWhatsApp, base: dict, nomes: dict[int, str]) -> dict:
    return {"id": c.id, "nome": c.nome, "dono": nomes.get(c.dono_id, ""), "minha": c.dono_id == usuario.id,
            "principal": c.id == conexoes.PRINCIPAL, "gerenciar": conexoes.pode_gerenciar(usuario, c),
            "compartilhar": conexoes.pode_compartilhar(usuario, c),
            "compartilhada_todos": c.compartilhada_todos, "compartilhada_com": conexoes.compartilhada_com(c),
            "situacao": conexoes.situacao(c.id, base)}


def _estado(db: Session, usuario: Usuario) -> dict:
    """Situação para a tela (e para a atualização automática: 3 s com QR code ou pedido esperando, senão 10 s)."""
    whatsapp_leads.marcar_tela(db, "wl_tela_vista_em")  # a ponte passa a trocar a cada 5 s
    base = whatsapp_leads.status(usar_cache=False)
    nomes = dict(db.execute(select(Usuario.id, Usuario.nome)).all())  # só o nome (antes vinha o cadastro inteiro)
    lista = (conexoes.todas(db) if autorizacao.pode(usuario, "whatsapp.compartilhar_todos")
             else conexoes.acessiveis(db, usuario))  # quem compartilha os números de todos vê todos
    cartoes = [_cartao(db, usuario, c, base, nomes) for c in lista]
    ultimo = db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.usuario_id == usuario.id)
                        .order_by(ComandoWhatsApp.id.desc()).limit(1)).scalars().first()
    pedido = None
    if ultimo and ultimo.acao != "renomear_contato" and (agora() - ultimo.criado_em).total_seconds() < 600:
        pedido = {"acao": ACOES.get(ultimo.acao, ultimo.acao), "status": ultimo.status, "erro": ultimo.erro,
                  "numero": json.loads(ultimo.dados or "{}").get("conexao", conexoes.PRINCIPAL)}
    db.commit()
    return {"ponte": config.WHATSAPP_PONTE, "computador": {"disponivel": bool(base.get("disponivel")),
                                                            "erro": base.get("erro", "")},
            "minha_id": conexoes.id_do_usuario(usuario.id), "numeros": cartoes, "pedido": pedido,
            "regras": base.get("regras") or {}}


def _endereco_do_webhook(request: Request) -> str:
    """Endereço público do webhook, para colar no painel da Meta (na Vercel o pedido chega por um proxy https)."""
    esquema = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{esquema}://{host}/api/webhooks/whatsapp"


@rotas.get("/whatsapp")
def tela_whatsapp(request: Request, usuario: Usuario = Depends(exige("whatsapp.ver")), db: Session = Depends(obter_db)):
    estado = _estado(db, usuario)
    equipe_ = [{"id": u.id, "nome": u.nome} for u in db.execute(
        select(Usuario).where(Usuario.perfil != "parceiro", Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars()]
    # API oficial da Meta (app/whatsapp_oficial.py): um número por AR; o Admin Master configura dentro da AR
    ar_oficial = marca.ar_da_tela(request, usuario) if autorizacao.pode(usuario, "whatsapp.gerenciar_todos") else None
    oficial = whatsapp_oficial.da_ar(db) if ar_oficial else None
    modelos = whatsapp_oficial.modelos_da_conta(db, oficial)
    previa = ""
    if oficial is not None:  # o texto do aviso (etapa 2), com os valores de exemplo
        previa = (whatsapp_oficial.preencher(whatsapp_oficial.corpo_renovacao(marca.da_ar(db, ar_oficial)["nome"]),
                                             whatsapp_oficial.EXEMPLO_DOS_VALORES)
                  + "\n\n" + whatsapp_oficial.RODAPE_RENOVACAO)
    return tela(request, "whatsapp.html", {"secao": "whatsapp", "estado": estado, "regras": estado["regras"], "equipe": equipe_,
                                           "url_local": config.WHATSAPP_LEADS_URL + "/whatsapp",
                                           "oficial_ar": ar_oficial, "oficial": oficial,
                                           "oficial_situacao": whatsapp_oficial.situacao(oficial),
                                           "webhook_url": _endereco_do_webhook(request),
                                           "oficial_modelos": modelos, "previa_do_modelo": previa,
                                           "nomes_de_uso": whatsapp_oficial.NOMES_DE_USO,
                                           "nomes_dos_modelos": whatsapp_oficial.NOMES_DOS_MODELOS,
                                           "situacoes_do_modelo": whatsapp_oficial.SITUACOES_DO_MODELO,
                                           "categorias_do_modelo": whatsapp_oficial.CATEGORIAS,
                                           "botoes_do_aviso": whatsapp_oficial.BOTOES_RENOVACAO,
                                           "pode_pedir_modelos": oficial is not None and any(
                                               (modelos.get(u) is None or modelos[u].status not in
                                                ("APPROVED", "PENDING", "IN_APPEAL"))
                                               for u in whatsapp_oficial.NOMES_DOS_MODELOS),
                                           "modelo_aprovado": any(m.status == "APPROVED" for m in modelos.values())})


def _conta_oficial_da_tela(request: Request, usuario: Usuario, db: Session, precisa_existir: bool = True):
    """A conta oficial da AR da tela, ou o motivo de não dar (Admin Master fora de uma AR; nada cadastrado)."""
    if marca.ar_da_tela(request, usuario) is None:
        return None, "Entre numa AR (painel do Admin Master) para configurar o número oficial dela."
    conta = whatsapp_oficial.da_ar(db)
    if conta is None and precisa_existir:
        return None, "Salve primeiro os dados da API oficial."
    return conta, ""


@rotas.post("/whatsapp/oficial", dependencies=[Depends(verificar_csrf)])
async def salvar_oficial(request: Request, usuario: Usuario = Depends(exige("whatsapp.gerenciar_todos")),
                         db: Session = Depends(obter_db)):
    conta, motivo = _conta_oficial_da_tela(request, usuario, db, precisa_existir=False)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/whatsapp#oficial")
    form = await request.form()
    dados = {c: str(form.get(c, "")) for c in ("nome", "waba_id", "phone_number_id", "token", "segredo")}
    conta, problemas = whatsapp_oficial.salvar(db, conta, dados)
    if problemas:
        db.rollback()
        avisar(request, " ".join(problemas), "erro")
        return voltar("/whatsapp#oficial")
    novidades = [x for x, campo in (("token novo", "token"), ("chave secreta nova", "segredo")) if dados[campo].strip()]
    registrar_log(db, usuario, "salvou_whatsapp_oficial", "whatsapp_oficial", conta.id,
                  f"número {conta.phone_number_id}" + (f" ({', '.join(novidades)})" if novidades else ""), request,
                  modulo="WhatsApp")
    db.commit()
    try:
        r = whatsapp_oficial.testar(db, conta)
        db.commit()
        avisar(request, ("Salvo. Achado na Meta" if r.get("ativado") is False else "Salvo e conectado")
               + f": {r['numero']} ({r['nome']}), limite {r['limite']} por dia."
                        + (" O app foi ligado à conta do WhatsApp (as respostas chegam pelo webhook)." if r["app_ligado"] else ""))
        if r["avisos"]:
            avisar(request, " ".join(r["avisos"]), "alerta")
    except whatsapp_cloud.ErroWhatsApp as erro:
        avisar(request, f"Salvo, mas o teste de conexão falhou: {erro}", "alerta")
    return voltar("/whatsapp#oficial")


@rotas.post("/whatsapp/oficial/testar", dependencies=[Depends(verificar_csrf)])
async def testar_oficial(request: Request, usuario: Usuario = Depends(exige("whatsapp.gerenciar_todos")),
                         db: Session = Depends(obter_db)):
    conta, motivo = _conta_oficial_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/whatsapp#oficial")
    try:
        r = whatsapp_oficial.testar(db, conta)
        db.commit()
        avisar(request, ("Achado na Meta" if r.get("ativado") is False else "Conectado")
               + f": {r['numero']} ({r['nome']}), qualidade {r['qualidade']}, limite {r['limite']} por dia.")
        if r["avisos"]:
            avisar(request, " ".join(r["avisos"]), "alerta")
    except whatsapp_cloud.ErroWhatsApp as erro:
        avisar(request, f"O teste de conexão falhou: {erro}", "erro")
    return voltar("/whatsapp#oficial")


@rotas.post("/whatsapp/oficial/ativar", dependencies=[Depends(verificar_csrf)])
async def ativar_numero_oficial(request: Request, usuario: Usuario = Depends(exige("whatsapp.gerenciar_todos")),
                                db: Session = Depends(obter_db)):
    """Ativa o número novo na API da Meta com a senha de 6 números (o último passo, que a Meta só aceita pela API). A
    senha não é guardada nem vai para o registro de atividades."""
    conta, motivo = _conta_oficial_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/whatsapp#ativar")
    form = await request.form()
    try:
        r = whatsapp_oficial.ativar_numero(db, conta, str(form.get("pin", "")), str(form.get("pin2", "")))
    except whatsapp_cloud.ErroWhatsApp as erro:
        if erro.codigo:  # chegou à Meta (ela conta as tentativas: 10 a cada 3 dias)
            registrar_log(db, usuario, "ativar_numero_whatsapp_oficial_recusado", "whatsapp_oficial", conta.id,
                          f"número {conta.phone_number_id}: {erro}", request, modulo="WhatsApp")
            db.commit()
        avisar(request, f"O número não foi ativado: {erro}", "erro")
        return voltar("/whatsapp#ativar")
    registrar_log(db, usuario, "ativou_numero_whatsapp_oficial", "whatsapp_oficial", conta.id,
                  f"número {conta.phone_number_id} ativado na API da Meta", request, modulo="WhatsApp")
    db.commit()
    avisar(request, "Número ativado na API da Meta" + (f": {r['numero']} ({r['nome']})" if r.get("numero") else "")
           + ". Guarde a senha de 6 números num lugar seguro (o sistema não guarda). Próximo passo: o webhook, logo abaixo.")
    if r.get("avisos"):
        avisar(request, " ".join(r["avisos"]), "alerta")
    return voltar("/whatsapp#ativar")


@rotas.post("/whatsapp/oficial/teste", dependencies=[Depends(verificar_csrf)])
async def mensagem_de_teste_oficial(request: Request, usuario: Usuario = Depends(exige("whatsapp.gerenciar_todos")),
                                    db: Session = Depends(obter_db)):
    """Manda UM modelo aprovado para um número da própria equipe (prova que o envio pela API funciona)."""
    conta, motivo = _conta_oficial_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/whatsapp#oficial")
    form = await request.form()
    telefone = str(form.get("telefone", "")).strip()
    modelo_do_teste = str(form.get("modelo", "")).strip()
    # o aviso de vencimento tem 3 campos: escrito aqui, vai preenchido com os dados de exemplo (como o botão "Enviar um
    # aviso de exemplo"); antes ia vazio e a Meta recusava (erro 132000, 22/11/2026)
    do_aviso = whatsapp_oficial.modelo_do_aviso_pelo_nome(modelo_do_teste)
    try:
        if do_aviso:
            whatsapp_oficial.enviar_teste_renovacao(db, conta, telefone, do_aviso)  # já vai para a tela API Oficial
            wamid = ""
        else:
            wamid = whatsapp_oficial.enviar_teste(conta, telefone, modelo_do_teste, str(form.get("idioma", "")))
    except whatsapp_cloud.ErroWhatsApp as erro:  # o motivo fica no registro (para conferir depois)
        registrar_log(db, usuario, "teste_whatsapp_oficial_recusado", "whatsapp_oficial", conta.id,
                      f"mensagem de teste para {telefone}: {erro}", request, modulo="WhatsApp")
        db.commit()
        avisar(request, f"O teste não saiu: {erro}", "erro")
        return voltar("/whatsapp#oficial")
    registrar_log(db, usuario, "teste_whatsapp_oficial", "whatsapp_oficial", conta.id,
                  f"mensagem de teste para {telefone} ({do_aviso or wamid[:40]})", request, modulo="WhatsApp")
    if not do_aviso:
        whatsapp_oficial.guardar_conversa(db, conta, telefone, "saida", f"[teste] modelo {modelo_do_teste}"
                                          if modelo_do_teste else "[teste] " + whatsapp_oficial.TEXTO_DE_TESTE,
                                          "modelo" if modelo_do_teste else "texto", wamid or "")
    db.commit()
    if do_aviso:
        avisar(request, f"Aviso de exemplo enviado ({do_aviso}), com os campos preenchidos com dados de exemplo. Ele "
                        "chega em alguns segundos; a entrega aparece no menu API Oficial.")
    elif modelo_do_teste:
        avisar(request, "Mensagem de teste enviada pela API oficial. Ela chega em alguns segundos no WhatsApp desse "
                        "número; a entrega aparece no menu API Oficial.")
    else:
        avisar(request, "Mensagem de teste enviada. Atenção: texto simples só chega para quem escreveu para o número "
                        "oficial nas últimas 24 horas. Se não chegar, o motivo aparece no menu API Oficial.")
    return voltar("/whatsapp#oficial")


@rotas.post("/whatsapp/oficial/modelos", dependencies=[Depends(verificar_csrf)])
async def pedir_modelos_oficial(request: Request, usuario: Usuario = Depends(exige("whatsapp.gerenciar_todos")),
                                db: Session = Depends(obter_db)):
    """Pede à Meta a aprovação dos modelos do aviso de vencimento da Renovação (etapa 2)."""
    conta, motivo = _conta_oficial_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/whatsapp#modelos")
    problemas = whatsapp_oficial.pedir_modelos_renovacao(db, conta)
    registrar_log(db, usuario, "pediu_modelos_whatsapp_oficial", "whatsapp_oficial", conta.id,
                  ("; ".join(problemas) or "modelos do aviso de renovação enviados para a aprovação da Meta")[:400],
                  request, modulo="WhatsApp")
    db.commit()
    if problemas:
        avisar(request, "Nem tudo chegou à Meta: " + " ".join(problemas), "erro")
    else:
        avisar(request, "Modelos enviados para a Meta aprovar. A resposta costuma sair em minutos (às vezes em até 24 "
                        "horas): o sistema confere sozinho de hora em hora, ou clique em Atualizar a situação.")
    return voltar("/whatsapp#modelos")


@rotas.post("/whatsapp/oficial/modelos/atualizar", dependencies=[Depends(verificar_csrf)])
async def atualizar_modelos_oficial(request: Request, usuario: Usuario = Depends(exige("whatsapp.gerenciar_todos")),
                                    db: Session = Depends(obter_db)):
    conta, motivo = _conta_oficial_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/whatsapp#modelos")
    try:
        mudaram = whatsapp_oficial.atualizar_modelos(db, conta)
    except whatsapp_cloud.ErroWhatsApp as erro:
        avisar(request, f"Não consegui falar com a Meta: {erro}", "erro")
        return voltar("/whatsapp#modelos")
    db.commit()
    avisar(request, "Situação dos modelos atualizada." if mudaram else "Nada mudou na Meta desde a última consulta.")
    return voltar("/whatsapp#modelos")


@rotas.post("/whatsapp/oficial/modelos/teste", dependencies=[Depends(verificar_csrf)])
async def teste_modelo_oficial(request: Request, usuario: Usuario = Depends(exige("whatsapp.gerenciar_todos")),
                               db: Session = Depends(obter_db)):
    """Um aviso de exemplo (EMPRESA EXEMPLO LTDA) para o WhatsApp de quem testa, com o modelo aprovado."""
    conta, motivo = _conta_oficial_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/whatsapp#modelos")
    form = await request.form()
    telefone = str(form.get("telefone", "")).strip()
    try:
        nome = whatsapp_oficial.enviar_teste_renovacao(db, conta, telefone)
    except whatsapp_cloud.ErroWhatsApp as erro:
        registrar_log(db, usuario, "teste_aviso_whatsapp_oficial_recusado", "whatsapp_oficial", conta.id,
                      f"aviso de exemplo para {telefone}: {erro}", request, modulo="WhatsApp")
        db.commit()
        avisar(request, f"O aviso de exemplo não saiu: {erro}", "erro")
        return voltar("/whatsapp#modelos")
    registrar_log(db, usuario, "teste_aviso_whatsapp_oficial", "whatsapp_oficial", conta.id,
                  f"aviso de exemplo ({nome}) para {telefone}", request, modulo="WhatsApp")
    db.commit()
    avisar(request, "Aviso de exemplo enviado pela API oficial: chega em alguns segundos no WhatsApp desse número. "
                    "Os botões do exemplo não fazem nada.")
    return voltar("/whatsapp#modelos")


@rotas.post("/whatsapp/oficial/remover", dependencies=[Depends(verificar_csrf)])
async def remover_oficial(request: Request, usuario: Usuario = Depends(exige("whatsapp.gerenciar_todos")),
                          db: Session = Depends(obter_db)):
    conta, motivo = _conta_oficial_da_tela(request, usuario, db)
    if motivo:
        avisar(request, motivo, "erro")
        return voltar("/whatsapp#oficial")
    registrar_log(db, usuario, "removeu_whatsapp_oficial", "whatsapp_oficial", conta.id,
                  f"número {conta.phone_number_id} (as chaves foram apagadas do sistema)", request, modulo="WhatsApp")
    db.delete(conta)
    db.commit()
    avisar(request, "API oficial removida do sistema. Nada mudou na conta da Meta.")
    return voltar("/whatsapp#oficial")


@rotas.get("/whatsapp/estado")
def estado_whatsapp(usuario: Usuario = Depends(exige("whatsapp.ver")), db: Session = Depends(obter_db)):
    return JSONResponse(_estado(db, usuario))


@rotas.post("/whatsapp/comando", dependencies=[Depends(verificar_csrf)])
async def comando_whatsapp(request: Request, acao: str = Form(...), numero: str = Form(""),
                           usuario: Usuario = Depends(exige("whatsapp.ver")), db: Session = Depends(obter_db)):
    if not config.WHATSAPP_PONTE:
        avisar(request, "Neste computador, use a tela WhatsApp do próprio WhatsApp Leads.", "alerta")
        return voltar("/whatsapp")
    if acao not in ACOES or acao == "renomear_contato":
        avisar(request, "Pedido desconhecido.", "erro")
        return voltar("/whatsapp")
    form = await request.form()
    dados: dict = {}
    if acao == "salvar_regras":
        if not autorizacao.pode(usuario, "whatsapp.regras"):
            avisar(request, "Só o administrador muda as regras de envio.", "erro")
            return voltar("/whatsapp")
        dados = {c: str(form.get(c, "")).strip() for c in ("intervalo_min_seg", "intervalo_max_seg", "limite_diario",
                                                            "horario_inicio", "horario_fim", "palavras_sair")}
        try:
            minimo, maximo, limite = (int(dados["intervalo_min_seg"]), int(dados["intervalo_max_seg"]),
                                      int(dados["limite_diario"]))
        except ValueError:
            avisar(request, "Use só números nas pausas e no limite diário.", "erro")
            return voltar("/whatsapp")
        if minimo < 1 or maximo < minimo or limite < 1:
            avisar(request, "A pausa máxima precisa ser maior ou igual à mínima.", "erro")
            return voltar("/whatsapp")
    else:
        # "meu" = o número da própria pessoa (criado na primeira conexão)
        if numero in ("", "meu"):
            c = conexoes.minha(db, usuario, criar=acao == "conectar")
        else:
            c = db.get(ConexaoWhatsApp, numero)
        if c is None or not conexoes.pode_gerenciar(usuario, c):
            avisar(request, "Só o dono do número (ou o administrador) pode fazer isso.", "erro")
            return voltar("/whatsapp")
        if acao == "remover" and c.id == conexoes.PRINCIPAL:
            avisar(request, "O número principal não pode ser removido (use Desligar).", "erro")
            return voltar("/whatsapp")
        dados = {"conexao": c.id}
        if acao == "conectar":
            dados["tipo"] = "teste" if form.get("tipo") == "teste" else "qr"
        if acao == "remover":
            db.delete(c)
    db.add(ComandoWhatsApp(acao=acao, dados=json.dumps(dados, ensure_ascii=False), usuario_id=usuario.id))
    registrar_log(db, usuario, "whatsapp_" + acao, "whatsapp", None, json.dumps(dados, ensure_ascii=False)[:200], request)
    db.commit()
    if not whatsapp_leads.status(usar_cache=False).get("disponivel"):
        avisar(request, "Pedido guardado. Ele será feito quando o computador com o WhatsApp Leads ligar.", "alerta")
    else:
        avisar(request, f"{ACOES[acao]}: pedido enviado ao computador do WhatsApp. Leva alguns segundos.")
    return voltar("/whatsapp")


@rotas.post("/whatsapp/compartilhar", dependencies=[Depends(verificar_csrf)])
async def compartilhar(request: Request, numero: str = Form(...), usuario: Usuario = Depends(exige("whatsapp.ver")),
                       db: Session = Depends(obter_db)):
    """Compartilhar um número com toda a equipe ou com pessoas escolhidas (o dono, o administrador e o gestor)."""
    c = db.get(ConexaoWhatsApp, numero)
    if c is None or not conexoes.pode_compartilhar(usuario, c):
        avisar(request, "Só o dono do número, o administrador ou o gestor podem compartilhar.", "erro")
        return voltar("/whatsapp")
    form = await request.form()
    ids = sorted({int(i) for i in form.getlist("usuarios") if str(i).isdigit() and int(i) != c.dono_id})
    from .. import autorizacao

    if motivo := autorizacao.motivo_para_nao_compartilhar(db, usuario, c.dono_id, c.compartilhada_todos,
                                                          conexoes.compartilhada_com(c), form.get("todos") == "on", ids):
        avisar(request, motivo, "erro")
        return voltar("/whatsapp")
    c.compartilhada_todos = form.get("todos") == "on"
    c.compartilhada_com = json.dumps(ids)
    nome = str(form.get("nome", "")).strip()
    if nome:
        c.nome = nome[:120]
    registrar_log(db, usuario, "whatsapp_compartilhar", "whatsapp", None,
                  f"{c.id}: todos={c.compartilhada_todos} usuarios={ids}", request)
    db.commit()
    avisar(request, "Compartilhamento salvo." if (c.compartilhada_todos or ids) else "Número não compartilhado: só o dono usa.")
    return voltar("/whatsapp")
