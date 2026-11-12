"""Tela Envios: o que já saiu (e-mail e WhatsApp), para quem, quando e como está; o que ainda vai sair (e por quê);
e como funcionam os disparos. Cada um vê os envios dos próprios leads; admin e gestor veem todos.

Em abas, do mesmo jeito da Minha fila (rotas/fila.py): Enviados (por dia, com os testes da campanha), Próximos
envios (por dia, com a situação de cada um e o botão certo) e Como funcionam os disparos."""

from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .. import autorizacao, campanhas, mensagens, util
from ..banco import agora, ler_config, obter_db
from ..modelos import Campanha, Lead, LogAuditoria, Mensagem, Tarefa, Usuario
from ..seguranca import exige
from ..web import tela

rotas = APIRouter()

STATUS_ENVIO = {"na_fila": ("Na fila", "selo-azul"), "enviada": ("Enviada", "selo-ok"), "entregue": ("Entregue", "selo-ok"),
                "lida": ("Lida", "selo-ok"), "falhou": ("Não saiu", "selo-erro"), "copiada": ("Copiada (envio manual)", ""),
                "recebida": ("Resposta recebida", "selo-alerta")}
PERIODOS = {"hoje": ("Hoje", 0), "7d": ("7 dias", 7), "30d": ("30 dias", 30), "90d": ("90 dias", 90)}
# Filtros de situação da aba Enviados: (nome do botão, cor do ponto)
SITUACOES_ENVIO = {"enviada": ("Enviada", "selo-ok"), "entregue": ("Entregue", "selo-ok"), "lida": ("Lida", "selo-ok"),
                   "na_fila": ("Na fila", "selo-azul"), "falhou": ("Não saiu", "selo-erro"),
                   "respondeu": ("Teve resposta", "selo-alerta"), "respostas": ("Respostas recebidas", "selo-alerta"),
                   "teste": ("Testes da campanha", "selo-roxo")}
ABAS = ("enviados", "proximos", "regras")
LIMITE_LISTA = 300     # envios mostrados de uma vez (os mais novos primeiro)
LIMITE_BUSCA = 3000    # envios olhados nos 90 dias, para os filtros e as contagens


def _so_dele(consulta, usuario: Usuario):
    """Só os envios dos leads que a pessoa alcança (ou feitos por ela)."""
    ids = autorizacao.donos_visiveis(usuario, "envios.ver")
    if ids is None:
        return consulta
    return consulta.where(or_(Lead.vendedor_id.in_(sorted(ids)), Mensagem.usuario_id == usuario.id))


def _teste(g: LogAuditoria) -> dict:
    """Um teste da campanha (registro "testou_campanha"): foi só para quem testou, nunca para uma empresa."""
    texto = g.detalhes or ""
    canal = "whatsapp" if "whatsapp" in texto else "email"
    destino = texto.rsplit(" para ", 1)[-1].strip() if " para " in texto else ""
    if canal == "whatsapp" and util.so_digitos(destino):
        destino = util.formatar_telefone(destino[2:] if destino.startswith("55") else destino)
    quantos = util.para_int(texto.split(" ", 1)[0]) or 0
    nome = "WhatsApp" if canal == "whatsapp" else "e-mail"
    resumo = (f"{quantos} {nome}{'s' if quantos > 1 and canal == 'whatsapp' else ''} de teste para {destino}"
              if quantos else f"Nenhuma mensagem de {nome} saiu no teste")
    return {"tipo": "teste", "quando": g.criado_em, "canal": canal, "campanha_id": g.entidade_id, "resumo": resumo,
            "quem": g.usuario_nome or ""}


def _grupos_do_passado(itens: list[dict], hoje: date) -> list[dict]:
    """Envios já feitos, um grupo por dia: Hoje, Ontem, depois o dia da semana (o mais novo primeiro)."""
    from .fila import DIAS_SEMANA

    grupos: list[dict] = []
    for item in itens:
        d = item["quando"].date()
        if not grupos or grupos[-1]["data"] != d:
            semana = DIAS_SEMANA[d.weekday()]
            if d == hoje:
                titulo, detalhe = "Hoje", f"{semana}, {d:%d/%m}"
            elif d == hoje - timedelta(days=1):
                titulo, detalhe = "Ontem", f"{semana}, {d:%d/%m}"
            else:
                titulo, detalhe = semana.capitalize(), f"{d:%d/%m}"
            grupos.append({"data": d, "titulo": titulo, "detalhe": detalhe, "itens": []})
        grupos[-1]["itens"].append(item)
    return grupos


@rotas.get("/envios")
def tela_envios(request: Request, canal: str = "", status: str = "", campanha: str = "", periodo: str = "7d",
                lead: str = "", busca: str = "", aba: str = "enviados", quando: str = "todos", situacao: str = "",
                usuario: Usuario = Depends(exige("envios.ver")), db: Session = Depends(obter_db)):
    from . import fila  # aqui dentro: a Minha fila também importa desta tela

    hoje = date.today()
    inicio_hoje = agora().replace(hour=0, minute=0, second=0, microsecond=0)
    aba = aba if aba in ABAS else "enviados"
    periodo = periodo if periodo in PERIODOS else "7d"
    status = status if status in SITUACOES_ENVIO or status in STATUS_ENVIO else ""
    quando = quando if quando in dict(fila.PERIODOS) else "todos"
    situacao = situacao if situacao in fila.SITUACOES else ""
    canal = canal if canal in ("email", "whatsapp") else ""
    camp_id = util.para_int(campanha) or 0
    lead_id = util.para_int(lead) or 0
    termo = util.chave_texto(busca)
    ids_visiveis = autorizacao.donos_visiveis(usuario, "envios.ver")

    # ---- Enviados: os envios dos últimos 90 dias são lidos uma vez; filtros e contagens são feitos aqui
    desde_max = inicio_hoje - timedelta(days=90)
    consulta = (select(Mensagem).outerjoin(Lead, Mensagem.lead_id == Lead.id)
                .where(Mensagem.canal.in_(["email", "whatsapp"]), Mensagem.criado_em >= desde_max))
    consulta = _so_dele(consulta, usuario)
    if lead_id:
        consulta = consulta.where(Mensagem.lead_id == lead_id)
    todas = db.execute(consulta.order_by(Mensagem.criado_em.desc(), Mensagem.id.desc()).limit(LIMITE_BUSCA)).scalars().all()
    ids_leads = {m.lead_id for m in todas if m.lead_id}
    leads_por_id = {l.id: l for l in db.execute(select(Lead).where(Lead.id.in_(ids_leads))).scalars()} if ids_leads else {}

    def desde(per: str):
        return inicio_hoje - timedelta(days=PERIODOS[per][1])

    def passa(m: Mensagem) -> bool:
        if canal and m.canal != canal:
            return False
        if camp_id and m.campanha_id != camp_id:
            return False
        if termo:
            l = leads_por_id.get(m.lead_id)
            return bool(l) and termo in util.chave_texto(l.empresa)
        return True

    def na_situacao(m: Mensagem, st: str) -> bool:
        if st == "respondeu":
            return bool(m.respondida) and m.status != "recebida"
        if st == "respostas":
            return m.status == "recebida"
        if st == "teste":
            return False
        if st:
            return m.status == st
        return m.status != "recebida"  # padrão: só o que a MS mandou

    log_q = select(LogAuditoria).where(LogAuditoria.acao == "testou_campanha", LogAuditoria.criado_em >= desde_max)
    if ids_visiveis is not None:
        log_q = log_q.where(LogAuditoria.usuario_id == usuario.id)
    testes = [] if lead_id else [_teste(g) for g in db.execute(log_q.order_by(LogAuditoria.criado_em.desc())).scalars()]

    def teste_passa(t: dict) -> bool:
        return not termo and (not canal or t["canal"] == canal) and (not camp_id or t["campanha_id"] == camp_id)

    base = [m for m in todas if passa(m)]
    testes = [t for t in testes if teste_passa(t)]
    com_testes = status in ("", "teste")
    contagem_periodo = {per: sum(1 for m in base if m.criado_em >= desde(per) and na_situacao(m, status))
                        + (sum(1 for t in testes if t["quando"] >= desde(per)) if com_testes else 0) for per in PERIODOS}
    no_periodo = [m for m in base if m.criado_em >= desde(periodo)]
    testes_periodo = [t for t in testes if t["quando"] >= desde(periodo)]
    contagem_status = {st: (len(testes_periodo) if st == "teste" else sum(1 for m in no_periodo if na_situacao(m, st)))
                       for st in SITUACOES_ENVIO}
    itens = [{"tipo": "envio", "quando": m.criado_em, "m": m} for m in no_periodo if na_situacao(m, status)]
    if com_testes:
        itens += testes_periodo
    itens.sort(key=lambda i: i["quando"], reverse=True)
    total_enviados = len(itens)
    grupos_enviados = _grupos_do_passado(itens[:LIMITE_LISTA], hoje)

    # ---- Próximos envios: o que ainda vai sair nas campanhas ativas (mesma regra e mesma situação da Minha fila)
    canais = [canal] if canal else ["email", "whatsapp"]
    prox_q = (select(Tarefa).join(Campanha, Tarefa.campanha_id == Campanha.id).outerjoin(Lead, Tarefa.lead_id == Lead.id)
              .where(Tarefa.status == "pendente", Campanha.status == "ativa", Tarefa.canal.in_(["email", "whatsapp"]),
                     or_(Tarefa.canal.in_(canais),
                         *([Tarefa.mensagem_whatsapp != ""] if "whatsapp" in canais else []),
                         *([Tarefa.mensagem_email != ""] if "email" in canais else [])),
                     Tarefa.data <= hoje + timedelta(days=7)))
    if ids_visiveis is not None:
        prox_q = prox_q.where(or_(Lead.vendedor_id.in_(sorted(ids_visiveis)), Campanha.usuario_id.in_(sorted(ids_visiveis))))
    if lead_id:
        prox_q = prox_q.where(Tarefa.lead_id == lead_id)
    tarefas = db.execute(prox_q.options(selectinload(Tarefa.lead)).order_by(Tarefa.data, Tarefa.hora, Tarefa.id)
                         .limit(fila.LIMITE_PENDENTES)).scalars().all()
    no_horario = mensagens.dentro_do_horario(db)
    conversaram = campanhas.leads_que_conversaram(db, [t.lead_id for t in tarefas if t.canal == "whatsapp"])
    email_auto = ler_config(db, "enviar_email_automatico") == "1"
    whats_auto = ler_config(db, "enviar_whatsapp_automatico") == "1"
    automaticas = campanhas.campanhas_que_saem_sozinhas(db)
    com_anterior = campanhas.toques_com_anterior_pendente(db, tarefas)
    recentes = campanhas.leads_com_whatsapp_recente(db, [t.lead_id for t in tarefas if t.canal == "whatsapp"])
    proximos = []
    for t in tarefas:
        chave, motivo = fila._situacao(t, hoje, no_horario, conversaram, email_auto, whats_auto, automaticas,
                                       com_anterior, recentes)
        rotulo, classe = fila.SITUACOES[chave]
        proximos.append({"t": t, "situacao": chave, "rotulo": rotulo, "classe": classe, "motivo": motivo,
                         "atrasado": t.data < hoje, "dias": (hoje - t.data).days})
    prox_base = [p for p in proximos if (not camp_id or p["t"].campanha_id == camp_id)
                 and (not termo or termo in util.chave_texto(p["t"].lead.empresa if p["t"].lead else ""))]
    prox_na_situacao = [p for p in prox_base if not situacao or p["situacao"] == situacao]
    contagem_quando = {k: sum(1 for p in prox_na_situacao if fila._no_periodo(p, k, hoje)) for k, _ in fila.PERIODOS}
    prox_no_periodo = [p for p in prox_base if fila._no_periodo(p, quando, hoje)]
    contagem_situacao = {k: sum(1 for p in prox_no_periodo if p["situacao"] == k) for k in fila.SITUACOES}
    prox_filtrados = [p for p in prox_no_periodo if not situacao or p["situacao"] == situacao]

    # ---- Números do topo
    resumo = {
        "email_hoje": mensagens.enviadas_hoje(db, "email"), "email_limite": mensagens.limite_diario(db, "email"),
        "whats_hoje": max(mensagens.whatsapp_hoje_por_numero(db).values(), default=0),
        "whats_limite": mensagens.limite_diario(db, "whatsapp"),
        "falharam": sum(1 for m in todas if m.status == "falhou" and m.criado_em >= desde(periodo)),
        "respostas": sum(1 for m in todas if m.status == "recebida" and m.criado_em >= desde(periodo)),
        "na_fila": sum(1 for m in todas if m.status == "na_fila"),
        "clique": sum(1 for p in proximos if p["situacao"] == "clique" and p["t"].data <= hoje),
    }
    regras = {chave: ler_config(db, chave) for chave in (
        "limite_diario_email", "limite_hora_email", "limite_diario_whatsapp", "limite_hora_whatsapp",
        "limite_diario_campanha", "limite_diario_dominio", "horas_entre_contatos", "horario_envio_inicio",
        "horario_envio_fim", "enviar_email_automatico", "enviar_whatsapp_automatico", "dias_sem_resposta",
        "limite_frios_whatsapp")}
    regras["horas_whatsapp"] = mensagens.horas_entre_contatos(db, "whatsapp")
    regras["horas_email"] = mensagens.horas_entre_contatos(db, "email")
    camp_q = select(Campanha).where(Campanha.arquivada.is_(False)).order_by(Campanha.criado_em.desc()).limit(100)
    camp_q = autorizacao.filtrar(camp_q, usuario, "envios.ver", Campanha.usuario_id)
    pessoas = {u.id: u.nome for u in db.execute(select(Usuario)).scalars()}
    nomes_camp = {c.id: c.nome for c in db.execute(select(Campanha)).scalars()}

    atuais = {"aba": aba, "periodo": periodo, "canal": canal, "status": status, "campanha": str(camp_id or ""),
              "busca": busca.strip(), "lead": str(lead_id or ""), "quando": quando, "situacao": situacao}
    padrao = {"aba": "enviados", "periodo": "7d", "quando": "todos"}

    def url_envios(**mudancas) -> str:
        """Endereço desta tela com os filtros atuais e as mudanças pedidas (valor padrão fica fora do endereço)."""
        params = {k: v for k, v in {**atuais, **mudancas}.items() if v and padrao.get(k) != v}
        return "/envios" + ("?" + urlencode(params) if params else "")

    return tela(request, "envios.html", {
        "resumo": resumo, "regras": regras, "STATUS_ENVIO": STATUS_ENVIO, "aba": aba, "hoje": hoje,
        "filtros": atuais, "url_envios": url_envios, "campanhas": db.execute(camp_q).scalars().all(),
        "lead_filtro": db.get(Lead, lead_id) if lead_id else None, "pessoas": pessoas, "nomes_camp": nomes_camp,
        "leads_por_id": leads_por_id,
        # aba Enviados
        "grupos_enviados": grupos_enviados, "total_enviados": total_enviados, "limite_lista": LIMITE_LISTA,
        "op_periodo": [(k, nome, contagem_periodo[k], "") for k, (nome, _) in PERIODOS.items()],
        "op_status": [(k, nome, contagem_status[k], ponto) for k, (nome, ponto) in SITUACOES_ENVIO.items()
                      if contagem_status[k] or status == k],
        "filtrando_enviados": bool(status or camp_id or termo or canal or periodo != "7d"),
        # aba Próximos envios
        "grupos_proximos": fila._agrupar_por_dia(prox_filtrados[:fila.LIMITE_MOSTRAR], hoje),
        "total_proximos": len(proximos), "limite_mostrar": fila.LIMITE_MOSTRAR,
        "ids_mostrados": [p["t"].id for p in prox_filtrados[:fila.LIMITE_MOSTRAR]],
        "total_prox_filtrados": len(prox_filtrados),
        "op_quando": [(k, nome, contagem_quando[k], "") for k, nome in fila.PERIODOS],
        "op_situacao": [(k, nome, contagem_situacao[k], cor) for k, (nome, cor) in fila.SITUACOES.items()
                        if contagem_situacao[k] or situacao == k],
        "filtrando_proximos": bool(situacao or camp_id or termo or canal or quando != "todos"),
        "canais_do_toque": campanhas.canais_do_toque, "texto_do_canal": campanhas.texto_do_canal,
    })
