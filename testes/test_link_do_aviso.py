"""Pedido da Maria (19/11/2026): "quando estamos clicando nos nomes das pessoas dentro do módulo Minha fila, o sistema
está direcionando para o lead ao invés de enviar para a campanha que está relacionada ao determinado lead. Verifique
isso no sistema como um todo." Nos avisos de campanha (Minha fila, Envios e Agenda), o nome da empresa abre a
CAMPANHA, já nas mensagens daquela empresa (#lead-<id>); quem não pode abrir a campanha continua indo para a ficha do
lead (o link nunca leva a uma página de erro). As telas do lead (Leads, Oportunidades e as tarefas do painel) continuam
abrindo a ficha."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.banco import agora, sessao
from app.main import app
from app.modelos import Campanha, Lead, Mensagem, Tarefa, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

VENDEDOR = "vendedor.link.aviso@mscertificados.com.br"


def _admin(db) -> Usuario:
    return db.execute(select(Usuario).where(Usuario.email == "admin@teste.com.br")).scalars().one()


def _entrar(email: str) -> TestClient:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _aviso(db, camp: Campanha, dono: Usuario, empresa: str) -> int:
    """Um lead do `dono` com um aviso de e-mail da campanha para hoje e um e-mail que saiu ontem (Envios)."""
    lead = Lead(empresa=empresa, email=f"contato@{empresa.split()[0].lower()}linkaviso.com.br",
                status="Abordagem criada", vendedor_id=dono.id)
    db.add(lead)
    db.flush()
    db.add(Tarefa(lead_id=lead.id, campanha_id=camp.id, canal="email", status="pendente", tipo="prospeccao",
                  data=date.today(), hora="23:58", acao="Contato por email", mensagem="Olá!", usuario_id=dono.id))
    # ontem: aparece em Envios e no Histórico (7 dias) sem gastar o limite de e-mails por hora/dia dos outros testes
    db.add(Mensagem(lead_id=lead.id, campanha_id=camp.id, canal="email", direcao="saida", status="enviada",
                    corpo="Olá! Primeiro e-mail.", usuario_id=dono.id, criado_em=agora() - timedelta(days=1)))
    db.flush()
    return lead.id


def test_nome_do_aviso_abre_a_campanha(cliente):
    with sessao() as db:
        admin = _admin(db)
        ms = db.execute(select(Tenant.id).where(Tenant.slug == "ms")).scalar_one()
        vendedor = db.execute(select(Usuario).where(Usuario.email == VENDEDOR)).scalars().first()
        if vendedor is None:
            vendedor = Usuario(nome="Vendedor Link Aviso", email=VENDEDOR, perfil="vendedor",
                               senha_hash=resumir_senha(SENHA), tenant_id=ms)
            db.add(vendedor)
            db.flush()
        camp = Campanha(nome="Campanha Link do Aviso", status="ativa", aprovado_em=agora(), usuario_id=admin.id,
                        canais="email")
        db.add(camp)
        db.flush()
        do_admin = _aviso(db, camp, admin, "ALFA LINK DO AVISO LTDA")
        do_vendedor = _aviso(db, camp, vendedor, "BETA LINK DO AVISO LTDA")
        db.commit()
        cid = camp.id

    # quem pode abrir a campanha: o nome (e o nome da campanha) levam à campanha, nas mensagens da empresa
    alvo = f'href="/campanhas/{cid}#lead-{do_admin}"'
    fila = cliente.get("/fila").text
    assert alvo in fila and f'href="/leads/{do_admin}"' not in fila
    assert alvo in cliente.get("/fila?aba=historico").text
    envios = cliente.get("/envios").text
    assert alvo in envios and f'href="/leads/{do_admin}"' not in envios
    assert alvo in cliente.get("/envios?aba=proximos").text
    assert alvo in cliente.get("/agenda").text
    pagina = cliente.get(f"/campanhas/{cid}").text  # a âncora existe na página da campanha
    assert f'id="lead-{do_admin}"' in pagina and f'id="lead-{do_vendedor}"' in pagina

    # quem não abre a campanha (o vendedor; a campanha é da administradora): continua indo para o lead
    vendedor = _entrar(VENDEDOR)
    fila = vendedor.get("/fila").text
    assert "BETA LINK DO AVISO LTDA" in fila and f'href="/leads/{do_vendedor}"' in fila
    assert f"/campanhas/{cid}" not in fila
    assert vendedor.get(f"/campanhas/{cid}").status_code == 404  # por isso o link não vai para lá

    with sessao() as db:  # limpa (a fila e os envios dos outros testes não veem estes avisos)
        for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars():
            t.status = "cancelada"
        db.get(Campanha, cid).status = "cancelada"
        db.commit()
