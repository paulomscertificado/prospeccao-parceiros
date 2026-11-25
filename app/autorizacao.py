"""Permissões em camadas: papéis, permissões "recurso.acao", alcance, exceções por usuário e módulos.

Ordem de decisão de uma permissão (ver docs/permissoes.md):
  1. módulo desligado            -> NEGA para todos
  2. NEGAR do usuário            -> NEGA
  3. PERMITIR do usuário         -> PERMITE (com o alcance da exceção, ou o do papel)
  4. permissão do papel          -> PERMITE (com o alcance do papel)
  5. nada disso                  -> NEGA

Alcance ("escopo") das permissões que tratam de dados com dono:
  tudo      -> qualquer registro
  abaixo    -> os da própria pessoa e os de quem tem papel abaixo do dela (hierarquia, 17/11/2026:
               administrador > gestor > funcionário > vendedor; papel criado = o nível do tipo em que se baseia)
  equipe    -> registros cujo dono é da mesma equipe (sem equipe = só os próprios)
  proprios  -> só os registros da própria pessoa

Uso no backend (toda rota, exportação, relatório e ação administrativa):
  Depends(exige("leads.ver"))                     -> a pessoa tem a permissão (em qualquer alcance)
  pode(usuario, "leads.editar", lead)             -> a pessoa pode agir NESTE registro
  garantir(usuario, "leads.editar", lead)         -> igual, mas responde 404 (não revela que o registro existe)
  filtrar(consulta, usuario, "leads.ver", Lead.vendedor_id)  -> lista só o que a pessoa pode ver
O menu e os botões das telas usam as mesmas regras, mas são só a camada de conforto.
"""

from dataclasses import dataclass
from datetime import date

from fastapi import Depends, HTTPException
from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session, object_session

from .modelos import ExcecaoPermissao, Papel, PermissaoPapel, Usuario

TUDO, ABAIXO, EQUIPE, PROPRIOS = "tudo", "abaixo", "equipe", "proprios"
ESCOPOS = {TUDO: "Tudo", ABAIXO: "Eu e quem está abaixo", EQUIPE: "Só a equipe", PROPRIOS: "Só os próprios"}
_ORDEM = {PROPRIOS: 1, EQUIPE: 2, ABAIXO: 2, TUDO: 3}
PERFIS_BASE = ("admin", "gestor", "funcionario", "vendedor", "parceiro")
# Hierarquia (pedido da Maria em 17/11/2026: "quero que quem for acima veja as coisas de quem está abaixo"): o nível
# vem do tipo base do papel (um papel criado pelo administrador tem o nível do tipo em que se baseia) e o admin master
# fica acima de todos. Alcance "abaixo" = os registros da própria pessoa e os de quem tem nível menor, na mesma AR.
NIVEIS = {"admin": 4, "gestor": 3, "funcionario": 2, "vendedor": 1, "parceiro": 0}
NIVEL_MASTER = 5


@dataclass(frozen=True)
class Permissao:
    codigo: str
    grupo: str
    nome: str
    com_escopo: bool = False      # trata de registros com dono (lead, parceiro, venda...)
    modulo: str = ""              # some quando o módulo é desligado
    padrao: str = ""              # quem tem hoje: A=admin, G=admin+gestor, F=+funcionário, E=equipe toda, P=parceiro


# Padrões = o acesso que cada perfil tinha antes das permissões em camadas, com a hierarquia de 17/11/2026 por cima:
# gestor e funcionário veem o que é deles e o de quem está abaixo (ver padrao_do_perfil).
CATALOGO = [
    Permissao("painel.ver", "Painel", "Ver o Dashboard e os avisos", True, padrao="E"),
    Permissao("relatorios.ver", "Painel", "Ver relatórios", True, padrao="E"),
    Permissao("relatorios.exportar", "Painel", "Exportar relatórios (planilha/PDF)", True, padrao="E"),
    Permissao("inteligencia.ver", "Painel", "Ver a Inteligência de prospecção", True, padrao="E"),

    Permissao("leads.ver", "Leads", "Ver leads e o pipeline", True, padrao="E"),
    Permissao("leads.criar", "Leads", "Cadastrar leads", padrao="E"),
    Permissao("leads.editar", "Leads", "Editar e trabalhar leads", True, padrao="E"),
    Permissao("leads.atribuir", "Leads", "Trocar o vendedor responsável pelo lead", padrao="G"),
    Permissao("leads.importar", "Leads", "Importar planilha de leads", padrao="E"),
    Permissao("leads.exportar", "Leads", "Exportar leads", True, padrao="E"),
    Permissao("leads.excluir", "Leads", "Excluir dados do lead (LGPD)", padrao="G"),
    Permissao("leads.liberar_contato", "Leads", "Desfazer opt-out (contato autorizou de novo)", padrao="G"),
    Permissao("prospeccao.buscar", "Leads", "Buscar empresas (Prospecção)", True, "prospeccao", padrao="E"),
    # Assertiva (18/11/2026): cada consulta é cobrada da marca; administrador e gestor por padrão
    Permissao("assertiva.consultar", "Leads", "Consultar na Assertiva (CPF, CNPJ, telefone, e-mail; cobrado por consulta)",
              modulo="assertiva", padrao="G"),

    # Sem alcance desde 16/11/2026 (pedido da Maria): a equipe toda vê e atende todas as respostas da AR
    Permissao("oportunidades.ver", "IA SDR", "Ver e atender as oportunidades (todas: a equipe toda vê)", padrao="E"),
    Permissao("oportunidades.respostas", "IA SDR", "Ver todas as respostas recebidas", padrao="G"),
    Permissao("campanhas.ver", "IA SDR", "Ver campanhas", True, "campanhas", "E"),
    Permissao("campanhas.criar", "IA SDR", "Criar campanhas", modulo="campanhas", padrao="E"),
    Permissao("campanhas.gerenciar", "IA SDR", "Aprovar, pausar, arquivar e excluir campanhas", True, "campanhas", "E"),
    Permissao("campanhas.excluir_andamento", "IA SDR", "Excluir campanha em andamento", modulo="campanhas", padrao="G"),
    Permissao("campanhas.escolher_numero", "IA SDR", "Escolher o número de WhatsApp da campanha", modulo="campanhas",
              padrao="A"),
    Permissao("campanhas.whatsapp_sozinho", "IA SDR",
              "Ligar o WhatsApp automático da campanha (contato frio sai sem clique)", modulo="campanhas", padrao="A"),
    # Renovação e Empresas novas valem para a AR toda (planilha da certificadora, busca paga na CNPJá): só quem
    # configura abre essas telas (17/11/2026); as campanhas delas seguem a hierarquia, como as outras
    Permissao("campanhas.configurar", "IA SDR",
              "Configurar a Renovação e as Empresas novas (planilha, textos, avisos e busca paga na CNPJá)",
              modulo="campanhas", padrao="G"),
    Permissao("fila.ver", "IA SDR", "Ver a fila de mensagens", True, padrao="E"),
    Permissao("fila.enviar", "IA SDR", "Enviar e editar mensagens da fila", True, padrao="E"),
    Permissao("envios.ver", "IA SDR", "Ver os envios", True, padrao="E"),

    Permissao("agenda.ver", "Agenda", "Ver a Agenda de prospecção", True, "agenda", "E"),
    Permissao("tarefas.editar", "Agenda", "Concluir, adiar e agendar tarefas", True, padrao="E"),

    Permissao("cadencias.ver", "Ferramentas", "Ver cadências", padrao="E"),
    Permissao("cadencias.editar", "Ferramentas", "Criar e alterar cadências", padrao="F"),
    Permissao("templates.ver", "Ferramentas", "Ver templates de mensagem", padrao="E"),
    Permissao("templates.editar", "Ferramentas", "Criar e alterar templates", padrao="F"),
    Permissao("categorias.ver", "Ferramentas", "Ver categorias de parceiros", padrao="F"),
    Permissao("categorias.sugerir", "Ferramentas", "Pedir à IA sugestões de categorias", padrao="F"),
    Permissao("categorias.editar", "Ferramentas", "Alterar categorias de parceiros", padrao="A"),
    Permissao("conhecimento.ver", "Ferramentas", "Ver a base de conhecimento", padrao="E"),
    Permissao("conhecimento.editar", "Ferramentas", "Alterar a base de conhecimento", padrao="F"),

    Permissao("parceiros.ver", "Parceiros", "Ver parceiros", True, padrao="E"),
    Permissao("parceiros.editar", "Parceiros", "Cadastrar e editar parceiros", True, padrao="E"),
    Permissao("parceiros.comercial", "Parceiros", "Comissão, chave Pix e vendedor do parceiro", padrao="G"),
    Permissao("parceiros.exportar", "Parceiros", "Exportar parceiros", True, padrao="E"),
    Permissao("clientes.ver", "Parceiros", "Ver clientes", True, padrao="E"),
    Permissao("clientes.editar", "Parceiros", "Cadastrar e editar clientes", True, padrao="E"),
    Permissao("clientes.exportar", "Parceiros", "Exportar clientes", True, padrao="E"),

    Permissao("vendas.ver", "Vendas", "Ver vendas", True, "vendas", "E"),
    Permissao("vendas.criar", "Vendas", "Registrar vendas", modulo="vendas", padrao="E"),
    Permissao("vendas.atribuir", "Vendas", "Escolher o vendedor da venda", modulo="vendas", padrao="G"),
    Permissao("vendas.excluir", "Vendas", "Excluir vendas", modulo="vendas", padrao="A"),
    Permissao("vendas.exportar", "Vendas", "Exportar vendas", True, "vendas", "E"),
    Permissao("comissoes.ver", "Vendas", "Ver comissões", True, "vendas", "E"),
    Permissao("comissoes.pagar", "Vendas", "Marcar comissões como pagas", modulo="vendas", padrao="A"),
    Permissao("comissoes.exportar", "Vendas", "Exportar comissões", True, "vendas", "E"),
    Permissao("produtos.editar", "Vendas", "Alterar produtos e preços", modulo="vendas", padrao="A"),
    Permissao("vencimentos.ver", "Vendas", "Ver vencimentos", True, "vendas", "E"),
    Permissao("vencimentos.editar", "Vendas", "Mudar a situação de um certificado", True, "vendas", "E"),
    Permissao("vencimentos.importar", "Vendas", "Importar planilha de vencimentos", modulo="vendas", padrao="G"),
    Permissao("vencimentos.exportar", "Vendas", "Exportar vencimentos", True, "vendas", "E"),

    Permissao("conversas.ver", "Comunicação", "Ver as conversas de WhatsApp", modulo="conversas", padrao="E"),
    Permissao("conversas.enviar", "Comunicação", "Responder pelas Conversas", modulo="conversas", padrao="E"),
    # "Apagar conversa" (25/11/2026): some do sistema para toda a equipe e não volta; administrador e gestor por padrão
    Permissao("conversas.apagar", "Comunicação", "Apagar conversas inteiras das Conversas (não dá para desfazer)",
              modulo="conversas", padrao="G"),
    # Tela API Oficial (21/11/2026): as conversas do número oficial da Meta; a equipe toda acompanha as respostas
    Permissao("oficial.ver", "Comunicação", "Ver as conversas da API oficial do WhatsApp", modulo="api_oficial",
              padrao="E"),
    Permissao("whatsapp.ver", "Comunicação", "Conectar e usar o próprio WhatsApp", padrao="E"),
    Permissao("whatsapp.gerenciar_todos", "Comunicação", "Gerenciar o WhatsApp de todos", padrao="A"),
    Permissao("whatsapp.compartilhar_todos", "Comunicação", "Compartilhar o WhatsApp de qualquer pessoa", padrao="G"),
    Permissao("whatsapp.regras", "Comunicação", "Mudar as regras de envio do WhatsApp", padrao="A"),
    Permissao("email.ver", "Comunicação", "Conectar e usar o próprio e-mail", padrao="E"),
    Permissao("email.gerenciar_todas", "Comunicação", "Gerenciar o e-mail de todos (e o principal)", padrao="A"),
    Permissao("email.compartilhar_todas", "Comunicação", "Compartilhar o e-mail de qualquer pessoa", padrao="G"),
    Permissao("email.outro_dominio", "Comunicação", "Enviar pelo próprio domínio e servidor de e-mail (fora do domínio da empresa)",
              padrao="G"),

    Permissao("ia.usar", "IA", "Usar a IA Comercial", modulo="ia_comercial", padrao="E"),

    Permissao("configuracoes.ver", "Administração", "Ver as Configurações", padrao="A"),
    Permissao("configuracoes.alterar", "Administração", "Alterar configurações, e-mail principal e base da Receita",
              padrao="A"),
    Permissao("usuarios.gerenciar", "Administração", "Criar e editar usuários", padrao="A"),
    Permissao("permissoes.gerenciar", "Administração", "Mudar papéis, permissões, exceções e módulos", padrao="A"),

    Permissao("portal.usar", "Portal do parceiro", "Usar o portal do parceiro", modulo="portal", padrao="P"),
]
POR_CODIGO = {p.codigo: p for p in CATALOGO}

# Módulos (chaves de funcionalidade). Vendas e Agenda continuam usando as chaves que já existiam.
MODULOS = {
    "vendas": ("Vendas, Vencimentos e Comissões", "mostrar_vendas"),
    "agenda": ("Agenda de prospecção", "mostrar_agenda"),
    "campanhas": ("IA SDR (campanhas)", "modulo_campanhas"),
    "prospeccao": ("Prospecção (buscar empresas)", "modulo_prospeccao"),
    "assertiva": ("Consultas na Assertiva (CPF, CNPJ, telefone, e-mail)", "modulo_assertiva"),
    "conversas": ("Conversas de WhatsApp", "modulo_conversas"),
    "api_oficial": ("Conversas da API oficial do WhatsApp", "modulo_api_oficial"),
    "ia_comercial": ("IA Comercial", "modulo_ia_comercial"),
    "portal": ("Portal do parceiro", "modulo_portal"),
    # sem permissões ligadas: só decide se o 2º e-mail em diante sai em HTML com a marca (visual.html_da_marca_ligado)
    "email_html": ("E-mail em HTML com a marca", "modulo_email_html"),
}
# Quem tem uma destas precisa da verificação em 2 etapas (como o admin e o gestor).
SENSIVEIS = ("configuracoes.alterar", "usuarios.gerenciar", "permissoes.gerenciar")
# Ninguém recebe NEGAR nestas (evita trancar o sistema sem administrador).
NAO_NEGAVEIS = ("permissoes.gerenciar",)


def so_ver(p: Permissao) -> bool:
    """Permissão só de ver (ou de exportar o que vê), sem mexer no registro."""
    return p.codigo.endswith((".ver", ".exportar"))


def padrao_do_perfil(perfil: str, p: Permissao) -> str:
    """Alcance padrão do perfil (ou "" se ele não tem). Hierarquia (17/11/2026): o administrador vê tudo; o gestor vê
    e cuida do que é dele e de quem está abaixo; o funcionário vê o de quem está abaixo e mexe só no dele; o vendedor
    fica com o dele."""
    if perfil == "parceiro":
        return TUDO if p.padrao == "P" else ""
    if perfil == "admin":
        return TUDO if p.padrao != "P" else ""
    if perfil == "gestor":
        return (ABAIXO if p.com_escopo else TUDO) if p.padrao in ("G", "F", "E") else ""
    if perfil == "funcionario" and p.padrao in ("F", "E"):
        return ((ABAIXO if so_ver(p) else PROPRIOS) if p.com_escopo else TUDO)
    if perfil == "vendedor" and p.padrao == "E":
        return PROPRIOS if p.com_escopo else TUDO
    return ""


def permitidas_no_perfil(perfil: str, p: Permissao) -> bool:
    """Parceiro só usa o portal; a equipe nunca usa o portal (ele mostra os dados de um parceiro só)."""
    return (p.modulo == "portal") == (perfil == "parceiro")


# ---------------------------------------------------------------- Preparação do banco

def preparar(db: Session) -> None:
    """Cria os 5 papéis do sistema e dá aos papéis as permissões novas do catálogo (com o padrão do perfil base).
    Nunca mexe no que o administrador já escolheu. Garante um admin master."""
    from . import config

    garantir_master(db)

    existentes = {p.codigo: p for p in db.execute(select(Papel)).scalars()}
    for codigo in PERFIS_BASE:
        if codigo not in existentes:
            papel = Papel(codigo=codigo, nome=config.PERFIS[codigo], base=codigo, sistema=True)
            db.add(papel)
            db.flush()
            existentes[codigo] = papel
    for papel in existentes.values():
        conhecidas = set(filter(None, (papel.permissoes_conhecidas or "").split(",")))
        novas = [p for p in CATALOGO if p.codigo not in conhecidas]
        if not novas:
            continue
        tem = {c for (c,) in db.execute(select(PermissaoPapel.permissao).where(PermissaoPapel.papel_id == papel.id))}
        for p in novas:
            escopo = padrao_do_perfil(papel.base, p)
            if escopo and p.codigo not in tem:
                db.add(PermissaoPapel(papel_id=papel.id, permissao=p.codigo, escopo=escopo))
        papel.permissoes_conhecidas = ",".join(sorted(conhecidas | {p.codigo for p in novas}))
    _aplicar_hierarquia(db, existentes)
    db.flush()


def _aplicar_hierarquia(db: Session, papeis: dict) -> None:
    """Uma vez só (17/11/2026, pedido da Maria): os papéis Gestor e Funcionário do sistema passam a ver o que é de
    quem está abaixo. Só troca o que ainda está no padrão antigo (o que o administrador mudou à mão fica)."""
    from .banco import gravar_config, ler_config

    if ler_config(db, "permissoes_hierarquia") == "1":
        return
    for codigo, antigo in (("gestor", TUDO), ("funcionario", PROPRIOS)):
        papel = papeis.get(codigo)
        if papel is None or not papel.sistema:
            continue
        for r in db.execute(select(PermissaoPapel).where(PermissaoPapel.papel_id == papel.id)).scalars():
            p = POR_CODIGO.get(r.permissao)
            if p is not None and p.com_escopo and r.escopo == antigo:
                r.escopo = padrao_do_perfil(codigo, p) or r.escopo
    gravar_config(db, "permissoes_hierarquia", "1")


# ---------------------------------------------------------------- Admin master e travas contra escalada
# Pedido da Maria em 13/11/2026 ("Sim, corrigir"): ninguém toma a conta do admin master (Paulo Marinho), só ele
# cria ou promove administradores e ninguém dá a alguém (ou a si mesmo) um poder que não tem. Vale no servidor, em
# Configurações > Usuários, em Permissões e no compartilhamento de WhatsApp/e-mail (o menu só esconde por conforto).

def garantir_master(db: Session) -> None:
    """Sem admin master ativo: o administrador ativo mais antigo vira o master (no sistema da MS, o Paulo Marinho)."""
    if db.execute(select(Usuario.id).where(Usuario.master.is_(True), Usuario.ativo.is_(True))).first():
        return
    primeiro = db.execute(select(Usuario).where(Usuario.perfil == "admin", Usuario.ativo.is_(True))
                          .order_by(Usuario.id)).scalars().first()
    if primeiro is not None:
        primeiro.master = True
        db.flush()


def e_master(usuario: Usuario | None) -> bool:
    return bool(usuario is not None and usuario.ativo and getattr(usuario, "master", False))


def papel_da_poder_de_admin(db: Session, papel: Papel | None) -> bool:
    """O papel é o de administrador ou tem alguma permissão de administração (SENSIVEIS)."""
    if papel is None:
        return False
    if papel.base == "admin":
        return True
    return db.execute(select(PermissaoPapel.id).where(PermissaoPapel.papel_id == papel.id,
                                                      PermissaoPapel.permissao.in_(SENSIVEIS))).first() is not None


def tem_poder_de_admin(db: Session, usuario: Usuario) -> bool:
    """A pessoa é administradora (ou master) ou tem, pelo papel ou por exceção, um poder de administração."""
    if getattr(usuario, "master", False) or usuario.perfil == "admin":
        return True
    efet = _calcular(db, usuario)[0]
    return any(p in efet for p in SENSIVEIS)


def motivo_para_nao_alterar(db: Session, quem: Usuario, alvo: Usuario | None) -> str:
    """Por que `quem` não pode alterar o cadastro, a senha, o 2FA ou as permissões de `alvo` ("" = pode). O master só é
    alterado por ele mesmo; quem tem poder de administrador, só pelo master (ou por si mesmo)."""
    if alvo is None or alvo.id == quem.id or e_master(quem):
        return ""
    if getattr(alvo, "master", False):
        return "Só o próprio admin master altera o cadastro, a senha, o código do celular e as permissões dele."
    if tem_poder_de_admin(db, alvo):
        return ("Só o admin master altera o cadastro, a senha, o código do celular e as permissões de um administrador "
                "(ou de quem tem poderes de administração).")
    return ""


def motivo_para_nao_dar_papel(db: Session, quem: Usuario, papel: Papel | None) -> str:
    """Ninguém dá um poder que não tem: só o master dá o papel de administrador ou um papel com poderes de
    administração ("" = pode)."""
    if papel is not None and papel_da_poder_de_admin(db, papel) and not e_master(quem):
        return ("Só o admin master dá o papel de administrador (ou um papel com poderes de administração, como criar "
                "usuários ou mudar permissões).")
    return ""


def motivo_para_nao_compartilhar(db: Session, quem: Usuario, dono_id: int | None, antes_todos: bool,
                                 antes_ids: list[int], todos: bool, ids: list[int]) -> str:
    """Compartilhar o WhatsApp/e-mail de outra pessoa (gestor, administrador): não pode se incluir, nem liberar para
    toda a equipe (que inclui quem compartilha), nem mexer no de um administrador ou do master. O dono da conta e o
    master podem tudo ("" = pode)."""
    if dono_id == quem.id or e_master(quem):
        return ""
    dono = db.get(Usuario, dono_id) if dono_id else None
    if dono is not None and tem_poder_de_admin(db, dono):
        return "Só o próprio dono (ou o admin master) compartilha o WhatsApp ou o e-mail de um administrador."
    if quem.id in ids and quem.id not in antes_ids:
        return ("Você não pode compartilhar com você mesmo o WhatsApp ou o e-mail de outra pessoa: peça ao dono "
                "(cada usuário dispara só pelo que é dele ou foi compartilhado por quem é dono).")
    if todos and not antes_todos:
        return "Só o dono (ou o admin master) libera o WhatsApp ou o e-mail dele para toda a equipe."
    return ""


# ---------------------------------------------------------------- Cálculo das permissões de uma pessoa

def _sessao(usuario: Usuario) -> Session | None:
    return object_session(usuario)


def papel_de(db: Session, usuario: Usuario) -> Papel | None:
    if usuario.papel_id:
        papel = db.get(Papel, usuario.papel_id)
        if papel is not None:
            return papel
    return db.execute(select(Papel).where(Papel.codigo == usuario.perfil)).scalars().first()


def modulos_ligados(db: Session) -> dict[str, bool]:
    from .banco import ler_config

    return {m: ler_config(db, chave) != "0" for m, (_, chave) in MODULOS.items()}


def _calcular(db: Session, usuario: Usuario) -> tuple[dict[str, str], dict[str, str]]:
    """Devolve (permissões efetivas {codigo: alcance}, motivo de cada decisão {codigo: texto})."""
    papel = papel_de(db, usuario)
    do_papel = {}
    if papel is not None:
        do_papel = {r.permissao: r.escopo for r in db.execute(
            select(PermissaoPapel).where(PermissaoPapel.papel_id == papel.id)).scalars()}
    hoje = date.today()
    excecoes = [e for e in db.execute(select(ExcecaoPermissao).where(ExcecaoPermissao.usuario_id == usuario.id))
                .scalars() if e.ate is None or e.ate >= hoje]
    negadas = {e.permissao for e in excecoes if e.efeito == "negar"}
    permitidas = {e.permissao: e for e in excecoes if e.efeito == "permitir"}
    ligados = modulos_ligados(db)
    nome_papel = papel.nome if papel else usuario.perfil
    efetivas, motivos = {}, {}
    for p in CATALOGO:
        if not permitidas_no_perfil(usuario.perfil, p):
            motivos[p.codigo] = "não se aplica a este tipo de usuário"
            continue
        if p.modulo and not ligados.get(p.modulo, True):
            motivos[p.codigo] = f"módulo desligado: {MODULOS[p.modulo][0]}"
            continue
        if p.codigo in negadas and p.codigo not in NAO_NEGAVEIS:
            motivos[p.codigo] = "exceção NEGAR deste usuário"
            continue
        if p.codigo in permitidas:
            e = permitidas[p.codigo]
            escopo = (e.escopo or do_papel.get(p.codigo) or PROPRIOS) if p.com_escopo else TUDO
            efetivas[p.codigo] = escopo
            motivos[p.codigo] = "exceção PERMITIR" + (f" até {e.ate:%d/%m/%Y}" if e.ate else "")
            continue
        if p.codigo in do_papel:
            efetivas[p.codigo] = do_papel[p.codigo] if p.com_escopo else TUDO
            motivos[p.codigo] = f"papel {nome_papel}"
            continue
        motivos[p.codigo] = f"o papel {nome_papel} não tem"
    return efetivas, motivos


def efetivas(usuario: Usuario | None, db: Session | None = None) -> dict[str, str]:
    """Permissões da pessoa {codigo: alcance}. Calculadas uma vez por pedido (guardadas no próprio objeto)."""
    if usuario is None:
        return {}
    guardado = usuario.__dict__.get("_permissoes")
    if guardado is not None:
        return guardado
    db = db or _sessao(usuario)
    if db is None:
        from .banco import sessao

        with sessao() as nova:
            resultado = _calcular(nova, usuario)[0]
    else:
        resultado = _calcular(db, usuario)[0]
    usuario.__dict__["_permissoes"] = resultado
    return resultado


def explicar(db: Session, usuario: Usuario) -> list[dict]:
    """Para a tela "acesso real": cada permissão, se vale, com que alcance e por quê."""
    efet, motivos = _calcular(db, usuario)
    return [{"p": p, "escopo": efet.get(p.codigo, ""), "motivo": motivos.get(p.codigo, "")} for p in CATALOGO]


def esquecer(usuario: Usuario) -> None:
    """Depois de mudar papel/exceções na mesma conexão com o banco."""
    usuario.__dict__.pop("_permissoes", None)
    usuario.__dict__.pop("_equipe_ids", None)
    usuario.__dict__.pop("_abaixo_ids", None)


def escopo(usuario: Usuario | None, permissao: str) -> str:
    """Alcance da permissão ("" = não tem)."""
    return efetivas(usuario).get(permissao, "")


def ve_tudo(usuario: Usuario | None, permissao: str) -> bool:
    return escopo(usuario, permissao) == TUDO


def ids_da_equipe(usuario: Usuario) -> set[int]:
    guardado = usuario.__dict__.get("_equipe_ids")
    if guardado is not None:
        return guardado
    ids = {usuario.id}
    db = _sessao(usuario)
    if usuario.equipe_id and db is not None:
        ids |= {i for (i,) in db.execute(select(Usuario.id).where(Usuario.equipe_id == usuario.equipe_id))}
    usuario.__dict__["_equipe_ids"] = ids
    return ids


def nivel(usuario: Usuario, db: Session | None = None) -> int:
    """Lugar da pessoa na hierarquia (NIVEIS): o do tipo base do papel dela; o admin master fica acima de todos."""
    if getattr(usuario, "master", False):
        return NIVEL_MASTER
    db = db or _sessao(usuario)
    papel = papel_de(db, usuario) if db is not None else None
    return NIVEIS.get(papel.base if papel is not None else usuario.perfil, 0)


def ids_abaixo(usuario: Usuario) -> set[int]:
    """A própria pessoa e quem tem papel de nível mais baixo, na mesma AR (inclusive quem já saiu: o que era dessas
    pessoas continua com quem está acima)."""
    guardado = usuario.__dict__.get("_abaixo_ids")
    if guardado is not None:
        return guardado
    ids = {usuario.id}
    db = _sessao(usuario)
    if db is not None:
        meu = nivel(usuario, db)
        bases = {pid: base for pid, base in db.execute(select(Papel.id, Papel.base))}
        consulta = select(Usuario.id, Usuario.perfil, Usuario.papel_id, Usuario.master)
        if getattr(usuario, "tenant_id", None) is not None:
            consulta = consulta.where(Usuario.tenant_id == usuario.tenant_id)
        for uid, perfil, papel_id, master in db.execute(consulta):
            outro = NIVEL_MASTER if master else NIVEIS.get(bases.get(papel_id) or perfil, 0)
            if outro < meu:
                ids.add(uid)
    usuario.__dict__["_abaixo_ids"] = ids
    return ids


def donos_visiveis(usuario: Usuario, permissao: str) -> set[int] | None:
    """None = todos; senão, os ids dos donos cujos registros a pessoa alcança (vazio = nenhum)."""
    alcance = escopo(usuario, permissao)
    if alcance == TUDO:
        return None
    if alcance == ABAIXO:
        return ids_abaixo(usuario)
    if alcance == EQUIPE:
        return ids_da_equipe(usuario)
    if alcance == PROPRIOS:
        return {usuario.id}
    return set()


def escolhe_de_quem(usuario: Usuario | None, permissao: str) -> bool:
    """A pessoa alcança registros de outras pessoas nesta permissão (tudo, quem está abaixo ou a equipe)? Então as
    telas mostram o filtro "de quem" para ela escolher."""
    if usuario is None:
        return False
    ids = donos_visiveis(usuario, permissao)
    return ids is None or len(ids) > 1


def pessoas_visiveis(usuario: Usuario | None, permissao: str, pessoas) -> list:
    """Das pessoas da lista, as que entram no filtro "de quem" da tela (as que a pessoa alcança nesta permissão);
    lista vazia quando ela só alcança a si mesma."""
    if not escolhe_de_quem(usuario, permissao):
        return []
    ids = donos_visiveis(usuario, permissao)
    return [p for p in pessoas if ids is None or p.id in ids]


def quem_tem(db: Session, permissao: str, ar: int | None) -> list[Usuario]:
    """As pessoas ativas da equipe da AR `ar` (sem o portal do parceiro e sem o Admin Master, que é da plataforma) que
    têm a permissão, com os módulos ligados nessa AR. Para as telas que mostram "quem vê" (o número oficial na tela
    WhatsApp, pedido da Maria em 23/11/2026). Calcula sem guardar nada nas pessoas (a conta é a da AR `ar`)."""
    from .banco import usar_config_da_ar

    if permissao not in POR_CODIGO:
        raise ValueError(f"Permissão desconhecida: {permissao}")
    anterior = db.info.get("ar_config")
    usar_config_da_ar(db, ar)
    try:
        pessoas = db.execute(select(Usuario).where(Usuario.ativo.is_(True), Usuario.perfil != "parceiro",
                                                   Usuario.tenant_id == ar).order_by(Usuario.nome)).scalars().all()
        return [p for p in pessoas if permissao in _calcular(db, p)[0]]
    finally:
        usar_config_da_ar(db, anterior)


def dono_de(obj) -> set[int | None]:
    """Quem é o dono do registro, para conferir o alcance."""
    nome = type(obj).__name__
    if nome in ("Lead", "Parceiro", "Venda"):
        return {obj.vendedor_id}
    if nome in ("Cliente", "Certificado"):
        return {obj.parceiro.vendedor_id if obj.parceiro else None}
    if nome in ("Campanha", "Busca"):
        return {obj.usuario_id}
    if nome == "Tarefa":
        return {obj.usuario_id} | ({obj.lead.vendedor_id} if obj.lead else set())
    if nome == "Oportunidade":
        return {obj.lead.vendedor_id if obj.lead else None}
    raise ValueError(f"Registro sem regra de dono: {nome}")


_SEM = object()


def pode(usuario: Usuario | None, permissao: str, obj=None, *, dono=_SEM, sem_dono: bool = False) -> bool:
    """A pessoa tem a permissão (e, se informado o registro ou o dono, alcança esse registro)?
    sem_dono=True: registro sem dono conta como alcançável (ex.: oportunidade de lead ainda sem vendedor)."""
    if permissao not in POR_CODIGO:
        raise ValueError(f"Permissão desconhecida: {permissao}")
    if usuario is None or not usuario.ativo:
        return False
    alcance = escopo(usuario, permissao)
    if not alcance:
        return False
    if obj is None and dono is _SEM:
        return True
    if alcance == TUDO:
        return True
    donos = dono_de(obj) if dono is _SEM else (set(dono) if isinstance(dono, (set, list, tuple)) else {dono})
    if None in donos and sem_dono:
        return True
    visiveis = donos_visiveis(usuario, permissao) or set()
    return any(d in visiveis for d in donos if d is not None)


def garantir(usuario: Usuario, permissao: str, obj, *, sem_dono: bool = False):
    """Devolve o registro se a pessoa pode; senão 404 (igual a "não existe", para não revelar dados)."""
    if obj is None or not pode(usuario, permissao, obj, sem_dono=sem_dono):
        raise HTTPException(404)
    return obj


def ids_que_pode(usuario: Usuario | None, permissao: str, registros) -> set[int]:
    """Dos registros, os ids dos que a pessoa alcança com a permissão (a mesma conta de `pode`, com o alcance calculado
    uma vez só). Ex.: as campanhas que ela pode abrir, para a tela só pôr o link onde ele abre."""
    if not pode(usuario, permissao):
        return set()
    visiveis = donos_visiveis(usuario, permissao)
    return {r.id for r in registros if r is not None
            and (visiveis is None or any(d in visiveis for d in dono_de(r) if d is not None))}


def filtrar(consulta, usuario: Usuario, permissao: str, coluna, sem_dono: bool = False):
    """Restringe a consulta aos registros que a pessoa alcança."""
    ids = donos_visiveis(usuario, permissao)
    if ids is None:
        return consulta
    if not ids:
        return consulta.where(false())
    condicao = coluna.in_(sorted(ids))
    return consulta.where(or_(condicao, coluna.is_(None)) if sem_dono else condicao)


def mensagem_sem_permissao(db: Session, permissao: str) -> str:
    p = POR_CODIGO[permissao]
    if p.modulo and not modulos_ligados(db).get(p.modulo, True):
        # Desde a Fase 3 os módulos são de cada AR e só o Admin Master liga, no Painel master (até 19/11/2026 o aviso
        # mandava todos para Permissões > Módulos, aba que só ele vê). Fora de uma AR vale o padrão da plataforma,
        # que ele muda nessa aba.
        from .banco import _ar_da_config

        onde = ("Painel master > Módulos de cada AR" if _ar_da_config(db)
                else "Permissões > Módulos (padrão da plataforma)")
        return f"A parte \"{MODULOS[p.modulo][0]}\" está desligada. Quem liga é o admin master, em {onde}."
    return f"Você não tem permissão para isso ({p.nome.lower()}). Se precisar, peça ao administrador."


def exige(*permissoes: str):
    """Dependência das rotas: só deixa passar quem tem TODAS as permissões informadas."""
    from .seguranca import SemPermissao, usuario_logado

    for codigo in permissoes:
        if codigo not in POR_CODIGO:
            raise ValueError(f"Permissão desconhecida: {codigo}")

    def _checar(usuario: Usuario = Depends(usuario_logado)) -> Usuario:
        for codigo in permissoes:
            if not pode(usuario, codigo):
                raise SemPermissao(mensagem_sem_permissao(_sessao(usuario), codigo))
        return usuario

    return _checar


# ---------------------------------------------------------------- White label, Fase 3: o que é da plataforma

MSG_DA_PLATAFORMA = ("Este é um modelo da plataforma, usado por todas as ARs: só o admin master muda. Para ajustar só "
                     "na sua AR, crie um novo (pode copiar deste).")


def da_plataforma(obj) -> bool:
    """Registro que vale para todas as ARs: modelo, cadência ou papel sem AR, e as categorias (que não têm AR)."""
    return obj is not None and getattr(obj, "tenant_id", None) is None


def pode_mudar(usuario, obj) -> bool:
    """O que é da plataforma só o Admin Master muda; o que é da AR, quem tem a permissão da tela."""
    return e_master(usuario) or not da_plataforma(obj)
