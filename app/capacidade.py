"""Quanto cabe por dia: quantas empresas novas as campanhas de cada marca comportam no envio automático.

Pedido da Maria em 25/11/2026: "faça um cálculo de quantas empresas novas e quantas campanhas eu consigo fazer no
máximo diariamente de forma automática ... use uma cadência de 4 toques" e, com a conta pronta, "faça aparecer isso nas
marcas que têm e-mail cadastrado no nosso sistema". A conta usa as mesmas regras das vagas (app/vagas.py e
app/vagas_email.py):

- WhatsApp: cada número DE VERDADE da marca (conectado e fora do MODO TESTE, que só simula: conexoes.para_enviar nunca o
  escolhe em produção) manda o que cabe num dia de envio (vagas.vagas_por_hora: uns 6 por hora no horário da marca,
  fora do almoço e com a folga do fim), até o limite por dia de cada número e o de contatos frios, se houver
  (Configurações > Geral). Os disparos de cada pessoa saem pelo número dela ou por um compartilhado com ela.
- E-mail: os limites são da marca, somando as contas dela (vagas_email.por_dia: uns 17 por hora, até o limite do dia).
- O envio automático só sai de segunda a sexta (mensagens.dentro_do_horario): 5 dias por semana.
- Cadência de N toques: cada empresa recebe um WhatsApp e um e-mail em cada toque (o toque "auto" da IA SDR manda os
  dois para quem tem os dois: cadencias.criar_tarefas). Depois de umas duas semanas, todo dia saem juntos o 1º toque das
  empresas que entraram hoje e os outros toques das que entraram antes: cabem (vagas do dia) ÷ N empresas novas por dia
  em cada número. Com WhatsApp e e-mail, vale o menor dos dois.
- Campanhas: não há limite de quantas; todas as campanhas da marca dividem as mesmas vagas. Cada campanha manda até
  limite_diario_campanha mensagens por dia (WhatsApp e e-mail somados: mensagens.bloqueio_de_envio): para usar tudo, é
  preciso ter algumas campanhas em andamento ao mesmo tempo.
- Só aparece nas marcas com conta de e-mail cadastrada (a principal conta para a marca dela, se estiver configurada).
  Quadro templates/_capacidade.html, na tela Campanhas (o Admin Master vê o de cada marca).
"""

import math

from sqlalchemy import select

from . import util, vagas, vagas_email
from .banco import ler_config, ler_config_int, usar_config_da_ar
from .modelos import ConexaoWhatsApp, ContaEmail, Tenant, Usuario

TOQUES_PADRAO = 4          # a cadência padrão da IA SDR (modelos.NOME_CADENCIA_SDR) e a da conta pedida pela Maria
OUTROS_TOQUES = (2, 3, 5)  # as outras cadências da Nova campanha (2, 3 e 5 toques; as Empresas novas têm 3)
DIAS_POR_SEMANA = 5        # o envio automático só sai de segunda a sexta
DIAS_DA_OCUPACAO = 10      # "agora": quanto já está marcado nos próximos 10 dias de envio

SITUACOES = {"ok": "conectado", "teste": "em modo teste, só simula: a mensagem não chega",
             "desconectado": "desconectado", "fora": "sem notícia do WhatsApp Leads agora"}


def contas_da_marca(db, ar: int) -> list[ContaEmail]:
    """As contas de e-mail cadastradas na marca (a principal só se o envio dela estiver configurado)."""
    from . import contas_email

    contas = db.execute(select(ContaEmail).order_by(ContaEmail.principal.desc(), ContaEmail.criado_em, ContaEmail.id)
                        .execution_options(sem_filtro_de_ar=True)).scalars()
    return [c for c in contas if contas_email._ar_da_conta(db, c) == ar
            and (contas_email.principal_pronta() if c.principal else bool((c.endereco or "").strip()))]


def pessoas_da_marca(db, ar: int) -> list[Usuario]:
    """Quem dispara campanhas na marca: as pessoas ativas dela (fora o portal dos parceiros) e, na marca padrão (a AR
    MS), o Admin Master, que fora das marcas fala por ela (ars.PADRAO)."""
    from . import marca

    filtros = (Usuario.ativo.is_(True), Usuario.perfil != "parceiro")
    pessoas = list(db.execute(select(Usuario).where(*filtros, Usuario.tenant_id == ar)
                              .execution_options(sem_filtro_de_ar=True)).scalars())
    if ar == marca.ar_padrao(db):
        pessoas += db.execute(select(Usuario).where(*filtros, Usuario.master.is_(True), Usuario.tenant_id.is_(None))
                              .execution_options(sem_filtro_de_ar=True)).scalars().all()
    return sorted(pessoas, key=lambda p: util.chave_texto(p.nome or ""))


def whatsapp_por_dia(db) -> int:
    """Quantos WhatsApps automáticos um número manda num dia de envio, com as configurações da marca de agora: as vagas
    do dia (vagas.vagas_por_hora) até o limite por dia do número e o de contatos frios (0 = sem limite)."""
    total = sum(v for v, _de, _ate in vagas.vagas_por_hora(db).values())
    for chave in ("limite_diario_whatsapp", "limite_frios_whatsapp"):
        limite = ler_config_int(db, chave, 0)
        if limite > 0:
            total = min(total, limite)
    return total


def empresas_por_dia(por_numero: list[int], email_dia: int, toques: int) -> dict:
    """Quantas empresas novas cabem por dia com uma cadência de `toques` toques (um WhatsApp e um e-mail em cada):
    {"whatsapp" (somando os números: cada um leva as campanhas de quem dispara por ele), "email", "empresas" (com os
    dois canais, o menor; com um só, o dele)}."""
    zap = sum(n // toques for n in por_numero)
    email = email_dia // toques
    empresas = min(zap, email) if zap and email else (zap or email)
    return {"toques": toques, "whatsapp": zap, "email": email, "empresas": empresas}


def da_marca(db, ar: int, toques: int = TOQUES_PADRAO) -> dict | None:
    """A conta de capacidade da marca `ar`, para o quadro _capacidade.html. None = a marca não tem conta de e-mail
    cadastrada (o quadro só aparece nas que têm)."""
    from . import campanhas, conexoes, contas_email, marca
    from .integracoes import whatsapp_leads

    contas = contas_da_marca(db, ar)
    if not contas:
        return None
    anterior = db.info.get("ar_config")
    usar_config_da_ar(db, ar)  # o horário, o ritmo e os limites da marca
    try:
        pessoas = pessoas_da_marca(db, ar)
        base = whatsapp_leads.status()
        fora = not base.get("disponivel")

        # ------------------------------------------------ WhatsApp: os números da marca e quem dispara por cada um
        por_numero = whatsapp_por_dia(db)
        numeros = []
        for c in db.execute(select(ConexaoWhatsApp).where(ConexaoWhatsApp.tenant_id == ar)
                            .order_by(ConexaoWhatsApp.criado_em, ConexaoWhatsApp.id)
                            .execution_options(sem_filtro_de_ar=True)).scalars():
            s = conexoes.situacao(c.id, base)
            estado = ("fora" if fora else "desconectado" if not s.get("conectado")
                      else "teste" if s.get("tipo") == "teste" else "ok")
            numeros.append({"id": c.id, "nome": c.nome or c.id, "dono_id": c.dono_id, "estado": estado,
                            "situacao": SITUACOES[estado], "conta": estado == "ok", "por_dia": por_numero, "quem": []})
        de_verdade = {n["id"]: n for n in numeros if n["conta"]}
        sem_numero = []
        for pessoa in pessoas:
            try:
                numero = conexoes.para_enviar(db, pessoa)
            except conexoes.SemNumero:
                numero = None
            if numero in de_verdade:
                de_verdade[numero]["quem"].append(pessoa.nome)
            elif not fora:
                sem_numero.append(pessoa.nome)  # os WhatsApps dela esperam um número de verdade

        # ------------------------------------------------ E-mail: as contas da marca e quem dispara por cada uma
        email_dia = vagas_email.por_dia(db)
        lista_contas = [{"id": c.id, "nome": vagas_email.nome_da_conta(c), "ativa": bool(c.ativa or c.principal),
                         "quem": []} for c in contas]
        por_id = {c["id"]: c for c in lista_contas}
        sem_conta, quem_envia_email = [], None
        for pessoa in pessoas:
            try:
                conta = contas_email.para_enviar(db, pessoa)
            except contas_email.SemConta:
                conta = None
            if conta is not None and conta.id in por_id:
                por_id[conta.id]["quem"].append(pessoa.nome)
                quem_envia_email = quem_envia_email or pessoa
            else:
                sem_conta.append(pessoa.nome)  # os e-mails dela esperam uma conta
        com_email = quem_envia_email is not None  # alguém da marca consegue mandar e-mail

        # ------------------------------------------------ A conta
        nos_numeros = [n["por_dia"] for n in de_verdade.values()]
        conta = empresas_por_dia(nos_numeros, email_dia if com_email else 0, toques)
        outras = [empresas_por_dia(nos_numeros, email_dia if com_email else 0, n) for n in OUTROS_TOQUES if n != toques]
        canais = 2 if conta["whatsapp"] and conta["email"] else 1
        mensagens_dia = conta["empresas"] * toques * canais  # WhatsApps e e-mails do dia, com a marca cheia
        por_campanha = ler_config_int(db, "limite_diario_campanha", 0)
        campanhas_minimas = max(1, math.ceil(mensagens_dia / por_campanha)) if por_campanha and mensagens_dia else 1

        # ------------------------------------------------ Agora: o que já está marcado nos próximos dias de envio
        marcados = cabem = 0
        for n in de_verdade.values():
            dono = db.get(Usuario, n["dono_id"]) if n["dono_id"] else None
            r = vagas.resumo(db, dono, DIAS_DA_OCUPACAO, n["id"])
            marcados += sum(d["marcados"] for d in r["dias"])
            cabem += sum(d["cabem"] for d in r["dias"])
        email_marcados = email_cabem = 0
        if com_email:
            r = vagas_email.resumo(db, quem_envia_email, DIAS_DA_OCUPACAO, ar)
            email_marcados = sum(d["marcados"] for d in r["dias"])
            email_cabem = sum(d["cabem"] for d in r["dias"])

        inicio = util.hora_hhmm(ler_config(db, "horario_envio_inicio"), "08:30")
        fim = util.hora_hhmm(ler_config(db, "horario_envio_fim"), "18:00")
        return {
            "ar": ar, "nome": marca.da_ar(db, ar)["nome"], "toques": toques, "horario": f"{inicio} às {fim}",
            "zap_por_hora": vagas.por_hora(db), "zap_intervalo": campanhas.texto_do_intervalo(db, "whatsapp"),
            "zap_por_numero": por_numero, "zap_dia": sum(nos_numeros), "numeros": numeros,
            "numeros_de_verdade": len(nos_numeros), "sem_numero": sem_numero, "whatsapp_fora": fora,
            "email_por_hora": vagas_email.por_hora(db), "email_intervalo": vagas_email.texto_do_intervalo(db),
            "email_dia": email_dia if com_email else 0, "contas": lista_contas, "sem_conta": sem_conta,
            "com_email": com_email,
            "whatsapp": conta["whatsapp"], "email": conta["email"], "empresas": conta["empresas"],
            "por_semana": conta["empresas"] * DIAS_POR_SEMANA, "outras": outras,
            "um_numero_a_mais": por_numero // toques,
            "por_campanha": por_campanha, "mensagens_dia": mensagens_dia, "campanhas_minimas": campanhas_minimas,
            "dias_ocupacao": DIAS_DA_OCUPACAO,
            "ocupacao": {"marcados": marcados, "cabem": cabem, "pct": round(100 * marcados / cabem) if cabem else 0},
            "ocupacao_email": {"marcados": email_marcados, "cabem": email_cabem,
                               "pct": round(100 * email_marcados / email_cabem) if email_cabem else 0},
        }
    finally:
        usar_config_da_ar(db, anterior)


def para_tela(db, usuario: Usuario | None) -> list[dict]:
    """Os quadros da tela Campanhas: o da marca de quem vê, se ela tem conta de e-mail cadastrada; o Admin Master fora
    das marcas vê o de cada marca ativa que tem (dentro de uma marca, só o dela). Só para quem cria campanhas."""
    from . import autorizacao, isolamento

    if usuario is None or not autorizacao.pode(usuario, "campanhas.criar"):
        return []
    ar = isolamento.ar_da_sessao(db)
    if ar is None and getattr(usuario, "master", False):
        ids = list(db.execute(select(Tenant.id).where(Tenant.situacao != "suspensa").order_by(Tenant.id)
                              .execution_options(sem_filtro_de_ar=True)).scalars())
    else:
        ar = ar if ar is not None else usuario.tenant_id
        ids = [ar] if ar and ar > 0 else []
    return [c for c in (da_marca(db, i) for i in ids) if c is not None]
