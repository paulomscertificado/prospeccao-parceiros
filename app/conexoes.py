"""Números de WhatsApp: cada usuário conecta o seu; o dono (ou o administrador) pode compartilhar.

Os números ficam ligados no computador da MS (WhatsApp Leads, um "conector" por número, identificado por
um id: "principal" = o número da MS; "u<id do usuário>" = o número daquele usuário). Aqui fica quem é o
dono de cada número e com quem ele está compartilhado; a situação (conectado, QR code) vem pela ponte.

Regras:
- cada pessoa usa o próprio número e os números compartilhados com ela; o administrador vê e controla todos;
- a IA SDR envia pelo número do responsável pelo lead (o próprio dele ou um compartilhado com ele);
  sem número conectado, o envio espera e a pessoa é avisada para conectar.
"""

import json

from sqlalchemy import select

from .integracoes import whatsapp_leads
from .modelos import Campanha, ConexaoWhatsApp, Lead, Tarefa, Usuario

PRINCIPAL = "principal"


class SemNumero(Exception):
    """Mensagem pronta para mostrar na tela."""


def id_do_usuario(usuario_id: int) -> str:
    return f"u{usuario_id}"


def garantir_principal(db) -> ConexaoWhatsApp:
    c = db.get(ConexaoWhatsApp, PRINCIPAL)
    if c is None:
        dono = db.execute(select(Usuario).where(Usuario.perfil == "admin").order_by(Usuario.id)).scalars().first()
        c = ConexaoWhatsApp(id=PRINCIPAL, nome="Número principal da MS", dono_id=dono.id if dono else None)
        db.add(c)
        db.flush()
    return c


def todas(db) -> list[ConexaoWhatsApp]:
    garantir_principal(db)
    return list(db.execute(select(ConexaoWhatsApp).order_by(ConexaoWhatsApp.criado_em)).scalars())


def compartilhada_com(c: ConexaoWhatsApp) -> list[int]:
    try:
        return [int(i) for i in json.loads(c.compartilhada_com or "[]")]
    except (ValueError, TypeError):
        return []


def pode_gerenciar(usuario: Usuario, c: ConexaoWhatsApp) -> bool:
    """Conectar, pausar, desligar e compartilhar: o dono e o administrador."""
    return usuario.perfil == "admin" or c.dono_id == usuario.id


def pode_usar(usuario: Usuario, c: ConexaoWhatsApp) -> bool:
    """Ver as conversas e enviar por este número."""
    return pode_gerenciar(usuario, c) or c.compartilhada_todos or usuario.id in compartilhada_com(c)


def acessiveis(db, usuario: Usuario) -> list[ConexaoWhatsApp]:
    return [c for c in todas(db) if pode_usar(usuario, c)]


def minha(db, usuario: Usuario, criar: bool = False) -> ConexaoWhatsApp | None:
    c = db.get(ConexaoWhatsApp, id_do_usuario(usuario.id))
    if c is None and criar:
        c = ConexaoWhatsApp(id=id_do_usuario(usuario.id), nome=f"WhatsApp de {usuario.nome}", dono_id=usuario.id)
        db.add(c)
        db.flush()
    return c


def situacao(id_conexao: str, base: dict | None = None) -> dict:
    """Situação de UM número: {"disponivel" (computador ligado), "conectado", "estado", "estado_codigo", "numero",
    "erro", "qr", "enviadas_hoje"}."""
    base = base if base is not None else whatsapp_leads.status()
    if not base.get("disponivel"):
        return {"disponivel": False, "conectado": False, "estado": "Computador desligado", "estado_codigo": "",
                "erro": base.get("erro", ""), "qr": ""}
    lista = base.get("conexoes")
    if lista is None and id_conexao == PRINCIPAL:  # versão antiga do WhatsApp Leads (um número só)
        return {**base, "disponivel": True}
    dados = (lista or {}).get(id_conexao)
    if not dados:
        return {"disponivel": True, "conectado": False, "estado": "Não conectado", "estado_codigo": "desconectado",
                "erro": "", "qr": ""}
    return {"disponivel": True, **dados}


def responsavel(db, lead: Lead | None = None, usuario: Usuario | None = None, tarefa: Tarefa | None = None) -> Usuario | None:
    """De quem é o envio: o vendedor/funcionário do lead; senão quem está agindo, quem recebeu a tarefa, o dono
    da campanha e, por último, o dono do número principal."""
    for uid in (lead.vendedor_id if lead else None, usuario.id if usuario else None,
                tarefa.usuario_id if tarefa else None):
        if uid:
            return db.get(Usuario, uid)
    if tarefa and tarefa.campanha_id:
        camp = db.get(Campanha, tarefa.campanha_id)
        if camp and camp.usuario_id:
            return db.get(Usuario, camp.usuario_id)
    principal = garantir_principal(db)
    return db.get(Usuario, principal.dono_id) if principal.dono_id else None


def para_enviar(db, quem: Usuario | None) -> str:
    """Número por onde sai o envio de `quem`: o próprio, se conectado; senão um compartilhado com ele e conectado."""
    if quem is None:
        raise SemNumero("Este lead não tem responsável. Defina o vendedor/funcionário do lead.")
    base = whatsapp_leads.status()
    if not base.get("disponivel"):
        raise SemNumero(base.get("erro") or "O computador com o WhatsApp Leads está desligado.")
    proprio = minha(db, quem)
    if proprio and situacao(proprio.id, base).get("conectado"):
        return proprio.id
    outros = sorted((c for c in acessiveis(db, quem) if c.id != (proprio.id if proprio else "")),
                    key=lambda c: (c.id != PRINCIPAL, c.criado_em))
    for c in outros:
        if situacao(c.id, base).get("conectado"):
            return c.id
    raise SemNumero(f"{quem.nome} ainda não conectou o WhatsApp. Conecte em WhatsApp > Meu WhatsApp para enviar "
                    "(ou peça ao administrador para compartilhar um número).")


def para_o_menu(db, usuario: Usuario) -> dict:
    """Bolinha do item WhatsApp do menu: o número da própria pessoa (ou o primeiro que ela pode usar)."""
    base = whatsapp_leads.status()
    proprio = minha(db, usuario)
    alvo = proprio or next(iter(acessiveis(db, usuario)), None)
    if alvo is None:
        return {"disponivel": base.get("disponivel", False), "conectado": False, "estado_codigo": "sem_numero"}
    return situacao(alvo.id, base)
