"""Empresa que cada usuário representa nas mensagens (ex.: MS Certificação Digital, Grupo Certy Certificados).

Cada usuário configura em Minha conta > "Empresa que eu represento": nome, site e apresentação curta. Quem não
preencher fala pela empresa padrão do sistema (MS Certificação Digital). Para outra empresa, as mensagens não falam
de onde é a validação (o "presencial em Recife" é da MS) nem de preço.

Os modelos de mensagem do sistema foram escritos com o nome da MS. `aplicar` troca esses trechos pela empresa do
usuário. É chamado ao montar as mensagens das campanhas (o time já vê o texto certo na aprovação) e de novo na hora
do envio (vale também para mensagens montadas antes desta configuração).
"""

import re

from .modelos import Usuario

PADRAO = {
    "nome": "MS Certificação Digital",
    "site": "mscertificados.com.br",
    "descricao": "Autoridade de Registro ICP-Brasil",
}


def da_pessoa(usuario: Usuario | None) -> dict:
    """Dados da empresa do usuário (o que estiver vazio vem do padrão do sistema)."""
    m = dict(PADRAO)
    if usuario is not None:
        for campo in PADRAO:
            valor = (getattr(usuario, f"empresa_{campo}", "") or "").strip()
            if valor:
                m[campo] = valor
    m["propria"] = m["nome"] != PADRAO["nome"]
    return m


def assinatura(usuario: Usuario | None, vendedor: str) -> str:
    m = da_pessoa(usuario)
    return f"\n\n{vendedor}\n{m['nome']}" + (f" · {m['site']}" if m["site"] else "")


def aplicar(texto: str, usuario: Usuario | None) -> str:
    """Troca a MS pela empresa do usuário nos textos montados com os modelos do sistema."""
    m = da_pessoa(usuario)
    if not texto or not m["propria"]:
        return texto
    t = texto
    # "da MS" → "do Grupo Certy" quando o nome é masculino (Grupo, Escritório, Instituto, Cartório...)
    masculino = (m["nome"].split() or [""])[0].lower() in {"grupo", "escritório", "escritorio", "instituto",
                                                            "cartório", "cartorio", "centro", "portal", "ponto"}
    if masculino:
        for de_ms in ("da MS Certificação Digital", "da MS Certificados"):
            t = t.replace(de_ms, f"do {m['nome']}")
        t = re.sub(r"\b(com a|pela|na) MS Certificação Digital\b",
                   lambda x: {"com a": "com o", "pela": "pelo", "na": "no"}[x.group(1)] + " " + m["nome"], t)
    t = t.replace("MS Certificação Digital", m["nome"]).replace("MS Certificados", m["nome"])
    t = t.replace("https://mscertificados.com.br", f"https://{m['site']}" if m["site"] else "")
    t = t.replace("mscertificados.com.br", m["site"])
    t = t.replace("Autoridade de Registro ICP-Brasil", m["descricao"]) if m["descricao"] else re.sub(
        r"\s*\(?,?\s*Autoridade de Registro ICP-Brasil[^).\n]*\)?", "", t)
    # onde é a validação é coisa da MS: some da mensagem de outra empresa
    t = re.sub(r"\s*\(presencial em Recife ou por videoconferência\)", "", t)
    t = re.sub(r"\s*presencial em Recife ou por videoconferência", "", t)
    t = re.sub(r"\s+em Recife\b", "", t)
    # "a MS cuida", "com a MS", "da MS" → nome da empresa
    t = re.sub(r"\b(a|da|na|pela|com a) MS\b(?! Certifica)", lambda x: f"{x.group(1)} {m['nome']}", t)
    t = re.sub(r" · $", "", t, flags=re.M)
    return t
