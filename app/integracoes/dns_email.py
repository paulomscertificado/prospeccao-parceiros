"""Confere no DNS se o domínio está pronto para enviar e-mail sem cair no spam (SPF, DKIM e DMARC).

Consulta pública via DNS do Google (dns.google). Só lê registros públicos do domínio.
"""

import httpx


def _txt(nome: str) -> list[str]:
    try:
        r = httpx.get("https://dns.google/resolve", params={"name": nome, "type": "TXT"}, timeout=10)
        return [a.get("data", "").replace('" "', "").strip('"') for a in r.json().get("Answer", []) if a.get("type") == 16]
    except (httpx.HTTPError, ValueError):
        return []


def _mx(dominio: str) -> list[str]:
    try:
        r = httpx.get("https://dns.google/resolve", params={"name": dominio, "type": "MX"}, timeout=10)
        return [a.get("data", "").split()[-1].rstrip(".").lower() for a in r.json().get("Answer", []) if a.get("type") == 15]
    except (httpx.HTTPError, ValueError):
        return []


def verificar(dominio: str) -> dict:
    """{"provedor", "itens": [(nome, ok, detalhe, como_resolver)]}."""
    mx = _mx(dominio)
    google = any("google" in m for m in mx)
    provedor = "Google Workspace (Gmail)" if google else (", ".join(mx[:2]) or "não identificado")
    spf = [t for t in _txt(dominio) if t.lower().startswith("v=spf1")]
    dkim = [t for t in _txt(f"google._domainkey.{dominio}") if "v=dkim1" in t.lower()] if google else []
    dmarc = [t for t in _txt(f"_dmarc.{dominio}") if t.lower().startswith("v=dmarc1")]
    itens = [
        ("SPF", bool(spf) and (not google or "_spf.google.com" in spf[0]), spf[0] if spf else "não encontrado",
         f'Crie no DNS um registro TXT em "{dominio}" com: v=spf1 include:_spf.google.com ~all'),
        ("DKIM", bool(dkim), "assinatura do Google encontrada" if dkim else "não encontrado",
         "No Google Admin (admin.google.com): Apps > Google Workspace > Gmail > Autenticar e-mail > Gerar novo "
         "registro. Copie o registro TXT (google._domainkey) para o DNS do domínio e volte para clicar em "
         "\"Iniciar autenticação\"." if google else "Ative o DKIM no seu provedor de e-mail e publique o registro no DNS."),
        ("DMARC", bool(dmarc), dmarc[0] if dmarc else "não encontrado",
         f'Crie no DNS um registro TXT em "_dmarc.{dominio}" com: v=DMARC1; p=none; '
         f'rua=mailto:dmarc@{dominio} (depois de algumas semanas sem problemas, mude p=none para p=quarantine).'),
    ]
    return {"provedor": provedor, "google": google, "itens": itens}
