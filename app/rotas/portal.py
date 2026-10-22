"""Portal do parceiro: o escritório vê só a própria carteira, indicações, vendas e comissão."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import util
from ..banco import obter_db
from ..modelos import Certificado, Cliente, Parceiro, Tarefa, Usuario, Venda
from ..seguranca import parceiro as so_parceiro
from ..seguranca import registrar_log, verificar_csrf
from ..vendas_servico import descrever_regra, responsavel_padrao
from ..web import avisar, tela, voltar

rotas = APIRouter(prefix="/portal")


def _meu(db: Session, usuario: Usuario) -> Parceiro:
    p = db.get(Parceiro, usuario.parceiro_id) if usuario.parceiro_id else None
    if not p:
        from ..seguranca import SemPermissao

        raise SemPermissao("Seu usuário não está ligado a um parceiro. Fale com a MS.")
    return p


@rotas.get("")
def painel(request: Request, usuario: Usuario = Depends(so_parceiro), db: Session = Depends(obter_db)):
    p = _meu(db, usuario)
    vendas = db.execute(select(Venda).where(Venda.parceiro_id == p.id).order_by(Venda.data.desc())).scalars().all()
    clientes = db.execute(select(Cliente).where(Cliente.parceiro_id == p.id)).scalars().all()
    hoje = date.today()
    vencendo = db.execute(select(Certificado).where(Certificado.parceiro_id == p.id,
                                                    Certificado.status.in_(["Ativo", "Em renovação"]),
                                                    Certificado.data_vencimento <= hoje + timedelta(days=60))
                          .order_by(Certificado.data_vencimento)).scalars().all()
    tipo, valor = (p.comissao_tipo, p.comissao_valor) if p.comissao_tipo else ("", 0)
    return tela(request, "portal.html", {
        "p": p, "vendas": vendas[:30], "vencendo": vencendo,
        "totais": {"indicados": len(clientes), "vendidos": len(vendas), "comissao": sum(v.comissao for v in vendas),
                   "a_receber": sum(v.comissao for v in vendas if not v.comissao_paga),
                   "recebida": sum(v.comissao for v in vendas if v.comissao_paga),
                   "mes": sum(v.comissao for v in vendas if v.data.month == hoje.month and v.data.year == hoje.year)},
        "regra": descrever_regra(tipo, valor) if tipo else "conforme a tabela de comissão de cada produto",
    })


@rotas.get("/indicar")
def indicar_tela(request: Request, usuario: Usuario = Depends(so_parceiro), db: Session = Depends(obter_db)):
    _meu(db, usuario)
    return tela(request, "portal_indicar.html")


@rotas.post("/indicar", dependencies=[Depends(verificar_csrf)])
def indicar(request: Request, nome: str = Form(...), cnpj: str = Form(""), contato: str = Form(""),
            telefone: str = Form(""), email: str = Form(""), produto: str = Form(""), observacoes: str = Form(""),
            autorizou: str = Form(""), usuario: Usuario = Depends(so_parceiro), db: Session = Depends(obter_db)):
    p = _meu(db, usuario)
    if not nome.strip() or not (util.normalizar_telefone(telefone) or util.email_valido(email)):
        avisar(request, "Informe o nome do cliente e um telefone ou e-mail válido.", "erro")
        return voltar("/portal/indicar")
    if autorizou != "on":
        avisar(request, "Confirme que o cliente autorizou o contato da MS (LGPD).", "erro")
        return voltar("/portal/indicar")
    c = Cliente(nome=nome.strip(), cnpj=util.formatar_cnpj(cnpj), contato=contato.strip(),
                telefone=util.formatar_telefone(telefone), email=email.strip().lower(), parceiro_id=p.id,
                status="Indicado", produto_interesse=produto.strip(), origem="Indicação (portal)",
                observacoes=(observacoes.strip() + "\nCliente autorizou o contato da MS (informado pelo parceiro).").strip())
    db.add(c)
    db.flush()
    db.add(Tarefa(tipo="indicacao", cliente_id=c.id, parceiro_id=p.id, usuario_id=responsavel_padrao(db, p),
                  canal="whatsapp" if c.telefone else "email", data=date.today(), hora="09:00",
                  acao=f"Contatar cliente indicado por {p.escritorio}: {c.nome}" + (f" ({produto})" if produto else ""),
                  mensagem=f"Olá{', ' + util.primeiro_nome(contato) if contato else ''}! Aqui é da MS Certificação Digital. "
                           f"O escritório {p.escritorio} nos indicou para cuidar do seu certificado digital. "
                           f"Podemos agendar a emissão?"))
    registrar_log(db, usuario, "indicou_cliente", "cliente", c.id, c.nome, request)
    db.commit()
    avisar(request, "Indicação enviada! Nossa equipe vai entrar em contato com o cliente.")
    return voltar("/portal/clientes")


@rotas.get("/clientes")
def carteira(request: Request, usuario: Usuario = Depends(so_parceiro), db: Session = Depends(obter_db)):
    p = _meu(db, usuario)
    clientes = db.execute(select(Cliente).where(Cliente.parceiro_id == p.id).order_by(Cliente.criado_em.desc())).scalars().all()
    vendas = db.execute(select(Venda).where(Venda.parceiro_id == p.id).order_by(Venda.data.desc())).scalars().all()
    return tela(request, "portal_clientes.html", {"p": p, "clientes": clientes, "vendas": vendas})


@rotas.get("/vencimentos")
def vencimentos(request: Request, usuario: Usuario = Depends(so_parceiro), db: Session = Depends(obter_db)):
    p = _meu(db, usuario)
    certs = db.execute(select(Certificado).where(Certificado.parceiro_id == p.id)
                       .order_by(Certificado.data_vencimento)).scalars().all()
    return tela(request, "portal_vencimentos.html", {"p": p, "certs": certs})
