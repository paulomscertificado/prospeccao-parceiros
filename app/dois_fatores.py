"""Verificação em 2 etapas: depois da senha, o código de 6 números de um app no celular (Google Authenticator,
Microsoft Authenticator...). Obrigatória para administrador e gestor (config.EXIGIR_2FA).

- O segredo fica criptografado no banco (usuarios.totp_segredo); o código muda a cada 30 segundos (TOTP, RFC 6238).
- Um código já usado não vale de novo (usuarios.totp_ultimo_passo).
- 8 códigos de recuperação de uso único, para quem perder o celular (guardados só como resumo).
- "Não pedir neste computador por 30 dias": cookie assinado, que deixa de valer quando o 2FA é zerado.
"""

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config

PASSO_SEG = 30
DIGITOS = 6
PERFIS_OBRIGADOS = ("admin", "gestor")
EMISSOR = "MS Prospeccao"  # sem acento: alguns apps autenticadores erram com acentos no QR
COOKIE_APARELHO = "ms_aparelho"
DIAS_APARELHO = 30
_LETRAS_RECUPERACAO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O e 1/I, que se confundem


def precisa(usuario) -> bool:
    """Pede o código no login: obrigatório para admin/gestor, e para quem já ativou."""
    if not config.EXIGIR_2FA:
        return False
    if usuario.perfil in PERFIS_OBRIGADOS or usuario.totp_ativo:
        return True
    from . import autorizacao  # quem recebeu poder de administrar (papel ou exceção) também precisa

    return any(autorizacao.pode(usuario, p) for p in autorizacao.SENSIVEIS)


def novo_segredo() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def passo_atual(momento: float | None = None) -> int:
    return int((time.time() if momento is None else momento) // PASSO_SEG)


def codigo(segredo: str, passo: int) -> str:
    chave = base64.b32decode(segredo)
    resumo = hmac.new(chave, struct.pack(">Q", passo), hashlib.sha1).digest()
    pos = resumo[-1] & 0x0F
    numero = struct.unpack(">I", resumo[pos:pos + 4])[0] & 0x7FFFFFFF
    return str(numero % 10 ** DIGITOS).zfill(DIGITOS)


def conferir(segredo: str, digitado: str, ultimo_passo: int = 0) -> int | None:
    """Passo do código certo (aceita 30 s antes ou depois, para celular com relógio um pouco errado), ou None.
    Código de um passo já usado não vale de novo."""
    digitado = "".join(c for c in (digitado or "") if c.isdigit())
    if len(digitado) != DIGITOS or not segredo:
        return None
    agora = passo_atual()
    for passo in (agora, agora - 1, agora + 1):
        if passo > (ultimo_passo or 0) and hmac.compare_digest(codigo(segredo, passo), digitado):
            return passo
    return None


def link_do_app(segredo: str, email: str) -> str:
    rotulo = quote(f"{EMISSOR}:{email}")
    return f"otpauth://totp/{rotulo}?secret={segredo}&issuer={quote(EMISSOR)}&digits={DIGITOS}&period={PASSO_SEG}"


def qr_svg(texto: str) -> str:
    import segno

    # omitsize: o SVG leva viewBox e encolhe/estica inteiro na tela (com width/height fixos, o CSS cortava o código);
    # borda de 4 módulos e preto puro: o mínimo que os apps de autenticação leem com folga
    return segno.make(texto, error="m").svg_inline(scale=5, border=4, dark="#000000", light="#ffffff", omitsize=True)


def segredo_em_grupos(segredo: str) -> str:
    return " ".join(segredo[i:i + 4] for i in range(0, len(segredo), 4))


# ---------------------------------------------------------------- Códigos de recuperação

def _resumo(codigo_rec: str) -> str:
    limpo = "".join(c for c in codigo_rec.upper() if c.isalnum())
    return hmac.new(config.SECRET_KEY.encode(), f"recuperacao:{limpo}".encode(), hashlib.sha256).hexdigest()


def novos_codigos_de_recuperacao(quantos: int = 8) -> tuple[list[str], str]:
    """(códigos para mostrar UMA vez, texto para guardar no banco: só os resumos)."""
    codigos = []
    for _ in range(quantos):
        texto = "".join(secrets.choice(_LETRAS_RECUPERACAO) for _ in range(8))
        codigos.append(f"{texto[:4]}-{texto[4:]}")
    return codigos, json.dumps([_resumo(c) for c in codigos])


def codigos_restantes(usuario) -> int:
    try:
        return len(json.loads(usuario.totp_recuperacao or "[]"))
    except ValueError:
        return 0


def usar_codigo_de_recuperacao(usuario, digitado: str) -> bool:
    """Confere e gasta um código de recuperação (cada um vale uma vez)."""
    try:
        guardados = json.loads(usuario.totp_recuperacao or "[]")
    except ValueError:
        return False
    alvo = _resumo(digitado or "")
    for i, r in enumerate(guardados):
        if hmac.compare_digest(r, alvo):
            usuario.totp_recuperacao = json.dumps(guardados[:i] + guardados[i + 1:])
            return True
    return False


def ativar(usuario, segredo: str, passo: int) -> list[str]:
    """Liga o 2FA da pessoa e devolve os códigos de recuperação (mostrar uma vez só)."""
    from .seguranca import criptografar

    codigos, resumos = novos_codigos_de_recuperacao()
    usuario.totp_segredo = criptografar(segredo)
    usuario.totp_ativo = True
    usuario.totp_ultimo_passo = passo
    usuario.totp_recuperacao = resumos
    usuario.versao_2fa = (usuario.versao_2fa or 1) + 1
    return codigos


def zerar(usuario) -> None:
    """Desliga o 2FA (celular perdido): no próximo login a pessoa configura de novo. Derruba as sessões abertas."""
    usuario.totp_segredo, usuario.totp_ativo, usuario.totp_ultimo_passo, usuario.totp_recuperacao = "", False, 0, ""
    usuario.versao_2fa = (usuario.versao_2fa or 1) + 1
    usuario.versao_sessao = (usuario.versao_sessao or 1) + 1


def segredo_de(usuario) -> str:
    from .seguranca import descriptografar

    texto = descriptografar(usuario.totp_segredo or "")
    return "" if texto.startswith("(não foi possível") else texto


# ---------------------------------------------------------------- Computador confiável

def _assinador() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SECRET_KEY, salt="aparelho-2fa")


def marca_do_aparelho(usuario) -> str:
    return _assinador().dumps({"u": usuario.id, "v": usuario.versao_2fa or 1})


def aparelho_confiavel(request, usuario) -> bool:
    marca = request.cookies.get(COOKIE_APARELHO, "")
    if not marca:
        return False
    try:
        dados = _assinador().loads(marca, max_age=DIAS_APARELHO * 24 * 3600)
    except (BadSignature, SignatureExpired):
        return False
    return dados.get("u") == usuario.id and dados.get("v") == (usuario.versao_2fa or 1)
