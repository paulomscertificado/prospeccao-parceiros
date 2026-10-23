"""Campaign Manager da IA SDR.

Fluxo: pedido em texto ("quero parceiros entre empresas que atendem PMEs em São Paulo")
 → categorias + região (a IA pergunta o que faltar) → busca na base da Receita → dedup
 → pesquisa pública + perfil + score (em paralelo) → seleciona os melhores → mensagens únicas
 → tarefas em RASCUNHO → APROVAÇÃO HUMANA → fila (e-mail automático com limites; WhatsApp/LinkedIn
 assistidos) → respostas → handoff. Depois do último toque sem resposta: "Sem resposta" (não insiste).
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from . import base_receita, cadencias, config, ia, mensagens, prospeccao, sdr, trabalhos, util
from .banco import agora, ler_config, ler_config_int, sessao
from .leads_servico import criar_lead, historico, mudar_status, registrar_contato
from .modelos import Cadencia, Campanha, Categoria, Lead, Tarefa, Usuario
from .modelos import NOME_CADENCIA_SDR

log = logging.getLogger(__name__)

PALAVRAS_CATEGORIA = [
    (r"contad|contab|contabil", "contabil"), (r"administradora|condom", "condominio"),
    (r"nota fiscal|nf-?e|emissor", "nf"), (r"software contab", "software_contabil"),
    (r"\berp\b|software de gest|sistema de gest|softwares?\b|sistemas\b", "erp"), (r"\bbpo\b|financeir", "bpo"),
    (r"\brh\b|folha|recursos humanos", "rh"), (r"consultori", "consultoria"), (r"despachant", "despachante"),
    (r"tecnologia|\bti\b", "tecnologia"), (r"associa", "associacao"), (r"cowork", "coworking"),
    (r"franquia|franqueador", "franquia"),
]
SUGESTAO_PMES = ["contabil", "bpo", "erp", "nf", "rh"]  # "empresas que atendem PMEs"


# ---------------------------------------------------------------- Entender o pedido

ESQUEMA_PEDIDO = {
    "type": "object",
    "properties": {
        "categorias": {"type": "array", "items": {"type": "string"}},
        "cidade": {"type": "string"}, "estado": {"type": "string"},
        "quantidade": {"type": ["integer", "null"]},
        "canais": {"type": "array", "items": {"type": "string", "enum": ["whatsapp", "email", "linkedin"]}},
        "objetivo": {"type": "string"}, "justificativa": {"type": "string"},
    },
    "required": ["categorias", "cidade", "estado", "quantidade", "canais", "objetivo", "justificativa"],
    "additionalProperties": False,
}


def interpretar_pedido(db, texto: str) -> dict:
    """Transforma o pedido em campos da campanha. 'faltando' diz o que a IA precisa perguntar."""
    codigos = {c.codigo: c.nome for c in db.execute(select(Categoria).where(Categoria.ativa.is_(True))).scalars()}
    base = prospeccao.interpretar_pedido(texto)
    t = util.chave_texto(texto)
    categorias = [cod for padrao, cod in PALAVRAS_CATEGORIA if re.search(padrao, t) and cod in codigos]
    justificativa = ""
    if not categorias and re.search(r"pme|pequenas e medias|pequenas empresas|atendem empresas", t):
        categorias = [c for c in SUGESTAO_PMES if c in codigos]
        justificativa = ("Para empresas que atendem PMEs, sugerimos as categorias com relacionamento recorrente e "
                         "demanda por certificado: contábeis, BPO financeiro, ERPs, emissores de NF e RH.")
    resultado = {"categorias": list(dict.fromkeys(categorias)), "cidade": base.get("cidade", ""),
                 "estado": base.get("estado", ""), "quantidade": base.get("quantidade"), "canais": [],
                 "objetivo": "Encontrar parceiros", "justificativa": justificativa, "fonte": "regras"}
    if ia.disponivel() and texto.strip():
        pedido = (f"Interprete o pedido de campanha de prospecção de PARCEIROS da MS Certificação Digital.\n"
                  f"Categorias disponíveis (use só estes códigos): "
                  f"{'; '.join(f'{k} = {v}' for k, v in codigos.items())}.\n"
                  "Se o pedido falar de um público (ex.: empresas que atendem PMEs), escolha as categorias que atendem "
                  "esse público e explique em justificativa. Deixe cidade/estado vazios se não forem citados "
                  "(estado = sigla UF). quantidade null se não citada.\n\nPEDIDO: " + texto[:1000])
        try:
            dados = ia.perguntar(db, pedido, ESQUEMA_PEDIDO, max_tokens=1200)
            dados["categorias"] = [c for c in dados.get("categorias", []) if c in codigos] or resultado["categorias"]
            for campo in ("cidade", "estado", "quantidade"):
                dados[campo] = dados.get(campo) or resultado[campo]
            dados["estado"] = (dados.get("estado") or "").upper()[:2]
            dados["fonte"] = "ia"
            resultado = dados
        except ia.ErroDaIA as erro:
            log.warning("Interpretação por IA falhou: %s", erro)
    faltando = []
    if not resultado.get("cidade") or resultado.get("estado") not in config.UFS:
        faltando.append("regiao")
    if not resultado.get("categorias"):
        faltando.append("segmento")
    resultado["faltando"] = faltando
    return resultado


def cadencia_sdr(db) -> Cadencia | None:
    return db.execute(select(Cadencia).where(Cadencia.nome == NOME_CADENCIA_SDR)).scalars().first()


# ---------------------------------------------------------------- Geração (segundo plano)

def _anotar(campanha_id: int, etapa: str, status: str | None = None, erro: str = ""):
    with sessao() as db:
        c = db.get(Campanha, campanha_id)
        c.etapa = etapa[:200]
        if status:
            c.status = status
        if erro:
            c.erro = erro


def _pesquisar(lead_id: int, usar_ia: bool) -> None:
    """Pesquisa UMA empresa. Qualquer problema (site quebrado, fonte fora do ar) fica só nela: a campanha segue."""
    from .pesquisa import pesquisar_lead

    try:
        with sessao() as db:
            lead = db.get(Lead, lead_id)
            if lead and not lead.pesquisado_em:
                pesquisar_lead(db, lead, usar_ia=usar_ia)
    except Exception as erro:  # noqa: BLE001 - uma empresa com problema não pode travar a campanha
        log.warning("Pesquisa da empresa %s falhou: %s", lead_id, erro)
        with sessao() as db:
            lead = db.get(Lead, lead_id)
            if lead and not lead.pesquisado_em:
                lead.pesquisado_em = agora()  # não tenta de novo a cada rodada
                from . import score

                score.atualizar(db, lead)  # nota e fit com os dados da Receita (sem o site)
                historico(db, lead.id, "sistema", "Não foi possível pesquisar o site desta empresa "
                          f"({str(erro)[:150]}). Ela segue com os dados da Receita.", None)


def _mensagens(lead_id: int, usuario_id: int, cta: str, tom: str) -> tuple[int, dict]:
    """Mensagens de UMA empresa. Se a IA falhar, usa os modelos por regras (a campanha não para)."""
    with sessao() as db:
        lead = db.get(Lead, lead_id)
        usuario = db.get(Usuario, lead.vendedor_id or usuario_id)
        try:
            return lead_id, sdr.gerar_mensagens(db, lead, usuario, cta, tom)
        except Exception as erro:  # noqa: BLE001
            log.warning("Mensagens da empresa %s: IA falhou (%s), usando os modelos", lead_id, erro)
            return lead_id, sdr.mensagens_por_regras(db, lead, usuario, cta)


def _buscar_candidatos(campanha_id: int) -> list[int]:
    """Etapa 1: empresas da base da Receita nas categorias e na região (o dobro, para poder escolher)."""
    with sessao() as db:
        camp = db.get(Campanha, campanha_id)
        usuario = db.get(Usuario, camp.usuario_id)
        cods = [c for c in camp.categorias.split(",") if c]
        cats = {c.codigo: c for c in db.execute(select(Categoria).where(Categoria.codigo.in_(cods))).scalars()}
        quantidade = max(1, camp.quantidade or 50)
        if not base_receita.disponivel(db):
            raise RuntimeError("A base da Receita ainda não foi importada (Configurações > Integrações).")
        candidatos: list[int] = []
        por_categoria = max(1, -(-quantidade * 2 // max(1, len(cods))))
        for cod in cods:
            achados = 0
            for dados in base_receita.buscar(db, camp.cidade, camp.estado, por_categoria, [cod]):
                if achados >= por_categoria:
                    break
                origem = dados.pop("origem")
                dados.pop("categoria", None)
                lead, motivo = criar_lead(db, dados, usuario, origem=origem)
                if not lead:
                    continue
                if motivo and (lead.opt_out or lead.perdido or lead.etapa >= 1 or lead.automacao_pausada):
                    continue  # já cadastrado e já trabalhado: não entra de novo
                if lead.categoria_id is None and cod in cats:
                    lead.categoria = cats[cod]
                candidatos.append(lead.id)
                achados += 1
        if not candidatos:
            nomes = ", ".join(c.nome for c in cats.values()) or "das categorias escolhidas"
            raise RuntimeError(f"Não encontrei empresas novas de {nomes} em \"{camp.cidade}\"/{camp.estado} na base da "
                               "Receita. Confira o nome da cidade (ou do bairro) e o estado, ou escolha outro segmento.")
        return list(dict.fromkeys(candidatos))


def etapa_gerar(campanha_id: int, _usuario_id, estado: dict, prazo: float) -> bool:
    """Monta a campanha em etapas (ver app/trabalhos.py) e deixa esperando aprovação.
    estado["fase"]: buscar → pesquisar → mensagens → montar."""
    fase = estado.setdefault("fase", "buscar")
    if fase == "buscar":
        _anotar(campanha_id, "Procurando empresas na base da Receita...", "gerando")
        estado.update(candidatos=_buscar_candidatos(campanha_id), feitos=0, fase="pesquisar")
        fase = "pesquisar"
    if fase == "pesquisar":
        candidatos, usar_ia = estado["candidatos"], ia.disponivel()
        _anotar(campanha_id, f"Pesquisando {len(candidatos)} empresas (site, Receita, perfil)...")
        with ThreadPoolExecutor(max_workers=5) as grupo:
            for lote, proximo in trabalhos.em_lotes(candidatos, estado["feitos"], 5, prazo):
                list(grupo.map(lambda i: _pesquisar(i, usar_ia), lote))
                estado["feitos"] = proximo
                _anotar(campanha_id, f"Pesquisando empresas: {proximo} de {len(candidatos)}...")
        if estado["feitos"] < len(candidatos):
            return False
        with sessao() as db:
            leads = [db.get(Lead, i) for i in candidatos]
            elegiveis = [l for l in leads if l and l.fit != "Sem fit" and not l.opt_out]
            elegiveis.sort(key=lambda l: (-l.score, l.id))
            quantidade = max(1, db.get(Campanha, campanha_id).quantidade or 50)
            estado.update(escolhidos=[l.id for l in elegiveis[:quantidade]], textos={}, fase="mensagens")
        fase = "mensagens"
    if fase == "mensagens":
        with sessao() as db:
            camp = db.get(Campanha, campanha_id)
            cta, tom, usuario_id = camp.cta, camp.tom, camp.usuario_id
        escolhidos, textos = estado["escolhidos"], estado["textos"]
        _anotar(campanha_id, f"Escrevendo mensagens únicas para {len(escolhidos)} empresas...")
        with ThreadPoolExecutor(max_workers=4) as grupo:
            for lote, _ in trabalhos.em_lotes(escolhidos, len(textos), 4, prazo):
                for lead_id, msgs in grupo.map(lambda i: _mensagens(i, usuario_id, cta, tom), lote):
                    textos[str(lead_id)] = msgs
                _anotar(campanha_id, f"Escrevendo mensagens: {len(textos)} de {len(escolhidos)}...")
        if len(textos) < len(escolhidos):
            return False
        estado["fase"] = "montar"
    _montar(campanha_id, estado["escolhidos"], {int(k): v for k, v in estado["textos"].items()})
    return True


def _montar(campanha_id: int, escolhidos: list[int], textos: dict[int, dict]) -> None:
    with sessao() as db:
        camp = db.get(Campanha, campanha_id)
        usuario = db.get(Usuario, camp.usuario_id)
        cad = db.get(Cadencia, camp.cadencia_id) if camp.cadencia_id else cadencia_sdr(db)
        leads = [l for l in (db.get(Lead, i) for i in escolhidos) if l]
        for lead in leads:
            if lead.vendedor_id is None and usuario.perfil in config.PERFIS_SO_PROPRIOS:
                lead.vendedor_id = usuario.id
        r = cadencias.aplicar(db, cad, leads, usuario, camp.inicio or date.today(), camp.id, textos,
                              [c for c in camp.canais.split(",") if c], "rascunho", camp.cta, camp.tom)
        camp.etapa = (f"Pronta: {r['leads']} empresas, {r['tarefas']} mensagens"
                      + (f" ({len(r['pulados'])} puladas)" if r["pulados"] else "") + ".")
        if ler_config(db, "aprovacao_obrigatoria") == "0":
            aprovar(db, camp, usuario)
        else:
            camp.status = "aguardando_aprovacao"
            sdr_notificar_aprovacao(db, camp)


def gerar(campanha_id: int) -> None:
    """Monta a campanha inteira de uma vez (testes e scripts)."""
    estado: dict = {}
    while not etapa_gerar(campanha_id, None, estado, float("inf")):
        pass


def sdr_notificar_aprovacao(db, camp: Campanha) -> None:
    from .modelos import Notificacao

    for u in db.execute(select(Usuario).where(Usuario.perfil.in_(["admin", "gestor"]), Usuario.ativo.is_(True))).scalars():
        db.add(Notificacao(usuario_id=u.id, texto=f"Campanha \"{camp.nome}\" pronta: APROVAÇÃO NECESSÁRIA",
                           link=f"/campanhas/{camp.id}"))


def _falhou(campanha_id: int, erro: str) -> None:
    _anotar(campanha_id, "Não foi possível montar a campanha.", "erro", erro)


trabalhos.tipo("campanha", _falhou)(etapa_gerar)


def gerar_em_segundo_plano(campanha_id: int) -> None:
    _anotar(campanha_id, "Na fila: começa em até 1 minuto..." if config.NA_NUVEM else "Começando...", "gerando")
    trabalhos.iniciar("campanha", campanha_id)


def etapa_personalizar(campanha_id: int, usuario_id: int, estado: dict, prazo: float) -> bool:
    """Troca a mensagem do PRIMEIRO passo de cada lead da campanha por uma mensagem escrita pela IA (em etapas)."""
    with sessao() as db:
        if "tarefas" not in estado:
            primeiras: dict[int, int] = {}
            for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == campanha_id, Tarefa.status == "pendente")
                                .order_by(Tarefa.data, Tarefa.id)).scalars():
                if t.lead_id:
                    primeiras.setdefault(t.lead_id, t.id)
            estado.update(tarefas=list(primeiras.values()), i=0, feitas=0)
    tarefas = estado["tarefas"]
    for lote, proximo in trabalhos.em_lotes(tarefas, estado["i"], 1, prazo):
        with sessao() as db:
            campanha = db.get(Campanha, campanha_id)
            usuario = db.get(Usuario, usuario_id)
            tarefa = db.get(Tarefa, lote[0])
            if tarefa and tarefa.lead and tarefa.canal in ("whatsapp", "email"):
                try:
                    r = ia.gerar_abordagem(db, tarefa.lead, usuario)
                except ia.ErroDaIA as erro:
                    campanha.status_ia = f"Parou: {erro}"[:120]
                    return True
                if tarefa.canal == "whatsapp":
                    tarefa.mensagem = r["mensagem_whatsapp"]
                else:
                    tarefa.assunto, tarefa.mensagem = r["assunto_email"], r["mensagem_email"]
                estado["feitas"] += 1
            campanha.status_ia = f"Personalizando: {proximo} de {len(tarefas)}"
        estado["i"] = proximo
    if estado["i"] < len(tarefas):
        return False
    with sessao() as db:
        db.get(Campanha, campanha_id).status_ia = f"Concluído: {estado['feitas']} mensagens personalizadas pela IA"
    return True


def _personalizacao_falhou(campanha_id: int, _erro: str) -> None:
    with sessao() as db:
        db.get(Campanha, campanha_id).status_ia = "Parou por um erro inesperado (veja o registro do sistema)."


trabalhos.tipo("personalizar", _personalizacao_falhou)(etapa_personalizar)


def personalizar(campanha_id: int, usuario_id: int) -> None:
    trabalhos.iniciar("personalizar", campanha_id, usuario_id)


# ---------------------------------------------------------------- Aprovação

def resumo_aprovacao(db, camp: Campanha) -> dict:
    tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.status.in_(["rascunho", "pendente"]))
                         .order_by(Tarefa.lead_id, Tarefa.data)).scalars().all()
    leads = {t.lead_id for t in tarefas}
    por_canal: dict[str, int] = {}
    for t in tarefas:
        por_canal[t.canal] = por_canal.get(t.canal, 0) + 1
    por_categoria: dict[str, int] = {}
    for lead_id in leads:
        lead = db.get(Lead, lead_id)
        nome = lead.categoria.nome if lead and lead.categoria else "Sem categoria"
        por_categoria[nome] = por_categoria.get(nome, 0) + 1
    automatico = ler_config(db, "enviar_email_automatico") == "1"
    from .integracoes import email_smtp

    return {"tarefas": tarefas, "leads": len(leads), "por_canal": por_canal, "por_categoria": por_categoria,
            "email_automatico": automatico and email_smtp.configurado(),
            "contatos_estimados": len(tarefas)}


def aprovar(db, camp: Campanha, usuario: Usuario) -> int:
    """Rascunhos viram tarefas de verdade (datas a partir de hoje)."""
    rascunhos = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.status == "rascunho")).scalars().all()
    if rascunhos:
        primeiro = min(t.data for t in rascunhos)
        atraso = max(0, (date.today() - primeiro).days)
        for t in rascunhos:
            t.status = "pendente"
            t.data = util.proximo_dia_util(t.data + timedelta(days=atraso)) if atraso else t.data
    camp.status = "ativa"
    camp.aprovado_por_id = usuario.id if usuario else None
    camp.aprovado_em = agora()
    return len(rascunhos)


def cancelar(db, camp: Campanha, usuario: Usuario) -> int:
    tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id,
                                              Tarefa.status.in_(["rascunho", "pendente"]))).scalars().all()
    for t in tarefas:
        t.status, t.concluida_em, t.resultado = "cancelada", agora(), f"Campanha cancelada por {usuario.nome}"
        if t.lead and t.lead.status == "Abordagem criada":
            t.lead.status = "Pesquisando" if t.lead.pesquisado_em else "Novo"
    camp.status = "cancelada"
    return len(tarefas)


# ---------------------------------------------------------------- Fila e fim de cadência (rotina)

def processar_fila(db, maximo: int = 25) -> dict:
    """Envia os e-mails automáticos das campanhas aprovadas, respeitando horário e limites."""
    from .integracoes import email_smtp

    feito = {"enviados": 0, "bloqueados": 0, "erros": 0}
    if ler_config(db, "enviar_email_automatico") != "1" or not email_smtp.configurado():
        return feito
    if not mensagens.dentro_do_horario(db):
        return feito
    hora = agora().strftime("%H:%M")
    consulta = (select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id)
                .where(Tarefa.status == "pendente", Tarefa.tipo == "prospeccao", Tarefa.canal == "email",
                       Tarefa.data <= date.today(), Campanha.status == "ativa",
                       Campanha.aprovado_em.is_not(None))  # só campanhas aprovadas na IA SDR
                .order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(maximo * 3))
    for t in db.execute(consulta).scalars():
        if feito["enviados"] >= maximo:
            break
        if t.data == date.today() and (t.hora or "00:00") > hora:
            continue
        lead = t.lead
        if not lead or not sdr.automacao_ativa(lead) or not lead.email:
            t.status, t.concluida_em, t.resultado = "cancelada", agora(), "Automação parada para este lead"
            continue
        bloqueio = mensagens.bloqueio_de_envio(db, lead, "email", t.campanha_id)
        if bloqueio:
            feito["bloqueados"] += 1
            if "limite" in bloqueio.lower() and "domínio" not in bloqueio:
                break  # limite do canal/campanha: o resto espera a próxima rodada
            continue
        try:
            id_externo = email_smtp.enviar(lead.email, t.assunto or "MS Certificação Digital", t.mensagem,
                                           lead_id=lead.id)
        except email_smtp.ErroEmail as erro:
            mensagens.registrar(db, lead.id, "email", t.mensagem, None, modo="api", status="falhou", assunto=t.assunto,
                                tarefa_id=t.id, erro=str(erro), campanha_id=t.campanha_id, angulo=t.angulo,
                                categoria_id=lead.categoria_id)
            feito["erros"] += 1
            break  # problema no servidor de e-mail: não insiste agora
        mensagens.registrar(db, lead.id, "email", t.mensagem, None, modo="api", status="enviada", assunto=t.assunto,
                            tarefa_id=t.id, id_externo=id_externo, campanha_id=t.campanha_id, angulo=t.angulo,
                            categoria_id=lead.categoria_id)
        t.status, t.concluida_em, t.resultado = "feita", agora(), "Enviado automaticamente pela fila"
        registrar_contato(db, lead, "email", f"E-mail enviado pela IA SDR ({config.ANGULOS.get(t.angulo, t.acao)}).", None)
        feito["enviados"] += 1
    return feito


def whatsapp_liberado(db, lead: Lead) -> bool:
    """A IA SDR só manda WhatsApp SOZINHA para quem já conversou com a MS: autorizou receber (consentimento)
    ou já mandou mensagem pelo WhatsApp. O primeiro contato frio continua com 1 clique de uma pessoa
    (conexão por QR code + política do WhatsApp: mensagem automática para quem não conhece o número = bloqueio)."""
    if lead.consentimento:
        return True
    from .modelos import Mensagem

    return db.execute(select(Mensagem.id).where(Mensagem.lead_id == lead.id, Mensagem.canal == "whatsapp",
                                                Mensagem.status == "recebida").limit(1)).first() is not None


def processar_fila_whatsapp(db, maximo: int = 3) -> dict:
    """Envia pelo WhatsApp conectado (WhatsApp Leads) os passos de WhatsApp das campanhas aprovadas, só para
    leads liberados (ver whatsapp_liberado). Poucos por rodada: a fila de lá ainda aplica pausas e limite diário."""
    from .integracoes import whatsapp_leads

    feito = {"enviados": 0, "bloqueados": 0, "erros": 0}
    if ler_config(db, "enviar_whatsapp_automatico") != "1" or not whatsapp_leads.configurado():
        return feito
    if not mensagens.dentro_do_horario(db):
        return feito
    if not whatsapp_leads.status().get("disponivel"):
        return feito  # computador com o WhatsApp Leads desligado: tudo espera, nada se perde
    hora = agora().strftime("%H:%M")
    consulta = (select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id)
                .join(Lead, Tarefa.lead_id == Lead.id)
                .where(Tarefa.status == "pendente", Tarefa.tipo == "prospeccao", Tarefa.canal == "whatsapp",
                       Tarefa.data <= date.today(), Campanha.status == "ativa", Campanha.aprovado_em.is_not(None))
                .order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(200))
    for t in db.execute(consulta).scalars():
        if feito["enviados"] >= maximo:
            break
        if t.data == date.today() and (t.hora or "00:00") > hora:
            continue
        lead = t.lead
        if not sdr.automacao_ativa(lead) or not whatsapp_liberado(db, lead) or not (t.mensagem or "").strip():
            continue  # contato frio (ou já com um humano): fica na Agenda para o clique
        try:
            sdr.enviar_whatsapp_conectado(db, t.mensagem, None, lead=lead, tarefa=t)
        except sdr.EnvioRecusado as erro:
            texto = str(erro).lower()
            if "ainda não conectou" in texto:  # o responsável não tem número: avisa (1 vez por dia) e segue
                _avisar_para_conectar(db, lead, t)
                feito["bloqueados"] += 1
                continue
            if "limite" in texto or "whatsapp leads" in texto or "desligado" in texto:
                feito["bloqueados"] += 1
                break  # limite do canal ou WhatsApp fora do ar: o resto espera a próxima rodada
            feito["bloqueados"] += 1
            continue
        t.resultado = "Enviada sozinha pela IA SDR (contato já conversou com a MS)"
        feito["enviados"] += 1
    return feito


def _avisar_para_conectar(db, lead: Lead, tarefa: Tarefa) -> None:
    """A IA SDR tem mensagem para sair, mas o responsável não conectou o WhatsApp: avisa uma vez por dia."""
    from . import conexoes
    from .banco import gravar_config
    from .modelos import Notificacao

    quem = conexoes.responsavel(db, lead, None, tarefa)
    if quem is None:
        return
    chave = f"aviso_conectar_{quem.id}"
    if ler_config(db, chave) == date.today().isoformat():
        return
    gravar_config(db, chave, date.today().isoformat())
    db.add(Notificacao(usuario_id=quem.id, link="/whatsapp",
                       texto="A IA SDR tem mensagens de WhatsApp esperando: conecte o seu número em WhatsApp > Meu WhatsApp."))


def finalizar_cadencias(db) -> int:
    """Depois do último toque sem resposta: 'Perdido – Sem resposta'. Não continua infinitamente."""
    dias = ler_config_int(db, "dias_sem_resposta", 3)
    limite = agora() - timedelta(days=dias)
    candidatos = db.execute(select(Lead).where(Lead.status.in_(["Abordagem criada", "Contatado", "Aguardando resposta"]),
                                               Lead.respondeu_em.is_(None))).scalars().all()
    total = 0
    for lead in candidatos:
        tarefas = db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id, Tarefa.tipo == "prospeccao")).scalars().all()
        if not tarefas or any(t.status in ("pendente", "rascunho") for t in tarefas):
            continue
        feitas = [t.concluida_em for t in tarefas if t.status in ("feita", "pulada") and t.concluida_em]
        if feitas and max(feitas) < limite:
            mudar_status(db, lead, "Perdido", None, "Sem resposta")
            historico(db, lead.id, "sistema", "Cadência concluída sem resposta: lead marcado como SEM RESPOSTA.")
            total += 1
    for camp in db.execute(select(Campanha).where(Campanha.status == "ativa")).scalars():
        pendentes = db.execute(select(func.count(Tarefa.id)).where(Tarefa.campanha_id == camp.id,
                                                                   Tarefa.status == "pendente")).scalar()
        if not pendentes and camp.aprovado_em:
            camp.status = "concluida"
    return total
