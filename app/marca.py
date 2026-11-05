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
    texto = re.sub(r"^1\. A .+? indica o cliente;$", "1. Vocês indicam o cliente;", texto or "", flags=re.M)
    texto = re.sub(r"^3\. A .+? é remunerada por certificado emitido;$",
                   "3. Vocês são remunerados por cada certificado emitido;", texto, flags=re.M)
    if not texto or not m["propria"]:
        return texto
    t = texto
    nome = m["nome"]
    # "a MS" vira "o Grupo Certy" quando o nome é masculino (Grupo, Escritório, Instituto, Cartório...)
    masculino = (nome.split() or [""])[0].lower() in {"grupo", "escritório", "escritorio", "instituto",
                                                       "cartório", "cartorio", "centro", "portal", "ponto"}
    artigos = {"a": "o", "da": "do", "na": "no", "pela": "pelo", "com a": "com o", "à": "ao", "para a": "para o"}

    def com_artigo(x):
        artigo = x.group(1)
        novo = artigos.get(artigo.lower(), artigo.lower()) if masculino else artigo.lower()
        if artigo[0].isupper():
            novo = novo[0].upper() + novo[1:]
        return f"{novo} {nome}"

    # "A MS faz", "a MS Certificação Digital tem", "da MS", "com a MS"... (maiúscula ou minúscula)
    t = re.sub(r"\b(para a|com a|pela|da|na|à|a)\s+MS(?:\s+Certificação Digital|\s+Certificados)?\b", com_artigo, t,
               flags=re.I)
    t = t.replace("MS Certificação Digital", nome).replace("MS Certificados", nome)
    t = t.replace("https://mscertificados.com.br", f"https://{m['site']}" if m["site"] else "")
    t = t.replace("mscertificados.com.br", m["site"])
    descricao = m["descricao"].strip().rstrip(".;,: ")  # o modelo já põe o ponto depois
    t = t.replace("Autoridade de Registro ICP-Brasil", descricao) if descricao else re.sub(
        r"\s*\(?,?\s*Autoridade de Registro ICP-Brasil[^).\n]*\)?", "", t)
    # onde é a validação é coisa da MS: some da mensagem de outra empresa
    t = re.sub(r"\s*\(presencial em Recife ou por videoconferência\)", "", t)
    t = re.sub(r"\s*presencial em Recife ou por videoconferência", "", t)
    t = re.sub(r"\s+em Recife\b", "", t)
    # "MS" solto dos modelos (ex.: "Parceria MS + Fulano"); não mexe em "MS" do nome do lead
    t = re.sub(r"\b(Parceria|parceria|equipe|time|Equipe|Time) MS\b", lambda x: f"{x.group(1)} {nome}", t)
    t = re.sub(r" · $", "", t, flags=re.M)
    return t
