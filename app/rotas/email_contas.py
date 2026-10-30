"""Tela E-mail: cada pessoa cadastra o PRÓPRIO e-mail @mscertificados.com.br; o dono, o administrador e o gestor
compartilham as contas (inclusive a principal da MS) com a equipe ou com pessoas escolhidas. Ver app/contas_email.py.
"""

import json
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, contas_email, util
from ..banco import obter_db
from ..integracoes import email_imap, email_smtp
from ..modelos import ContaEmail, Usuario
from ..seguranca import criptografar, equipe, registrar_log, verificar_csrf
from ..web import avisar, tela, voltar

rotas = APIRouter()
DESTINO = "/email"


def _cartao(usuario: Usuario, c: ContaEmail, nomes: dict[int, str]) -> dict:
    cred = contas_email.credenciais(c)
    return {"id": c.id, "nome": c.nome or cred.endereco, "endereco": cred.endereco, "principal": c.principal,
            "dono": nomes.get(c.dono_id, ""), "minha": not c.principal and c.dono_id == usuario.id,
            "ativa": c.ativa if not c.principal else contas_email.principal_pronta(),
            "le_respostas": bool(cred.imap_host), "ultimo_erro": c.ultimo_erro,
            "gerenciar": contas_email.pode_gerenciar(usuario, c), "compartilhar": contas_email.pode_compartilhar(usuario, c),
            "usar": contas_email.pode_usar(usuario, c),
            "compartilhada_todos": c.compartilhada_todos, "compartilhada_com": contas_email.compartilhada_com(c)}


@rotas.get("/email")
def tela_email(request: Request, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    nomes = {u.id: u.nome for u in db.execute(select(Usuario)).scalars()}
    contas = [_cartao(usuario, c, nomes) for c in contas_email.visiveis(db, usuario)]
    db.commit()  # a principal é criada no primeiro acesso
    equipe_ = [{"id": u.id, "nome": u.nome} for u in db.execute(
        select(Usuario).where(Usuario.perfil != "parceiro", Usuario.ativo.is_(True)).order_by(Usuario.nome)).scalars()]
    try:
        por_onde = contas_email.credenciais(contas_email.para_enviar(db, usuario)).endereco
    except contas_email.SemConta as erro:
        por_onde = ""
        avisar(request, str(erro), "alerta")
    return tela(request, "email_contas.html", {"contas": contas, "equipe": equipe_, "dominio": config.EMAIL_DOMINIO,
                                               "minha": contas_email.minha(db, usuario), "por_onde": por_onde})


def _conta(db: Session, conta_id: int) -> ContaEmail:
    c = db.get(ContaEmail, conta_id)
    if c is None:
        raise HTTPException(404)
    return c


@rotas.post("/email/minha", dependencies=[Depends(verificar_csrf)])
def salvar_minha(request: Request, endereco: str = Form(...), nome_remetente: str = Form(""), senha: str = Form(""),
                 usuario_login: str = Form(""), ler_respostas: str = Form(""),
                 usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    """Cadastra ou atualiza o e-mail da própria pessoa (Google Workspace: senha de app de 16 letras)."""
    endereco = endereco.strip().lower()
    login = usuario_login.strip().lower() or endereco
    if not util.email_valido(endereco) or not util.email_valido(login):
        avisar(request, "Digite um e-mail válido.", "erro")
        return voltar(DESTINO)
    if config.EMAIL_DOMINIO and not endereco.endswith("@" + config.EMAIL_DOMINIO):
        avisar(request, f"O e-mail precisa ser do domínio @{config.EMAIL_DOMINIO} (é ele que tem a autorização "
                        "SPF/DKIM para não cair no spam).", "erro")
        return voltar(DESTINO)
    outra = db.execute(select(ContaEmail).where(ContaEmail.endereco == endereco, ContaEmail.dono_id != usuario.id,
                                                ContaEmail.principal.is_(False))).scalars().first()
    if outra or endereco == contas_email.credenciais(None).endereco:
        avisar(request, "Este e-mail já está cadastrado no sistema por outra pessoa (ou é o principal da MS). "
                        "Peça para compartilharem com você.", "erro")
        return voltar(DESTINO)
    digitada = senha.replace(" ", "").strip()
    c = contas_email.minha(db, usuario)
    if digitada and not re.fullmatch(r"[A-Za-z]{16}", digitada):
        avisar(request, f"A senha de app do Google tem 16 letras (ex.: abcd efgh ijkl mnop) e você digitou "
                        f"{len(digitada)} caracteres: parece a senha normal da conta, que não funciona aqui. Crie a "
                        "senha de app em myaccount.google.com/apppasswords.", "erro")
        return voltar(DESTINO)
    if not digitada and (c is None or not c.senha_cripto):
        avisar(request, "Informe a senha de app do Google (16 letras).", "erro")
        return voltar(DESTINO)
    if c is None:
        c = ContaEmail(dono_id=usuario.id, **contas_email.GOOGLE)
        db.add(c)
    c.endereco, c.login = endereco, login
    c.nome_remetente = (nome_remetente.strip().replace('"', "") or f"{usuario.nome} | MS Certificação Digital")[:120]
    c.nome = c.nome or f"E-mail de {usuario.nome}"
    if digitada:
        c.senha_cripto = criptografar(digitada)
    c.ler_respostas, c.ativa, c.ultimo_erro = ler_respostas == "on", True, ""
    db.flush()
    registrar_log(db, usuario, "salvou_email_proprio", "email", c.id, endereco, request)
    db.commit()
    avisar(request, f"E-mail salvo: {endereco}. Agora clique em \"Enviar e-mail de teste\".")
    return voltar(DESTINO)


@rotas.post("/email/{conta_id:int}/testar", dependencies=[Depends(verificar_csrf)])
def testar(request: Request, conta_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    c = _conta(db, conta_id)
    if not (contas_email.pode_gerenciar(usuario, c) or contas_email.pode_usar(usuario, c)):
        raise HTTPException(403)
    try:
        email_smtp.enviar(usuario.email, "Teste – e-mail das campanhas da MS Certificação Digital",
                          "Este é um e-mail de teste do sistema de Prospecção de Parceiros.\n\nSe ele chegou na caixa "
                          "de entrada (e não no spam), esta conta está pronta para as campanhas.", com_rodape=False,
                          conta=c)
        c.ultimo_erro = ""
        avisar(request, f"E-mail de teste enviado para {usuario.email}. Confira se chegou na caixa de entrada.")
    except email_smtp.ErroEmail as erro:
        c.ultimo_erro = str(erro)[:500]
        avisar(request, str(erro), "erro")
    if c.ler_respostas and not c.principal and not c.ultimo_erro:
        try:
            email_imap.testar(c)
        except email_imap.ErroImap as erro:
            c.ultimo_erro = f"Leitura das respostas: {erro}"[:500]
            avisar(request, c.ultimo_erro, "erro")
    registrar_log(db, usuario, "testou_email", "email", c.id, c.ultimo_erro[:200], request)
    db.commit()
    return voltar(DESTINO)


@rotas.post("/email/{conta_id:int}/ligar", dependencies=[Depends(verificar_csrf)])
def ligar(request: Request, conta_id: int, ativa: str = Form(""), usuario: Usuario = Depends(equipe),
          db: Session = Depends(obter_db)):
    c = _conta(db, conta_id)
    if c.principal or not contas_email.pode_gerenciar(usuario, c):
        avisar(request, "Só o dono da conta (ou o administrador) pode fazer isso.", "erro")
        return voltar(DESTINO)
    c.ativa = ativa == "1"
    registrar_log(db, usuario, "ligou_email" if c.ativa else "pausou_email", "email", c.id, c.endereco, request)
    db.commit()
    avisar(request, "Conta ligada: as campanhas voltam a sair por ela." if c.ativa else
           "Conta pausada: os e-mails das campanhas saem por outra conta liberada para a pessoa (ou esperam).")
    return voltar(DESTINO)


@rotas.post("/email/{conta_id:int}/remover", dependencies=[Depends(verificar_csrf)])
def remover(request: Request, conta_id: int, usuario: Usuario = Depends(equipe), db: Session = Depends(obter_db)):
    c = _conta(db, conta_id)
    if c.principal or not contas_email.pode_gerenciar(usuario, c):
        avisar(request, "Só o dono da conta (ou o administrador) pode remover. O principal não pode ser removido.", "erro")
        return voltar(DESTINO)
    registrar_log(db, usuario, "removeu_email", "email", c.id, c.endereco, request)
    db.delete(c)
    db.commit()
    avisar(request, "Conta removida do sistema (a senha guardada foi apagada).")
    return voltar(DESTINO)


@rotas.post("/email/compartilhar", dependencies=[Depends(verificar_csrf)])
async def compartilhar(request: Request, conta: int = Form(...), usuario: Usuario = Depends(equipe),
                       db: Session = Depends(obter_db)):
    """Com toda a equipe ou com pessoas escolhidas: o dono, o administrador e o gestor."""
    c = _conta(db, conta)
    if not contas_email.pode_compartilhar(usuario, c):
        avisar(request, "Só o dono da conta, o administrador ou o gestor podem compartilhar.", "erro")
        return voltar(DESTINO)
    form = await request.form()
    ids = sorted({int(i) for i in form.getlist("usuarios") if str(i).isdigit() and int(i) != c.dono_id})
    c.compartilhada_todos = form.get("todos") == "on"
    c.compartilhada_com = json.dumps(ids)
    nome = str(form.get("nome", "")).strip()
    if nome:
        c.nome = nome[:120]
    registrar_log(db, usuario, "email_compartilhar", "email", c.id, f"todos={c.compartilhada_todos} usuarios={ids}",
                  request)
    db.commit()
    avisar(request, "Compartilhamento salvo." if (c.compartilhada_todos or ids) else
           ("E-mail principal sem compartilhamento: agora só envia por ele quem você escolher. Quem não tiver conta "
            "própria nem compartilhada fica com os e-mails esperando." if c.principal
            else "Conta não compartilhada: só o dono usa."))
    return voltar(DESTINO)
