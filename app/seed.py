"""Dados FICTÍCIOS só para demonstração (python -m app.seed ou popular_demo.bat).

Tudo fica marcado: leads com origem "Demonstração", parceiros com "[DEMO]", clientes com origem
"Demonstração" e usuários com e-mail @demo.example. Os sites e e-mails usam o domínio reservado
.example e os telefones usam DDD inexistente: nada disso é de uma empresa ou pessoa real.
Para remover: Configurações > Apagar dados de demonstração.
"""

import random
import secrets
import sys
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select, update

from . import cadencias, score, util
from .banco import criar_tabelas, sessao
from .leads_servico import criar_lead, mudar_status, registrar_contato, registrar_resposta
from .modelos import (Busca, Cadencia, Campanha, Certificado, Cliente, Historico, Lead, LogAuditoria, Mensagem,
                      Parceiro, Produto, Tarefa, Usuario, Venda)
from .seguranca import resumir_senha
from .vendas_servico import processar_vencimentos, registrar_venda

MARCA = "[DEMO]"
DOMINIO_USUARIOS = "@demo.example"

NOMES = ["Alfa", "Beta", "Gama", "Delta", "Ômega", "Horizonte", "Pioneira", "Central", "Atlântico", "Serra",
         "Aurora", "Vértice", "Prisma", "Nobre", "Ideal", "Sólida", "Ativa", "Real", "Prime", "Integra",
         "Contorno", "Rota", "Equilíbrio", "Bússola", "Farol", "Raiz", "Ponte", "Capital", "Fiel", "Mérito"]
PREFIXOS = ["Contabilidade", "Escritório Contábil", "Assessoria Contábil", "Contábil", "Consultoria Contábil"]
CIDADES = [("São Paulo", "SP"), ("Campinas", "SP"), ("Recife", "PE"), ("Olinda", "PE"), ("Rio de Janeiro", "RJ"),
           ("Belo Horizonte", "MG"), ("Curitiba", "PR"), ("Salvador", "BA")]
RESPONSAVEIS = ["Paula Exemplo", "Carlos Exemplo", "Renata Exemplo", "Marcos Exemplo", "Juliana Exemplo", "Rafael Exemplo"]
ESPECIALIDADES = ["Contabilidade empresarial", "Abertura de empresas", "MEI e pequenas empresas",
                  "Fiscal/tributário", "Departamento pessoal", "Médicos e profissionais liberais"]


def _telefone_ficticio(n: int) -> str:
    return f"(00) 9{n:04d}-{n:04d}"  # DDD 00 não existe


def popular(db) -> dict:
    rnd = random.Random(42)
    senha = secrets.token_urlsafe(9)
    usuarios = []
    for nome, perfil in [("Gestora Demonstração", "gestor"), ("Ana Demonstração", "vendedor"),
                         ("Bruno Demonstração", "vendedor")]:
        email = util.sem_acento(nome).lower().replace(" ", ".") + DOMINIO_USUARIOS
        u = db.execute(select(Usuario).where(Usuario.email == email)).scalars().first()
        if not u:
            u = Usuario(nome=nome, email=email, senha_hash=resumir_senha(senha), perfil=perfil)
            db.add(u)
        usuarios.append(u)
    db.flush()
    vendedores = [u for u in usuarios if u.perfil == "vendedor"]
    admin = db.execute(select(Usuario).where(Usuario.perfil == "admin").order_by(Usuario.id)).scalars().first() or usuarios[0]
    cadencia = db.execute(select(Cadencia).order_by(Cadencia.id)).scalars().first()
    produtos = list(db.execute(select(Produto).where(Produto.ativo.is_(True))).scalars())
    for pr in produtos:
        if not pr.custo:
            pr.custo = round(pr.preco * 0.35, 2)  # custo de exemplo para a demonstração

    leads = []
    hoje = date.today()
    for i in range(72):
        cidade, uf = CIDADES[i % len(CIDADES)]
        nome = f"{PREFIXOS[i % len(PREFIXOS)]} {NOMES[i % len(NOMES)]}" + (f" {i // len(NOMES) + 1}" if i >= len(NOMES) else "")
        slug = f"demo{i:02d}"
        dados = {
            "empresa": f"{nome} {MARCA}", "responsavel": rnd.choice(RESPONSAVEIS), "cargo": rnd.choice(["Sócio", "Sócia-diretora", "Gerente"]),
            "cidade": cidade, "estado": uf, "especialidade": rnd.choice(ESPECIALIDADES),
            "tipo_empresa": "Escritório de contabilidade",
            "site": f"https://www.{slug}.example" if rnd.random() < 0.7 else "",
            "email": f"contato@{slug}.example" if rnd.random() < 0.8 else "",
            "whatsapp": _telefone_ficticio(i + 1) if rnd.random() < 0.75 else "",
            "instagram": f"@{slug}.contabil" if rnd.random() < 0.5 else "",
            "linkedin": f"https://www.linkedin.com/company/{slug}-example" if rnd.random() < 0.35 else "",
            "qtd_clientes_estimada": rnd.choice([None, 40, 80, 150, 300, 500]),
            "funcionarios": rnd.choice([None, 3, 6, 12, 25]),
            "equipe_comercial": rnd.random() < 0.25, "multiplos_socios": rnd.random() < 0.45,
            "atende_empresas": rnd.random() < 0.6, "vendedor_id": vendedores[i % 2].id,
            "observacoes": "Lead fictício para demonstração.",
        }
        lead, _ = criar_lead(db, dados, admin, origem="Demonstração", checar_duplicado=False)
        lead.criado_em = datetime.now() - timedelta(days=rnd.randint(0, 150), hours=rnd.randint(0, 10))
        leads.append(lead)
    db.flush()

    # Funil: uma parte avança de etapa.
    caminhos = ["Contatado", "Aguardando resposta", "Respondeu", "Interessado", "Humano assumiu",
                "Reunião", "Negociação", "Parceiro", "Parceiro ativo"]
    parceiros = []
    for i, lead in enumerate(leads[:48]):
        vendedor = db.get(Usuario, lead.vendedor_id)
        alvo = rnd.choices(range(len(caminhos)), weights=[12, 10, 7, 6, 5, 4, 3, 4, 12])[0]
        registrar_contato(db, lead, "whatsapp", "Primeiro contato pelo WhatsApp (demonstração).", vendedor)
        if alvo >= 2:
            registrar_resposta(db, lead, "whatsapp", "Resposta do lead (demonstração): quero saber mais.", vendedor)
        for status in caminhos[:alvo + 1]:
            if caminhos.index(status) >= 2:
                mudar_status(db, lead, status, vendedor)
        base = lead.criado_em
        for campo, dias in (("contatado_em", 2), ("respondeu_em", 5), ("interessado_em", 8), ("reuniao_em", 12),
                            ("proposta_em", 16), ("convertido_em", 22)):
            if getattr(lead, campo):
                setattr(lead, campo, min(base + timedelta(days=dias), datetime.now()))
        lead.ultimo_contato = lead.contatado_em
        if lead.parceiro_id:
            p = db.get(Parceiro, lead.parceiro_id)
            p.observacoes = f"{MARCA} Parceiro fictício."
            p.data_entrada = (lead.convertido_em or datetime.now()).date()
            parceiros.append(p)
    for lead in leads[48:56]:
        mudar_status(db, lead, "Perdido", db.get(Usuario, lead.vendedor_id),
                     rnd.choice(["Sem interesse", "Sem resposta", "Já possui parceiro"]))
    db.flush()

    # Vendas e certificados dos parceiros.
    for idx, p in enumerate(parceiros):
        if idx % 4 == 3:
            continue  # alguns parceiros ficam parados
        for _ in range(rnd.randint(1, 9)):
            cliente = Cliente(nome=f"Cliente Fictício {rnd.randint(100, 999)} {MARCA}", parceiro_id=p.id,
                              origem="Demonstração", status="Indicado", telefone=_telefone_ficticio(rnd.randint(100, 999)))
            db.add(cliente)
            db.flush()
            dia = max(p.data_entrada, hoje - timedelta(days=rnd.randint(0, 120)))
            registrar_venda(db, cliente=cliente, produto=rnd.choice(produtos), parceiro=p, valor=None, data=dia,
                            tipo="nova", vendedor=db.get(Usuario, p.vendedor_id) if p.vendedor_id else admin)
    # Certificados antigos vencendo (controle de renovação).
    for i in range(14):
        p = rnd.choice(parceiros) if parceiros else None
        cliente = Cliente(nome=f"Empresa Fictícia {i + 1} {MARCA}", parceiro_id=p.id if p else None,
                          origem="Demonstração", status="Emitido")
        db.add(cliente)
        db.flush()
        venc = hoje + timedelta(days=rnd.choice([-5, 3, 6, 12, 20, 28, 45, 58, 75, 88, 120]))
        db.add(Certificado(cliente_id=cliente.id, cliente_nome=cliente.nome, tipo=rnd.choice(produtos).nome,
                           data_emissao=venc - timedelta(days=365), data_vencimento=venc,
                           parceiro_id=p.id if p else None, status="Ativo"))
    db.flush()
    processar_vencimentos(db)

    # Campanha com cadência para os leads novos.
    novos = [l for l in leads if l.status == "Novo"][:12]
    if cadencia and novos:
        campanha = Campanha(nome=f"Campanha de demonstração {MARCA}", cadencia_id=cadencia.id, usuario_id=admin.id)
        db.add(campanha)
        db.flush()
        cadencias.aplicar(db, cadencia, novos, admin, hoje - timedelta(days=2), campanha.id)
    for lead in leads:
        score.atualizar(db, lead)
    return {"usuarios": [u.email for u in usuarios], "senha": senha, "leads": len(leads), "parceiros": len(parceiros)}


def apagar_demonstracao(db) -> int:
    ids_leads = [i for (i,) in db.execute(select(Lead.id).where(Lead.origem == "Demonstração"))]
    ids_parc = [i for (i,) in db.execute(select(Parceiro.id).where(Parceiro.observacoes.contains(MARCA)))]
    ids_cli = [i for (i,) in db.execute(select(Cliente.id).where(Cliente.origem == "Demonstração"))]
    ids_users = [i for (i,) in db.execute(select(Usuario.id).where(Usuario.email.like(f"%{DOMINIO_USUARIOS}")))]
    ids_vendas = [i for (i,) in db.execute(select(Venda.id).where(
        (Venda.parceiro_id.in_(ids_parc)) | (Venda.cliente_id.in_(ids_cli))))]
    db.execute(delete(Tarefa).where((Tarefa.lead_id.in_(ids_leads)) | (Tarefa.parceiro_id.in_(ids_parc))
                                    | (Tarefa.cliente_id.in_(ids_cli))))
    db.execute(delete(Mensagem).where(Mensagem.lead_id.in_(ids_leads)))
    db.execute(delete(Certificado).where((Certificado.parceiro_id.in_(ids_parc)) | (Certificado.cliente_id.in_(ids_cli))
                                         | (Certificado.venda_id.in_(ids_vendas))))
    db.execute(delete(Venda).where(Venda.id.in_(ids_vendas)))
    db.execute(delete(Cliente).where(Cliente.id.in_(ids_cli) | Cliente.parceiro_id.in_(ids_parc)))
    db.execute(update(Lead).where(Lead.parceiro_id.in_(ids_parc)).values(parceiro_id=None))
    db.execute(update(Usuario).where(Usuario.parceiro_id.in_(ids_parc)).values(parceiro_id=None, ativo=False))
    db.execute(delete(Parceiro).where(Parceiro.id.in_(ids_parc)))
    db.execute(delete(Historico).where(Historico.lead_id.in_(ids_leads)))
    db.execute(delete(Lead).where(Lead.id.in_(ids_leads)))
    db.execute(delete(Campanha).where(Campanha.nome.contains(MARCA)))
    for modelo, campo in ((Lead, "vendedor_id"), (Parceiro, "vendedor_id"), (Venda, "vendedor_id"), (Tarefa, "usuario_id"),
                          (Historico, "usuario_id"), (Mensagem, "usuario_id"), (LogAuditoria, "usuario_id"),
                          (Busca, "usuario_id"), (Campanha, "usuario_id")):
        db.execute(update(modelo).where(getattr(modelo, campo).in_(ids_users)).values({campo: None}))
    db.execute(delete(Usuario).where(Usuario.id.in_(ids_users)))
    return len(ids_leads) + len(ids_parc) + len(ids_cli) + len(ids_users)


def main():
    criar_tabelas()
    with sessao() as db:
        if not db.execute(select(Usuario.id).where(Usuario.perfil == "admin")).first():
            print("Primeiro abra o sistema (iniciar.bat) e crie a conta de administrador. Depois rode este arquivo.")
            return 1
        if db.execute(select(Lead.id).where(Lead.origem == "Demonstração").limit(1)).first():
            print("Os dados de demonstração já existem. Para recriar, apague em Configurações e rode de novo.")
            return 0
        r = popular(db)
    print(f"Pronto! {r['leads']} leads e {r['parceiros']} parceiros FICTÍCIOS criados.")
    print("Usuários de demonstração (mesma senha para todos):")
    for email in r["usuarios"]:
        print(f"  {email}")
    print(f"  Senha: {r['senha']}")
    print("Para remover tudo: Configurações > Apagar dados de demonstração.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
