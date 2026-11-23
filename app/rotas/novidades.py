"""O que o navegador pergunta de tempos em tempos para os avisos como no WhatsApp (app/novidades.py e
static/notificacoes.js; pedido da Maria em 23/11/2026): os números vermelhos do menu e as mensagens e respostas que
chegaram depois da última olhada. Só a equipe (o portal do parceiro não tem esses avisos)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import novidades
from ..banco import obter_db
from ..modelos import Usuario
from ..seguranca import usuario_logado

rotas = APIRouter()


@rotas.get("/novidades")
def novidades_do_navegador(c: int = -1, o: int = -1, n: int = -1, usuario: Usuario = Depends(usuario_logado),
                           db: Session = Depends(obter_db)):
    if usuario.perfil == "parceiro":
        return {"contadores": {}, "ultimos": {}, "novas": []}
    desde = {chave: valor for chave, valor in (("c", c), ("o", o), ("n", n)) if valor >= 0}
    return novidades.resumo(db, usuario, desde)
