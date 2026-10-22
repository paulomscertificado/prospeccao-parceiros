"""Trabalhos longos feitos em etapas curtas (montar campanha, buscar empresas, personalizar com IA).

Por quê: na nuvem (Vercel) cada pedido tem tempo máximo e nada roda "em segundo plano" depois da resposta.
Então cada trabalho guarda no banco o ponto onde parou (campo `estado`, em JSON) e anda um pedaço por vez:
- neste computador: uma linha de execução própria roda as etapas até o fim, logo depois do clique;
- na nuvem: o agendador chama /api/cron a cada minuto, e cada chamada anda alguns minutos de trabalho.
Se a nuvem cortar uma chamada no meio, a trava vence sozinha e o trabalho continua da última etapa salva.

Cada tipo registra uma função `etapa(ref_id, usuario_id, estado, prazo) -> bool` (True = terminou) que
altera `estado` e para assim que `time.monotonic()` passar do `prazo`, e uma função `erro(ref_id, texto)`.
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from . import config
from .banco import agora, sessao
from .modelos import Trabalho, Trava

log = logging.getLogger(__name__)

TIPOS: dict[str, tuple] = {}  # tipo -> (etapa, erro)
SEGUNDOS_POR_ETAPA_LOCAL = 120


def tipo(nome: str, ao_falhar):
    """Decorador: registra a função de etapa de um tipo de trabalho."""
    def registrar(funcao):
        TIPOS[nome] = (funcao, ao_falhar)
        return funcao
    return registrar


# ---------------------------------------------------------------- Travas

def pegar_trava(nome: str, segundos: int) -> bool:
    """True se conseguiu a trava (ninguém mais está fazendo isso). Ela vence sozinha depois de `segundos`."""
    agora_ = datetime.now()
    ate = agora_ + timedelta(seconds=segundos)
    with sessao() as db:
        if db.execute(update(Trava).where(Trava.nome == nome, Trava.ate < agora_).values(ate=ate)).rowcount:
            return True
    try:
        with sessao() as db:
            db.add(Trava(nome=nome, ate=ate))
        return True
    except IntegrityError:
        return False  # já existe e ainda vale: outra cópia está trabalhando


def soltar_trava(nome: str) -> None:
    with sessao() as db:
        db.execute(update(Trava).where(Trava.nome == nome).values(ate=datetime(2000, 1, 1)))


# ---------------------------------------------------------------- Trabalhos

def iniciar(tipo_: str, ref_id: int, usuario_id: int | None = None, estado: dict | None = None) -> int:
    """Põe o trabalho na fila. Neste computador já começa na hora; na nuvem, o agendador pega em até 1 minuto."""
    with sessao() as db:
        t = Trabalho(tipo=tipo_, ref_id=ref_id, usuario_id=usuario_id, estado=json.dumps(estado or {}))
        db.add(t)
        db.flush()
        trabalho_id = t.id
    if not config.NA_NUVEM:
        threading.Thread(target=_ate_o_fim, args=(trabalho_id,), daemon=True, name=f"{tipo_}-{ref_id}").start()
    return trabalho_id


def _ate_o_fim(trabalho_id: int) -> None:
    while executar(trabalho_id, SEGUNDOS_POR_ETAPA_LOCAL) == "continua":
        pass


def executar(trabalho_id: int, segundos: float) -> str:
    """Anda o trabalho por até `segundos`. Devolve "continua", "feito", "erro" ou "ocupado" (outra cópia está nele)."""
    nome_trava = f"trabalho:{trabalho_id}"
    if not pegar_trava(nome_trava, int(segundos) + 120):
        return "ocupado"
    try:
        with sessao() as db:
            t = db.get(Trabalho, trabalho_id)
            if t is None or t.status != "na_fila":
                return t.status if t else "erro"
            tipo_, ref_id, usuario_id, estado = t.tipo, t.ref_id, t.usuario_id, json.loads(t.estado or "{}")
        etapa, ao_falhar = TIPOS[tipo_]
        try:
            terminou = etapa(ref_id, usuario_id, estado, time.monotonic() + segundos)
            novo_status, erro = ("feito" if terminou else "na_fila"), ""
        except Exception as e:  # noqa: BLE001 - um trabalho com erro não pode travar os outros
            log.exception("Erro no trabalho %s (%s %s)", trabalho_id, tipo_, ref_id)
            novo_status, erro = "erro", str(e)[:500] or e.__class__.__name__
            try:
                ao_falhar(ref_id, erro)
            except Exception:  # noqa: BLE001
                log.exception("Erro ao registrar a falha do trabalho %s", trabalho_id)
        with sessao() as db:
            t = db.get(Trabalho, trabalho_id)
            t.estado, t.status, t.erro = json.dumps(estado, ensure_ascii=False), novo_status, erro
            t.etapas += 1
            t.atualizado_em = agora()
        return "continua" if novo_status == "na_fila" else novo_status
    finally:
        soltar_trava(nome_trava)


def rodar_pendentes(prazo: float) -> int:
    """Na nuvem (agendador): anda os trabalhos da fila até o prazo. Devolve quantas etapas rodaram."""
    rodadas = 0
    with sessao() as db:
        ids = list(db.execute(select(Trabalho.id).where(Trabalho.status == "na_fila").order_by(Trabalho.id)).scalars())
    for trabalho_id in ids:
        while (resta := prazo - time.monotonic()) > 10:
            resultado = executar(trabalho_id, resta - 5)
            rodadas += 1
            if resultado != "continua":
                break
    return rodadas


def retomar_interrompidos() -> None:
    """Neste computador: trabalhos que estavam rodando quando o sistema foi fechado continuam de onde pararam."""
    with sessao() as db:
        ids = list(db.execute(select(Trabalho.id).where(Trabalho.status == "na_fila")).scalars())
    for trabalho_id in ids:
        threading.Thread(target=_ate_o_fim, args=(trabalho_id,), daemon=True, name=f"trabalho-{trabalho_id}").start()


def em_lotes(itens: list, inicio: int, tamanho: int, prazo: float):
    """Percorre `itens` a partir de `inicio`, de `tamanho` em `tamanho`, enquanto houver tempo.
    Devolve (lote, próximo_inicio) a cada volta."""
    i = inicio
    while i < len(itens) and time.monotonic() < prazo:
        lote = itens[i:i + tamanho]
        yield lote, i + len(lote)
        i += len(lote)
