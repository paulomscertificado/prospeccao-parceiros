"""Permissões em camadas: papéis, permissões "recurso.acao", alcance, exceções por usuário e módulos.

Ordem de decisão de uma permissão (ver docs/permissoes.md):
  1. módulo desligado            -> NEGA para todos
  2. NEGAR do usuário            -> NEGA
  3. PERMITIR do usuário         -> PERMITE (com o alcance da exceção, ou o do papel)
  4. permissão do papel          -> PERMITE (com o alcance do papel)
  5. nada disso                  -> NEGA

Alcance ("escopo") das permissões que tratam de dados com dono:
  tudo      -> qualquer registro
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

TUDO, EQUIPE, PROPRIOS = "tudo", "equipe", "proprios"
ESCOPOS = {TUDO: "Tudo", EQUIPE: "Só a equipe", PROPRIOS: "Só os próprios"}
_ORDEM = {PROPRIOS: 1, EQUIPE: 2, TUDO: 3}
PERFIS_BASE = ("admin", "gestor", "funcionario", "vendedor", "parceiro")


@dataclass(frozen=True)
class Permissao:
    codigo: str
    grupo: str
    nome: str
    com_escopo: bool = False      # trata de registros com dono (lead, parceiro, venda...)
    modulo: str = ""              # some quando o módulo é desligado
    padrao: str = ""              # quem tem hoje: A=admin, G=admin+gestor, F=+funcionário, E=equipe toda, P=parceiro


# Padrões = exatamente o acesso que cada perfil tinha antes das permissões em camadas (ninguém ganha nem perde).
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

    Permissao("oportunidades.ver", "IA SDR", "Ver e assumir oportunidades", True, padrao="E"),
    Permissao("oportunidades.respostas", "IA SDR", "Ver todas as respostas recebidas", padrao="G"),
    Permissao("campanhas.ver", "IA SDR", "Ver campanhas", True, "campanhas", "E"),
    Permissao("campanhas.criar", "IA SDR", "Criar campanhas", modulo="campanhas", padrao="E"),
    Permissao("campanhas.gerenciar", "IA SDR", "Aprovar, pausar, arquivar e excluir campanhas", True, "campanhas", "E"),
    Permissao("campanhas.excluir_andamento", "IA SDR", "Excluir campanha em andamento", modulo="campanhas", padrao="G"),
    Permissao("campanhas.escolher_numero", "IA SDR", "Escolher o número de WhatsApp da campanha", modulo="campanhas",
              padrao="A"),
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
    Permissao("whatsapp.ver", "Comunicação", "Conectar e usar o próprio WhatsApp", padrao="E"),
    Permissao("whatsapp.gerenciar_todos", "Comunicação", "Gerenciar o WhatsApp de todos", padrao="A"),
    Permissao("whatsapp.compartilhar_todos", "Comunicação", "Compartilhar o WhatsApp de qualquer pessoa", padrao="G"),
    Permissao("whatsapp.regras", "Comunicação", "Mudar as regras de envio do WhatsApp", padrao="A"),
    Permissao("email.ver", "Comunicação", "Conectar e usar o próprio e-mail", padrao="E"),
    Permissao("email.gerenciar_todas", "Comunicação", "Gerenciar o e-mail de todos (e o principal)", padrao="A"),
    Permissao("email.compartilhar_todas", "Comunicação", "Compartilhar o e-mail de qualquer pessoa", padrao="G"),

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
    "conversas": ("Conversas de WhatsApp", "modulo_conversas"),
    "ia_comercial": ("IA Comercial", "modulo_ia_comercial"),
    "portal": ("Portal do parceiro", "modulo_portal"),
}
# Quem tem uma destas precisa da verificação em 2 etapas (como o admin e o gestor).
SENSIVEIS = ("configuracoes.alterar", "usuarios.gerenciar", "permissoes.gerenciar")
# Ninguém recebe NEGAR nestas (evita trancar o sistema sem administrador).
NAO_NEGAVEIS = ("permissoes.gerenciar",)


def padrao_do_perfil(perfil: str, p: Permissao) -> str:
    """Alcance que o perfil tinha antes (ou "" se não tinha)."""
    if perfil == "parceiro":
        return TUDO if p.padrao == "P" else ""
    if perfil == "admin":
        return TUDO if p.padrao != "P" else ""
    if perfil == "gestor":
        return TUDO if p.padrao in ("G", "F", "E") else ""
    if perfil == "funcionario" and p.padrao in ("F", "E"):
        return PROPRIOS if p.com_escopo else TUDO
    if perfil == "vendedor" and p.padrao == "E":
        return PROPRIOS if p.com_escopo else TUDO
    return ""


def permitidas_no_perfil(perfil: str, p: Permissao) -> bool:
    """Parceiro só usa o portal; a equipe nunca usa o portal (ele mostra os dados de um parceiro só)."""
    return (p.modulo == "portal") == (perfil == "parceiro")


# ---------------------------------------------------------------- Preparação do banco

def preparar(db: Session) -> None:
    """Cria os 5 papéis do sistema e dá aos papéis as permissões novas do catálogo (com o padrão do perfil base).
    Nunca mexe no que o administrador já escolheu."""
    from . import config

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
    db.flush()


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


def donos_visiveis(usuario: Usuario, permissao: str) -> set[int] | None:
    """None = todos; senão, os ids dos donos cujos registros a pessoa alcança (vazio = nenhum)."""
    alcance = escopo(usuario, permissao)
    if alcance == TUDO:
        return None
    if alcance == EQUIPE:
        return ids_da_equipe(usuario)
    if alcance == PROPRIOS:
        return {usuario.id}
    return set()


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
        return (f"A parte \"{MODULOS[p.modulo][0]}\" está desligada. O administrador liga em "
                "Permissões > Módulos.")
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
