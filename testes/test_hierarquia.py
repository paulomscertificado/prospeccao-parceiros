"""Hierarquia (pedido da Maria em 17/11/2026: "quero que quem for acima veja as coisas de quem está abaixo"): o gestor
vê e cuida do que é dele e de quem está abaixo (não do que é do administrador), o funcionário vê o de quem está abaixo
e mexe só no dele, o vendedor fica com o dele. Renovação e Empresas novas (planilha, busca paga na CNPJá) só para
quem configura; as campanhas delas seguem a hierarquia."""

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import autorizacao
from app.banco import gravar_config, ler_config, sessao
from app.main import app
from app.modelos import Campanha, Papel, PermissaoPapel, Usuario
from app.seguranca import resumir_senha
from conftest import csrf_de, ligar_modulos

SENHA = "senhaHier123"
PESSOAS = {"ges": ("gestor", "Ges Hierarquia"), "fun": ("funcionario", "Fun Hierarquia"),
           "vena": ("vendedor", "Vena Hierarquia"), "venb": ("vendedor", "Venb Hierarquia")}
_C: dict = {}


def _email(chave: str) -> str:
    return f"{chave}.hier@teste.com.br"


def _entrar(chave: str) -> TestClient:
    c = TestClient(app)
    pagina = c.get("/login")
    c.post("/login", data={"csrf": csrf_de(pagina.text), "email": _email(chave), "senha": SENHA})
    return c


def _cenario() -> dict:
    """Gestor, funcionário e dois vendedores, cada um com uma campanha de parceiros e uma de renovação; o admin
    master (acima de todos) também."""
    if _C:
        return _C
    ligar_modulos("campanhas")
    with sessao() as db:
        ids = {"master": db.execute(select(Usuario).where(Usuario.master.is_(True))).scalars().first().id}
        for chave, (perfil, nome) in PESSOAS.items():
            u = Usuario(nome=nome, email=_email(chave), perfil=perfil, senha_hash=resumir_senha(SENHA))
            db.add(u)
            db.flush()
            ids[chave] = u.id
        for chave in ("master", *PESSOAS):
            camp = Campanha(nome=f"Campanha Hier {chave}.", usuario_id=ids[chave])
            renov = Campanha(nome=f"Renovacao Hier {chave}.", usuario_id=ids[chave], tipo="renovacao")
            db.add_all([camp, renov])
            db.flush()
            ids[f"camp_{chave}"], ids[f"renov_{chave}"] = camp.id, renov.id
    _C.update(ids)
    return _C


def test_cada_um_alcanca_o_seu_e_o_de_quem_esta_abaixo(cliente):
    c = _cenario()
    with sessao() as db:
        u = {k: db.get(Usuario, c[k]) for k in PESSOAS}
        ges = autorizacao.donos_visiveis(u["ges"], "campanhas.ver")
        assert {c["ges"], c["fun"], c["vena"], c["venb"]} <= ges and c["master"] not in ges
        fun = autorizacao.donos_visiveis(u["fun"], "campanhas.ver")
        assert {c["fun"], c["vena"], c["venb"]} <= fun and not {c["ges"], c["master"]} & fun
        assert autorizacao.donos_visiveis(u["vena"], "campanhas.ver") == {c["vena"]}

        camp_vena = db.get(Campanha, c["camp_vena"])
        assert autorizacao.pode(u["ges"], "campanhas.gerenciar", camp_vena)  # o gestor cuida
        assert autorizacao.pode(u["fun"], "campanhas.ver", camp_vena)  # o funcionário vê...
        assert not autorizacao.pode(u["fun"], "campanhas.gerenciar", camp_vena)  # ...mas não mexe
        assert not autorizacao.pode(u["venb"], "campanhas.ver", camp_vena)  # colega do mesmo nível não vê
        assert not autorizacao.pode(u["ges"], "campanhas.ver", db.get(Campanha, c["camp_master"]))  # nem quem está acima

        # filtro "de quem" das telas: só quem alcança outras pessoas, e só elas
        todos = db.execute(select(Usuario)).scalars().all()
        visiveis = {p.id for p in autorizacao.pessoas_visiveis(u["ges"], "fila.ver", todos)}
        assert {c["ges"], c["fun"], c["vena"]} <= visiveis and c["master"] not in visiveis
        assert autorizacao.pessoas_visiveis(u["vena"], "fila.ver", todos) == []


def test_telas_de_campanha_seguem_a_hierarquia(cliente):
    c = _cenario()
    ges, fun, vena = _entrar("ges"), _entrar("fun"), _entrar("vena")
    assert ges.get(f"/campanhas/{c['camp_vena']}").status_code == 200
    assert ges.get(f"/campanhas/{c['camp_fun']}").status_code == 200
    assert ges.get(f"/campanhas/{c['camp_master']}").status_code == 404
    assert fun.get(f"/campanhas/{c['camp_vena']}").status_code == 200
    assert fun.get(f"/campanhas/{c['camp_ges']}").status_code == 404
    assert vena.get(f"/campanhas/{c['camp_vena']}").status_code == 200
    assert vena.get(f"/campanhas/{c['camp_venb']}").status_code == 404

    lista = ges.get("/campanhas?de=todos").text  # o gestor escolhe "todos": o dele e o de quem está abaixo
    assert "Campanha Hier vena." in lista and "Campanha Hier fun." in lista and "Campanha Hier ges." in lista
    assert "Campanha Hier master." not in lista
    assert "Campanha Hier ges." in ges.get("/campanhas").text and "Campanha Hier vena." not in ges.get("/campanhas").text

    # Minha fila: o gestor escolhe entre quem está abaixo; o vendedor não tem o filtro
    assert "Vena Hierarquia" in ges.get("/fila").text
    assert "Venb Hierarquia" not in vena.get("/fila").text


def test_renovacao_e_empresas_novas_so_para_quem_configura(cliente):
    c = _cenario()
    vena, ges = _entrar("vena"), _entrar("ges")
    assert vena.get("/renovacao").status_code == 403
    assert vena.get("/empresas-novas").status_code == 403
    csrf = csrf_de(vena.get("/minha-conta").text)
    assert vena.post("/empresas-novas/buscar", data={"csrf": csrf, "quantidade": "10"}).status_code == 403
    assert vena.post("/renovacao/configurar", data={"csrf": csrf, "canal_whatsapp": "1"}).status_code == 403

    pagina = ges.get("/renovacao")
    assert pagina.status_code == 200
    assert "Renovacao Hier vena." in pagina.text and "Renovacao Hier master." not in pagina.text
    assert ges.get("/empresas-novas").status_code == 200

    # quem não abre a tela Renovação vê as campanhas de renovação dela na lista de Campanhas
    assert "Renovacao Hier vena." in vena.get("/campanhas").text
    assert "Renovacao Hier vena." not in ges.get("/campanhas?de=todos").text  # quem configura vê na tela Renovação


def test_hierarquia_aplicada_uma_vez_sem_desfazer_o_que_o_admin_mudou(cliente):
    with sessao() as db:
        papeis = {p.codigo: p for p in db.execute(select(Papel)).scalars()}

        def linha(codigo, permissao):
            return db.execute(select(PermissaoPapel).where(PermissaoPapel.papel_id == papeis[codigo].id,
                                                           PermissaoPapel.permissao == permissao)).scalars().first()

        # como estava antes da hierarquia, mais um ajuste feito à mão pelo administrador
        linha("gestor", "leads.ver").escopo = "tudo"
        linha("gestor", "relatorios.ver").escopo = "equipe"
        linha("funcionario", "leads.ver").escopo = "proprios"
        linha("funcionario", "leads.editar").escopo = "proprios"
        gravar_config(db, "permissoes_hierarquia", "0")
        db.flush()

        autorizacao.preparar(db)
        assert linha("gestor", "leads.ver").escopo == "abaixo"
        assert linha("gestor", "relatorios.ver").escopo == "equipe"  # escolha do administrador: fica
        assert linha("funcionario", "leads.ver").escopo == "abaixo"
        assert linha("funcionario", "leads.editar").escopo == "proprios"  # mexer, só no que é dele
        assert ler_config(db, "permissoes_hierarquia") == "1"

        linha("gestor", "leads.ver").escopo = "tudo"  # já aplicada: não troca de novo
        autorizacao.preparar(db)
        assert linha("gestor", "leads.ver").escopo == "tudo"
        linha("gestor", "leads.ver").escopo = "abaixo"  # volta ao padrão para os outros testes
        linha("gestor", "relatorios.ver").escopo = "abaixo"


def test_lista_vazia_leva_as_campanhas_da_equipe(cliente):
    """Pedido da Maria (26/11/2026): o usuário novo do Jefferson abriu Campanhas em "Só as minhas", ainda sem campanhas,
    e achou que não via as da equipe. Lista vazia de quem vê as de outras pessoas: o aviso diz quantas a equipe tem e
    leva a elas ("Todas" + "Toda a equipe"); quem só vê as próprias continua com o aviso de sempre."""
    c = _cenario()
    with sessao() as db:
        for chave, perfil in (("gesnovo", "gestor"), ("vennovo", "vendedor")):
            if not db.execute(select(Usuario).where(Usuario.email == _email(chave))).scalars().first():
                db.add(Usuario(nome=f"Novo {chave}", email=_email(chave), perfil=perfil,
                               senha_hash=resumir_senha(SENHA)))
    ges = _entrar("gesnovo")
    pagina = ges.get("/campanhas").text  # abre em "Só as minhas": ele ainda não tem nenhuma
    assert "Você ainda não tem campanhas." in pagina and 'href="?ver=todas&amp;de=todos"' in pagina
    total = int(re.search(r"A equipe tem (\d+) campanha", pagina).group(1))
    equipe = ges.get("/campanhas?ver=todas&de=todos").text
    assert "Campanha Hier vena." in equipe and "Ver as campanhas da equipe" not in equipe
    assert equipe.count('class="camp"') == total > 0  # o número do aviso é o que aparece em Todas + Toda a equipe

    pagina = ges.get(f"/campanhas?ver=arquivadas&de={c['vena']}").text  # como o Jefferson: pessoa escolhida em Arquivadas
    assert "Vena Hierarquia não tem campanhas arquivadas." in pagina and "Ver as campanhas da equipe" in pagina
    pagina = ges.get("/campanhas?ver=arquivadas&de=todos").text
    assert "A equipe não tem campanhas arquivadas." in pagina and f"As {total} campanhas da equipe estão em" in pagina

    pagina = _entrar("vennovo").get("/campanhas").text  # o vendedor só vê as próprias: o aviso de sempre
    assert "Nenhuma campanha aqui." in pagina and "Ver as campanhas da equipe" not in pagina
