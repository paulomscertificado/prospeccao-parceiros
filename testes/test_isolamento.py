"""White label, Fase 2: cada AR vê e grava só o que é dela (app/isolamento.py).

Uma pessoa do Grupo Certy com o papel de ADMINISTRADOR (o que mais alcança) percorre TODAS as rotas GET do sistema,
sem id e com os ids de tudo o que é da AR MS: nenhuma resposta pode trazer o dado da MS. Depois tenta as rotas POST com
os ids da MS: nada da MS pode mudar. Controles: ela vê o que é do Grupo Certy, e o Admin Master vê as duas ARs.
"""
import re
from datetime import date, timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.banco import sessao
from app.main import app
from app.modelos import (Campanha, Certificado, Cliente, ConexaoWhatsApp, ContaEmail, Historico, Lead, Mensagem,
                         MensagemWhatsApp, Notificacao, Oportunidade, Parceiro, Tarefa, Tenant, Usuario, Venda,
                         VisualCampanha)
from app.seguranca import limite_pedidos, resumir_senha
from conftest import SENHA, csrf_de

SIGILO = "SIGILOMS7Q"     # aparece só nos dados da AR MS
CERTY = "VISIVELCERTY3K"  # aparece só nos dados do Grupo Certy
FORA = ("/api/", "/descadastrar", "/sair", "/logout", "/static")  # máquinas (senha própria), saída e arquivos


def _zerar_limite():
    for chave in list(limite_pedidos._eventos):
        limite_pedidos.zerar(chave)


def _entrar(email: str) -> TestClient:
    c = TestClient(app)
    c.post("/login", data={"csrf": csrf_de(c.get("/login").text), "email": email, "senha": SENHA})
    return c


@pytest.fixture(scope="module")
def duas_ars(cliente):
    """Uma pessoa e um pouco de tudo em cada AR."""
    with sessao() as db:
        ids_ar = {s: i for i, s in db.execute(select(Tenant.id, Tenant.slug))}
        ms = Usuario(nome=f"Admin {SIGILO}", email="admin.isolamento@ms.com.br", perfil="admin",
                     senha_hash=resumir_senha(SENHA), empresa_nome="MS Certificação Digital")
        certy = Usuario(nome="Admin Certy", email="admin.isolamento@grupocerty.com.br", perfil="admin",
                        senha_hash=resumir_senha(SENHA), empresa_nome="Grupo Certy")
        db.add_all([ms, certy])
        db.flush()
        assert (ms.tenant_id, certy.tenant_id) == (ids_ar["ms"], ids_ar["grupo-certy"])  # AR pela empresa
        lead = Lead(empresa=f"{SIGILO} Contabilidade", vendedor_id=ms.id, email="contato@sigiloms7q.com.br",
                    whatsapp="81988887777", responsavel=f"Dono {SIGILO}")
        lead_certy = Lead(empresa=f"{CERTY} Ltda", vendedor_id=certy.id)
        camp = Campanha(nome=f"Campanha {SIGILO}", usuario_id=ms.id)
        db.add_all([lead, lead_certy, camp])
        db.flush()
        cliente_ms = Cliente(nome=f"Cliente {SIGILO}")
        parceiro = Parceiro(escritorio=f"Parceiro {SIGILO}", vendedor_id=ms.id)
        visual = VisualCampanha(nome=f"Visual {SIGILO}", usuario_id=ms.id)
        db.add_all([cliente_ms, parceiro, visual])
        db.flush()
        tarefa = Tarefa(data=date.today(), lead_id=lead.id, campanha_id=camp.id, usuario_id=ms.id,
                        mensagem=f"Mensagem {SIGILO}")
        cert = Certificado(cliente_nome=f"Certificado {SIGILO}", data_vencimento=date.today() + timedelta(days=20),
                           lead_id=lead.id, campanha_id=camp.id)
        db.add_all([tarefa, cert, Historico(lead_id=lead.id, tipo="nota", descricao=f"Nota {SIGILO}"),
                    Mensagem(canal="email", lead_id=lead.id, assunto=f"Assunto {SIGILO}", corpo=f"Corpo {SIGILO}"),
                    Oportunidade(lead_id=lead.id, resumo=f"Resumo {SIGILO}"),
                    Venda(cliente_id=cliente_ms.id, observacoes=f"Venda {SIGILO}"),
                    ConexaoWhatsApp(id=f"u{ms.id}", nome=f"Numero {SIGILO}", dono_id=ms.id),
                    ContaEmail(nome=f"Conta {SIGILO}", dono_id=ms.id, endereco="sigiloms7q@mscertificados.com.br"),
                    Notificacao(usuario_id=ms.id, texto=f"Aviso {SIGILO}")])
        db.flush()
        db.add(MensagemWhatsApp(id_wl=990771, telefone="81988887777", conexao=f"u{ms.id}", direcao="entrada",
                                nome=f"Contato {SIGILO}", texto=f"Oi {SIGILO}"))
        db.flush()
        do_ms = [o for o in (lead, camp, tarefa, cert, cliente_ms, parceiro, visual) if o.tenant_id != ids_ar["ms"]]
        assert not do_ms, do_ms  # tudo nasceu na AR MS (pela pessoa dona)
        ids_ms = sorted({lead.id, camp.id, tarefa.id, cert.id, cliente_ms.id, parceiro.id, visual.id, ms.id})
        dados = {"certy_email": certy.email, "ms_email": ms.email, "ids_ms": ids_ms, "lead_ms": lead.id,
                 "lead_certy": lead_certy.id, "camp_ms": camp.id, "conexao_ms": f"u{ms.id}"}
    return dados


def _foto_ms(dados) -> tuple:
    with sessao() as db:
        lead, camp = db.get(Lead, dados["lead_ms"]), db.get(Campanha, dados["camp_ms"])
        return (lead and (lead.empresa, lead.status, lead.vendedor_id, lead.opt_out, lead.etapa),
                camp and (camp.nome, camp.status, camp.aprovado_em),
                db.execute(select(Tarefa.status).where(Tarefa.lead_id == dados["lead_ms"])).scalars().all())


PLATAFORMA = ("/cadencias", "/categorias", "/templates", "/permissoes")  # modelos e papéis da plataforma: Fase 3


def _todas_as_rotas():
    """(caminho completo, rota) das 178 rotas (esta versão do FastAPI guarda os routers incluídos à parte)."""
    for item in app.routes:
        if isinstance(item, APIRoute):
            yield item.path, item
        elif type(item).__name__ == "_IncludedRouter":
            prefixo = getattr(item.include_context, "prefix", "") or ""
            for rota in item.original_router.routes:
                if isinstance(rota, APIRoute):
                    yield prefixo + rota.path, rota


def _rotas(metodo: str):
    for caminho, rota in _todas_as_rotas():
        if metodo in rota.methods and not caminho.startswith(FORA):
            yield caminho, rota


def _caminhos(caminho: str, rota, dados) -> list[str]:
    """O caminho sem parâmetro, ou com cada id da MS (e o telefone e o número de WhatsApp da MS nos de texto)."""
    nomes = re.findall(r"\{(\w+)(?::[^}]*)?\}", caminho)
    if not nomes:
        return [caminho]
    valores = [str(i) for i in dados["ids_ms"]] + ["81988887777", dados["conexao_ms"]]
    if len(nomes) > 1:
        valores = valores[:3]
    return [re.sub(r"\{(\w+)(?::[^}]*)?\}", v, caminho) for v in valores]


def test_pessoa_do_grupo_certy_nunca_ve_nada_da_ar_ms(duas_ars):
    _zerar_limite()
    c = _entrar(duas_ars["certy_email"])
    vazou, quebrou, percorridas = [], [], 0
    try:
        for modelo, rota in _rotas("GET"):
            for caminho in _caminhos(modelo, rota, duas_ars):
                percorridas += 1
                if percorridas % 150 == 0:
                    _zerar_limite()
                r = c.get(caminho, follow_redirects=False)
                if SIGILO in r.text:
                    vazou.append((caminho, r.status_code))
                if r.status_code >= 500:
                    quebrou.append(caminho)
    finally:
        _zerar_limite()
    assert percorridas >= 60  # as 65 rotas GET (menos as de máquina), as com id uma vez por id da MS
    assert not vazou, f"dado da AR MS apareceu para o Grupo Certy em: {vazou}"
    assert not quebrou, f"tela com erro para a pessoa do Grupo Certy: {quebrou}"
    assert CERTY in c.get(f"/leads/{duas_ars['lead_certy']}").text  # controle: ela vê o que é do Grupo Certy


def test_ar_ms_nao_ve_o_grupo_certy_e_o_admin_master_ve_as_duas(cliente, duas_ars):
    _zerar_limite()
    try:
        do_ms, da_certy = f"/leads/{duas_ars['lead_ms']}", f"/leads/{duas_ars['lead_certy']}"
        ms = _entrar(duas_ars["ms_email"])  # administrador da AR MS (não o master)
        assert SIGILO in ms.get(do_ms).text
        r = ms.get(da_certy)
        assert r.status_code == 404 and CERTY not in r.text
        # Admin Master (primeiro acesso): a plataforma toda, até a Fase 3
        assert SIGILO in cliente.get(do_ms).text and CERTY in cliente.get(da_certy).text
    finally:
        _zerar_limite()


def test_pessoa_do_grupo_certy_nao_muda_nada_da_ar_ms(duas_ars):
    _zerar_limite()
    c = _entrar(duas_ars["certy_email"])
    token = csrf_de(c.get("/minha-conta").text)
    antes = _foto_ms(duas_ars)
    try:
        for modelo, rota in _rotas("POST"):
            if "{" not in modelo or modelo.startswith(PLATAFORMA):
                continue
            for caminho in _caminhos(modelo, rota, duas_ars):
                c.post(caminho, data={"csrf": token}, follow_redirects=False)
            _zerar_limite()
    finally:
        _zerar_limite()
    assert _foto_ms(duas_ars) == antes, "uma rota POST mexeu em dado da AR MS"
