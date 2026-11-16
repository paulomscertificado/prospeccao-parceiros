"""Marca de cada AR (white label, Fase 5) e a empresa que cada pessoa representa nas mensagens.

Telas (`da_tela`): quem é de uma AR vê o nome, o logo, as cores e a fonte dela (tabela marcas_ar, tela Configurações >
Marca). Antes de entrar, e o Admin Master fora das ARs, veem a plataforma: neutra, sem o nome de nenhuma AR (decisão
de 14/11/2026: um endereço só para todas; o nome neutro é a configuração `plataforma_nome`, que só o master muda).

Mensagens (`da_pessoa`, `aplicar`): saem em nome da "empresa que eu represento" da pessoa (Minha conta) ou, sem ela,
da marca da AR dela (Admin Master e quem não tem AR: a AR MS, ars.PADRAO). Os modelos do sistema foram escritos com o
nome da MS; `aplicar` troca esses trechos pela empresa de quem envia e, para quem não fala pela MS, tira onde é a
validação (o "presencial em Recife" é da MS). É chamado ao montar as mensagens das campanhas (o time já vê o texto
certo na aprovação) e de novo na hora do envio (vale também para mensagens montadas antes).

A marca fica guardada na memória por alguns minutos: cada leitura no banco é tráfego do Supabase.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import re
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import object_session

from . import config
from .modelos import MarcaAR, Tenant, Usuario

# como os modelos de mensagem do sistema foram escritos: `aplicar` troca isto pela empresa de quem envia
MS = {"nome": "MS Certificação Digital", "site": "mscertificados.com.br",
      "descricao": "Autoridade de Registro ICP-Brasil"}
PADRAO = MS  # os campos da "empresa que eu represento" (Minha conta): nome, site e descrição
PLATAFORMA = "Prospecção de Parceiros"  # nome neutro até a plataforma ganhar o dela (configuração plataforma_nome)
DESCRICAO_PADRAO = "Autoridade de Registro ICP-Brasil"
FONTES = ("Inter", "Montserrat", "Poppins", "Roboto", "Open Sans", "Lato", "Nunito", "Raleway", "Work Sans")
TIPOS_LOGO = {"image/png": "PNG", "image/jpeg": "JPG", "image/webp": "WebP"}  # SVG não: pode levar código
LIMITE_LOGO = 300_000  # 300 KB: o logo aparece em toda tela
LOGO_LARGO = 1.8  # largura/altura: daqui para cima o logo fica sozinho na linha de cima do menu (Grupo Certy: 4,9)
ALTURA_LOGO_TRATADO = 240  # px: o menu mostra até 44 px de altura; mais que isso só pesa (tráfego do Supabase)
MAXIMO_PIXELS = 25_000_000  # imagem maior que isso (em pixels) nem é aberta para tirar o fundo
RUIDO_DO_FUNDO = 3  # tons de diferença do fundo que ainda contam como fundo (manchinhas do JPG)
VALIDADE = 300  # segundos que a marca fica na memória (muda pouco; Configurações > Marca limpa na hora)
COR = re.compile(r"^#[0-9a-fA-F]{6}$")
DOMINIO = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
MASCULINOS = {"grupo", "escritório", "escritorio", "instituto", "cartório", "cartorio", "centro", "portal", "ponto",
              "banco", "sistema", "núcleo", "nucleo", "consórcio", "consorcio", "sindicato", "conselho"}
_CONTRACOES = {("de", "a"): "da", ("de", "o"): "do", ("em", "a"): "na", ("em", "o"): "no",
               ("por", "a"): "pela", ("por", "o"): "pelo", ("a", "a"): "à", ("a", "o"): "ao"}
_guardadas: dict = {}  # ar -> (até quando, marca); "plataforma" e "ar_ms" também
_logos: dict = {}  # ar -> (até quando, bytes, tipo)


# ---------------------------------------------------------------- frases ("com a MS", "do Grupo Certy")
def artigo_de(nome: str) -> str:
    """"o" para nomes masculinos (Grupo, Escritório, Instituto...); "a" para os outros (a MS, a Certisign)."""
    return "o" if (nome.split() or [""])[0].lower() in MASCULINOS else "a"


def frase(m: dict, prep: str = "", nome: bool = False, maiuscula: bool = False) -> str:
    """"a MS", "com a MS", "do Grupo Certy", "pela sua empresa"... (prep: "", "de", "em", "com", "para", "por", "a")."""
    artigo = m["artigo"]
    inicio = _CONTRACOES.get((prep, artigo)) or (f"{prep} {artigo}" if prep else artigo)
    texto = f"{inicio} {m['nome'] if nome else m['curto']}"
    return texto[0].upper() + texto[1:] if maiuscula else texto


# ---------------------------------------------------------------- cores e fonte nas telas
def _rgb(cor: str) -> tuple:
    c = cor.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _misturar(a, b, quanto: float) -> tuple:
    return tuple(x + (y - x) * quanto for x, y in zip(a, b))


def _luz(rgb) -> float:
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (canal(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste_com_branco(cor) -> float:
    return 1.05 / (_luz(_rgb(cor) if isinstance(cor, str) else cor) + 0.05)


def _legivel(rgb) -> tuple:
    """A cor escurecida só o bastante para um texto branco em cima dela ser legível (contraste 4,5 do WCAG)."""
    for _ in range(40):
        if contraste_com_branco(rgb) >= 4.6:
            break
        rgb = _misturar(rgb, (0, 0, 0), 0.04)
    return rgb


def tema(cor: str = "", detalhe: str = "", fundo: str = "", fonte: str = "") -> str:
    """Variáveis do estilo.css que trocam as cores e a fonte do sistema pelas da marca (vazio = as do sistema).
    Botões e textos usam a cor escurecida até o branco ficar legível; os detalhes usam a cor original."""
    v = {}
    if COR.match(cor or ""):
        original = _rgb(cor)
        base = _legivel(original)
        v["--azul"] = _hex(base)
        v["--azul-escuro"] = _hex(_misturar(base, (0, 0, 0), 0.22))
        v["--azul-medio"] = _hex(_misturar(base, (255, 255, 255), 0.08))
        v["--azul-claro"] = _hex(_misturar(original, (255, 255, 255), 0.88))
        v["--roxo"], v["--roxo-escuro"], v["--roxo-claro"] = v["--azul-medio"], v["--azul-escuro"], v["--azul-claro"]
        v["--foco"] = _hex(_misturar(original, (255, 255, 255), 0.45))
        v["--menu-texto"] = "#ffffff"
        v["--menu-suave"] = "rgba(255,255,255,.78)"
        v["--menu-rotulo"] = "rgba(255,255,255,.75)"
        v["--menu-ativo"] = "rgba(255,255,255,.16)"
        v["--texto-sobre-azul"] = "rgba(255,255,255,.82)"
        v["--destaque-rotulo"] = "rgba(255,255,255,.88)"
    detalhe = detalhe if COR.match(detalhe or "") else (cor if COR.match(cor or "") else "")
    if detalhe:
        d = _rgb(detalhe)
        acao = _legivel(d)
        v["--verde-marca"] = _hex(d)
        v["--cta"] = _hex(acao)
        v["--cta-escuro"] = _hex(_misturar(acao, (0, 0, 0), 0.12))
        v["--cta-claro"] = _hex(_misturar(d, (255, 255, 255), 0.88))
    if COR.match(fundo or ""):
        v["--fundo"] = fundo.lower()
    if fonte in FONTES and fonte != "Inter":
        v["--fonte"] = f'"{fonte}", "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif'
    return ";".join(f"{k}:{valor}" for k, valor in v.items())


def endereco_da_fonte(fonte: str) -> str:
    if fonte not in FONTES or fonte == "Inter":
        return ""  # a Inter já vem em toda tela
    return f"https://fonts.googleapis.com/css2?family={fonte.replace(' ', '+')}:wght@400;500;600;700;800&display=swap"


# ---------------------------------------------------------------- logo
def _assinatura_logo(ar: int) -> str:
    """O endereço do logo leva uma assinatura: ninguém descobre as ARs da plataforma trocando o número."""
    return hmac.new(config.SECRET_KEY.encode(), f"logo:{ar}".encode(), hashlib.sha256).hexdigest()[:16]


def endereco_do_logo(ar: int, versao: int) -> str:
    return f"/marca/logo/{ar}/{_assinatura_logo(ar)}?v={versao}"


def logo_confere(ar: int, assinatura: str) -> bool:
    return hmac.compare_digest(_assinatura_logo(ar), assinatura or "")


def logo(db, ar: int) -> tuple[bytes, str] | None:
    guardado = _logos.get(ar)
    if guardado and guardado[0] > time.monotonic():
        return guardado[1], guardado[2]
    linha = db.execute(select(MarcaAR.logo, MarcaAR.logo_tipo).where(MarcaAR.tenant_id == ar)).first()
    if linha is None or not linha.logo or not linha.logo_tipo:
        return None
    _logos[ar] = (time.monotonic() + VALIDADE, linha.logo, linha.logo_tipo)
    return linha.logo, linha.logo_tipo


def problema_no_logo(dados: bytes) -> str:
    from .visual import tipo_da_imagem

    if not dados:
        return "O arquivo do logo está vazio."
    if len(dados) > LIMITE_LOGO:
        return f"O logo tem {len(dados) // 1000} KB; o limite é {LIMITE_LOGO // 1000} KB. Diminua a imagem e envie de novo."
    if tipo_da_imagem(dados) not in TIPOS_LOGO:
        return "O logo precisa ser uma imagem PNG, JPG ou WebP (PNG com fundo transparente fica melhor)."
    return ""


def proporcao_do_logo(dados: bytes) -> float | None:
    """Largura/altura do logo (só lê o cabeçalho da imagem). None = não deu para ler."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(dados)) as imagem:
            largura, altura = imagem.size
    except Exception:  # noqa: BLE001  (arquivo que diz ser imagem mas não abre)
        return None
    return round(largura / altura, 3) if largura and altura else None


def _tabela_de_transparencia(fundo: int) -> list[float]:
    """Para cada tom (0 a 255) de um canal: quanto ele é logo (1) e quanto é fundo (0), pela distância até o tom do
    fundo nesse canal ("cor para transparência"). As manchinhas do JPG perto do fundo (RUIDO_DO_FUNDO) contam como fundo."""
    tabela = []
    for tom in range(256):
        faixa, diferenca = (255 - fundo, tom - fundo) if tom > fundo else (fundo, fundo - tom)
        if faixa <= RUIDO_DO_FUNDO or diferenca <= RUIDO_DO_FUNDO:
            tabela.append(0.0)
        else:
            tabela.append(min(1.0, (diferenca - RUIDO_DO_FUNDO) / (faixa - RUIDO_DO_FUNDO)))
    return tabela


def tirar_fundo_do_logo(dados: bytes) -> bytes | None:
    """O fundo liso do logo vira transparente e as sobras em volta são cortadas (PNG). Feito para o logo claro que veio
    num fundo branco ou cinza (o JPG do Grupo Certy: logo branco em cinza-claro aparecia como um retângulo no menu).
    O fundo é a cor das bordas da imagem; a borda do desenho fica meio transparente, sem contorno da cor antiga.
    Logo já transparente: só corta as sobras. None = não achou um fundo liso (bordas de várias cores) ou não sobrou
    nada do desenho: o logo fica como veio."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(dados)) as aberta:
            if aberta.width * aberta.height > MAXIMO_PIXELS:
                return None
            imagem = aberta.convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    if imagem.height > ALTURA_LOGO_TRATADO:
        imagem = imagem.resize((max(1, round(imagem.width * ALTURA_LOGO_TRATADO / imagem.height)), ALTURA_LOGO_TRATADO),
                               Image.LANCZOS)
    largura, altura = imagem.size
    pontos = imagem.load()
    borda = [pontos[x, y] for x in range(largura) for y in {0, altura - 1}]
    borda += [pontos[x, y] for y in range(1, altura - 1) for x in {0, largura - 1}]
    if sum(1 for p in borda if p[3] < 16) < 0.9 * len(borda):  # ainda não é transparente: procura o fundo liso
        opacos = [p for p in borda if p[3] >= 240]
        if not opacos:
            return None
        fundo = tuple(sorted(p[canal] for p in opacos)[len(opacos) // 2] for canal in range(3))
        parecidos = sum(1 for p in opacos if max(abs(p[c] - fundo[c]) for c in range(3)) <= 12)
        if parecidos < 0.9 * len(borda):
            return None
        tabelas = [_tabela_de_transparencia(tom) for tom in fundo]
        crus = imagem.tobytes()
        saida = bytearray(len(crus))
        for i in range(0, len(crus), 4):
            r, g, b, a = crus[i], crus[i + 1], crus[i + 2], crus[i + 3]
            quanto = max(tabelas[0][r], tabelas[1][g], tabelas[2][b])
            if quanto <= 0 or a == 0:
                continue  # fundo: fica transparente (zeros)
            for c, tom in enumerate((r, g, b)):  # tira a cor do fundo que se misturou na borda do desenho
                saida[i + c] = max(0, min(255, round(fundo[c] + (tom - fundo[c]) / quanto)))
            saida[i + 3] = round(quanto * a)
        imagem = Image.frombytes("RGBA", (largura, altura), bytes(saida))
    caixa = imagem.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if caixa is None:
        return None
    esquerda, topo, direita, baixo = caixa  # 1 px de folga: a borda suave do desenho não é cortada
    imagem = imagem.crop((max(0, esquerda - 1), max(0, topo - 1), min(largura, direita + 1), min(altura, baixo + 1)))
    arquivo = io.BytesIO()
    imagem.save(arquivo, "PNG", optimize=True)
    return arquivo.getvalue()


# ---------------------------------------------------------------- a marca de uma AR e a da plataforma
@contextmanager
def _sessao(db=None, usuario=None):
    if db is None and usuario is not None:
        try:
            db = object_session(usuario)
        except Exception:  # noqa: BLE001  (não é uma linha do banco: ex.: testes, prévias)
            db = None
    if db is not None:
        yield db
        return
    from .banco import FabricaSessao

    with FabricaSessao() as nova:
        yield nova


def _com_frase(m: dict) -> dict:
    m["frase"] = lambda prep="", nome=False, maiuscula=False: frase(m, prep, nome, maiuscula)
    return m


def _montar(ar: int, slug: str, nome_ar: str, linha: MarcaAR | None) -> dict:
    valor = (lambda campo: (getattr(linha, campo) or "").strip() if linha is not None else "")
    nome = valor("nome") or nome_ar
    curto = valor("curto") or nome
    m = {"ar": ar, "slug": slug, "e_ms": slug == "ms", "plataforma": False,
         "nome": nome, "curto": curto, "artigo": valor("artigo") or artigo_de(curto),
         "site": valor("site"), "descricao": valor("descricao") or DESCRICAO_PADRAO,
         "dominio_email": valor("dominio_email").lower(), "cor": valor("cor"), "cor_detalhe": valor("cor_detalhe"),
         "cor_fundo": valor("cor_fundo"), "fonte": valor("fonte"), "titulo": f"{curto} Parceiros",
         "logo_url": (endereco_do_logo(ar, int(linha.atualizado_em.timestamp()))
                      if linha is not None and linha.logo_tipo and linha.atualizado_em else "")}
    m["logo_largo"] = bool(m["logo_url"] and (linha.logo_proporcao or 0) >= LOGO_LARGO)
    m["css"] = tema(m["cor"], m["cor_detalhe"], m["cor_fundo"], m["fonte"])
    m["fonte_url"] = endereco_da_fonte(m["fonte"])
    return _com_frase(m)


def da_plataforma(db=None) -> dict:
    """A plataforma: neutra (sem o nome de nenhuma AR). Antes de entrar e para o Admin Master fora das ARs."""
    guardada = _guardadas.get("plataforma")
    if guardada and guardada[0] > time.monotonic():
        return guardada[1]
    nome = PLATAFORMA
    if db is not None:
        from .banco import ler_config

        nome = (ler_config(db, "plataforma_nome") or "").strip() or PLATAFORMA
    m = _com_frase({"ar": None, "slug": "", "e_ms": False, "plataforma": True, "nome": nome, "curto": "sua empresa",
                    "artigo": "a", "site": "", "descricao": "", "dominio_email": "", "cor": "", "cor_detalhe": "",
                    "cor_fundo": "", "fonte": "", "titulo": nome, "logo_url": "", "logo_largo": False, "css": "",
                    "fonte_url": ""})
    if db is not None:
        _guardadas["plataforma"] = (time.monotonic() + VALIDADE, m)
    return m


def da_ar(db, ar: int | None) -> dict:
    """A marca da AR `ar` (sem AR: a plataforma)."""
    if not ar:
        return da_plataforma(db)
    guardada = _guardadas.get(ar)
    if guardada and guardada[0] > time.monotonic():
        return guardada[1]
    linha = db.execute(select(MarcaAR).where(MarcaAR.tenant_id == ar)).scalars().first()
    tenant = db.execute(select(Tenant.slug, Tenant.nome).where(Tenant.id == ar)).first()
    m = _montar(ar, tenant.slug if tenant else "", tenant.nome if tenant else "", linha)
    _guardadas[ar] = (time.monotonic() + VALIDADE, m)
    return m


def esquecer(ar=None) -> None:
    """Depois de mudar uma marca: a próxima leitura vem do banco (sem `ar`: todas)."""
    if ar is None:
        _guardadas.clear()
        _logos.clear()
    else:
        _guardadas.pop(ar, None)
        _logos.pop(ar, None)
        _guardadas.pop("plataforma", None)


def ar_padrao(db) -> int | None:
    """Admin Master e quem ainda não tem AR falam pela AR MS (decisão de 14/11/2026, ars.PADRAO)."""
    if "ar_ms" not in _guardadas:
        from . import ars

        _guardadas["ar_ms"] = db.execute(select(Tenant.id).where(Tenant.slug == ars.PADRAO["do_master"])).scalar()
    return _guardadas["ar_ms"]


def ar_da_tela(request, usuario) -> int | None:
    """A AR cuja marca a tela mostra: a da pessoa; o Admin Master só dentro de uma AR ("Entrar na AR")."""
    if usuario is None:
        return None
    if getattr(usuario, "master", False):
        return request.session.get("ar_entrada") or None
    return usuario.tenant_id


def da_tela(request, usuario, db=None) -> dict:
    with _sessao(db) as s:
        return da_ar(s, ar_da_tela(request, usuario))


# ---------------------------------------------------------------- em nome de quem as mensagens saem
def da_pessoa(usuario: Usuario | None, ar: int | None = None, db=None) -> dict:
    """A empresa em nome de quem as mensagens desta pessoa saem: a que ela representa (Minha conta) ou, sem ela, a
    marca da AR (`ar` quando a mensagem é de uma AR que não é a da pessoa; Admin Master e sem AR: a AR MS)."""
    with _sessao(db, usuario) as s:
        if ar is None:
            ar = getattr(usuario, "tenant_id", None) or ar_padrao(s)
        base = da_ar(s, ar)
    m = {"nome": base["nome"], "site": base["site"], "descricao": base["descricao"], "curto": base["curto"],
         "artigo": base["artigo"], "dominio_email": base["dominio_email"], "ar": base["ar"]}
    for campo in ("nome", "site", "descricao"):
        valor = (getattr(usuario, f"empresa_{campo}", "") or "").strip() if usuario is not None else ""
        if valor:
            m[campo] = valor
    m["outra_empresa"] = m["nome"] != base["nome"]  # a pessoa representa uma empresa que não é a marca da AR dela
    if m["outra_empresa"]:
        m["curto"], m["artigo"] = m["nome"], artigo_de(m["nome"])
    m["da_ms"] = base["e_ms"] and not m["outra_empresa"]  # o que é só da MS (validação em Recife, WhatsApp da MS)
    m["propria"] = m["nome"] != MS["nome"]  # os modelos (escritos com o nome da MS) precisam da troca
    return _com_frase(m)


def assinatura(usuario: Usuario | None, vendedor: str, ar: int | None = None) -> str:
    m = da_pessoa(usuario, ar)
    return f"\n\n{vendedor}\n{m['nome']}" + (f" · {m['site']}" if m["site"] else "")


def aplicar(texto: str, usuario: Usuario | None, ar: int | None = None) -> str:
    """Troca a MS pela empresa de quem envia nos textos montados com os modelos do sistema."""
    m = da_pessoa(usuario, ar)
    texto = re.sub(r"^1\. A .+? indica o cliente;$", "1. Vocês indicam o cliente;", texto or "", flags=re.M)
    texto = re.sub(r"^3\. A .+? é remunerada por certificado emitido;$",
                   "3. Vocês são remunerados por cada certificado emitido;", texto, flags=re.M)
    if not texto:
        return texto
    t = texto
    if m["propria"]:
        nome = m["nome"]
        masculino = m["artigo"] == "o"
        artigos = {"a": "o", "da": "do", "na": "no", "pela": "pelo", "com a": "com o", "à": "ao", "para a": "para o"}

        def com_artigo(x):
            artigo = x.group(1)
            novo = artigos.get(artigo.lower(), artigo.lower()) if masculino else artigo.lower()
            if artigo[0].isupper():
                novo = novo[0].upper() + novo[1:]
            return f"{novo} {nome}"

        # "A MS faz", "a MS Certificação Digital tem", "da MS", "com a MS"... (maiúscula ou minúscula)
        t = re.sub(r"\b(para a|com a|pela|da|na|à|a)\s+MS(?:\s+Certificação Digital|\s+Certificados)?\b", com_artigo,
                   t, flags=re.I)
        t = t.replace("MS Certificação Digital", nome).replace("MS Certificados", nome)
        # "MS" solto dos modelos (ex.: "Parceria MS + Fulano"); não mexe em "MS" do nome do lead
        t = re.sub(r"\b(Parceria|parceria|equipe|time|Equipe|Time) MS\b", lambda x: f"{x.group(1)} {nome}", t)
    if m["site"] != MS["site"]:
        t = t.replace("https://mscertificados.com.br", f"https://{m['site']}" if m["site"] else "")
        t = t.replace("mscertificados.com.br", m["site"])
    descricao = m["descricao"].strip().rstrip(".;,: ")  # o modelo já põe o ponto depois
    if descricao != MS["descricao"]:
        t = t.replace("Autoridade de Registro ICP-Brasil", descricao) if descricao else re.sub(
            r"\s*\(?,?\s*Autoridade de Registro ICP-Brasil[^).\n]*\)?", "", t)
    if not m["da_ms"]:  # onde é a validação é coisa da MS: some da mensagem de outra empresa
        t = re.sub(r"\s*\(presencial em Recife ou por videoconferência\)", "", t)
        t = re.sub(r"\s*presencial em Recife ou por videoconferência", "", t)
        t = re.sub(r"\s+em Recife\b", "", t)
    return re.sub(r" · $", "", t, flags=re.M)


def config_da_marca(db, ar: int, chave: str) -> str:
    """Configurações que falam da empresa (banco.CHAVES_DA_MARCA) quando a AR não tem valor próprio: vêm da marca dela,
    nunca da plataforma (antes da Fase 5 eram os textos da MS)."""
    m = da_ar(db, ar)
    if chave == "empresa_nome":
        return m["nome"]
    if chave == "link_parceria":
        return f"https://{m['site']}" if m["site"] else ""
    if chave == "programa_parceria":
        return (f"Programa de parceria {frase(m, 'de', nome=True)} ({m['descricao']}"
                + (f", {m['site']}" if m["site"] else "") + "): o escritório contábil indica os clientes que precisam "
                f"de certificado digital; a equipe {frase(m, 'de')} entra em contato e cuida de todo o processo "
                f"(emissão e validação); o escritório recebe comissão por certificado emitido; {frase(m)} controla os "
                "vencimentos e cuida das renovações, mantendo o escritório como parceiro.")
    return ""  # whatsapp_convite: só o número que a própria AR cadastrar


# ---------------------------------------------------------------- gravar (Configurações > Marca)
def _limpar_site(valor: str) -> str:
    v = valor.strip().lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")
    return v.rstrip("/")


def _gravar_logo(linha: MarcaAR, dados: bytes, tirar_fundo: bool) -> list[str]:
    from .visual import tipo_da_imagem

    problemas = []
    if tirar_fundo:
        tratado = tirar_fundo_do_logo(dados)
        if tratado is None:
            problemas.append("O logo não tem um fundo liso (de uma cor só) para tirar: ficou como veio.")
        elif len(tratado) > LIMITE_LOGO:
            problemas.append(f"Sem o fundo, o logo ficou com {len(tratado) // 1000} KB (limite {LIMITE_LOGO // 1000} KB): "
                             "ficou como veio. Envie uma imagem menor.")
        else:
            dados = tratado
    linha.logo, linha.logo_tipo, linha.logo_proporcao = dados, tipo_da_imagem(dados), proporcao_do_logo(dados)
    return problemas


def salvar(db, ar: int, dados: dict, novo_logo: bytes | None = None, tirar_logo: bool = False,
           tirar_fundo: bool = False) -> list[str]:
    """Grava a marca da AR `ar`. Devolve os problemas encontrados (vazio = gravou tudo). `tirar_fundo`: o fundo liso
    do logo novo (ou, sem arquivo novo, do logo de agora) vira transparente (`tirar_fundo_do_logo`)."""
    problemas = []
    linha = db.get(MarcaAR, ar)
    if linha is None:
        linha = MarcaAR(tenant_id=ar)
        db.add(linha)
    textos = {"nome": 120, "curto": 60, "descricao": 160}
    for campo, tamanho in textos.items():
        if campo in dados:
            valor = re.sub(r"\s+", " ", str(dados[campo] or "")).strip()
            setattr(linha, campo, (valor.rstrip(".;,: ") if campo == "descricao" else valor)[:tamanho])
    if "artigo" in dados:
        linha.artigo = dados["artigo"] if dados["artigo"] in ("a", "o") else ""
    if "site" in dados:
        linha.site = _limpar_site(str(dados["site"] or ""))[:120]
    if "dominio_email" in dados:
        dominio = str(dados["dominio_email"] or "").strip().lower().lstrip("@")
        if dominio and not DOMINIO.match(dominio):
            problemas.append(f"O domínio de e-mail \"{dominio}\" não parece um domínio (ex.: suaempresa.com.br).")
        else:
            linha.dominio_email = dominio[:120]
    for campo, rotulo in (("cor", "principal"), ("cor_detalhe", "dos detalhes"), ("cor_fundo", "do fundo")):
        if campo in dados:
            cor = str(dados[campo] or "").strip()
            if cor and not COR.match(cor):
                problemas.append(f"A cor {rotulo} precisa ser no formato #RRGGBB (ex.: #E86A1F).")
            else:
                setattr(linha, campo, cor.upper())
    if "fonte" in dados:
        linha.fonte = dados["fonte"] if dados["fonte"] in FONTES and dados["fonte"] != "Inter" else ""
    if novo_logo:
        problema = problema_no_logo(novo_logo)
        if problema:
            problemas.append(problema)
        else:
            problemas += _gravar_logo(linha, novo_logo, tirar_fundo)
    elif tirar_logo:
        linha.logo, linha.logo_tipo, linha.logo_proporcao = None, "", None
    elif tirar_fundo:
        if linha.logo_tipo and linha.logo:
            problemas += _gravar_logo(linha, linha.logo, True)
        else:
            problemas.append("Não há logo para tirar o fundo: escolha o arquivo do logo.")
    from .banco import agora

    linha.atualizado_em = agora()  # muda o endereço do logo: o navegador busca o novo
    esquecer(ar)
    return problemas


# ---------------------------------------------------------------- preparação do banco
MS_CONFIG = {  # os textos da MS que eram da plataforma até a Fase 5 (passam a ser da AR MS em `garantir`)
    "empresa_nome": "MS Certificação Digital",
    "link_parceria": "https://mscertificados.com.br",
    "programa_parceria": (
        "Programa de parceria da MS Certificação Digital (Autoridade de Registro ICP-Brasil, "
        "mscertificados.com.br): o escritório contábil indica os clientes que precisam de certificado "
        "digital; a equipe da MS entra em contato e cuida de todo o processo (emissão e validação presencial "
        "em Recife ou por videoconferência); o escritório recebe comissão por certificado emitido; a MS "
        "controla os vencimentos e cuida das renovações, mantendo o escritório como parceiro."),
}


def garantir(db) -> None:
    """Na preparação do banco (uma vez por publicação): a marca da AR MS (como o sistema sempre foi, com o logo de
    sempre), os textos da MS que eram da plataforma passam a ser só da AR MS, e o papel "Funcionário MS" vira
    "Funcionário" (nome que todas as ARs veem)."""
    from . import ars
    from .banco import CHAVES_DA_MARCA
    from .modelos import Configuracao, ConfiguracaoAR, Papel

    ms = db.execute(select(Tenant.id).where(Tenant.slug == ars.AR_MS)).scalar()
    if ms is not None:
        if db.get(MarcaAR, ms) is None:
            arquivo = Path(__file__).resolve().parent / "static" / "logo-ms.png"
            logo_ms = arquivo.read_bytes() if arquivo.exists() else None
            db.add(MarcaAR(tenant_id=ms, nome=MS["nome"], curto="MS", artigo="a", site=MS["site"],
                           descricao=MS["descricao"], dominio_email=config.EMAIL_DOMINIO, logo=logo_ms,
                           logo_tipo="image/png" if logo_ms else "",
                           logo_proporcao=proporcao_do_logo(logo_ms) if logo_ms else None))
        for chave in sorted(CHAVES_DA_MARCA - {"empresa_nome"}):  # o nome sai da marca (aba Marca), sem cópia
            if db.get(ConfiguracaoAR, (ms, chave)) is None:
                da_plataforma_ = db.get(Configuracao, chave)
                valor = da_plataforma_.valor if da_plataforma_ is not None else MS_CONFIG.get(chave, "")
                if valor:
                    db.add(ConfiguracaoAR(tenant_id=ms, chave=chave, valor=valor))
    db.execute(update(Papel).where(Papel.codigo == "funcionario", Papel.nome == "Funcionário MS")
               .values(nome=config.PERFIS["funcionario"]))
    from .modelos import Cadencia

    for cad in db.execute(select(Cadencia).where(Cadencia.tenant_id.is_(None),
                                                 Cadencia.descricao.like("%WhatsApp da MS%"))).scalars():
        cad.descricao = cad.descricao.replace("WhatsApp da MS", "WhatsApp da empresa")  # cadência que todas as ARs veem
    for linha in db.execute(select(MarcaAR).where(MarcaAR.logo_tipo != "", MarcaAR.logo_proporcao.is_(None))).scalars():
        linha.logo_proporcao = proporcao_do_logo(linha.logo or b"")  # logos de antes da medida (uma vez só)
    esquecer()
