"""Segurança: senhas com hash, criptografia de dados sensíveis, sessão, CSRF, limites de tentativas,
permissões por perfil e registro de auditoria (logs)."""

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .banco import agora, obter_db
from .modelos import LogAuditoria, Usuario

ITERACOES = 310_000


# ---------------------------------------------------------------- Senhas

def resumir_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    resumo = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, ITERACOES)
    return f"pbkdf2_sha256${ITERACOES}${sal.hex()}${resumo.hex()}"


def senha_confere(senha: str, guardado: str) -> bool:
    try:
        _, iteracoes, sal, resumo = guardado.split("$")
        calculado = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal), int(iteracoes))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(calculado.hex(), resumo)


def problema_na_senha(senha: str) -> str:
    if len(senha) < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    if senha.isdigit() or senha.isalpha():
        return "Use letras e números na senha."
    return ""


# ---------------------------------------------------------------- Criptografia (ex.: chave Pix do parceiro)

_fernet = Fernet(config.CHAVE_CRIPTOGRAFIA.encode())


def criptografar(texto: str) -> str:
    return _fernet.encrypt(texto.encode("utf-8")).decode() if texto else ""


def descriptografar(texto: str) -> str:
    if not texto:
        return ""
    try:
        return _fernet.decrypt(texto.encode()).decode("utf-8")
    except InvalidToken:
        return "(não foi possível ler: a chave de criptografia mudou)"


# ---------------------------------------------------------------- Limite de tentativas (rate limiting)

class Limitador:
    """Conta eventos por chave numa janela de tempo (memória do servidor)."""

    def __init__(self, maximo: int, janela_seg: int):
        self.maximo, self.janela = maximo, janela_seg
        self._eventos: dict[str, deque] = defaultdict(deque)
        self._trava = threading.Lock()

    def _limpar(self, fila: deque, agora_s: float):
        while fila and fila[0] <= agora_s - self.janela:
            fila.popleft()

    def bloqueado(self, chave: str) -> bool:
        with self._trava:
            fila = self._eventos[chave]
            self._limpar(fila, time.monotonic())
            return len(fila) >= self.maximo

    def registrar(self, chave: str) -> bool:
        """Registra o evento. Devolve False se passou do limite."""
        with self._trava:
            agora_s = time.monotonic()
            fila = self._eventos[chave]
            self._limpar(fila, agora_s)
            if len(fila) >= self.maximo:
                return False
            fila.append(agora_s)
            return True

    def zerar(self, chave: str):
        with self._trava:
            self._eventos.pop(chave, None)


limite_login = Limitador(maximo=5, janela_seg=15 * 60)      # 5 senhas erradas a cada 15 min
limite_pedidos = Limitador(maximo=240, janela_seg=60)       # pedidos de alteração por minuto, por IP
limite_api = Limitador(maximo=120, janela_seg=60)           # webhooks e API


def ip_de(request: Request) -> str:
    if config.PRODUCAO:
        encaminhado = request.headers.get("x-forwarded-for", "")
        if encaminhado:
            return encaminhado.split(",")[0].strip()
    return request.client.host if request.client else "?"


# ---------------------------------------------------------------- Sessão e CSRF

class PrecisaLogin(Exception):
    pass


class SemPermissao(Exception):
    pass


def token_csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def verificar_csrf(request: Request):
    """Dependência dos formulários: confere o token CSRF em todo POST."""
    if request.method != "POST":
        return
    esperado = request.session.get("csrf", "")
    recebido = request.headers.get("x-csrf-token", "")
    if not recebido:
        form = await request.form()
        recebido = str(form.get("csrf", ""))
    if not esperado or not hmac.compare_digest(esperado, recebido):
        raise SemPermissao("O formulário expirou. Recarregue a página e tente de novo.")
    if not limite_pedidos.registrar(ip_de(request)):
        raise SemPermissao("Muitas ações em pouco tempo. Espere um minuto e tente de novo.")


def entrar(request: Request, usuario: Usuario):
    request.session.clear()
    request.session.update({
        "usuario_id": usuario.id,
        "versao": usuario.versao_sessao,
        "ultimo_uso": int(time.time()),
        "csrf": secrets.token_urlsafe(32),
    })


def usuario_logado(request: Request, db: Session = Depends(obter_db)) -> Usuario:
    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        raise PrecisaLogin()
    ultimo = request.session.get("ultimo_uso", 0)
    if time.time() - ultimo > config.MINUTOS_SESSAO_OCIOSA * 60:
        request.session.clear()
        raise PrecisaLogin("Sua sessão expirou. Entre de novo.")
    usuario = db.get(Usuario, usuario_id)
    if not usuario or not usuario.ativo or usuario.versao_sessao != request.session.get("versao"):
        request.session.clear()
        raise PrecisaLogin()
    request.session["ultimo_uso"] = int(time.time())
    request.state.usuario = usuario
    return usuario


def exigir(*perfis: str):
    """Dependência: só deixa passar os perfis informados."""

    def _checar(usuario: Usuario = Depends(usuario_logado)) -> Usuario:
        if usuario.perfil not in perfis:
            raise SemPermissao("Seu perfil não tem acesso a esta parte do sistema.")
        return usuario

    return _checar


EQUIPE = ("admin", "gestor", "funcionario", "vendedor")
GESTAO = ("admin", "gestor")
equipe = exigir(*EQUIPE)
gestao = exigir(*GESTAO)
admin = exigir("admin")
ferramentas = exigir(*config.PERFIS_FERRAMENTAS)  # Funcionário MS também usa (o vendedor não)
parceiro = exigir("parceiro")


def ve_tudo(usuario: Usuario) -> bool:
    return usuario.perfil in GESTAO


# ---------------------------------------------------------------- Auditoria

def registrar_log(db: Session, usuario: Usuario | None, acao: str, entidade: str = "",
                  entidade_id: int | None = None, detalhes: str = "", request: Request | None = None):
    db.add(LogAuditoria(
        usuario_id=usuario.id if usuario else None,
        usuario_nome=usuario.nome if usuario else "sistema",
        acao=acao, entidade=entidade, entidade_id=entidade_id, detalhes=detalhes[:2000],
        ip=ip_de(request) if request else "", criado_em=agora(),
    ))


def existe_usuario(db: Session) -> bool:
    return db.execute(select(Usuario.id).limit(1)).first() is not None


def marcar_login(db: Session, usuario: Usuario):
    usuario.ultimo_login = datetime.now().replace(microsecond=0)
