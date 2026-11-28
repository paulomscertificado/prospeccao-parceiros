"""Menu na barra de cima (novo visual, 27/11/2026, pedido da Maria, com as sugestões que ela aceitou): grupos em cima,
telas do grupo embaixo; segunda barra só com 2 telas ou mais no grupo; número vermelho do grupo = soma das telas dele;
Painel master à vista só para o Admin Master; cores só as da marca (nenhuma cor da MS fixa no CSS do menu)."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import marca, web
from app.banco import sessao
from app.main import app
from app.modelos import Lead, Oportunidade, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de


def _menu(html: str) -> str:
    return html.split("<main")[0]


def _grupo_aberto(html: str) -> str:
    m = re.search(r'<a class="cima-grupo ativo" href="[^"]*" aria-current="true">\s*<svg.*?</svg>([^<]+)', html, re.S)
    return m.group(1).strip() if m else ""


def test_tela_marcada_pelo_endereco_e_pelas_telas_sem_item_proprio():
    menu = web.MENU_EQUIPE
    assert web.item_marcado(menu, "/leads/12") == "/leads"
    assert web.item_marcado(menu, "/leads/pipeline") == "/leads"
    assert web.item_marcado(menu, "/") == "/"
    assert web.item_marcado(menu, "/visuais/3") == "/campanhas"
    assert web.item_marcado(menu, "/templates/0") == "/cadencias"
    assert web.item_marcado(menu, "/minha-conta") == "" and web.item_marcado(menu, "/notificacoes") == ""
    sem_whatsapp = [m for m in menu if m[0] not in web.DENTRO_DAS_CONFIGURACOES]  # quem vê as Configurações
    assert web.item_marcado(sem_whatsapp, "/whatsapp") == "/configuracoes"
    assert web.item_marcado(sem_whatsapp, "/categorias") == "/configuracoes"
    assert web.item_marcado(web.MENU_PARCEIRO, "/portal/clientes") == "/portal/clientes"
    assert web.item_marcado(web.MENU_PARCEIRO, "/portal") == "/portal"


def test_grupos_na_ordem_com_a_segunda_barra_so_quando_ha_escolha():
    grupos = web.menu_em_grupos(web.MENU_EQUIPE, "/leads", {"oportunidades_novas": 2, "conversas_nao_lidas": 3})
    titulos = [g["titulo"] for g in grupos]
    assert titulos == ["Visão geral", "Prospecção", "Operação", "Relacionamento", "Análise", "Configurações"]
    prospeccao = grupos[1]
    assert prospeccao["aberto"] and prospeccao["segunda_barra"] and prospeccao["link"] == "/campanhas"
    assert [m[0] for m in prospeccao["itens"]] == ["/campanhas", "/empresas-novas", "/renovacao", "/prospeccao",
                                                   "/assertiva", "/leads", "/cadencias"]
    assert grupos[2]["soma"] == 3 and grupos[3]["soma"] == 2 and grupos[1]["contadores"] == []
    painel = web.menu_em_grupos(web.MENU_EQUIPE, "/", {})
    assert painel[0]["aberto"] and not painel[0]["segunda_barra"]  # Visão geral: só o Dashboard
    # quem vê as Configurações não tem Permissões, WhatsApp e E-mail no menu (web.DENTRO_DAS_CONFIGURACOES)
    menu_admin = [m for m in web.MENU_EQUIPE if m[0] not in web.DENTRO_DAS_CONFIGURACOES]
    configuracoes = web.menu_em_grupos(menu_admin, "/configuracoes", {})
    assert configuracoes[-1]["aberto"] and not configuracoes[-1]["segunda_barra"]
    assert web.menu_em_grupos(menu_admin, "/whatsapp", {})[-1]["aberto"]
    assert not any(g["aberto"] for g in web.menu_em_grupos(web.MENU_EQUIPE, "/minha-conta", {}))
    # tela que não está em nenhum grupo vai para "Outros" (e nunca some do menu)
    outros = web.menu_em_grupos(web.MENU_EQUIPE + [("/nova-tela", "Nova tela", "grafico")], "/", {})
    assert outros[-1]["titulo"] == "Outros" and outros[-1]["itens"][0][0] == "/nova-tela"


def test_menu_de_cima_na_tela(cliente):
    leads = cliente.get("/leads").text
    assert 'class="menu menu-cima' in _menu(leads) and _grupo_aberto(leads) == "Prospecção"
    assert 'class="cima-sub com-telas"' in leads and 'class="item ativo" href="/leads"' in leads
    assert 'href="/master">Painel master</a>' in _menu(leads)  # quem roda os testes é o Admin Master
    for caminho in ("/", "/configuracoes", "/minha-conta", "/notificacoes"):
        pagina = cliente.get(caminho).text
        assert 'class="cima-sub"' in pagina and 'class="cima-sub com-telas"' not in pagina, caminho
    assert _grupo_aberto(cliente.get("/configuracoes?aba=geral").text) == "Configurações"
    assert _grupo_aberto(cliente.get("/whatsapp").text) == "Configurações"
    assert _grupo_aberto(cliente.get("/minha-conta").text) == ""
    assert 'id="link-avisos"' in leads and 'id="notif-config"' in leads and 'href="/sair"' in leads


def test_numero_vermelho_do_grupo_soma_as_telas_dele(cliente):
    with sessao() as db:
        lead = Lead(empresa="Contábil do Menu de Cima", cidade="Recife", estado="PE")
        db.add(lead)
        db.flush()
        db.add(Oportunidade(lead_id=lead.id, status="nova", resposta="Tenho interesse."))
    pagina = cliente.get("/leads").text
    item = re.search(r'<span class="contador" id="contador-oportunidades"[^>]*>(\d+)</span>', pagina)
    grupo = re.search(r'<span class="contador" data-soma="contador-oportunidades"[^>]*>(\d+)</span>', pagina)
    celular = re.search(r'<button id="abrir-menu"[^>]*>☰<span class="contador" data-soma="([^"]+)"[^>]*>(\d+)</span>',
                        pagina)
    assert item and grupo and int(item.group(1)) >= 1 and grupo.group(1) == item.group(1)
    assert celular and "contador-oportunidades" in celular.group(1).split() and int(celular.group(2)) >= int(item.group(1))


def test_vendedor_ve_o_whatsapp_no_grupo_operacao():
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    with sessao() as db:
        if db.query(Usuario).filter(Usuario.email == "vendedor.cima@exemplo.com.br").first() is None:
            db.add(Usuario(nome="Vendedor de Cima", email="vendedor.cima@exemplo.com.br", perfil="vendedor",
                           senha_hash=resumir_senha(SENHA)))
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": "vendedor.cima@exemplo.com.br",
                           "senha": SENHA})
    pagina = c.get("/whatsapp").text
    assert _grupo_aberto(pagina) == "Operação" and 'class="item ativo" href="/whatsapp"' in pagina
    assert "Painel master" not in _menu(pagina) and 'href="/configuracoes"' not in _menu(pagina)


def test_cores_do_menu_vem_da_marca():
    css = marca.tema("#E86A1F", "#F7931E", "#F5F5F5", "Montserrat")
    variaveis = dict(par.split(":", 1) for par in css.split(";"))
    assert variaveis["--menu-sub"].startswith("rgba(255,255,255")
    assert variaveis["--menu-destaque"] in ("#f7931e", "#ffffff") and variaveis["--sobre-destaque"]
    # detalhe que some na barra de baixo (quase da mesma cor): o traço da tela aberta fica branco
    assert dict(p.split(":", 1) for p in marca.tema("#1E40AF", "#1E3A8A").split(";"))["--menu-destaque"] == "#ffffff"
    # detalhe claro: a inicial da pessoa vai escura em cima dele
    assert dict(p.split(":", 1) for p in marca.tema("", "#FFD60A").split(";"))["--sobre-destaque"] != "#ffffff"
    assert marca.tema() == ""  # sem marca própria: as cores de sempre, do estilo.css


def test_nenhuma_cor_da_ms_fixa_no_css_do_menu():
    css = Path(__file__).resolve().parent.parent.joinpath("app", "static", "estilo.css").read_text(encoding="utf-8")
    raiz, resto = css.split("}", 1)  # as variáveis do :root são o padrão (a MS e quem não tem cor própria)
    menu = resto.split("/* ---------- Estrutura: menu na barra de cima", 1)[1].split("/* ---------- Cartões", 1)[0]
    celular = css.split("/* Celular e tablet: o menu de cima vira a gaveta", 1)[1].split("@media (max-width: 760px)", 1)[0]
    cores_da_ms = re.compile(r"#(0d3b66|0a2f57|12456f|3cc77a|1f9d5c|b9cbdd|06301b|dbe6f0|9fb3c8)|219,\s*230,\s*240",
                             re.I)
    assert cores_da_ms.search(menu) is None and cores_da_ms.search(celular) is None
    assert "--menu-destaque" in raiz and "--sobre-destaque" in raiz and "--menu-sub" in raiz
