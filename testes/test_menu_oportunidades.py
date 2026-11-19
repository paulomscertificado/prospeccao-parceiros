"""Pedido da Maria (19/11/2026): o número vermelho ao lado de "Oportunidades" no menu mostrava os avisos não lidos do
sininho (o mesmo "Avisos (N)" do rodapé) e parecia haver oportunidades que a tela não mostrava (no Grupo Certy: menu
6, aba "Novas" 0). Agora o número é o de oportunidades NOVAS da AR de quem vê, a mesma conta da aba "Novas"."""

import re

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.banco import sessao
from app.main import app
from app.modelos import Lead, Notificacao, Oportunidade, Tenant, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

CERTY = "admin.menu.oportunidades@grupocerty.com.br"
MASTER = "admin@teste.com.br"  # o primeiro acesso dos testes: o Admin Master
MENU = re.compile(r'href="/oportunidades">.*?Oportunidades(?:<span class="contador"[^>]*>(\d+)</span>)?', re.S)


def _numero_do_menu(html: str) -> int:
    achado = MENU.search(html)
    assert achado, "o menu não tem Oportunidades"
    return int(achado.group(1) or 0)


def _entrar(email: str) -> TestClient:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def _novas(db, ar: int | None = None) -> int:
    consulta = (select(func.count(Oportunidade.id)).join(Lead, Oportunidade.lead_id == Lead.id)
                .where(Oportunidade.status == "nova"))
    if ar:
        consulta = consulta.where(Oportunidade.tenant_id == ar)
    return db.execute(consulta.execution_options(sem_filtro_de_ar=True)).scalar() or 0


def test_numero_do_menu_e_o_de_oportunidades_novas_da_ar(cliente):
    with sessao() as db:
        ars = {slug: i for i, slug in db.execute(select(Tenant.id, Tenant.slug))}
        certy = db.execute(select(Usuario).where(Usuario.email == CERTY)).scalars().first()
        if certy is None:
            certy = Usuario(nome="Admin Menu Certy", email=CERTY, perfil="admin", senha_hash=resumir_senha(SENHA),
                            tenant_id=ars["grupo-certy"])
            db.add(certy)
            db.flush()
        for i in range(3):  # avisos do sininho: não entram mais no número do menu
            db.add(Notificacao(usuario_id=certy.id, texto=f"Aviso do sininho {i}", link="/campanhas"))
        for ar, nome in ((ars["grupo-certy"], "LEAD MENU CERTY LTDA"), (ars["ms"], "LEAD MENU MS LTDA")):
            lead = Lead(tenant_id=ar, empresa=nome, cidade="Recife", estado="PE", status="Interessado",
                        automacao_pausada=True)
            db.add(lead)
            db.flush()
            db.add(Oportunidade(tenant_id=ar, lead_id=lead.id, temperatura="quente", canal="whatsapp", status="nova",
                                classificacao="QUER SABER MAIS", resposta="Quero saber mais"))
        db.commit()
        da_certy, de_todas = _novas(db, ars["grupo-certy"]), _novas(db)
    assert de_todas > da_certy >= 1

    # a administradora do Grupo Certy: as novas da AR dela (não os avisos do sininho, nem as da MS)
    pagina = _entrar(CERTY).get("/leads").text
    assert _numero_do_menu(pagina) == da_certy
    avisos = re.search(r"Avisos \((\d+)\)", pagina)
    assert avisos and int(avisos.group(1)) >= 3  # o sininho continua no rodapé do menu

    # o Admin Master fora de uma AR vê todas
    assert _numero_do_menu(_entrar(MASTER).get("/leads").text) == de_todas
