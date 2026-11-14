"""Relógio das filas: quem chama o /api/cron a cada minuto (Fase 0 do plano white label, 13/11/2026).

Até agora quem chama é o Agendador do Windows do computador da MS (dados/chamar_cron.ps1): o cron da Vercel só chama
1 vez por dia, porque o plano gratuito (Hobby) não deixa mais que isso. Com o plano Pro, o cron da Vercel chama a cada
minuto (vercel.json) e o computador vira só RESERVA: ele chama com ?reserva=1 e a rodada só acontece se a nuvem não
chamou nos últimos 3 minutos. Assim a troca não deixa buraco nenhum, e o portão da Fase 0 fica medido: 7 dias
seguidos sem a reserva precisar rodar.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .banco import agora, gravar_config, ler_config_json, sessao

CHAVE = "relogio_filas"
ESPERA_DA_RESERVA = timedelta(minutes=3)  # a nuvem chamou há menos que isso: a reserva não roda
# "A nuvem já chama a cada minuto" = 3 intervalos seguidos entre 30 s e 2 min. Uma chamada repetida (o mesmo aviso
# entregue duas vezes, segundos depois) não conta, senão o cron diário do plano gratuito pareceria "a cada minuto".
INTERVALO_MINIMO = timedelta(seconds=30)
INTERVALO_MAXIMO = timedelta(minutes=2)
INTERVALOS_PARA_LIGAR = 3
NUVEM_ATRASADA = timedelta(minutes=10)    # a partir daí vira aviso por e-mail (alertas.problemas_agora)
DIAS_DO_PORTAO = 7


def _data(texto) -> datetime | None:
    try:
        return datetime.fromisoformat(texto) if texto else None
    except (TypeError, ValueError):
        return None


def origem(user_agent: str, reserva: bool) -> str:
    """"nuvem" (o cron da Vercel, que se apresenta como vercel-cron/1.0), "reserva" (o computador) ou "outro"."""
    if "vercel-cron" in (user_agent or "").lower():
        return "nuvem"
    return "reserva" if reserva else "outro"


def estado(db) -> dict:
    return ler_config_json(db, CHAVE, {}) or {}


def registrar_nuvem() -> None:
    """O cron da Vercel chamou. Depois de 3 intervalos seguidos de cerca de 1 minuto, marca desde quando a nuvem chama
    a cada minuto (o cron diário do plano gratuito nunca faz isso)."""
    with sessao() as db:
        e = estado(db)
        agora_ = agora()
        anterior = _data(e.get("nuvem_em"))
        if anterior is not None and INTERVALO_MINIMO <= agora_ - anterior < INTERVALO_MAXIMO:
            e["nuvem_seguidas"] = int(e.get("nuvem_seguidas") or 0) + 1
        elif anterior is None or agora_ - anterior >= INTERVALO_MAXIMO:
            e["nuvem_seguidas"] = 0  # (chamada repetida, segundos depois: não conta nem zera)
        if not e.get("nuvem_desde") and int(e.get("nuvem_seguidas") or 0) >= INTERVALOS_PARA_LIGAR:
            e["nuvem_desde"] = agora_.isoformat(timespec="seconds")
        e["nuvem_em"] = agora_.isoformat(timespec="seconds")
        gravar_config(db, CHAVE, e)


def reserva_dispensada() -> bool:
    """O computador chamou como reserva: True se a nuvem chamou há pouco (a rodada não precisa dele). Quando a reserva
    precisa rodar depois que a nuvem já chamava a cada minuto, conta a vez: é o que o portão da Fase 0 mede."""
    with sessao() as db:
        e = estado(db)
        agora_ = agora()
        nuvem = _data(e.get("nuvem_em"))
        if nuvem is not None and agora_ - nuvem < ESPERA_DA_RESERVA:
            return True
        if e.get("nuvem_desde"):
            e["reserva_vezes"] = int(e.get("reserva_vezes") or 0) + 1
            e["reserva_em"] = agora_.isoformat(timespec="seconds")
            gravar_config(db, CHAVE, e)
    return False


def nuvem_atrasada(db) -> datetime | None:
    """A última chamada da nuvem, se ela já chamava a cada minuto e está parada há mais de 10 minutos."""
    e = estado(db)
    if not e.get("nuvem_desde"):
        return None
    ultima = _data(e.get("nuvem_em"))
    return ultima if ultima is not None and agora() - ultima > NUVEM_ATRASADA else None


def resumo(db) -> dict:
    """Para a tela Configurações > Integrações (quadro dos avisos)."""
    e = estado(db)
    r = {"nuvem_em": _data(e.get("nuvem_em")), "nuvem_desde": _data(e.get("nuvem_desde")),
         "reserva_vezes": int(e.get("reserva_vezes") or 0), "reserva_em": _data(e.get("reserva_em"))}
    if r["nuvem_desde"] is not None:
        inicio = max(d for d in (r["nuvem_desde"], r["reserva_em"]) if d is not None)
        r["dias_sem_reserva"] = max(0, (agora() - inicio).days)
        r["portao_ok"] = r["dias_sem_reserva"] >= DIAS_DO_PORTAO
    return r
