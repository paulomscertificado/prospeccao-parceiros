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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from . import base_receita, bases_importadas, cadencias, config, contas_email, email_validacao, reservas, ia, mensagens, prospeccao, sdr, trabalhos, util
from .banco import agora, gravar_config, ler_config, ler_config_int, sessao
from .leads_servico import criar_lead, historico, limpar_campos, mudar_status, registrar_contato
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
        # quem criou a campanha assina e envia (mesmo que a ficha já tivesse outro vendedor: ver _montar)
        usuario = db.get(Usuario, usuario_id)
        try:
            return lead_id, sdr.gerar_mensagens(db, lead, usuario, cta, tom)
        except Exception as erro:  # noqa: BLE001
            log.warning("Mensagens da empresa %s: IA falhou (%s), usando os modelos", lead_id, erro)
            return lead_id, sdr.mensagens_por_regras(db, lead, usuario, cta, tom)


def _leads_em_outras_campanhas(db, campanha_id: int) -> set[int]:
    """Leads com envio ainda por fazer em outra campanha em andamento: não entram em duas campanhas ao mesmo tempo.
    (Depois que a outra campanha acaba, quem decide é a reserva: ver app/reservas.py.)"""
    return set(db.execute(
        select(Tarefa.lead_id).join(Campanha, Tarefa.campanha_id == Campanha.id)
        .where(Tarefa.campanha_id != campanha_id, Tarefa.lead_id.is_not(None),
               Tarefa.status.in_(["pendente", "rascunho"]),
               Campanha.status.in_(["gerando", "aguardando_aprovacao", "ativa", "pausada"]))
        .distinct()).scalars())


MAXIMO_BUSCA = 4000  # empresas olhadas por segmento, no máximo, para completar a campanha


def celular_do_lead(lead: Lead) -> str:
    """Um celular (DDD + 9 + 8 dígitos) do telefone do lead ou do anotado da Receita nas observações."""
    for numero in [lead.telefone or ""] + re.findall(r"\(?\d{2}\)?\s?9\d{4}-?\d{4}", lead.observacoes or ""):
        digitos = util.so_digitos(numero)
        if len(digitos) == 11 and digitos[2] == "9":
            return digitos
    return ""


def tem_canal(lead: Lead, canais: list[str]) -> bool:
    email = lead.email and not lead.email_invalido  # e-mail que não existe não conta como canal
    return any({"whatsapp": lead.whatsapp, "email": email, "linkedin": lead.linkedin}.get(c) for c in canais or ["whatsapp", "email"])


def _buscar_candidatos(campanha_id: int) -> list[int]:
    """Etapa 1: empresas da base escolhida (Receita ou lista importada) nas categorias e na região (o dobro, para poder escolher).
    Cada campanha pega empresas DIFERENTES: pula quem já está em outra campanha ativa, quem já foi contatado,
    pediu para sair ou foi encerrado, e procura mais fundo na base até completar a quantidade."""
    with sessao() as db:
        camp = db.get(Campanha, campanha_id)
        usuario = db.get(Usuario, camp.usuario_id)
        cods = [c for c in camp.categorias.split(",") if c]
        cats = {c.codigo: c for c in db.execute(select(Categoria).where(Categoria.codigo.in_(cods))).scalars()}
        quantidade = max(1, camp.quantidade or 50)
        base = camp.base or bases_importadas.RECEITA
        nome_base = bases_importadas.nome(db, base)
        if not bases_importadas.disponivel(db, base):
            raise RuntimeError(f"A {nome_base} não tem empresas (importe em Configurações > Integrações).")
        candidatos: list[int] = []
        canais = [c for c in camp.canais.split(",") if c]
        so_fixo: list[int] = []
        ja_usados = _leads_em_outras_campanhas(db, campanha_id)
        por_categoria = max(1, -(-quantidade * 2 // max(1, len(cods))))
        for cod in cods:
            achados, vistos, limite_busca = 0, set(), por_categoria
            while achados < por_categoria:
                resultados = bases_importadas.buscar(db, base, camp.cidade, camp.estado, limite_busca, [cod])
                for dados in resultados:
                    if achados >= por_categoria:
                        break
                    if dados["cnpj"] in vistos:
                        continue  # já olhada na volta anterior
                    vistos.add(dados["cnpj"])
                    origem = dados.pop("origem")
                    dados.pop("categoria", None)
                    lead, motivo = criar_lead(db, dados, usuario, origem=origem)
                    if not lead or lead.id in candidatos:
                        continue
                    if lead.id in ja_usados:
                        continue  # já está em outra campanha: esta campanha pega outras empresas
                    if reservas.de_outro(lead, camp.usuario_id):
                        continue  # travada com outro usuário (60 dias ou até ele liberar)
                    if motivo and (lead.opt_out or lead.perdido or lead.etapa >= 1 or lead.automacao_pausada):
                        continue  # já cadastrado e já trabalhado: não entra de novo
                    if lead.categoria_id is None and cod in cats:
                        lead.categoria = cats[cod]
                    if "whatsapp" in canais and not lead.whatsapp:
                        lead.whatsapp = celular_do_lead(lead)
                        limpar_campos(lead)  # formata e recalcula a chave: sem ela, a resposta não acha a empresa
                    if "email" in canais and lead.email:
                        email_validacao.utilizavel(db, lead)  # domínio sem e-mail: já entra sem esse canal
                    if not tem_canal(lead, canais):
                        if not lead.telefone:
                            continue  # sem nenhum contato: não dá nem para pesquisar
                        so_fixo.append(lead.id)  # só fixo: entra também; o time pesquisa o WhatsApp na internet
                    candidatos.append(lead.id)
                    achados += 1
                # acabaram as empresas da região, ou já olhamos o bastante
                if len(resultados) < limite_busca * 3 or limite_busca * 3 >= MAXIMO_BUSCA:
                    break
                limite_busca = min(limite_busca * 4, MAXIMO_BUSCA // 3)
        if not candidatos:
            nomes = ", ".join(c.nome for c in cats.values()) or "das categorias escolhidas"
            lugar = f"\"{camp.cidade}\"/{camp.estado}" if camp.cidade else camp.estado
            raise RuntimeError(f"Não encontrei empresas novas de {nomes} em {lugar} na {nome_base}. Confira o nome da "
                               "cidade (ou do bairro) e o estado, ou escolha outro segmento ou outra base.")
        return list(dict.fromkeys(candidatos))


def etapa_gerar(campanha_id: int, _usuario_id, estado: dict, prazo: float) -> bool:
    """Monta a campanha em etapas (ver app/trabalhos.py) e deixa esperando aprovação.
    estado["fase"]: buscar → pesquisar → mensagens → montar."""
    fase = estado.setdefault("fase", "buscar")
    if fase == "novas":  # Empresas novas: as empresas vêm da API da CNPJá (app/empresas_novas.py)
        from . import empresas_novas

        _anotar(campanha_id, f"Cadastrando as empresas abertas ({estado.get('feitos', 0)} lidas)...", "gerando")
        if not empresas_novas.etapa_importar(campanha_id, estado, prazo):
            return False
        if not estado["escolhidos"]:
            raise RuntimeError("Nenhuma empresa nova para contatar (todas já estavam cadastradas e em atendimento).")
        estado["fase"] = fase = "montar"
    if fase == "buscar":
        with sessao() as db:
            onde = bases_importadas.nome(db, (db.get(Campanha, campanha_id).base or "receita"))
        _anotar(campanha_id, f"Procurando empresas na {onde}...", "gerando")
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
            elegiveis = [l for l in leads if l and l.fit != "Sem fit" and not l.opt_out and not l.perdido]
            canais = [c for c in db.get(Campanha, campanha_id).canais.split(",") if c]
            for l in elegiveis:
                if "whatsapp" in canais and not l.whatsapp:
                    l.whatsapp = celular_do_lead(l)  # celular informado à Receita: a campanha tenta o WhatsApp nele
                    limpar_campos(l)  # formata e recalcula a chave: sem ela, a resposta não acha a empresa
            # Quem já tem WhatsApp/e-mail vem primeiro; quem só tem telefone fixo entra também (WhatsApp sem número:
            # o time pesquisa o contato na internet e cadastra na própria campanha).
            elegiveis.sort(key=lambda l: (not tem_canal(l, canais), -l.score, l.id))
            quantidade_c = max(1, db.get(Campanha, campanha_id).quantidade or 50)
            estado["so_fixo"] = [l.id for l in elegiveis[:quantidade_c] if not tem_canal(l, canais)]
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
    _montar(campanha_id, estado["escolhidos"], {int(k): v for k, v in estado["textos"].items()}, estado.get("so_fixo", []))
    return True


def _montar(campanha_id: int, escolhidos: list[int], textos: dict[int, dict], so_fixo: list[int] | None = None) -> None:
    with sessao() as db:
        camp = db.get(Campanha, campanha_id)
        usuario = db.get(Usuario, camp.usuario_id)
        cad = db.get(Cadencia, camp.cadencia_id) if camp.cadencia_id else cadencia_sdr(db)
        leads = [l for l in (db.get(Lead, i) for i in escolhidos) if l]
        for lead in leads:
            if lead.vendedor_id != usuario.id and _livre_para_campanha(lead):
                # o lead passa a ser de quem criou a campanha: assina as mensagens e envia pelo WhatsApp/e-mail dela
                if lead.vendedor_id:
                    anterior = db.get(Usuario, lead.vendedor_id)
                    historico(db, lead.id, "sistema", f"Responsável passou de {anterior.nome if anterior else '?'} "
                                                      f"para {usuario.nome} (entrou na campanha \"{camp.nome}\").",
                              usuario)
                lead.vendedor_id = usuario.id
            if not reservas.de_outro(lead, usuario.id):
                reservas.reservar(db, lead, usuario, f"campanha \"{camp.nome}\"")
        r = cadencias.aplicar(db, cad, leads, usuario, camp.inicio or date.today(), camp.id, textos,
                              [c for c in camp.canais.split(",") if c], "rascunho", camp.cta, camp.tom,
                              foco_whatsapp=camp.tipo == "empresas_novas")  # venda: WhatsApp; e-mail se não tiver
        camp.etapa = (f"Pronta: {r['leads']} empresas, {r['tarefas']} mensagens"
                      + (f" ({len(r['pulados'])} puladas)" if r["pulados"] else "") + ".")
        if so_fixo:
            from .modelos import Notificacao

            camp.etapa += (f" {len(so_fixo)} empresas ainda sem WhatsApp (só telefone fixo): pesquise o contato na "
                           "internet e cadastre na campanha.")
            camp.so_fixo = ",".join(str(i) for i in so_fixo)
            db.add(Notificacao(usuario_id=usuario.id, link=f"/campanhas/{camp.id}#ligacoes",
                               texto=f"{len(so_fixo)} empresas da campanha \"{camp.nome}\" estão sem WhatsApp: pesquise e cadastre o número"))
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
    for t in [t for t in rascunhos if t.canal not in ("email", "whatsapp")]:
        t.status = "cancelada"  # campanhas antigas com ligação: a campanha só manda e-mail e WhatsApp
    rascunhos = [t for t in rascunhos if t.status == "rascunho"]
    if rascunhos:
        primeiro = min(t.data for t in rascunhos)
        atraso = max(0, (date.today() - primeiro).days)
        for t in rascunhos:
            t.status = "pendente"
            if (t.hora or "09:00").endswith(":00"):  # campanha montada antes (09:00 do passo): vira horário natural
                t.hora = cadencias.hora_natural(db)  # (horário escolhido à mão, como 10:20, fica como está)
            t.data = util.proximo_dia_util(t.data + timedelta(days=atraso)) if atraso else t.data
        _sem_horario_no_passado(db, rascunhos)
    camp.status = "ativa"
    camp.aprovado_por_id = usuario.id if usuario else None
    camp.aprovado_em = agora()
    return len(rascunhos)


def _sem_horario_no_passado(db, tarefas: list[Tarefa]) -> int:
    """Aprovada depois do horário marcado (ex.: montada de manhã e aprovada à tarde): o toque de hoje que já passou ganha
    um horário novo daqui a pouco (ou vai para o próximo dia, se o horário de envio de hoje acabou). Os toques seguintes
    da mesma empresa nunca ficam antes dele. Devolve quantos mudaram."""
    agora_txt = agora().strftime("%Y-%m-%d %H:%M")
    mudou = 0
    por_lead: dict[int, list[Tarefa]] = {}
    for t in tarefas:
        por_lead.setdefault(t.lead_id, []).append(t)
    for lista in por_lead.values():
        lista.sort(key=lambda t: (t.data, t.hora or "", t.id or 0))
        anterior = None
        for t in lista:
            if f"{t.data:%Y-%m-%d} {t.hora or '00:00'}" <= agora_txt:
                t.data, t.hora = cadencias.dia_e_hora_futuros(db, t.data)
                mudou += 1
            if anterior and (t.data, t.hora or "") < (anterior.data, anterior.hora or ""):
                t.data, t.hora = cadencias.dia_e_hora_futuros(db, anterior.data)
                if (t.data, t.hora) <= (anterior.data, anterior.hora or ""):
                    t.data, t.hora = cadencias.dia_e_hora_futuros(db, anterior.data + timedelta(days=1))
                mudou += 1
            anterior = t
    return mudou


def cancelar(db, camp: Campanha, usuario: Usuario) -> int:
    tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id,
                                              Tarefa.status.in_(["rascunho", "pendente"]))).scalars().all()
    for t in tarefas:
        t.status, t.concluida_em, t.resultado = "cancelada", agora(), f"Campanha cancelada por {usuario.nome}"
        if t.lead and t.lead.status == "Abordagem criada":
            t.lead.status = "Pesquisando" if t.lead.pesquisado_em else "Novo"
    camp.status = "cancelada"
    return len(tarefas)


def cancelar_toques(db, tarefas: list[Tarefa], usuario: Usuario, origem: str = "Minha fila") -> int:
    """Botão Cancelar da Minha fila e de Envios: cancela só os toques escolhidos que ainda não saíram (os outros toques
    da empresa continuam). A empresa que fica sem nenhum toque em aberto volta para "Pesquisando"/"Novo", como ao
    cancelar a campanha, e pode entrar em outra campanha. Devolve quantos foram cancelados."""
    cancelados = 0
    afetados: dict[int, Lead] = {}
    for t in tarefas:
        if t.status not in ("pendente", "rascunho"):
            continue  # já saiu ou já foi cancelado
        t.status, t.concluida_em = "cancelada", agora()
        t.resultado = f"Cancelado por {usuario.nome} ({origem})"
        cancelados += 1
        if t.lead_id:
            afetados[t.lead_id] = t.lead
            historico(db, t.lead_id, "campanha", f"Envio de {config.CANAIS.get(t.canal, t.canal)} programado para "
                                                 f"{t.data:%d/%m} cancelado por {usuario.nome} ({origem}).", usuario)
    db.flush()
    for lead_id, lead in afetados.items():
        em_aberto = db.execute(select(Tarefa.id).where(Tarefa.lead_id == lead_id, Tarefa.tipo == "prospeccao",
                                                       Tarefa.status.in_(["pendente", "rascunho"])).limit(1)).first()
        if not em_aberto and lead is not None and lead.status == "Abordagem criada":
            lead.status = "Pesquisando" if lead.pesquisado_em else "Novo"
    return cancelados


def excluir(db, camp: Campanha, usuario: Usuario) -> None:
    """Apaga a campanha. Antes cancela o que estava programado; as empresas (leads) e o histórico das mensagens
    já enviadas continuam no sistema."""
    from sqlalchemy import delete, update

    from .modelos import Mensagem, Trabalho

    cancelar(db, camp, usuario)
    db.execute(update(Mensagem).where(Mensagem.campanha_id == camp.id).values(campanha_id=None))
    db.execute(delete(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.status.in_(["cancelada", "rascunho"])))
    db.execute(update(Tarefa).where(Tarefa.campanha_id == camp.id).values(campanha_id=None))
    db.execute(delete(Trabalho).where(Trabalho.tipo.in_(["campanha", "personalizar"]), Trabalho.ref_id == camp.id))
    db.delete(camp)


def andamento(db, camp: Campanha) -> list[dict]:
    """Por empresa: cada toque da campanha (canal, data) e a situação: programado, enviado, não saiu, cancelado."""
    from .modelos import Mensagem

    tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id)
                         .order_by(Tarefa.lead_id, Tarefa.data, Tarefa.id)).scalars().all()
    envios = {m.tarefa_id: m for m in db.execute(select(Mensagem).where(Mensagem.campanha_id == camp.id,
                                                                         Mensagem.tarefa_id.is_not(None))).scalars()}
    respondeu = {m.lead_id for m in db.execute(select(Mensagem).where(Mensagem.campanha_id == camp.id,
                                                                       Mensagem.respondida.is_(True))).scalars()}
    linhas: dict[int, dict] = {}
    for t in tarefas:
        if not t.lead:
            continue
        linha = linhas.setdefault(t.lead_id, {"lead": t.lead, "toques": [], "respondeu": t.lead_id in respondeu})
        m = envios.get(t.id)
        if m:
            situacao = {"enviada": "enviado", "entregue": "enviado", "lida": "enviado", "na_fila": "na_fila",
                        "falhou": "falhou", "copiada": "manual"}.get(m.status, "enviado")
        else:
            situacao = {"rascunho": "rascunho", "pendente": "programado", "feita": "enviado", "cancelada": "cancelado",
                        "pulada": "cancelado"}.get(t.status, t.status)
        linha["toques"].append({"canal": t.canal, "data": t.data, "hora": t.hora or "", "angulo": t.angulo, "situacao": situacao,
                                "quando": m.criado_em if m else None, "erro": m.erro if m else ""})
        linha.setdefault("tarefas", []).append(t)
    for linha in linhas.values():  # tirada da campanha: nada mais sai para ela
        tarefas = linha.pop("tarefas")
        linha["removida"] = all(t.status == "cancelada" and (t.resultado or "").startswith("Removido da campanha")
                                for t in tarefas)
        linha["motivo"] = (tarefas[0].resultado or "").partition(": ")[2] if linha["removida"] else ""
    return sorted(linhas.values(), key=lambda l: l["removida"])


def mensagens_para_teste(db, campanhas_ids: list[int]) -> dict[int, dict[str, int]]:
    """Quantas mensagens de e-mail e de WhatsApp (ainda não enviadas) cada campanha tem: {id: {"email": n, "whatsapp": n}}."""
    contagem: dict[int, dict[str, int]] = {i: {"email": 0, "whatsapp": 0} for i in campanhas_ids}
    if not campanhas_ids:
        return contagem
    tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id.in_(campanhas_ids),
                                              Tarefa.status.in_(["rascunho", "pendente"]))).scalars()
    for t in tarefas:
        for canal in ("email", "whatsapp"):
            if _texto_do_canal(t, canal)[1]:
                contagem[t.campanha_id][canal] += 1
    return contagem


def _texto_do_canal(t: Tarefa, canal: str) -> tuple[str, str]:
    """(assunto, texto) do toque no canal pedido: a mensagem principal ou o modelo guardado do outro canal."""
    if t.canal == canal and (t.mensagem or "").strip():
        return t.assunto or "", t.mensagem
    if canal == "whatsapp":
        return "", (t.mensagem_whatsapp or "").strip()
    if canal == "email":
        return t.assunto_email or t.assunto or "", (t.mensagem_email or "").strip()
    return "", ""


def enviar_teste(db, camp: Campanha, usuario: Usuario, canal: str, destino: str,
                 empresas: int = 1, todos_os_toques: bool = False) -> dict:
    """Ambiente de teste: manda as mensagens de UM canal da campanha (e-mail ou WhatsApp) para o e-mail/WhatsApp DE
    QUEM ESTÁ TESTANDO, com "[TESTE]" no começo. Nenhum lead recebe nada, nada conta nos limites e a campanha
    não muda de situação."""
    from . import conexoes
    from .integracoes import email_smtp, whatsapp_leads

    tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id,
                                              Tarefa.status.in_(["rascunho", "pendente"]))
                         .order_by(Tarefa.lead_id, Tarefa.data, Tarefa.id)).scalars().all()
    escolhidas, leads = [], []
    for t in tarefas:
        if not _texto_do_canal(t, canal)[1]:
            continue
        if t.lead_id not in leads:
            if len(leads) >= max(1, min(empresas, 5)):
                continue
            leads.append(t.lead_id)
        elif not todos_os_toques:
            continue
        escolhidas.append(t)
    feito = {"enviadas": 0, "erros": []}
    numero, conta = "", None
    if canal == "email" and escolhidas:
        try:
            conta = contas_email.para_enviar(db, usuario)
        except contas_email.SemConta as erro:
            feito["erros"].append(f"E-mail: {erro}")
            return feito
    if canal == "whatsapp" and escolhidas:
        try:
            numero = conexoes.da_campanha(db, camp) or conexoes.para_enviar(db, usuario)
        except conexoes.SemNumero as erro:
            feito["erros"].append(f"WhatsApp: {erro}")
            return feito
    for t in escolhidas:
        empresa = t.lead.empresa if t.lead else "empresa"
        rotulo = f"[TESTE · {empresa} · {config.ANGULOS.get(t.angulo, t.acao)}]"
        assunto, texto = _texto_do_canal(t, canal)
        try:
            from . import visual

            if canal == "email":
                from . import marca

                assunto, texto = marca.aplicar(assunto, usuario), marca.aplicar(texto, usuario)
                email_smtp.enviar(destino, f"[TESTE] {assunto or marca.da_pessoa(usuario)['nome']}",
                                  f"{rotulo}\n\n{texto}", lead_id=None, conta=conta,
                                  html=visual.html_do_email(db, t, t.lead, usuario, f"{rotulo}\n\n{texto}"))
            else:
                # no teste a imagem vai mesmo para contato frio: quem recebe é a própria pessoa que testa
                imagem = visual.imagem_do_whatsapp(db, t, t.lead, so_para_quem_conversou=False)
                whatsapp_leads.enviar(destino, "Teste", f"{rotulo}\n\n{texto}", db=db, manual=True,
                                      usuario_id=usuario.id, conexao=numero, midia_id=imagem.id if imagem else None)
            feito["enviadas"] += 1
        except (email_smtp.ErroEmail, whatsapp_leads.ErroWhatsAppLeads) as erro:
            feito["erros"].append(f"{'E-mail' if canal == 'email' else 'WhatsApp'}: {erro}")
            break
    return feito


def whatsapp_de_hoje(db, camp: Campanha) -> list[Tarefa]:
    """Mensagens de WhatsApp da campanha para hoje (ou atrasadas): enviadas com 1 clique na própria campanha."""
    return list(db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.canal == "whatsapp",
                                                Tarefa.status == "pendente", Tarefa.data <= date.today())
                           .order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(100)).scalars())


# ---------------------------------------------------------------- Fila e fim de cadência (rotina)

# Envios automáticos: um de cada vez por canal, com 3 a 4 minutos entre eles, sempre num intervalo diferente.
# O relógio roda a cada minuto, então o próximo fica liberado entre 2,5 e 3,5 min depois: na prática sai 3 ou 4 min
# depois do anterior (sorteado), nunca vários no mesmo minuto.
INTERVALO_AUTOMATICO_SEG = (150, 210)


def _vez_do_canal(db, canal: str) -> bool:
    """Já passou o intervalo desde o último envio automático deste canal?"""
    if not config.ESPACAR_ENVIOS:
        return True
    return ler_config(db, f"proximo_envio_automatico:{canal}") <= agora().isoformat(timespec="seconds")


def _anotar_envio(db, canal: str) -> None:
    """Depois de um envio automático: sorteia quando o próximo deste canal pode sair."""
    import random

    if config.ESPACAR_ENVIOS:
        proximo = agora() + timedelta(seconds=random.uniform(*INTERVALO_AUTOMATICO_SEG))
        gravar_config(db, f"proximo_envio_automatico:{canal}", proximo.isoformat(timespec="seconds"))


def _ja_na_hora(hoje: date, hora: str):
    """Filtro SQL: toques de dias anteriores ou de hoje cujo horário já chegou. Antes isso era conferido um a um
    depois da consulta, e os toques de mais tarde ocupavam as vagas da consulta (limit) à toa."""
    return or_(Tarefa.data < hoje, and_(Tarefa.data == hoje, func.coalesce(Tarefa.hora, "") <= hora))


def _limite_da_campanha(motivo: str) -> bool:
    """O bloqueio é só desta campanha (limite diário da campanha): as outras campanhas continuam saindo."""
    return "desta campanha" in motivo.lower()


def processar_fila(db, maximo: int = 25) -> dict:
    """Envia os e-mails automáticos das campanhas aprovadas, respeitando horário, limites e o intervalo de 3 a 4
    minutos entre um e-mail e outro (_vez_do_canal)."""
    from .integracoes import email_smtp

    feito = {"enviados": 0, "bloqueados": 0, "erros": 0}
    if ler_config(db, "enviar_email_automatico") != "1" or not email_smtp.configurado():
        return feito
    if not mensagens.dentro_do_horario(db):
        return feito
    if not _vez_do_canal(db, "email"):
        return feito  # o último e-mail automático saiu há menos de 3 minutos
    hora = agora().strftime("%H:%M")
    # Só o que já está na hora (filtro no banco) e uma consulta folgada: toques que esperam (responsável sem e-mail,
    # caixa pausada, campanha no limite do dia) não podem tomar as vagas e travar os das outras campanhas.
    consulta = (select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id)
                .where(Tarefa.status == "pendente", Tarefa.tipo == "prospeccao", Tarefa.canal == "email",
                       _ja_na_hora(date.today(), hora), Campanha.status == "ativa",
                       Campanha.aprovado_em.is_not(None))  # só campanhas aprovadas na IA SDR
                .order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(max(maximo * 3, 400)))
    campanhas_no_limite: set[int] = set()
    for t in db.execute(consulta).scalars():
        if feito["enviados"] >= maximo:
            break
        if t.campanha_id in campanhas_no_limite:
            feito["bloqueados"] += 1
            continue
        lead = t.lead
        if not lead or not sdr.automacao_ativa(lead) or not lead.email:
            t.status, t.concluida_em, t.resultado = "cancelada", agora(), "Automação parada para este lead"
            continue
        bloqueio = mensagens.bloqueio_de_envio(db, lead, "email", t.campanha_id)
        if bloqueio:
            feito["bloqueados"] += 1
            if _limite_da_campanha(bloqueio):
                campanhas_no_limite.add(t.campanha_id)
                continue  # só esta campanha chegou ao limite do dia: as outras seguem
            if "limite" in bloqueio.lower() and "domínio" not in bloqueio:
                break  # limite do canal (dia/hora): o resto espera a próxima rodada
            continue
        try:
            conta = conta_do_toque(db, t)
        except contas_email.SemConta as erro:
            feito["bloqueados"] += 1
            _avisar_sem_conta(db, t, str(erro))
            continue  # o responsável ainda não tem e-mail: espera e avisa
        if ler_config(db, _chave_pausa(conta)) > agora().isoformat(timespec="seconds"):
            feito["bloqueados"] += 1
            continue  # esta conta deu erro há pouco: espera antes de tentar de novo (as outras seguem)
        erro = _enviar_email_da_tarefa(db, t, None, "Enviado automaticamente pela fila", conta,
                                       registrar_erro_da_caixa=False)
        if erro == DESTINATARIO_RECUSADO:
            feito["erros"] += 1
            if config.ESPACAR_ENVIOS:
                _anotar_envio(db, "email")  # o servidor foi chamado: o próximo também espera o intervalo
                break
            continue  # só o e-mail deste lead não sai: a fila segue com os outros
        if erro:
            feito["erros"] += 1
            gravar_config(db, _chave_pausa(conta),
                          (agora() + timedelta(minutes=PAUSA_FILA_EMAIL)).isoformat(timespec="seconds"))
            log.warning("Conta de e-mail %s pausada por %s min: %s", contas_email.chave(conta), PAUSA_FILA_EMAIL, erro)
            _avisar_caixa_com_erro(db, t, conta, erro)
            continue  # problema nesta caixa de envio: não insiste nela agora
        feito["enviados"] += 1
        if config.ESPACAR_ENVIOS:
            _anotar_envio(db, "email")
            break  # um por vez: o próximo sai daqui a 3 ou 4 minutos
    return feito


DESTINATARIO_RECUSADO = "destinatario"
PAUSA_FILA_EMAIL = 15  # minutos sem tentar depois de um erro da caixa de envio


def _chave_pausa(conta) -> str:
    return "fila_email_pausada_ate:" + contas_email.chave(conta)


def conta_do_toque(db, t: Tarefa, usuario: Usuario | None = None):
    """Conta de e-mail por onde sai o toque: a do responsável pelo lead (app/contas_email.py)."""
    from . import conexoes

    return contas_email.para_enviar(db, conexoes.responsavel(db, t.lead, usuario, t))


def _avisar_caixa_com_erro(db, t: Tarefa, conta, erro: str) -> None:
    """A caixa de envio recusou (senha errada, servidor fora): um aviso por dia para cada pessoa que cuida dela —
    o responsável pelo lead e quem pode trocar a senha da conta (principal: os administradores)."""
    from . import autorizacao, conexoes
    from .modelos import Notificacao

    hoje = date.today().isoformat()
    pessoas = {}
    quem = conexoes.responsavel(db, t.lead, None, t)
    if quem is not None:
        pessoas[quem.id] = quem
    if conta is None or conta.principal:
        for u in db.execute(select(Usuario).where(Usuario.ativo.is_(True))).scalars():
            if autorizacao.pode(u, "email.gerenciar_todas"):
                pessoas[u.id] = u
    elif conta.dono_id:
        pessoas.setdefault(conta.dono_id, None)
    for uid in pessoas:
        marca = f"aviso_caixa_email:{contas_email.chave(conta)}:{uid}"
        if ler_config(db, marca) == hoje:
            continue
        gravar_config(db, marca, hoje)
        db.add(Notificacao(usuario_id=uid, link="/email",
                           texto=f"E-mails de campanha parados (eles esperam na fila): {erro}"[:300]))


def _avisar_sem_conta(db, t: Tarefa, motivo: str) -> None:
    """Responsável sem e-mail para enviar: avisa uma vez por dia (o toque continua esperando)."""
    from . import conexoes
    from .modelos import Notificacao

    quem = conexoes.responsavel(db, t.lead, None, t)
    if quem is None:
        return
    marca = f"aviso_sem_email:{quem.id}"
    if ler_config(db, marca) == date.today().isoformat():
        return
    gravar_config(db, marca, date.today().isoformat())
    db.add(Notificacao(usuario_id=quem.id, link="/email", texto=f"E-mails de campanha esperando: {motivo}"[:300]))


def _enviar_email_da_tarefa(db, t: Tarefa, usuario: Usuario | None, resultado: str, conta=None,
                            registrar_erro_da_caixa: bool = True) -> str:
    """Envia o e-mail do toque e registra (enviada ou falhou). Devolve "" se saiu; DESTINATARIO_RECUSADO se o
    endereço do lead foi recusado (só este toque é cancelado); senão o erro (da caixa de envio ou falta de conta).
    conta: por onde sai (None = a do responsável pelo lead).
    registrar_erro_da_caixa=False (fila automática): erro da caixa de envio (senha, servidor) não vira "Não saiu" a
    cada tentativa; o toque só continua esperando e quem cuida da conta recebe um aviso por dia."""
    from .integracoes import email_smtp

    lead = t.lead
    if not email_validacao.utilizavel(db, lead):
        t.status, t.concluida_em = "cancelada", agora()
        t.resultado = f"E-mail não existe: {lead.email_motivo or 'endereço inválido'}"[:500]
        return DESTINATARIO_RECUSADO
    if conta is None:
        try:
            conta = conta_do_toque(db, t, usuario)
        except contas_email.SemConta as erro:
            return str(erro)
    from . import conexoes, marca

    from . import visual

    quem = conexoes.responsavel(db, lead, usuario, t)
    t.assunto, t.mensagem = marca.aplicar(t.assunto, quem), marca.aplicar(t.mensagem, quem)
    html = visual.html_do_email(db, t, lead, quem, t.mensagem, email_smtp.link_descadastro(lead.id))
    try:
        id_externo = email_smtp.enviar(lead.email, t.assunto or marca.da_pessoa(quem)["nome"], t.mensagem,
                                       lead_id=lead.id, conta=conta, html=html)
    except email_smtp.ErroEmail as erro:
        do_lead = isinstance(erro, email_smtp.ErroDestinatario)
        if not do_lead and not registrar_erro_da_caixa:
            return str(erro) or "erro no servidor de e-mail"
        falha = mensagens.registrar(db, lead.id, "email", t.mensagem, usuario, modo="api", status="falhou",
                                    assunto=t.assunto, tarefa_id=t.id, erro=str(erro), campanha_id=t.campanha_id,
                                    angulo=t.angulo, categoria_id=lead.categoria_id)
        falha.conexao = contas_email.chave(conta)
        if do_lead:
            email_validacao.marcar_invalido(db, lead, f"o servidor recusou o endereço ({str(erro)[:120]})", usuario)
            t.status, t.concluida_em, t.resultado = "cancelada", agora(), f"E-mail não saiu: {str(erro)[:200]}"
            historico(db, lead.id, "sistema", f"E-mail recusado: {erro} Confira o endereço do lead.", usuario, "email")
            return DESTINATARIO_RECUSADO
        return str(erro) or "erro no servidor de e-mail"
    saiu = mensagens.registrar(db, lead.id, "email", t.mensagem, usuario, modo="api", status="enviada",
                               assunto=t.assunto, tarefa_id=t.id, id_externo=id_externo, campanha_id=t.campanha_id,
                               angulo=t.angulo, categoria_id=lead.categoria_id)
    saiu.conexao = contas_email.chave(conta)
    t.status, t.concluida_em, t.resultado = "feita", agora(), resultado
    registrar_contato(db, lead, "email", f"E-mail enviado pela IA SDR ({config.ANGULOS.get(t.angulo, t.acao)}).",
                      usuario)
    return ""


def para_disparar(db, camp: Campanha) -> dict[str, list[Tarefa]]:
    """Toques de hoje (ou atrasados) da campanha ativa que podem sair por clique, por canal: 1 por empresa. Usa o
    modelo guardado do outro canal quando o toque está marcado no outro canal."""
    feito: dict[str, list[Tarefa]] = {"whatsapp": [], "email": []}
    if camp.status != "ativa":
        return feito
    tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.status == "pendente",
                                              Tarefa.data <= date.today())
                         .order_by(Tarefa.data, Tarefa.hora, Tarefa.id)).scalars().all()
    vistos: dict[str, set] = {"whatsapp": set(), "email": set()}
    for t in tarefas:
        lead = t.lead
        if not lead or not sdr.automacao_ativa(lead):
            continue
        for canal in ("whatsapp", "email"):
            contato = lead.whatsapp if canal == "whatsapp" else lead.email  # WhatsApp em branco: não sai
            if contato and _texto_do_canal(t, canal)[1] and t.lead_id not in vistos[canal]:
                vistos[canal].add(t.lead_id)
                feito[canal].append(t)
    return feito


def trocar_canal(t: Tarefa, canal: str) -> None:
    """Passa o toque para o outro canal usando a versão reserva; o texto do canal antigo fica guardado como reserva."""
    if t.canal == canal:
        return
    assunto, texto = _texto_do_canal(t, canal)
    if t.canal == "email" and not t.mensagem_email:
        t.mensagem_email, t.assunto_email = t.mensagem, t.assunto
    if t.canal == "whatsapp" and not t.mensagem_whatsapp:
        t.mensagem_whatsapp = t.mensagem
    t.canal, t.mensagem, t.assunto = canal, texto, assunto


def texto_do_canal(t: Tarefa, canal: str) -> tuple[str, str]:
    return _texto_do_canal(t, canal)


def editar_texto_do_canal(t: Tarefa, canal: str, texto: str, assunto: str = "") -> None:
    """Grava o texto (e o assunto, no e-mail) da versão daquele canal: a principal ou a reserva."""
    texto = texto.strip()
    if t.canal == canal:
        t.mensagem = texto
        if canal == "email":
            t.assunto = assunto[:200]
    elif canal == "whatsapp":
        t.mensagem_whatsapp = texto
    else:
        t.mensagem_email, t.assunto_email = texto, assunto[:200]


def canais_do_toque(t: Tarefa) -> list[str]:
    """Canais em que o toque tem mensagem pronta (o marcado primeiro)."""
    outros = [c for c in ("email", "whatsapp") if c != t.canal]
    return [c for c in [t.canal] + outros if c in ("email", "whatsapp") and _texto_do_canal(t, c)[1]]


def enviar_toque_agora(db, t: Tarefa, usuario: Usuario, canal: str = "") -> str:
    """Clique em "Enviar agora" / "Enviar de novo" (Minha fila): manda este toque já, pelo canal dele, com as mesmas
    regras (horário, limites, controle de frequência, opt-out). Devolve "" se saiu ou o motivo de não ter saído."""
    lead = t.lead
    canal = canal or t.canal
    if canal not in ("email", "whatsapp"):
        return "Este toque não é de e-mail nem de WhatsApp."
    if not _texto_do_canal(t, canal)[1]:
        return f"Este toque não tem versão de {'e-mail' if canal == 'email' else 'WhatsApp'}."
    if canal == "whatsapp" and not (lead and (lead.whatsapp or "").strip()):
        return sdr.SEM_WHATSAPP
    if canal == "email" and not (lead and lead.email):
        return "Este lead não tem e-mail."
    original = (t.canal, t.mensagem, t.assunto, t.mensagem_whatsapp, t.mensagem_email, t.assunto_email)
    trocar_canal(t, canal)
    erro = _enviar_toque(db, t, usuario)
    if erro:  # não saiu: o toque volta ao canal que estava
        t.canal, t.mensagem, t.assunto, t.mensagem_whatsapp, t.mensagem_email, t.assunto_email = original
    return erro


def _enviar_toque(db, t: Tarefa, usuario: Usuario) -> str:
    lead = t.lead
    if not lead or not sdr.automacao_ativa(lead):
        return "A automação está parada para este lead (respondeu, opt-out ou está com alguém)."
    if not _texto_do_canal(t, t.canal)[1]:
        return "Este toque está sem mensagem."
    if not mensagens.dentro_do_horario(db):
        return "Fora do horário de envio (Configurações). Tente de novo no horário comercial."
    if t.canal == "email" and not lead.email:
        return "Este lead não tem e-mail."
    bloqueio = mensagens.bloqueio_de_envio(db, lead, t.canal, t.campanha_id)
    if bloqueio:
        return bloqueio
    t.status = "pendente"
    if t.canal == "email":
        erro = _enviar_email_da_tarefa(db, t, usuario, f"Enviado por {usuario.nome} (Minha fila)")
        if erro == DESTINATARIO_RECUSADO:
            return ("O e-mail deste lead foi recusado (endereço inválido ou inexistente). Corrija o e-mail na ficha "
                    "do lead; este toque foi cancelado.")
        if erro:
            return f"O e-mail não saiu: {erro}"
        return ""
    try:
        sdr.enviar_whatsapp_conectado(db, t.mensagem, usuario, lead=lead, tarefa=t)
    except sdr.EnvioRecusado as erro:
        return str(erro)
    t.resultado = f"Enviado por {usuario.nome} (Minha fila)"
    return ""


def disparar(db, camp: Campanha, usuario: Usuario, canal: str) -> dict:
    """Clique em "Disparar campanha" (WhatsApp ou e-mail): manda AGORA, pelo canal escolhido, o toque de hoje de
    cada empresa. Continua 1 a 1, com horário, limites, controle de frequência e opt-out; o WhatsApp entra na fila
    do WhatsApp Leads (pausas e limite diário de lá). O que não sair agora continua programado."""
    from collections import Counter

    # "motivos": por que cada uma não saiu (antes tudo virava "controle de frequência ou opt-out", até o
    # WhatsApp em branco na ficha, e a pessoa não sabia o que corrigir)
    feito = {"enviados": 0, "bloqueados": 0, "erros": [], "parou": "", "motivos": Counter()}
    if canal not in ("whatsapp", "email"):
        return feito
    if not mensagens.dentro_do_horario(db):
        feito["parou"] = "fora do horário de envio (Configurações). Tente de novo no horário comercial"
        return feito
    for t in para_disparar(db, camp)[canal]:
        lead = t.lead
        trocar_canal(t, canal)
        bloqueio = mensagens.bloqueio_de_envio(db, lead, canal, t.campanha_id)
        if bloqueio:
            feito["bloqueados"] += 1
            if "limite" in bloqueio.lower() and "domínio" not in bloqueio:
                feito["parou"] = bloqueio
                break
            feito["motivos"][motivo_curto(bloqueio)] += 1
            continue
        if canal == "email":
            erro = _enviar_email_da_tarefa(db, t, usuario, f"Disparado por {usuario.nome}")
            if erro == DESTINATARIO_RECUSADO:
                feito["erros"].append(f"{lead.empresa}: e-mail recusado (endereço inválido)")
                continue
            if erro:
                feito["erros"].append(f"O e-mail não saiu: {erro}")
                break
        else:
            try:
                sdr.enviar_whatsapp_conectado(db, t.mensagem, usuario, lead=lead, tarefa=t)
            except sdr.EnvioRecusado as erro:
                texto_erro = str(erro)
                if any(p in texto_erro.lower() for p in ("limite", "desligado", "não conectou", "desconectado",
                                                           "whatsapp leads")):
                    feito["parou"] = texto_erro
                    break
                feito["bloqueados"] += 1
                feito["motivos"][motivo_curto(texto_erro)] += 1
                continue
            t.resultado = f"Disparado por {usuario.nome}"
        feito["enviados"] += 1
    return feito


def motivo_curto(texto: str) -> str:
    """Por que uma mensagem do disparo não saiu, em poucas palavras (as do mesmo motivo são contadas juntas)."""
    t = (texto or "").lower()
    if texto == sdr.SEM_WHATSAPP or "não tem whatsapp/telefone" in t:
        return "campo WhatsApp em branco na ficha"
    if "opt-out" in t:
        return "pediu para não receber mensagens (opt-out)"
    if "controle de frequência" in t:
        return "recebeu mensagem há pouco (controle de frequência)"
    if "inválido" in t or "anonimizado" in t:
        return "número marcado como inválido"
    if "contatos frios" in t and "pausad" in t:
        return "número pausado hoje: pedidos para sair"
    if "contatos frios" in t:
        return "número chegou ao teto de contatos frios do dia"
    return (texto or "motivo desconhecido").strip().rstrip(".")


def resumo_dos_motivos(motivos) -> str:
    """Ex.: "campo WhatsApp em branco na ficha (3); recebeu mensagem há pouco (controle de frequência) (1)"."""
    return "; ".join(f"{m} ({n})" for m, n in motivos.most_common())


def whatsapp_liberado(db, lead: Lead) -> bool:
    """A IA SDR só manda WhatsApp SOZINHA para quem já conversou com a MS: autorizou receber (consentimento)
    ou já mandou mensagem pelo WhatsApp. Nas campanhas que não saem sozinhas (campanhas_que_saem_sozinhas), o
    primeiro contato frio continua com 1 clique de uma pessoa
    (conexão por QR code + política do WhatsApp: mensagem automática para quem não conhece o número = bloqueio)."""
    return bool(lead.consentimento) or lead.id in leads_que_conversaram(db, [lead.id])


TIPOS_QUE_SAEM_SOZINHOS = ("empresas_novas",)
DIAS_ATRASO_AUTOMATICO = 2  # toque com mais atraso que isto não sai sozinho (espera o clique): evita rajada


def campanhas_que_saem_sozinhas(db) -> dict[int, str]:
    """Campanhas cujo WhatsApp sai sozinho depois da aprovação, mesmo para quem nunca conversou com a MS
    ({id: tipo}): as de Empresas novas (pedido da Maria em 11/11/2026: "se eu aprovei a campanha, era para entrar na
    fila de disparos") e as de parceiros em que o admin ligou o "WhatsApp sai sozinho" (Campanha.whatsapp_sozinho,
    pedido de 12/11/2026). Saem pela mesma fila automática, com as mesmas travas: um a cada 3 minutos, limite por
    hora, por dia e por número, teto de contatos frios por número, horário de envio, controle de frequência e SAIR.
    Nas outras campanhas de parceiros o contato frio continua com o clique de uma pessoa."""
    linhas = db.execute(select(Campanha.id, Campanha.tipo).where(
        or_(Campanha.tipo.in_(TIPOS_QUE_SAEM_SOZINHOS), Campanha.whatsapp_sozinho.is_(True)),
        Campanha.status == "ativa", Campanha.aprovado_em.is_not(None))).all()
    return {cid: tipo for cid, tipo in linhas}


def motivo_automatico(automaticas, campanha_id) -> str:
    """Por que o WhatsApp desta campanha sai sozinho (para a Minha fila e o registro do envio)."""
    tipo = automaticas.get(campanha_id) if isinstance(automaticas, dict) else TIPOS_QUE_SAEM_SOZINHOS[0]
    if tipo in TIPOS_QUE_SAEM_SOZINHOS:
        return "campanha de Empresas novas aprovada"
    return "campanha aprovada com WhatsApp automático"


def toque_sai_sozinho(t: Tarefa, automaticas, hoje: date | None = None) -> bool:
    """O toque é de uma campanha que sai sozinha e não está atrasado demais?"""
    hoje = hoje or date.today()
    return t.campanha_id in automaticas and t.data >= hoje - timedelta(days=DIAS_ATRASO_AUTOMATICO)


def _toque_anterior_pendente():
    """Condição do banco: a mesma empresa tem, na mesma campanha, um WhatsApp anterior que ainda não saiu. Assim o
    "último contato" nunca sai antes da apresentação (ex.: 1º toque parado há dias esperando o clique e os
    seguintes chegando no dia deles)."""
    anterior = aliased(Tarefa)
    hora_ant, hora = func.coalesce(anterior.hora, ""), func.coalesce(Tarefa.hora, "")
    return (select(anterior.id).where(
        anterior.campanha_id == Tarefa.campanha_id, anterior.lead_id == Tarefa.lead_id, anterior.canal == "whatsapp",
        anterior.status == "pendente", anterior.id != Tarefa.id,
        or_(anterior.data < Tarefa.data,
            and_(anterior.data == Tarefa.data, or_(hora_ant < hora, and_(hora_ant == hora, anterior.id < Tarefa.id)))))
        .exists())


def toques_com_anterior_pendente(db, tarefas) -> set[int]:
    """Dos toques de WhatsApp informados, os que esperam um toque anterior da mesma empresa (mesma campanha) sair
    (a mesma regra de _toque_anterior_pendente, para as telas Minha fila e Envios)."""
    tarefas = [t for t in tarefas if t.canal == "whatsapp" and t.campanha_id and t.lead_id]
    if not tarefas:
        return set()
    linhas = db.execute(select(Tarefa.id, Tarefa.campanha_id, Tarefa.lead_id, Tarefa.data, Tarefa.hora).where(
        Tarefa.status == "pendente", Tarefa.canal == "whatsapp",
        Tarefa.lead_id.in_({t.lead_id for t in tarefas}), Tarefa.campanha_id.in_({t.campanha_id for t in tarefas}))).all()
    primeiro: dict[tuple[int, int], tuple] = {}
    for tid, cid, lid, data, hora in linhas:
        chave, ordem = (cid, lid), (data, hora or "", tid)
        if chave not in primeiro or ordem < primeiro[chave]:
            primeiro[chave] = ordem
    return {t.id for t in tarefas if primeiro.get((t.campanha_id, t.lead_id), (None, None, t.id))[2] != t.id}


def leads_que_conversaram(db, ids) -> set[int]:
    """Dos leads informados, os que já mandaram mensagem DE GENTE pelo WhatsApp (a regra de whatsapp_liberado, numa
    consulta só: a tela Minha fila confere centenas de toques de uma vez). Resposta de robô, chatbot ou ausência não
    conta (auditoria de 11/11/2026: 37 respostas de robô liberavam WhatsApp sozinho): as marcadas como "robo" e as
    antigas que têm cara de robô (sdr.e_resposta_automatica)."""
    from .modelos import Mensagem

    ids = [i for i in set(ids or []) if i]
    if not ids:
        return set()
    linhas = db.execute(select(Mensagem.lead_id, Mensagem.corpo).where(
        Mensagem.lead_id.in_(ids), Mensagem.canal == "whatsapp", Mensagem.status == "recebida",
        Mensagem.modo != "robo")).all()
    return {lid for lid, corpo in linhas if not sdr.e_resposta_automatica(corpo or "")}


def processar_fila_whatsapp(db, maximo: int = 3) -> dict:
    """Envia pelo WhatsApp conectado (WhatsApp Leads) os passos de WhatsApp das campanhas aprovadas, só para
    leads liberados (ver whatsapp_liberado). Poucos por rodada: a fila de lá ainda aplica pausas e limite diário."""
    from .integracoes import whatsapp_leads

    feito = {"enviados": 0, "bloqueados": 0, "erros": 0}
    if ler_config(db, "enviar_whatsapp_automatico") != "1" or not whatsapp_leads.configurado():
        return feito
    if not mensagens.dentro_do_horario(db):
        return feito
    if not _vez_do_canal(db, "whatsapp"):
        return feito  # a última mensagem automática saiu há menos de 3 minutos
    if not whatsapp_leads.status().get("disponivel"):
        return feito  # computador com o WhatsApp Leads desligado: tudo espera, nada se perde
    from .modelos import Mensagem

    hora = agora().strftime("%H:%M")
    hoje = date.today()
    # Só quem pode receber sozinho (filtro no banco): campo WhatsApp preenchido e contato que já conversou ou autorizou,
    # ou toque de campanha que sai sozinha depois da aprovação (Empresas novas ou com o WhatsApp automático ligado,
    # sem atraso grande).
    # Antes os toques frios (que esperam o clique e continuam pendentes) ocupavam as 200 vagas da consulta e os
    # liberados que viessem depois deles nunca saíam.
    conversou = (select(Mensagem.id).where(Mensagem.lead_id == Lead.id, Mensagem.canal == "whatsapp",
                                           Mensagem.status == "recebida", Mensagem.modo != "robo").exists())
    da_campanha_automatica = and_(or_(Campanha.tipo.in_(TIPOS_QUE_SAEM_SOZINHOS), Campanha.whatsapp_sozinho.is_(True)),
                                  Tarefa.data >= hoje - timedelta(days=DIAS_ATRASO_AUTOMATICO))
    consulta = (select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id)
                .join(Lead, Tarefa.lead_id == Lead.id)
                .where(Tarefa.status == "pendente", Tarefa.tipo == "prospeccao", Tarefa.canal == "whatsapp",
                       _ja_na_hora(hoje, hora), Campanha.status == "ativa", Campanha.aprovado_em.is_not(None),
                       func.coalesce(Lead.whatsapp, "") != "",
                       or_(Lead.consentimento.is_(True), conversou, da_campanha_automatica),
                       ~_toque_anterior_pendente())  # o toque anterior da empresa sai primeiro
                .order_by(Tarefa.data, Tarefa.hora, Tarefa.id).limit(200))
    automaticas = campanhas_que_saem_sozinhas(db)
    campanhas_no_limite: set[int] = set()
    for t in db.execute(consulta).scalars():
        if feito["enviados"] >= maximo:
            break
        if t.campanha_id in campanhas_no_limite:
            continue
        lead = t.lead
        if not (lead.whatsapp or "").strip():
            continue  # campo WhatsApp em branco: a mensagem espera alguém cadastrar o número
        automatica = toque_sai_sozinho(t, automaticas, hoje)
        if not sdr.automacao_ativa(lead) or not (t.mensagem or "").strip():
            continue  # lead respondeu, saiu ou está com um humano
        if not automatica and not whatsapp_liberado(db, lead):
            continue  # contato frio de campanha de parceiros: fica na Agenda para o clique
        try:
            sdr.enviar_whatsapp_conectado(db, t.mensagem, None, lead=lead, tarefa=t)
        except sdr.EnvioRecusado as erro:
            texto = str(erro).lower()
            if "ainda não conectou" in texto:  # o responsável não tem número: avisa (1 vez por dia) e segue
                _avisar_para_conectar(db, lead, t)
                feito["bloqueados"] += 1
                continue
            if "limite" in texto and "este número" in texto:
                feito["bloqueados"] += 1
                continue  # este número chegou ao limite: os leads de outros números seguem
            if _limite_da_campanha(texto):
                feito["bloqueados"] += 1
                campanhas_no_limite.add(t.campanha_id)
                continue  # só esta campanha chegou ao limite do dia: as outras seguem
            if "limite" in texto or "whatsapp leads" in texto or "desligado" in texto:
                feito["bloqueados"] += 1
                break  # limite do canal ou WhatsApp fora do ar: o resto espera a próxima rodada
            feito["bloqueados"] += 1
            continue
        t.resultado = (f"Enviada sozinha ({motivo_automatico(automaticas, t.campanha_id)})" if automatica
                       else "Enviada sozinha pela IA SDR (contato já conversou com a MS)")
        feito["enviados"] += 1
        if config.ESPACAR_ENVIOS:
            _anotar_envio(db, "whatsapp")
            break  # uma por vez: a próxima sai daqui a 3 ou 4 minutos
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
    # Uma consulta só (antes era 1 + 1 por lead, a cada hora, o que fica lento na nuvem com muitos leads): lead sem
    # toque em aberto e cujo último toque feito/pulado foi há mais de `dias` dias.
    em_aberto = select(Tarefa.lead_id).where(Tarefa.tipo == "prospeccao", Tarefa.status.in_(["pendente", "rascunho"]),
                                             Tarefa.lead_id.is_not(None))  # sem NULL: o NOT IN não pode falhar
    ultimo = (select(Tarefa.lead_id.label("lead_id"), func.max(Tarefa.concluida_em).label("quando"))
              .where(Tarefa.tipo == "prospeccao", Tarefa.status.in_(["feita", "pulada"]),
                     Tarefa.concluida_em.is_not(None), Tarefa.lead_id.is_not(None))
              .group_by(Tarefa.lead_id).subquery())
    candidatos = db.execute(select(Lead).join(ultimo, ultimo.c.lead_id == Lead.id).where(
        Lead.status.in_(["Abordagem criada", "Contatado", "Aguardando resposta"]), Lead.respondeu_em.is_(None),
        ultimo.c.quando < limite, Lead.id.not_in(em_aberto))).scalars().all()
    total = 0
    for lead in candidatos:
        mudar_status(db, lead, "Perdido", None, "Sem resposta")
        historico(db, lead.id, "sistema", "Cadência concluída sem resposta: lead marcado como SEM RESPOSTA.")
        total += 1
    for camp in db.execute(select(Campanha).where(Campanha.status == "ativa")).scalars():
        pendentes = db.execute(select(func.count(Tarefa.id)).where(Tarefa.campanha_id == camp.id,
                                                                   Tarefa.status == "pendente")).scalar()
        if not pendentes and camp.aprovado_em:
            camp.status = "concluida"
    return total


def conferir_emails(db, camp: Campanha, maximo: int = 400) -> dict:
    """Confere os e-mails dos leads da campanha que ainda têm toque de e-mail pendente (domínio que não recebe
    e-mail ou endereço mal escrito) e tira os inválidos. Devolve {"conferidos", "invalidos", "toques_cancelados"}."""
    ids = list(dict.fromkeys(i for (i,) in db.execute(select(Tarefa.lead_id).where(
        Tarefa.campanha_id == camp.id, Tarefa.canal == "email", Tarefa.status.in_(["pendente", "rascunho"]),
        Tarefa.lead_id.is_not(None)))))[:maximo]
    feito = {"conferidos": 0, "invalidos": 0, "toques_cancelados": 0}
    for lead in db.execute(select(Lead).where(Lead.id.in_(ids))).scalars():
        feito["conferidos"] += 1
        antes = db.execute(select(func.count()).select_from(Tarefa).where(
            Tarefa.lead_id == lead.id, Tarefa.canal == "email", Tarefa.status.in_(["pendente", "rascunho"]))).scalar()
        lead.email_verificado_em = None  # confere de novo agora, mesmo que já tenha sido conferido
        if not email_validacao.utilizavel(db, lead):
            feito["invalidos"] += 1
            if lead.email_invalido:
                for t in db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id, Tarefa.canal == "email",
                                                         Tarefa.status.in_(["pendente", "rascunho"]))).scalars():
                    t.status, t.concluida_em, t.resultado = "cancelada", agora(),                         f"E-mail não existe: {lead.email_motivo}"[:500]
            feito["toques_cancelados"] += antes
    return feito



# ---------------------------------------------------------------- E-mails que não existem: corrigir e reenviar

_CANCELADO_POR_EMAIL = ("E-mail não existe", "E-mail não saiu")


def emails_invalidos(db, camp: Campanha) -> list[dict]:
    """Empresas desta campanha com e-mail marcado como inexistente, para o time pesquisar o endereço certo.
    [{"lead", "toques_parados", "foi_devolvido"}]"""
    ids = {i for (i,) in db.execute(select(Tarefa.lead_id).where(Tarefa.campanha_id == camp.id,
                                                                  Tarefa.lead_id.is_not(None)))}
    if not ids:
        return []
    itens = []
    leads = db.execute(select(Lead).where(Lead.id.in_(ids), Lead.email_invalido.is_(True), Lead.opt_out.is_(False))
                       .order_by(Lead.empresa)).scalars()
    for lead in leads:
        if (lead.email_conferido or "") != lead.email:
            continue  # já corrigido: a marca antiga não vale
        parados = db.execute(select(func.count()).select_from(Tarefa).where(
            Tarefa.campanha_id == camp.id, Tarefa.lead_id == lead.id, Tarefa.canal == "email",
            Tarefa.status == "cancelada", Tarefa.resultado.like("E-mail n%"))).scalar()
        itens.append({"lead": lead, "toques_parados": parados, "foi_devolvido": _foi_devolvido(lead)})
    return itens


def _foi_devolvido(lead: Lead) -> bool:
    """O e-mail chegou a sair e voltou (devolução ou recusa do servidor), em vez de ser barrado antes."""
    return bool(re.search(r"devolvido|recusou", lead.email_motivo or ""))


def corrigir_email(db, camp: Campanha, lead: Lead, novo: str, usuario: Usuario) -> dict:
    """Troca o e-mail do lead, tira a marca de inexistente e põe a empresa de volta no cronograma da campanha:
    os toques de e-mail parados voltam (datas empurradas para hoje em diante, mantendo o intervalo entre eles) e,
    se o e-mail tinha voltado, o último toque é reenviado hoje. Lança ValueError com o motivo se o endereço novo
    não serve. Devolve {"reativados", "reenvio"}."""
    from .leads_servico import limpar_campos

    novo = (novo or "").strip().lower()
    if not email_validacao.formato_valido(novo):
        raise ValueError("o e-mail está escrito errado. Confira e tente de novo (ex.: contato@escritorio.com.br)")
    if novo == (lead.email or "").lower():
        raise ValueError("é o mesmo e-mail que não existe. Pesquise o endereço certo da empresa")
    ok, motivo = email_validacao.conferir(novo)
    if ok is False:
        raise ValueError(motivo)
    antigo, devolvido = lead.email, _foi_devolvido(lead)
    lead.email = novo
    limpar_campos(lead)
    lead.email_invalido, lead.email_motivo, lead.email_conferido = False, "", lead.email
    lead.email_verificado_em = agora() if ok else None
    historico(db, lead.id, "contato", f"E-mail corrigido pelo time: {antigo} → {lead.email}. "
                                      "A empresa voltou para o cronograma da campanha.", usuario, "email")

    feito = {"reativados": 0, "reenvio": False}
    if camp.status not in ("aguardando_aprovacao", "ativa", "pausada"):
        return feito  # campanha encerrada/cancelada: só corrige o cadastro
    novo_status = "rascunho" if camp.status == "aguardando_aprovacao" else "pendente"
    parados = db.execute(select(Tarefa).where(
        Tarefa.campanha_id == camp.id, Tarefa.lead_id == lead.id, Tarefa.canal == "email",
        Tarefa.status == "cancelada").order_by(Tarefa.data, Tarefa.id)).scalars().all()
    parados = [t for t in parados if (t.resultado or "").startswith(_CANCELADO_POR_EMAIL)]
    hoje = date.today()
    if parados and novo_status == "pendente" and parados[0].data < hoje:
        atraso = hoje - parados[0].data  # empurra todos juntos: o intervalo entre os toques continua igual
        for t in parados:
            t.data = t.data + atraso
    for t in parados:
        t.status, t.concluida_em, t.resultado = novo_status, None, ""
        feito["reativados"] += 1

    if devolvido and novo_status == "pendente":
        ultimo = db.execute(select(Tarefa).where(
            Tarefa.campanha_id == camp.id, Tarefa.lead_id == lead.id, Tarefa.canal == "email",
            Tarefa.status == "feita").order_by(Tarefa.concluida_em.desc(), Tarefa.id.desc())).scalars().first()
        if ultimo:
            db.add(Tarefa(tipo=ultimo.tipo, lead_id=lead.id, campanha_id=camp.id, passo_id=ultimo.passo_id,
                          usuario_id=ultimo.usuario_id, canal="email", data=hoje, hora=ultimo.hora or "09:00",
                          acao=f"Reenvio para o e-mail corrigido ({ultimo.acao})"[:250], assunto=ultimo.assunto,
                          mensagem=ultimo.mensagem, mensagem_whatsapp=ultimo.mensagem_whatsapp,
                          mensagem_email=ultimo.mensagem_email, assunto_email=ultimo.assunto_email,
                          angulo=ultimo.angulo, status="pendente"))
            feito["reenvio"] = True
    return feito



# ---------------------------------------------------------------- Responsável diferente de quem criou a campanha

def _livre_para_campanha(lead: Lead) -> bool:
    """Ninguém conversou com a empresa ainda: pode passar para quem criou a campanha."""
    return lead.humano_id is None and lead.contatado_em is None and lead.respondeu_em is None


def responsaveis_diferentes(db, camp: Campanha) -> list[dict]:
    """Empresas da campanha (com envio ainda por fazer) cujo responsável não é quem criou a campanha: as mensagens
    estão assinadas por outra pessoa e sairiam pelo WhatsApp/e-mail dela. [{"lead", "responsavel", "pode_passar"}]"""
    if not camp.usuario_id or camp.status not in ("aguardando_aprovacao", "ativa", "pausada"):
        return []
    ids = {i for (i,) in db.execute(select(Tarefa.lead_id).where(
        Tarefa.campanha_id == camp.id, Tarefa.status.in_(["rascunho", "pendente"]), Tarefa.lead_id.is_not(None)))}
    if not ids:
        return []
    itens = []
    for lead in db.execute(select(Lead).where(Lead.id.in_(ids), Lead.vendedor_id.is_not(None),
                                              Lead.vendedor_id != camp.usuario_id).order_by(Lead.empresa)).scalars():
        itens.append({"lead": lead, "responsavel": db.get(Usuario, lead.vendedor_id),
                      "pode_passar": _livre_para_campanha(lead)})
    return itens


def _trocar_assinatura(texto: str, velho: str, novo: str) -> str:
    if not texto or not velho or velho == novo:
        return texto
    texto = re.sub(rf"\n\n{re.escape(velho)}\n(?=[^\n]+$)", f"\n\n{novo}\n", texto)
    return re.sub(rf"\bSou {re.escape(velho)}(,| da| e)", lambda m: f"Sou {novo}{m.group(1)}", texto)


def assumir_empresas(db, camp: Campanha, usuario: Usuario | None) -> dict:
    """Passa para quem criou a campanha as empresas com outro responsável (as que ninguém trabalhou ainda) e troca a
    assinatura das mensagens que ainda vão sair. Devolve {"empresas", "mensagens", "mantidas"}."""
    dono = db.get(Usuario, camp.usuario_id) if camp.usuario_id else None
    feito = {"empresas": 0, "mensagens": 0, "mantidas": 0}
    if dono is None:
        return feito
    novo = util.primeiro_nome(dono.nome) if dono.perfil != "parceiro" else "a equipe"
    for item in responsaveis_diferentes(db, camp):
        lead, antigo = item["lead"], item["responsavel"]
        if not item["pode_passar"]:
            feito["mantidas"] += 1
            continue
        velho = util.primeiro_nome(antigo.nome) if antigo and antigo.perfil != "parceiro" else "a equipe"
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == camp.id, Tarefa.lead_id == lead.id,
                                                 Tarefa.status.in_(["rascunho", "pendente"]))).scalars():
            antes = (t.mensagem, t.mensagem_email, t.mensagem_whatsapp)
            t.mensagem = _trocar_assinatura(t.mensagem, velho, novo)
            t.mensagem_email = _trocar_assinatura(t.mensagem_email, velho, novo)
            t.mensagem_whatsapp = _trocar_assinatura(t.mensagem_whatsapp, velho, novo)
            if t.usuario_id == lead.vendedor_id:
                t.usuario_id = dono.id
            if (t.mensagem, t.mensagem_email, t.mensagem_whatsapp) != antes:
                feito["mensagens"] += 1
        historico(db, lead.id, "sistema", f"Responsável passou de {antigo.nome if antigo else '?'} para {dono.nome} "
                                          f"(campanha \"{camp.nome}\"); assinatura das mensagens trocada.", usuario)
        lead.vendedor_id = dono.id
        feito["empresas"] += 1
    return feito
