"""API externa: webhook do WhatsApp Cloud API (respostas, status e opt-out automático).

Protegida por: token de verificação, assinatura HMAC da Meta (X-Hub-Signature-256) e limite de pedidos.
"""

import hmac
import json
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import func, or_, select

from .. import config, relogio, sdr, trabalhos, util
from ..rotinas import responder_automaticamente, rodada
from ..banco import agora, gravar_config, ler_config_int, sessao
from ..integracoes import whatsapp_cloud
from ..modelos import ComandoWhatsApp, Lead, Mensagem, MensagemWhatsApp, PonteWhatsApp
from ..seguranca import ip_de, limite_api

rotas = APIRouter(prefix="/api")
log = logging.getLogger(__name__)


@rotas.get("/saude")
def saude():
    return {"ok": True}


@rotas.get("/webhooks/whatsapp")
def webhook_verificar(request: Request):
    p = request.query_params
    if (p.get("hub.mode") == "subscribe" and config.WHATSAPP_VERIFY_TOKEN
            and p.get("hub.verify_token") == config.WHATSAPP_VERIFY_TOKEN):
        return PlainTextResponse(p.get("hub.challenge", ""))
    return PlainTextResponse("token inválido", status_code=403)


@rotas.post("/webhooks/whatsapp")
async def webhook_receber(request: Request):
    if not limite_api.registrar(ip_de(request)):
        return JSONResponse({"erro": "muitos pedidos"}, status_code=429)
    corpo = await request.body()
    if not whatsapp_cloud.assinatura_valida(corpo, request.headers.get("x-hub-signature-256", "")):
        return JSONResponse({"erro": "assinatura inválida"}, status_code=403)
    try:
        dados = json.loads(corpo)
    except json.JSONDecodeError:
        return JSONResponse({"erro": "json inválido"}, status_code=400)
    recebidas, status = whatsapp_cloud.ler_webhook(dados)
    with sessao() as db:
        for s in status:
            msg = db.execute(select(Mensagem).where(Mensagem.id_externo == s["id"])).scalars().first()
            if msg and s["status"] in ("delivered", "read", "failed"):
                msg.status = {"delivered": "entregue", "read": "lida", "failed": "falhou"}[s["status"]]
        for r in recebidas:
            telefone = util.normalizar_telefone(r["de"])
            if not telefone:
                continue
            lead = db.execute(select(Lead).where(or_(Lead.chave_whatsapp == telefone, Lead.chave_telefone == telefone))
                              .limit(1)).scalars().first()
            if not lead:
                continue
            analise = sdr.processar_resposta(db, lead, r["texto"], "whatsapp")
            responder_automaticamente(db, lead, "whatsapp", analise)  # API oficial: número único da Meta
    return {"ok": True}


# ---------------------------------------------------------------- Agendador (sistema na nuvem)

def _senha_confere(recebida: str, esperada: str) -> bool:
    return bool(esperada) and hmac.compare_digest(recebida.encode(), esperada.encode())


@rotas.get("/cron")
def cron(request: Request):
    """Chamado a cada minuto pela Vercel Cron (ou cron-job.org) com "Authorization: Bearer CRON_SECRET".
    Faz a rodada do relógio (fila de e-mail, respostas, rotinas de hora em hora) e anda os trabalhos longos."""
    if not config.CRON_SECRET:
        return JSONResponse({"erro": "Falta CRON_SECRET nas variáveis do sistema."}, status_code=503)
    if not _senha_confere(request.headers.get("authorization", "").removeprefix("Bearer ").strip(), config.CRON_SECRET):
        return JSONResponse({"erro": "senha inválida"}, status_code=403)
    # Fase 0 (white label): com o plano Pro, o cron da Vercel chama a cada minuto e o computador da MS vira reserva
    # (?reserva=1): ele só faz a rodada se a nuvem não chamou nos últimos minutos (app/relogio.py).
    quem = relogio.origem(request.headers.get("user-agent", ""), request.query_params.get("reserva") == "1")
    if quem == "nuvem":
        relogio.registrar_nuvem()
    elif quem == "reserva" and relogio.reserva_dispensada():
        return {"rodada": False, "etapas": 0, "reserva": "dispensada"}
    prazo = time.monotonic() + config.SEGUNDOS_POR_RODADA
    resultado = {"rodada": False, "etapas": 0}
    if trabalhos.pegar_trava("rodada", 300):  # duas chamadas ao mesmo tempo não podem enviar o mesmo e-mail
        # (300 s = tempo máximo da função na Vercel: uma rodada demorada nunca roda junto com a seguinte)
        try:
            rodada(None)
            resultado["rodada"] = True
        finally:
            trabalhos.soltar_trava("rodada")
    resultado["etapas"] = trabalhos.rodar_pendentes(prazo)
    from ..modelos import Trabalho

    with sessao() as db:  # o agendador do Windows usa isto: com trabalho na fila, chama a cada minuto mesmo à noite
        resultado["pendentes"] = db.execute(select(func.count(Trabalho.id)).where(
            Trabalho.status.in_(["na_fila", "rodando"]))).scalar() or 0
    return resultado


# ---------------------------------------------------------------- Ponte com o WhatsApp Leads (sistema na nuvem)

def _ponte_autorizada(request: Request) -> bool:
    return config.WHATSAPP_PONTE and _senha_confere(request.headers.get("x-token", ""), config.WHATSAPP_PONTE_TOKEN)


@rotas.get("/ponte/teste")
def ponte_teste(request: Request):
    """Usado pelo ligar_nuvem.bat do WhatsApp Leads para conferir endereço e token."""
    if not _ponte_autorizada(request):
        return JSONResponse({"erro": "token inválido"}, status_code=403)
    return {"ok": True}


@rotas.get("/ponte/midia/{mid:int}")
def ponte_midia(request: Request, mid: int):
    """Imagem de um visual para o computador com o WhatsApp Leads mandar junto com a mensagem (senha da ponte)."""
    from fastapi.responses import Response

    from ..modelos import VisualCampanha

    if not _ponte_autorizada(request):
        return JSONResponse({"erro": "token inválido"}, status_code=403)
    with sessao() as db:
        v = db.get(VisualCampanha, mid)
        if v is None or not v.imagem:
            return JSONResponse({"erro": "imagem não encontrada"}, status_code=404)
        return Response(v.imagem, media_type=v.imagem_tipo or "application/octet-stream",
                        headers={"X-Hash": v.imagem_hash})


@rotas.post("/ponte/arte/{pid:int}")
async def ponte_arte(request: Request, pid: int):
    """A arte do aviso de vencimento que o computador desenhou para a mensagem `pid` da ponte (senha da ponte): fica
    guardada para ir no e-mail do mesmo aviso (renovacao.email_com_arte)."""
    from ..modelos import ArteAviso

    if not _ponte_autorizada(request):
        return JSONResponse({"erro": "token inválido"}, status_code=403)
    dados = await request.body()
    if not dados.startswith(b"\x89PNG") or len(dados) > 3_000_000:
        return JSONResponse({"erro": "imagem inválida"}, status_code=400)
    with sessao() as db:
        item = db.get(PonteWhatsApp, pid)
        if item is None or not item.arte:
            return JSONResponse({"erro": "mensagem não encontrada"}, status_code=404)
        try:
            tarefa_id = int(json.loads(item.arte).get("tarefa") or 0) or None
        except (ValueError, TypeError, AttributeError):
            tarefa_id = None
        existente = db.execute(select(ArteAviso).where(ArteAviso.ponte_id == pid)).scalars().first()
        if existente is not None:
            existente.imagem = dados
        else:
            db.add(ArteAviso(ponte_id=pid, tarefa_id=tarefa_id, imagem=dados))
    return {"ok": True}


@rotas.post("/ponte/troca")
async def ponte_troca(request: Request):
    """O computador com o WhatsApp Leads avisa o status e leva as mensagens que estão esperando."""
    if not _ponte_autorizada(request):
        return JSONResponse({"erro": "token inválido"}, status_code=403)
    try:
        dados = await request.json()
    except ValueError:
        return JSONResponse({"erro": "json inválido"}, status_code=400)
    with sessao() as db:
        _gravar_status(db, dados.get("status") or {})
        envios = []
        # "retirada" antes de devolver: se a resposta se perder, a mensagem NÃO é enviada duas vezes.
        for item in db.execute(select(PonteWhatsApp).where(PonteWhatsApp.status == "aguardando")
                               .order_by(PonteWhatsApp.id).limit(50)).scalars():
            item.status = "retirada"
            envio = {"id": item.id, "telefone": item.telefone, "nome": item.nome, "texto": item.texto,
                     "resposta": item.resposta, "manual": item.manual, "conexao": item.conexao or "principal"}
            if item.arte:  # aviso de vencimento (Renovação): o computador desenha a arte do site com estes dados
                try:
                    envio["arte"] = json.loads(item.arte)
                except ValueError:
                    pass
            if item.midia_id:  # imagem do visual: o computador baixa em /api/ponte/midia/<id> (e guarda pelo hash)
                from ..modelos import VisualCampanha

                v = db.get(VisualCampanha, item.midia_id)
                if v is not None and v.imagem_hash:
                    envio["midia"] = {"id": v.id, "hash": v.imagem_hash, "tipo": v.imagem_tipo}
            envios.append(envio)
        comandos = []
        for c in db.execute(select(ComandoWhatsApp).where(ComandoWhatsApp.status == "aguardando")
                            .order_by(ComandoWhatsApp.id).limit(10)).scalars():
            c.status = "retirado"
            comandos.append({"id": c.id, "acao": c.acao, "dados": json.loads(c.dados or "{}")})
        desde = ler_config_int(db, "wl_ultimo_id", 0)
        desde_conversas = ler_config_int(db, "wl_conv_ultimo_id", 0)
        # rápido com a tela WhatsApp/Conversas aberta, com pedidos ou enquanto as conversas antigas são copiadas
        rapido = comandos or envios or _tela_aberta(db) or ler_config_int(db, "wl_conv_pendente", 0)
        intervalo = 3 if rapido else 30
    return {"desde": desde, "envios": envios, "comandos": comandos, "intervalo": intervalo,
            "desde_conversas": desde_conversas}


CAMPOS_STATUS = ("conectado", "tipo", "estado", "numero", "enviadas_hoje", "limite_diario", "dentro_do_horario",
                 "horario", "estado_codigo", "erro", "qr", "regras", "conexoes",
                 "espera")  # de quantos em quantos segundos o computador dá sinal (1 min de dia, 5 min à noite)


def _gravar_status(db, recebido: dict) -> None:
    status = {k: recebido.get(k) for k in CAMPOS_STATUS}
    status["visto_em"] = agora().isoformat()
    gravar_config(db, "wl_status", status)


def _guardar_conversas(db, conversas: dict) -> None:
    """Cópia das conversas do WhatsApp Leads (todas as mensagens) para a tela Conversas."""
    from datetime import datetime

    mensagens = conversas.get("mensagens") or []
    ids = [int(m["id"]) for m in mensagens]
    existentes = set(db.execute(select(MensagemWhatsApp.id_wl).where(MensagemWhatsApp.id_wl.in_(ids))).scalars()) if ids else set()
    for m in mensagens:
        if int(m["id"]) in existentes:
            continue
        # celular sempre com o 9 (o WhatsApp entrega números antigos sem ele): é a chave da conversa na tela
        telefone = util.com_nono_digito(m.get("telefone", "")) or util.so_digitos(m.get("telefone", ""))
        try:
            criado = datetime.fromisoformat(str(m.get("criado_em", ""))[:19])
        except ValueError:
            criado = agora()
        db.add(MensagemWhatsApp(id_wl=int(m["id"]), telefone=telefone[:20], nome=str(m.get("nome") or "")[:200],
                                conexao=str(m.get("conexao") or "principal")[:40],
                                direcao=str(m.get("direcao", ""))[:10], texto=str(m.get("texto") or ""),
                                status=str(m.get("status") or "")[:20], erro=str(m.get("erro") or "")[:500],
                                origem=str(m.get("origem") or "")[:30], criado_em=criado,
                                lida=m.get("direcao") != "entrada" or m.get("origem") == "historico"))
    for s in conversas.get("status") or []:
        msg = db.execute(select(MensagemWhatsApp).where(MensagemWhatsApp.id_wl == int(s["id"]))).scalars().first()
        if msg and (msg.status != s.get("status") or msg.erro != (s.get("erro") or "")):
            msg.status, msg.erro = str(s.get("status") or "")[:20], str(s.get("erro") or "")[:500]
    if "ultimo_id" in conversas:
        gravar_config(db, "wl_conv_ultimo_id", str(int(conversas["ultimo_id"])))
    gravar_config(db, "wl_conv_pendente", "1" if len(mensagens) >= 300 else "0")


def _tela_aberta(db) -> bool:
    """Alguém está com a tela WhatsApp aberta (ela se atualiza a cada 3 s)? Então a ponte troca a cada 3 s."""
    from datetime import datetime

    from ..banco import ler_config

    try:
        return (agora() - datetime.fromisoformat(ler_config(db, "wl_tela_vista_em"))).total_seconds() < 20
    except ValueError:
        return False


@rotas.post("/ponte/retorno")
async def ponte_retorno(request: Request):
    """O computador devolve o id de cada mensagem na fila de lá e as novidades (respostas, status, quem saiu)."""
    if not _ponte_autorizada(request):
        return JSONResponse({"erro": "token inválido"}, status_code=403)
    try:
        dados = await request.json()
    except ValueError:
        return JSONResponse({"erro": "json inválido"}, status_code=400)
    with sessao() as db:
        for c in dados.get("confirmados", []):
            item = db.get(PonteWhatsApp, int(c.get("id", 0)))
            if item is None:
                continue
            msg = db.execute(select(Mensagem).where(Mensagem.modo == "whatsapp-leads",
                                                    Mensagem.id_externo == f"p{item.id}")).scalars().first()
            if c.get("erro"):
                item.status, item.erro = "erro", str(c["erro"])[:500]
                if msg:
                    msg.status, msg.erro = "falhou", item.erro
            else:
                item.status, item.id_wl = "na_fila", str(c.get("id_wl", ""))
                if msg:
                    msg.id_externo = item.id_wl
        for c in dados.get("comandos") or []:
            comando = db.get(ComandoWhatsApp, int(c.get("id") or 0))
            if comando:
                comando.status, comando.erro = ("erro", str(c["erro"])[:500]) if c.get("erro") else ("feito", "")
        if dados.get("status"):  # status logo depois dos pedidos (ex.: QR code novo)
            _gravar_status(db, dados["status"])
        if dados.get("conversas"):
            _guardar_conversas(db, dados["conversas"])
        novidades = dados.get("novidades") or {}
        resultado = sdr.aplicar_novidades_whatsapp(db, novidades) if novidades else {}
        if "ultimo_id" in novidades:
            gravar_config(db, "wl_ultimo_id", str(int(novidades["ultimo_id"])))
    return {"ok": True, **resultado}
