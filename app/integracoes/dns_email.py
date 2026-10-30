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


# Seletores de DKIM mais usados (o nome varia por provedor; sem saber o seletor não dá para achar a chave)
SELETORES_DKIM = ("default", "selector1", "selector2", "dkim", "mail", "k1", "s1", "s2", "zmail", "zoho",
                  "hostingermail1", "hostingermail2", "titan1", "locaweb", "mx", "smtp", "key1", "everlytickey1")


def _provedor(mx: list[str]) -> str:
    if any("google" in m for m in mx):
        return "google"
    if any("outlook.com" in m for m in mx):
        return "microsoft"
    return ""


def verificar(dominio: str) -> dict:
    """{"provedor", "google", "itens": [(nome, ok, detalhe, como_resolver)]}. Funciona para o domínio da MS e para
    o domínio próprio de um gestor (Google Workspace, Microsoft 365 ou outro provedor)."""
    mx = _mx(dominio)
    tipo = _provedor(mx)
    google = tipo == "google"
    provedor = {"google": "Google Workspace (Gmail)", "microsoft": "Microsoft 365 (Outlook)"}.get(
        tipo, ", ".join(mx[:2]) or "não identificado")
    spf = [t for t in _txt(dominio) if t.lower().startswith("v=spf1")]
    inclui = {"google": "_spf.google.com", "microsoft": "spf.protection.outlook.com"}.get(tipo, "")
    if google:
        seletores = ("google",)
    elif tipo == "microsoft":
        seletores = ("selector1", "selector2")
    else:
        seletores = SELETORES_DKIM
    dkim = ""
    for seletor in seletores:
        if any("v=dkim1" in t.lower() or "p=" in t.lower() for t in _txt(f"{seletor}._domainkey.{dominio}")):
            dkim = seletor
            break
    dmarc = [t for t in _txt(f"_dmarc.{dominio}") if t.lower().startswith("v=dmarc1")]
    como_spf = (f'Crie no DNS um registro TXT em "{dominio}" com: v=spf1 include:{inclui} ~all' if inclui else
                f'Crie no DNS um registro TXT em "{dominio}" com o SPF que o seu provedor de e-mail indica '
                '(começa com v=spf1 e inclui o servidor de envio dele).')
    if google:
        como_dkim = ("No Google Admin (admin.google.com): Apps > Google Workspace > Gmail > Autenticar e-mail > Gerar "
                     "novo registro. Copie o registro TXT (google._domainkey) para o DNS do domínio e volte para "
                     "clicar em \"Iniciar autenticação\".")
    elif tipo == "microsoft":
        como_dkim = ("No Microsoft 365 Defender (security.microsoft.com): Políticas > Autenticação de e-mail > DKIM. "
                     "Crie no DNS os dois CNAME (selector1 e selector2) indicados e ative a assinatura.")
    else:
        como_dkim = ("Ative o DKIM no painel do seu provedor de e-mail e publique no DNS o registro que ele mostrar. "
                     "Se já fez e aparece aqui como faltando, o seu provedor usa um nome de seletor diferente: "
                     "confira no painel dele.")
    itens = [
        ("SPF", bool(spf) and (not inclui or inclui in spf[0]), spf[0] if spf else "não encontrado", como_spf),
        ("DKIM", bool(dkim), f"assinatura encontrada (seletor {dkim})" if dkim else "não encontrado", como_dkim),
        ("DMARC", bool(dmarc), dmarc[0] if dmarc else "não encontrado",
         f'Crie no DNS um registro TXT em "_dmarc.{dominio}" com: v=DMARC1; p=none; '
         f'rua=mailto:dmarc@{dominio} (depois de algumas semanas sem problemas, mude p=none para p=quarantine).'),
    ]
    return {"provedor": provedor, "google": google, "itens": itens}
