"""Aplicação web: junta as rotas, a segurança e as rotinas automáticas."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import arquivo_env, config
from .banco import criar_tabelas, preparar_banco_na_nuvem, sessao
from .seguranca import PrecisaLogin, SemPermissao
from .web import PASTA, avisar, tela

log = logging.getLogger(__name__)


async def _relogio():
    """Fila (1 min), respostas por e-mail (5 min), vencimentos e fim de cadências (1 h). Ver app/rotinas.py."""
    from .rotinas import rodada

    numero = 0
    while True:
        await asyncio.to_thread(rodada, numero)
        numero += 1
        await asyncio.sleep(60)


def destravar_buscas():
    """Buscas antigas (de antes dos trabalhos em etapas) que ficaram pela metade não terminam mais."""
    from sqlalchemy import select, update

    from .modelos import Busca, Trabalho

    with sessao() as db:
        com_trabalho = select(Trabalho.ref_id).where(Trabalho.tipo == "busca", Trabalho.status == "na_fila")
        db.execute(update(Busca).where(Busca.status.in_(["na fila", "buscando", "enriquecendo"]), Busca.id.not_in(com_trabalho))
                   .values(status="erro", erro="A busca foi interrompida porque o sistema foi fechado. Faça a busca de novo."))


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    if config.NA_NUVEM:
        yield  # na nuvem: banco preparado no primeiro pedido e relógio pelo agendador (/api/cron)
        return
    from . import trabalhos

    criar_tabelas()
    destravar_buscas()
    trabalhos.retomar_interrompidos()
    tarefa = asyncio.create_task(_relogio())
    yield
    tarefa.cancel()


app = FastAPI(title="Prospecção de Parceiros – MS Certificação Digital", lifespan=ciclo_de_vida,
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY, session_cookie="ms_sessao",
                   max_age=12 * 60 * 60, same_site="lax", https_only=config.PRODUCAO)
app.mount("/static", StaticFiles(directory=str(PASTA / "static")), name="static")


@app.middleware("http")
async def cabecalhos_de_seguranca(request: Request, chamar_proximo):
    if config.NA_NUVEM:
        await asyncio.to_thread(preparar_banco_na_nuvem)
        await asyncio.to_thread(arquivo_env.carregar_do_banco)  # e-mail salvo pela tela (vale para todas as cópias)
    resposta = await chamar_proximo(request)
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if config.PRODUCAO:
        resposta.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resposta


@app.exception_handler(PrecisaLogin)
async def _precisa_login(request: Request, erro: PrecisaLogin):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"erro": "Faça login de novo."}, status_code=401)
    if str(erro):
        avisar(request, str(erro), "alerta")
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(SemPermissao)
async def _sem_permissao(request: Request, erro: SemPermissao):
    texto = str(erro) or "Você não tem permissão para isso."
    if request.url.path.startswith("/api/") or request.headers.get("x-csrf-token"):
        return JSONResponse({"erro": texto}, status_code=403)
    return tela(request, "erro.html", {"titulo": "Acesso não permitido", "mensagem": texto}, status_code=403)


@app.exception_handler(404)
async def _nao_encontrado(request: Request, erro):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"erro": "Não encontrado."}, status_code=404)
    return tela(request, "erro.html", {"titulo": "Página não encontrada",
                                       "mensagem": "O endereço não existe ou o registro foi apagado."}, status_code=404)


from .rotas import admin, agenda, api, auth, comercial, conversas, leads, painel, portal, sdr, whatsapp  # noqa: E402

for modulo in (auth, painel, sdr, leads, agenda, comercial, admin, conversas, whatsapp, portal, api):
    app.include_router(modulo.rotas)
