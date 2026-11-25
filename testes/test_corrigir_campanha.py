"""Campanha que não foi montada: "Corrigir e montar de novo" (pedido da Maria em 24/11/2026: "Campanha 09 contém um
erro, pois não foi encontrado novos CNPJS na cidade que utilizei. Sugiro uma opção para editar ou refazer campanha").
A tela da Nova campanha abre com tudo o que a campanha tinha; ao salvar, a MESMA campanha é montada de novo (sem
criar outra) e continua de quem era."""

import html as html_lib
import json
import re
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import campanhas
from app.banco import sessao
from app.main import app
from app.modelos import Campanha, LogAuditoria, Usuario
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

ERRO = ('Não encontrei empresas novas de Escritórios contábeis, Administradoras de condomínios em "Campo Verde"/MT na '
        'lista "contabilidades e adm cond PE & MG". Confira o nome da cidade (ou do bairro) e o estado, ou escolha '
        'outro segmento ou outra base.')
PERGUNTA = "Vocês atendem condomínios aqui na região?"


def _com_erro(db, dono_id: int, nome: str = "Camapnha 9", **outros) -> Campanha:
    """Uma campanha como a da Maria: a montagem parou porque a base não tinha empresas na cidade."""
    dados = dict(nome=nome, categorias="contabil,condominio", cidade="Campo Verde", estado="MT", quantidade=30,
                 canais="whatsapp,email", objetivo="Encontrar parceiros", tom="direto", cta=PERGUNTA,
                 cadencia_id=campanhas.cadencia_sdr(db).id, usuario_id=dono_id, status="erro",
                 etapa="Não foi possível montar a campanha.", erro=ERRO, inicio=date.today() - timedelta(days=2))
    dados.update(outros)
    camp = Campanha(**dados)
    db.add(camp)
    db.flush()
    return camp


def _admin(db) -> Usuario:
    return db.execute(select(Usuario).where(Usuario.email == "admin@teste.com.br")).scalars().one()


def _formulario(csrf: str, cid: int, cadencia_id: int, **outros) -> dict:
    dados = {"csrf": csrf, "corrigir": str(cid), "pedido": "", "base": "receita", "estado": "PE", "cidade": "Recife",
             "categorias": ["contabil"], "quantidade": "20", "tom": "consultivo", "cadencia_id": str(cadencia_id),
             "cta": "", "cta_livre": "", "envio_html": "texto", "nome": "Campanha 9", "canais": ["whatsapp", "email"],
             "inicio": date.today().isoformat(), "objetivo": "Encontrar parceiros"}
    dados.update(outros)
    return dados


def _entrar(email: str) -> TestClient:
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


def test_corrigir_abre_com_tudo_marcado_e_monta_a_mesma_campanha(cliente, monkeypatch):
    montadas = []
    monkeypatch.setattr(campanhas, "gerar_em_segundo_plano", montadas.append)
    with sessao() as db:
        admin = _admin(db)
        camp = _com_erro(db, admin.id)
        cid, dono_id, cadencia_id = camp.id, admin.id, camp.cadencia_id
        total_antes = db.execute(select(func.count(Campanha.id))).scalar()
    try:
        # a página da campanha com erro oferece a correção (e a lista também)
        pagina = html_lib.unescape(cliente.get(f"/campanhas/{cid}").text)
        assert "Corrigir e montar de novo" in pagina and f'href="/campanhas/{cid}/corrigir"' in pagina
        assert f'href="/campanhas/{cid}/corrigir"' in cliente.get("/campanhas?ver=erro").text

        # a tela de correção vem com tudo o que a campanha tinha
        tela = html_lib.unescape(cliente.get(f"/campanhas/{cid}/corrigir").text)
        assert "Corrigir a campanha" in tela and "Por que não foi montada:" in tela and ERRO in tela
        assert f'name="corrigir" value="{cid}"' in tela and "Montar a campanha de novo" in tela
        assert 'value="Campo Verde"' in tela and "<option selected>MT</option>" in tela
        for codigo in ("contabil", "condominio"):
            assert re.search(rf'name="categorias" data-nome="[^"]*" value="{codigo}" checked', tela), codigo
        assert 'value="outro" id="q-outro" checked' in tela and 'name="quantidade_outra" min="1" max="500" value="30"' in tela
        assert 'name="tom" value="direto" checked' in tela and 'name="tom" value="consultivo" checked' not in tela
        assert re.search(rf'name="cadencia_id" value="{cadencia_id}"[^>]*checked', tela)
        assert 'id="cta-minha" checked' in tela and f'name="cta_livre" maxlength="200" value="{PERGUNTA}"' in tela
        assert 'name="nome" required value="Camapnha 9"' in tela
        assert 'name="canais" value="whatsapp" checked' in tela and 'name="canais" value="email" checked' in tela
        # o início era anteontem: vem hoje (a tela não aceita data passada)
        assert f'name="inicio" required value="{date.today().isoformat()}"' in tela
        assert f'href="/campanhas/{cid}">Voltar' in tela

        # troca a cidade e o segmento: a MESMA campanha volta a ser montada
        r = cliente.post("/campanhas/nova", data=_formulario(csrf_de(tela), cid, cadencia_id))
        assert r.url.path == f"/campanhas/{cid}" and "Campanha corrigida" in html_lib.unescape(r.text)
        assert montadas == [cid]
        with sessao() as db:
            assert db.execute(select(func.count(Campanha.id))).scalar() == total_antes  # nenhuma campanha nova
            camp = db.get(Campanha, cid)
            assert (camp.cidade, camp.estado, camp.categorias, camp.nome, camp.quantidade, camp.tom, camp.cta) == (
                "Recife", "PE", "contabil", "Campanha 9", 20, "consultivo", "")
            assert (camp.status, camp.erro, camp.usuario_id, camp.inicio) == ("gerando", "", dono_id, date.today())
            log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "corrigiu_campanha",
                                                        LogAuditoria.entidade_id == cid)).scalars().one()
            mudancas = json.loads(log.mudancas)
            assert mudancas["cidade"] == ["Campo Verde", "Recife"] and mudancas["estado"] == ["MT", "PE"]

        # mandar de novo (outra aba, clique duplo) não mexe na campanha que já está sendo montada
        r = cliente.post("/campanhas/nova", data=_formulario(csrf_de(tela), cid, cadencia_id, cidade="Olinda"))
        assert "Esta campanha não está mais com erro" in html_lib.unescape(r.text)
        assert montadas == [cid]
        with sessao() as db:
            assert db.get(Campanha, cid).cidade == "Recife"
        r = cliente.get(f"/campanhas/{cid}/corrigir")
        assert r.url.path == f"/campanhas/{cid}"
        assert "Só dá para corrigir uma campanha que não conseguiu ser montada" in html_lib.unescape(r.text)
    finally:
        with sessao() as db:
            db.get(Campanha, cid).status = "cancelada"  # sai do caminho dos outros testes


def test_so_a_campanha_da_ia_sdr_que_nao_foi_montada(cliente):
    with sessao() as db:
        admin = _admin(db)
        novas = _com_erro(db, admin.id, nome="Corrigir Empresas Novas", tipo="empresas_novas")
        pronta = _com_erro(db, admin.id, nome="Corrigir Já Montada", status="aguardando_aprovacao", erro="")
        ids = (novas.id, pronta.id)
        assert not campanhas.pode_corrigir(novas) and not campanhas.pode_corrigir(pronta)
    try:
        for cid in ids:
            assert "Corrigir e montar de novo" not in cliente.get(f"/campanhas/{cid}").text
            r = cliente.get(f"/campanhas/{cid}/corrigir")
            assert r.url.path == f"/campanhas/{cid}" and "Só dá para corrigir" in html_lib.unescape(r.text)
    finally:
        with sessao() as db:
            for cid in ids:
                db.get(Campanha, cid).status = "cancelada"


def test_a_campanha_corrigida_continua_de_quem_era_e_so_quem_pode_corrige(cliente, monkeypatch):
    monkeypatch.setattr(campanhas, "gerar_em_segundo_plano", lambda cid: None)
    with sessao() as db:
        ana = Usuario(nome="Ana Corrigir Campanha", email="ana.corrigir@teste.com.br", perfil="vendedor",
                      senha_hash=resumir_senha(SENHA))
        bia = Usuario(nome="Bia Corrigir Campanha", email="bia.corrigir@teste.com.br", perfil="vendedor",
                      senha_hash=resumir_senha(SENHA))
        db.add_all([ana, bia])
        db.flush()
        ana_id = ana.id
        cid = _com_erro(db, ana.id, nome="Campanha da Ana").id
        cadencia_id = campanhas.cadencia_sdr(db).id
    try:
        # a colega do mesmo nível não vê nem corrige a campanha da Ana
        bia_c = _entrar("bia.corrigir@teste.com.br")
        assert bia_c.get(f"/campanhas/{cid}/corrigir").status_code == 404
        csrf_bia = csrf_de(bia_c.get("/campanhas/nova").text)
        assert bia_c.post("/campanhas/nova", data=_formulario(csrf_bia, cid, cadencia_id)).status_code == 404
        with sessao() as db:
            assert db.get(Campanha, cid).cidade == "Campo Verde"

        # o administrador corrige: a campanha continua da Ana (os disparos são dela)
        tela = html_lib.unescape(cliente.get(f"/campanhas/{cid}/corrigir").text)
        assert "Campanha da Ana" in tela
        cliente.post("/campanhas/nova", data=_formulario(csrf_de(tela), cid, cadencia_id, nome="Campanha da Ana"))
        with sessao() as db:
            camp = db.get(Campanha, cid)
            assert (camp.status, camp.usuario_id, camp.cidade) == ("gerando", ana_id, "Recife")

        # a própria Ana também pode corrigir a dela
        with sessao() as db:
            db.get(Campanha, cid).status = "erro"
        ana_c = _entrar("ana.corrigir@teste.com.br")
        tela = html_lib.unescape(ana_c.get(f"/campanhas/{cid}/corrigir").text)
        assert "Corrigir a campanha" in tela and "Vagas de WhatsApp no número de" not in tela
        ana_c.post("/campanhas/nova", data=_formulario(csrf_de(tela), cid, cadencia_id, cidade="Olinda"))
        with sessao() as db:
            assert (db.get(Campanha, cid).cidade, db.get(Campanha, cid).status) == ("Olinda", "gerando")
    finally:
        with sessao() as db:
            db.get(Campanha, cid).status = "cancelada"
            for u in db.execute(select(Usuario).where(Usuario.email.like("%.corrigir@teste.com.br"))).scalars():
                u.ativo = False
