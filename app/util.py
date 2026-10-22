"""Funções pequenas de apoio: normalização (CNPJ, telefone, domínio, e-mail), datas e formatação."""

import re
import unicodedata
from datetime import date, datetime, timedelta

PROVEDORES_GRATUITOS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.br", "live.com", "icloud.com",
    "bol.com.br", "uol.com.br", "terra.com.br", "ig.com.br", "msn.com", "hotmail.com.br", "outlook.com.br",
}


def so_digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")


def chave_texto(texto: str) -> str:
    """Texto comparável: minúsculo, sem acento e sem espaços extras."""
    return re.sub(r"\s+", " ", sem_acento(texto or "").lower()).strip()


# ---------------------------------------------------------------- CNPJ

def normalizar_cnpj(cnpj: str) -> str:
    """CNPJ só com números e letras maiúsculas (desde jul/2026 há CNPJ alfanumérico: 12 posições
    podem ter letras; os 2 dígitos verificadores continuam numéricos)."""
    texto = re.sub(r"[^0-9A-Za-z]", "", str(cnpj or "")).upper()
    return texto


def cnpj_valido(cnpj: str) -> bool:
    d = normalizar_cnpj(cnpj)
    if len(d) != 14 or not d[12:].isdigit() or d == d[0] * 14:
        return False

    def digito(base: str, pesos: list[int]) -> str:
        resto = sum((ord(n) - 48) * p for n, p in zip(base, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)

    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6] + p1
    return d[12] == digito(d[:12], p1) and d[13] == digito(d[:13], p2)


def formatar_cnpj(cnpj: str) -> str:
    d = normalizar_cnpj(cnpj)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11 and d.isdigit():
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return cnpj or ""


def achar_cnpjs(texto: str) -> list[str]:
    """CNPJs válidos citados num texto (ex.: rodapé de um site)."""
    achados = []
    for bruto in re.findall(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", texto or ""):
        d = so_digitos(bruto)
        if cnpj_valido(d) and d not in achados:
            achados.append(d)
    return achados


# ---------------------------------------------------------------- Telefone

def normalizar_telefone(telefone: str) -> str:
    """Telefone brasileiro só com dígitos, com DDD e sem o 55. Vazio se não parecer um telefone."""
    d = so_digitos(telefone)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if d.startswith("0") and len(d) in (11, 12):
        d = d[1:]
    return d if len(d) in (10, 11) else ""


def formatar_telefone(telefone: str) -> str:
    d = normalizar_telefone(telefone)
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return telefone or ""


def link_whatsapp(telefone: str, texto: str = "") -> str:
    from urllib.parse import quote

    d = normalizar_telefone(telefone)
    if not d:
        return ""
    return f"https://wa.me/55{d}" + (f"?text={quote(texto)}" if texto else "")


# ---------------------------------------------------------------- Site, domínio, e-mail, redes

def normalizar_site(site: str) -> str:
    site = (site or "").strip()
    if not site:
        return ""
    if not re.match(r"^https?://", site, re.I):
        site = "https://" + site
    return site.rstrip("/")


def dominio(site_ou_email: str) -> str:
    texto = (site_ou_email or "").strip().lower()
    if "@" in texto and "/" not in texto:
        texto = texto.split("@", 1)[1]
    texto = re.sub(r"^https?://", "", texto)
    texto = texto.split("/")[0].split("?")[0].split(":")[0]
    if texto.startswith("www."):
        texto = texto[4:]
    return texto if "." in texto else ""


DOMINIOS_GENERICOS = {"facebook.com", "instagram.com", "linkedin.com", "wa.me", "api.whatsapp.com",
                      "linktr.ee", "google.com", "goo.gl", "bit.ly", "youtube.com", "twitter.com", "x.com",
                      "tiktok.com", "sites.google.com", "business.site", "m.facebook.com"}


def dominio_proprio(site: str) -> str:
    """Domínio que identifica a empresa (redes sociais e encurtadores não contam)."""
    d = dominio(site)
    return "" if d in DOMINIOS_GENERICOS else d


def email_valido(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}", (email or "").strip()))


def dominio_empresarial(email: str) -> str:
    """Domínio do e-mail só quando é da empresa (não Gmail, Hotmail...)."""
    d = dominio(email)
    return "" if d in PROVEDORES_GRATUITOS else d


def normalizar_instagram(valor: str) -> str:
    valor = (valor or "").strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", valor)
    if m:
        valor = m.group(1)
    valor = valor.lstrip("@").strip("/")
    return f"@{valor}" if valor else ""


def link_instagram(valor: str) -> str:
    v = normalizar_instagram(valor)
    return f"https://instagram.com/{v[1:]}" if v else ""


def normalizar_link(valor: str) -> str:
    valor = (valor or "").strip()
    if valor and not valor.startswith("http"):
        valor = "https://" + valor.lstrip("/")
    return valor


# ---------------------------------------------------------------- Números e datas

def para_int(valor) -> int | None:
    d = so_digitos(valor)
    return int(d) if d else None


def para_float(valor) -> float:
    """Aceita "1.234,56", "1234.56", "R$ 100"."""
    texto = str(valor or "").replace("R$", "").replace(" ", "").strip()
    if not texto:
        return 0.0
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def para_data(valor) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor or "").strip()[:10]
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    return None


def somar_meses(d: date, meses: int) -> date:
    mes = d.month - 1 + meses
    ano = d.year + mes // 12
    mes = mes % 12 + 1
    import calendar

    dia = min(d.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def proximo_dia_util(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def moeda(valor) -> str:
    valor = float(valor or 0)
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def porcentagem(valor, casas: int = 1) -> str:
    return f"{float(valor or 0):.{casas}f}%".replace(".", ",")


def data_br(valor) -> str:
    if not valor:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def so_data_br(valor) -> str:
    if not valor:
        return ""
    if isinstance(valor, datetime):
        valor = valor.date()
    return valor.strftime("%d/%m/%Y")


def primeiro_nome(nome: str) -> str:
    partes = (nome or "").strip().split()
    return partes[0].capitalize() if partes else ""


def taxa(parte, total) -> float:
    return round(100.0 * parte / total, 1) if total else 0.0
