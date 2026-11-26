"""Renovação de uma marca com dias diferentes dos da MS (26/11/2026, pedido da Maria: o Grupo Certy importou a planilha
com vencimentos mais longe e escolheu avisos 25, 15, 5 e 1 dia antes; a MS usa 12, 6, 3 e 1). A montagem da campanha
roda em segundo plano (trabalhos.executar), sem a marca da tela: os textos dos avisos e o horário e os feriados da 2ª
onda saíam da plataforma (a da MS), e a campanha aprovada dias depois pelo Admin Master fora das marcas tinha as datas
contadas de novo com os dias da plataforma. Aqui tudo segue a marca da campanha. Celulares e e-mails só destes testes.
"""

import json
from datetime import date, timedelta

from sqlalchemy import delete, select

from app import cadencias, campanhas, renovacao, trabalhos
from app.banco import config_da_ar, gravar_config, gravar_config_da_ar, ler_config, sessao
from app.isolamento import ligar
from app.modelos import Campanha, ConfiguracaoAR, Tarefa, Usuario
from test_renovacao import _SemLinha, _limpar, _linha
from test_renovacao_ar import _ids_ar, _importar, _montar_pelo_trabalho, _pessoa

CHAVES = ("renov_dias", "renov_mensagens", "renov_hora_inicio", "renov_hora_fim")
DIAS_DA_CERTY = (25, 15, 5, 1)
TEXTO_DA_CERTY = ("Olá, {responsavel}! Aviso do Grupo Certy, com o texto da marca.\n\n{vencimentos}\n\n"
                  "(Se não quiser receber estes avisos, é só responder SAIR.)")


def _certy(db) -> tuple[int, int, str]:
    """A administradora do Grupo Certy e a AR dele, com os dias, o horário e o texto do 1º aviso próprios; a plataforma
    com os dias do piloto da MS (12, 6, 3 e 1), como no sistema em 26/11/2026. Devolve (pessoa, AR, dias da
    plataforma antes do teste)."""
    ar = _ids_ar(db)["grupo-certy"]
    certy = _pessoa(db, "Thamires Dias", "thamires.dias@grupocerty.com.br", "admin", "Grupo Certy")
    with config_da_ar(db, None):
        antes = ler_config(db, "renov_dias")
        gravar_config(db, "renov_dias", "12,6,3,1")
    gravar_config_da_ar(db, ar, "renov_dias", ",".join(str(d) for d in DIAS_DA_CERTY))
    gravar_config_da_ar(db, ar, "renov_hora_inicio", "10:00")
    gravar_config_da_ar(db, ar, "renov_hora_fim", "16:00")
    gravar_config_da_ar(db, ar, "renov_mensagens", json.dumps({"renov_aviso": {"whatsapp": TEXTO_DA_CERTY}}))
    return certy.id, ar, antes


def _desfazer(ar: int, dias_antes: str) -> None:
    with sessao() as db:
        _limpar(db)
        db.execute(delete(ConfiguracaoAR).where(ConfiguracaoAR.tenant_id == ar, ConfiguracaoAR.chave.in_(CHAVES)))
        with config_da_ar(db, None):
            gravar_config(db, "renov_dias", dias_antes)


def _whatsapps(db, cid: int, status: str = "rascunho") -> list[Tarefa]:
    return sorted(db.execute(select(Tarefa).where(Tarefa.campanha_id == cid, Tarefa.canal == "whatsapp",
                                                  Tarefa.status == status)).scalars(), key=lambda t: (t.data, t.hora))


def test_montagem_em_segundo_plano_usa_os_dias_e_o_texto_da_marca(cliente, monkeypatch):
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    with sessao() as db:
        _limpar(db)
        certy_id, ar, dias_antes = _certy(db)
    try:
        with sessao() as db:  # na tela da Thamires (Grupo Certy)
            certy = db.get(Usuario, certy_id)
            ligar(db, certy)
            _importar(db, [_linha(22, "7720001", "e-CPF A1 12 meses", "", "", "CLIENTE DIAS CERTY", "52998224725",
                                  "cliente.dias@testedias-certy.com.br", "81987730001")], certy)
            assert renovacao.dias_aviso(db) == DIAS_DA_CERTY and renovacao.janela(db) == 25
            camp = renovacao.criar_campanha(db, certy, quantidade=10)
            assert camp is not None
            cid = camp.id
            venc = date.today() + timedelta(days=22)
            esperado = [d for d in renovacao.datas_dos_avisos(venc, renovacao.primeiro_dia(db, certy), True,
                                                              DIAS_DA_CERTY, renovacao.dias_sem_envio(db, certy)) if d]
        _montar_pelo_trabalho(cid)
        with sessao() as db:
            camp = db.get(Campanha, cid)
            assert camp.status == "aguardando_aprovacao", camp.erro
            zaps = _whatsapps(db, cid)
            assert [t.data for t in zaps] == esperado  # 25, 15, 5 e 1 dia antes (não os 12, 6, 3 e 1 da plataforma)
            assert zaps[0].angulo == "renov_aviso"
            assert "Aviso do Grupo Certy, com o texto da marca" in zaps[0].mensagem  # antes: o texto da plataforma
    finally:
        _desfazer(ar, dias_antes)


def test_segunda_onda_sai_no_horario_da_marca(cliente, monkeypatch):
    """"Montar com todos da planilha": o contato com um certificado vencendo daqui a 22 dias e outro daqui a 80 recebe
    duas ondas de avisos. A 2ª onda usava o horário da plataforma (até as 18:00), e não o da marca (até as 16:00)."""
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)

    class _NoFim:  # o sorteio do horário sempre no fim da faixa: mostra até que horas cada aviso pode ir
        @staticmethod
        def randint(a, b):
            return b

    monkeypatch.setattr(cadencias, "random", _NoFim)
    with sessao() as db:
        _limpar(db)
        certy_id, ar, dias_antes = _certy(db)
    try:
        with sessao() as db:
            certy = db.get(Usuario, certy_id)
            ligar(db, certy)
            email, celular = "cliente.ondas@testedias-certy.com.br", "81987730011"
            _importar(db, [_linha(22, "7720011", "e-CPF A1 12 meses", "", "", "CLIENTE ONDAS CERTY", "52998224725",
                                  email, celular),
                           _linha(80, "7720012", "e-CPF A3 36 meses", "", "", "CLIENTE ONDAS CERTY", "52998224725",
                                  email, celular)], certy)
            camp = renovacao.criar_campanha(db, certy, None, ate=renovacao.ATE_TODOS)
            assert camp is not None
            cid = camp.id
        _montar_pelo_trabalho(cid)
        with sessao() as db:
            assert db.get(Campanha, cid).status == "aguardando_aprovacao"
            tarefas = db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars().all()
            assert len({t.certificado_id for t in tarefas}) == 2  # as duas ondas
            assert tarefas and all(t.hora <= "16:00" for t in tarefas), sorted({t.hora for t in tarefas})
    finally:
        _desfazer(ar, dias_antes)


def test_aprovada_dias_depois_pelo_admin_master_fora_das_marcas_usa_os_dias_da_marca(cliente, monkeypatch):
    monkeypatch.setattr(trabalhos.threading, "Thread", _SemLinha)
    with sessao() as db:
        _limpar(db)
        certy_id, ar, dias_antes = _certy(db)
    try:
        with sessao() as db:
            certy = db.get(Usuario, certy_id)
            ligar(db, certy)
            _importar(db, [_linha(22, "7720021", "e-CPF A1 12 meses", "", "", "CLIENTE APROVA CERTY", "52998224725",
                                  "cliente.aprova@testedias-certy.com.br", "81987730021")], certy)
            cid = renovacao.criar_campanha(db, certy, quantidade=10).id
        _montar_pelo_trabalho(cid)
        with sessao() as db:  # aprovada 3 dias depois de montada: as datas são contadas de novo do vencimento
            for t in db.execute(select(Tarefa).where(Tarefa.campanha_id == cid)).scalars():
                t.data -= timedelta(days=3)
        with sessao() as db:
            master = db.execute(select(Usuario).where(Usuario.master.is_(True))).scalars().first()
            ligar(db, master)  # o Admin Master fora das marcas (sem "Entrar na AR"): as configurações da plataforma
            camp = db.get(Campanha, cid)
            campanhas.aprovar(db, camp, master)
            venc = date.today() + timedelta(days=22)
            dono = db.get(Usuario, certy_id)
            with config_da_ar(db, ar):
                esperado = [d for d in renovacao.datas_dos_avisos(venc, renovacao.primeiro_dia(db, dono), True,
                                                                  DIAS_DA_CERTY, renovacao.dias_sem_envio(db, dono))
                            if d]
            zaps = _whatsapps(db, cid, "pendente")
            assert [t.data for t in zaps] == esperado  # antes: 12, 6, 3 e 1 dia antes (os da plataforma)
            db.rollback()
    finally:
        _desfazer(ar, dias_antes)
