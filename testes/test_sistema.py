"""Testes de ponta a ponta do sistema (rodar com testar.bat)."""

import io
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import ia, prospeccao, util
from app.banco import sessao
from app.main import app
from app.modelos import Certificado, Cliente, Historico, Lead, Parceiro, Produto, Tarefa, Usuario, Venda
from app.vendas_servico import calcular, processar_vencimentos
from conftest import SENHA, csrf_de


def _lead_por_nome(nome):
    with sessao() as db:
        return db.execute(select(Lead).where(Lead.empresa == nome)).scalars().first()


def _criar_lead(cliente, csrf, **campos):
    dados = {"csrf": csrf, "empresa": "Contabilidade Teste", "estado": "PE", "cidade": "Recife"}
    dados.update(campos)
    return cliente.post("/leads/novo", data=dados, follow_redirects=False)


# ---------------------------------------------------------------- Regras puras

def test_utilitarios():
    assert util.cnpj_valido("11.222.333/0001-81")
    assert not util.cnpj_valido("11.222.333/0001-82")
    assert util.cnpj_valido("12.ABC.345/01DE-35")  # CNPJ alfanumérico (exemplo oficial da Receita)
    assert util.formatar_cnpj("12abc34501de35") == "12.ABC.345/01DE-35"
    assert util.normalizar_telefone("+55 (81) 99999-8888") == "81999998888"
    assert util.dominio("https://www.contabil.com.br/contato") == "contabil.com.br"
    assert util.dominio_proprio("https://facebook.com/escritorio") == ""
    assert util.dominio_empresarial("fulano@gmail.com") == ""
    assert util.moeda(1234.5) == "R$ 1.234,50"


def test_calculadora_exemplo_do_pedido():
    r = calcular(100, 40, "fixo", 20)
    assert r == {"receita": 100, "custo": 40, "comissao": 20, "lucro_bruto": 40, "margem": 40.0}
    assert calcular(200, 50, "percentual", 10)["comissao"] == 20


def test_interpretar_pedido():
    r = prospeccao.interpretar_pedido("Quero encontrar 100 escritórios contábeis de alto potencial em São Paulo")
    assert r["quantidade"] == 100 and r["cidade"] == "São Paulo" and r["estado"] == "SP"


# ---------------------------------------------------------------- Login e segurança

def test_sem_login_vai_para_login():
    with TestClient(app) as anonimo:
        r = anonimo.get("/leads", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"


def test_post_sem_csrf_e_recusado(cliente):
    r = cliente.post("/leads/novo", data={"empresa": "Sem token"})
    assert r.status_code == 403


def test_limite_de_tentativas_de_login():
    with TestClient(app) as outro:
        token = csrf_de(outro.get("/login").text)
        for _ in range(5):
            outro.post("/login", data={"csrf": token, "email": "x@teste.com.br", "senha": "errada123"})
        r = outro.post("/login", data={"csrf": token, "email": "x@teste.com.br", "senha": "errada123"})
        assert r.status_code == 429


# ---------------------------------------------------------------- Leads, score e deduplicação

def test_cadastro_score_e_deduplicacao(cliente, csrf):
    r = _criar_lead(cliente, csrf, empresa="Contábil Dedup", whatsapp="(81) 98888-7777", site="www.dedup.com.br",
                    cnpj="11.222.333/0001-81", email="contato@dedup.com.br", atende_empresas="on")
    assert r.status_code == 303
    lead = _lead_por_nome("Contábil Dedup")
    assert lead.score == 5 + 10 + 5  # site sem rede social (metade) + atende empresas + contato direto
    assert lead.potencial == "Baixo potencial"
    for campo, valor in [("whatsapp", "81 98888-7777"), ("site", "https://dedup.com.br/"),
                         ("cnpj", "11222333000181"), ("email", "CONTATO@dedup.com.br")]:
        r = _criar_lead(cliente, csrf, empresa=f"Outro nome {campo}", **{campo: valor})
        assert r.headers["location"] == f"/leads/{lead.id}", campo
    assert _lead_por_nome("Outro nome site") is None


def test_importacao_csv(cliente, csrf):
    csv = ("Empresa;Nome;CNPJ;Telefone;Email;Cidade;UF\n"
           "Escritório Importado;Ana Souza;;(81) 3222-1111;ana@importado.com.br;Recife;PE\n"
           "Inválido;;123;;;Recife;PE\n"
           "Repetido;;;;contato@dedup.com.br;Recife;PE\n").encode("utf-8")
    r = cliente.post("/leads/importar", data={"csrf": csrf, "origem": "Teste"},
                     files={"arquivo": ("leads.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 200
    assert "Importados" in r.text
    assert _lead_por_nome("Escritório Importado").origem == "Teste"
    assert _lead_por_nome("Inválido") is None and _lead_por_nome("Repetido") is None


def test_pipeline_registra_historico_e_converte(cliente, csrf):
    _criar_lead(cliente, csrf, empresa="Contábil Pipeline", email="a@pipeline.com.br")
    lead = _lead_por_nome("Contábil Pipeline")
    r = cliente.post(f"/api/leads/{lead.id}/status", json={"status": "Interessado"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["score"] >= 25  # interesse (20) + contato direto (5)
    r = cliente.post(f"/api/leads/{lead.id}/status", json={"status": "Parceiro"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    with sessao() as db:
        lead = db.get(Lead, lead.id)
        assert lead.parceiro_id and lead.respondeu_em and lead.interessado_em and lead.convertido_em
        assert db.get(Parceiro, lead.parceiro_id).status == "EM ATIVAÇÃO"
        textos = [h.descricao for h in db.execute(select(Historico).where(Historico.lead_id == lead.id)).scalars()]
        assert any("Interessado" in t for t in textos) and any("Convertido em parceiro" in t for t in textos)


def test_cadencia_cria_tarefas_e_resposta_cancela(cliente, csrf):
    _criar_lead(cliente, csrf, empresa="Contábil Cadência", whatsapp="(81) 97777-1111", responsavel="João Pereira")
    lead = _lead_por_nome("Contábil Cadência")
    r = cliente.post("/leads/acoes", data={"csrf": csrf, "ids": str(lead.id), "acao": "cadencia", "cadencia_id": "1",
                                           "inicio": date.today().isoformat()}, follow_redirects=False)
    assert r.status_code == 303
    with sessao() as db:
        tarefas = db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id)).scalars().all()
        assert len(tarefas) == 6
        primeira = min(tarefas, key=lambda t: t.data)
        assert "Olá, João!" in primeira.mensagem and "{{" not in primeira.mensagem
        assert all(t.data.weekday() < 5 for t in tarefas)
        primeira_id = primeira.id
    assert "follow-up" in cliente.get("/agenda").text
    cliente.post(f"/agenda/{primeira_id}/respondeu", data={"csrf": csrf, "resultado": "Tenho interesse, me liga"})
    with sessao() as db:
        lead_db = db.get(Lead, lead.id)
        assert lead_db.status == "Interessado" and lead_db.automacao_pausada  # IA SDR: interesse → humano
        assert lead_db.classificacao_resposta == "QUER LIGAÇÃO"
        pendentes = db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id, Tarefa.status == "pendente")).all()
        assert pendentes == []


def test_opt_out_bloqueia_mensagens(cliente, csrf):
    _criar_lead(cliente, csrf, empresa="Contábil Opt", whatsapp="(81) 96666-2222")
    lead = _lead_por_nome("Contábil Opt")
    cliente.post(f"/leads/{lead.id}/opt-out", data={"csrf": csrf})
    r = cliente.post("/api/mensagens/registrar", json={"lead_id": lead.id, "canal": "whatsapp", "corpo": "oi"},
                     headers={"X-CSRF-Token": csrf})
    assert r.status_code == 409
    r = cliente.post("/leads/acoes", data={"csrf": csrf, "ids": str(lead.id), "acao": "cadencia", "cadencia_id": "1"})
    with sessao() as db:
        assert db.execute(select(Tarefa).where(Tarefa.lead_id == lead.id)).first() is None


def test_controle_de_frequencia(cliente, csrf):
    _criar_lead(cliente, csrf, empresa="Contábil Frequência", whatsapp="(81) 95555-3333")
    lead = _lead_por_nome("Contábil Frequência")
    r1 = cliente.post("/api/mensagens/registrar", json={"lead_id": lead.id, "canal": "whatsapp", "corpo": "1"},
                      headers={"X-CSRF-Token": csrf})
    r2 = cliente.post("/api/mensagens/registrar", json={"lead_id": lead.id, "canal": "whatsapp", "corpo": "2"},
                      headers={"X-CSRF-Token": csrf})
    assert r1.json()["aviso"] == "" and "frequência" in r2.json()["aviso"]


# ---------------------------------------------------------------- Vendas, comissão e vencimentos

def test_venda_comissao_e_vencimento(cliente, csrf):
    with sessao() as db:
        parceiro = Parceiro(escritorio="Parceiro Venda", status="EM ATIVAÇÃO", comissao_tipo="fixo", comissao_valor=25)
        db.add(parceiro)
        db.flush()
        pid = parceiro.id
        produto_id = db.execute(select(Produto.id).where(Produto.nome == "e-CNPJ A1 (1 ano)")).scalar()
    r = cliente.post("/vendas/nova", data={"csrf": csrf, "cliente_nome": "Empresa Cliente", "parceiro_id": str(pid),
                                           "produto_id": str(produto_id), "data": date.today().isoformat()})
    assert r.status_code == 200
    with sessao() as db:
        venda = db.execute(select(Venda).where(Venda.parceiro_id == pid)).scalars().one()
        assert venda.valor == 200 and venda.comissao == 25
        assert db.get(Parceiro, pid).status == "ATIVO"  # ativado na primeira venda
        cert = db.execute(select(Certificado).where(Certificado.venda_id == venda.id)).scalars().one()
        assert cert.data_vencimento.year == date.today().year + 1
        # Alerta de vencimento: simula o certificado faltando 12 dias
        cert.data_vencimento = date.today() + timedelta(days=12)
        cert.ultimo_alerta = None
        processar_vencimentos(db)
        tarefa = db.execute(select(Tarefa).where(Tarefa.certificado_id == cert.id)).scalars().one()
        assert tarefa.tipo == "renovacao" and "vence em 12 dias" in tarefa.acao and tarefa.parceiro_id == pid
        assert cert.ultimo_alerta == 15
        processar_vencimentos(db)  # não duplica
        assert len(db.execute(select(Tarefa).where(Tarefa.certificado_id == cert.id)).all()) == 1


# ---------------------------------------------------------------- Base da Receita e prospecção

def _zip(pasta, nome, linhas):
    import zipfile

    with zipfile.ZipFile(pasta / nome, "w") as z:
        z.writestr(nome.replace(".zip", ".CSV"), "\n".join(";".join(f'"{c}"' for c in l) for l in linhas).encode("latin-1"))


def _estab(basico, nome, cnae, situacao, municipio, ddd, tel, email):
    linha = [""] * 30
    linha[0], linha[1], linha[2], linha[3], linha[4], linha[5] = basico, "0001", "00", "1", nome, situacao
    linha[10], linha[11], linha[13], linha[14], linha[15] = "20100315", cnae, "RUA", "DAS FLORES", "10"
    linha[17], linha[18], linha[19], linha[20], linha[21], linha[22], linha[27] = "BOA VISTA", "50000000", "PE", municipio, ddd, tel, email
    return linha


def test_limpeza_dos_dados_da_receita():
    from app import base_receita

    assert base_receita._titulo("RIO DE JANEIRO") == "Rio de Janeiro"
    assert base_receita._primeiro_email("A@X.COM.BR        b@y.com") == "a@x.com.br"
    assert base_receita._primeiro_email("sem email") == ""
    assert prospeccao._tokens("Wcont Assessoria Contabil Ltda") == {"wcont"}


def test_descobrir_site_nao_chuta(monkeypatch):
    class Resposta:
        def __init__(self, url, texto=""):
            self.url, self.text, self.status_code = url, texto, 200
            self.headers = {"content-type": "text/html"}

    class ClienteFalso:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url):
            # provedor de internet redireciona para a página dele; o site do escritório responde normal
            return Resposta("https://www.provedor.com.br/" if "provedor" in url else url,
                            "CNPJ 11.222.333/0001-81" if "semnome" in url else "")

    monkeypatch.setattr(prospeccao.httpx, "Client", ClienteFalso)
    assert prospeccao.descobrir_site("Wcont Assessoria", "fiscal@wcontassessoria.com.br") == "https://www.wcontassessoria.com.br"
    assert prospeccao.descobrir_site("Mario Emery Contabil", "emery@provedor.com.br") == ""
    assert prospeccao.descobrir_site("Outro Nome", "a@qualquer.com.br") == ""  # nome não combina e sem CNPJ
    assert prospeccao.descobrir_site("Outro Nome", "a@semnome.com.br", "11222333000181") == "https://www.semnome.com.br"
    assert prospeccao.descobrir_site("Fulano", "fulano@gmail.com") == ""


def test_base_receita_e_busca(tmp_path, cliente):
    from app import base_receita
    from app.modelos import Busca

    _zip(tmp_path, "Municipios.zip", [["2531", "RECIFE"], ["2441", "OLINDA"]])
    _zip(tmp_path, "Estabelecimentos0.zip", [
        _estab("11111111", "CONTABIL RECIFE", "6920601", "02", "2531", "81", "32226666", "CONTATO@CONTABILRECIFE.COM.BR"),
        _estab("22222222", "CONSULTORIA TRIBUTARIA", "6920602", "02", "2531", "81", "999998888", ""),
        _estab("33333333", "ESCRITORIO BAIXADO", "6920601", "08", "2531", "81", "32223333", ""),
        _estab("44444444", "PADARIA", "1091101", "02", "2531", "81", "32224444", ""),
        _estab("55555555", "CONTABIL OLINDA", "6920601", "02", "2441", "81", "34295555", ""),
    ])
    _zip(tmp_path, "Empresas0.zip", [["11111111", "CONTABIL RECIFE LTDA", "2062", "49", "1000,00", "03", ""]])
    assert base_receita.importar_pasta(str(tmp_path)) == 3  # ativos e só contabilidade
    with sessao() as db:
        achados = base_receita.buscar(db, "Recife", "PE", 10)
        assert {a["empresa"] for a in achados} == {"Contabil Recife", "Consultoria Tributaria"}
        assert achados[0]["email"] == "contato@contabilrecife.com.br" and achados[0]["cnpj"] == "11111111000100"
        busca = Busca(cidade="Recife", estado="PE", quantidade=10, fontes="receita", enriquecer=False)
        db.add(busca)
        db.flush()
        busca_id = busca.id
    prospeccao.executar_busca(busca_id)
    with sessao() as db:
        busca = db.get(Busca, busca_id)
        assert busca.status == "concluida" and busca.novos == 2
        lead = db.execute(select(Lead).where(Lead.empresa == "Contabil Recife")).scalars().one()
        assert lead.origem == "Prospecção: base da Receita Federal" and lead.telefone == "(81) 3222-6666"
    prospeccao.executar_busca(busca_id)  # repetir a busca não duplica
    with sessao() as db:
        assert len(db.execute(select(Lead).where(Lead.empresa == "Contabil Recife")).all()) == 1
    assert "Contabil Recife" in cliente.get(f"/prospeccao/busca/{busca_id}").text


# ---------------------------------------------------------------- IA sem chave (regras)

def test_ia_sem_chave_usa_regras(cliente, csrf):
    lead = _lead_por_nome("Contábil Cadência")
    with sessao() as db:
        lead = db.get(Lead, lead.id)
        r = ia.gerar_abordagem(db, lead, db.execute(select(Usuario)).scalars().first())
        assert r["fonte"] == "regras" and r["mensagem_whatsapp"] and "{{" not in r["mensagem_email"]
    analise = ia.resposta_por_regras("Já trabalhamos com outra certificadora")
    assert "Já tem parceiro de certificação" in analise["objecoes"]
    assert ia.resposta_por_regras("SAIR")["interesse"] == "pediu para sair"
    r = cliente.post(f"/leads/{lead.id}/qualificar", data={"csrf": csrf})
    assert r.status_code == 200 and "Qualificação" in r.text


# ---------------------------------------------------------------- Telas, exportações e perfis

def test_demonstracao_e_todas_as_telas(cliente):
    from app.seed import popular

    with sessao() as db:
        info = popular(db)
    assert info["leads"] == 72
    paginas = ["/", "/?periodo=tudo", "/prospeccao", "/prospeccao?pedido=Quero+100+em+Recife", "/leads",
               "/leads/pipeline", "/leads/novo", "/leads/importar", "/cadencias", "/cadencias/1", "/cadencias/0",
               "/templates/1", "/templates/0", "/agenda", "/agenda?ver=feitas", "/parceiros", "/parceiros?aba=ranking",
               "/parceiros?aba=parados", "/parceiros/0", "/clientes", "/vencimentos", "/vencimentos?janela=todos",
               "/vendas", "/comissoes", "/relatorios?periodo=tudo", "/ia", "/configuracoes",
               "/configuracoes?aba=score", "/configuracoes?aba=usuarios", "/configuracoes?aba=integracoes",
               "/configuracoes?aba=lgpd", "/configuracoes?aba=logs", "/minha-conta"]
    from app.metricas import PERGUNTAS

    paginas += [f"/ia?pergunta={c}" for c, _ in PERGUNTAS]
    with sessao() as db:
        lead_id = db.execute(select(Lead.id).where(Lead.origem == "Demonstração")).scalars().first()
        parceiro_id = db.execute(select(Parceiro.id)).scalars().first()
    paginas += [f"/leads/{lead_id}", f"/parceiros/{parceiro_id}"]
    for pagina in paginas:
        r = cliente.get(pagina)
        assert r.status_code == 200, f"{pagina}: {r.status_code}"
    for tipo in ("leads", "parceiros", "clientes", "vendas", "comissoes", "vencimentos"):
        for formato in ("csv", "xlsx", "pdf"):
            r = cliente.get(f"/exportar/{tipo}.{formato}")
            assert r.status_code == 200 and len(r.content) > 100, f"{tipo}.{formato}"
    for formato in ("csv", "xlsx", "pdf"):
        assert cliente.get(f"/relatorios/exportar.{formato}?periodo=tudo").status_code == 200


def test_perfis_vendedor_e_parceiro(cliente, csrf):
    with sessao() as db:
        from app.seguranca import resumir_senha

        ana = Usuario(nome="Vend Teste", email="vend@teste.com.br", senha_hash=resumir_senha(SENHA), perfil="vendedor")
        db.add(ana)
        parceiro = db.execute(select(Parceiro)).scalars().first()
        portal = Usuario(nome="Parc Teste", email="parc@teste.com.br", senha_hash=resumir_senha(SENHA),
                         perfil="parceiro", parceiro_id=parceiro.id)
        db.add(portal)
        db.flush()
        meu = Lead(empresa="Lead da Vend", vendedor_id=ana.id)
        db.add(meu)
        db.flush()
        meu_id = meu.id
        alheio_id = db.execute(select(Lead.id).where(Lead.vendedor_id != ana.id)).scalars().first()
    with TestClient(app) as vend:
        token = csrf_de(vend.get("/login").text)
        vend.post("/login", data={"csrf": token, "email": "vend@teste.com.br", "senha": SENHA})
        assert vend.get(f"/leads/{meu_id}").status_code == 200
        assert vend.get(f"/leads/{alheio_id}").status_code == 404
        assert vend.get("/configuracoes").status_code == 403
        assert "Lead da Vend" in vend.get("/leads").text
    with TestClient(app) as parc:
        token = csrf_de(parc.get("/login").text)
        r = parc.post("/login", data={"csrf": token, "email": "parc@teste.com.br", "senha": SENHA}, follow_redirects=False)
        assert r.headers["location"] == "/portal"
        assert parc.get("/portal").status_code == 200
        assert parc.get("/leads").status_code == 403
        token = csrf_de(parc.get("/portal/indicar").text)
        parc.post("/portal/indicar", data={"csrf": token, "nome": "Cliente Indicado", "telefone": "(81) 94444-5555",
                                           "autorizou": "on"})
        assert "Cliente Indicado" in parc.get("/portal/clientes").text
    with sessao() as db:
        c = db.execute(select(Cliente).where(Cliente.nome == "Cliente Indicado")).scalars().one()
        assert db.execute(select(Tarefa).where(Tarefa.cliente_id == c.id, Tarefa.tipo == "indicacao")).first()


def test_apagar_demonstracao(cliente, csrf):
    r = cliente.post("/configuracoes/apagar-demo", data={"csrf": csrf})
    assert r.status_code == 200
    with sessao() as db:
        assert db.execute(select(Lead.id).where(Lead.origem == "Demonstração")).first() is None
        assert db.execute(select(Usuario.id).where(Usuario.email.like("%@demo.example"))).first() is None


def test_vendas_vencimentos_comissoes_ocultos_por_padrao(cliente):
    from app.banco import gravar_config, sessao

    pagina = cliente.get("/").text
    assert 'href="/vendas"' not in pagina and 'href="/comissoes"' not in pagina and 'href="/vencimentos"' not in pagina
    assert "Comissão gerada" not in pagina and "Ranking dos parceiros" not in pagina
    assert 'href="/leads"' in pagina and "Conversão do funil" in pagina
    with sessao() as db:
        gravar_config(db, "mostrar_vendas", "1")
    try:
        pagina = cliente.get("/").text
        assert 'href="/vendas"' in pagina and "Comissão gerada" in pagina and "Ranking dos parceiros" in pagina
    finally:
        with sessao() as db:
            gravar_config(db, "mostrar_vendas", "0")
