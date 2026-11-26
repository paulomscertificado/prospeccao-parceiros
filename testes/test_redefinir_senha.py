"""redefinir_senha.bat (26/11/2026): a opção 1, "sistema na internet", entra no servidor e troca a senha no banco do
sistema no ar (servidor/redefinir_senha.sh). Até então ela usava o dados/supabase.txt, o banco ANTIGO de antes da
mudança para o servidor (17/11/2026), e a senha do sistema no ar não mudava. Testado sem internet e sem servidor: o ssh
daqui é de mentira e nada sai deste computador."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import redefinir_senha
from app.banco import sessao
from app.modelos import Usuario
from app.seguranca import resumir_senha, senha_confere

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "servidor" / "pc"))
import baixar_copias  # noqa: E402  (o mesmo módulo que o redefinir_senha usa para entrar no servidor)

IP = "203.0.113.10"  # endereço de documentação: não existe


def _computador(tmp_path: Path, monkeypatch, com_ip: bool = True, com_chave: bool = True) -> Path:
    """Um computador de mentira com (ou sem) o acesso ao servidor das cópias de segurança."""
    (tmp_path / "dados").mkdir()
    if com_ip:
        (tmp_path / "dados" / "agendador.txt").write_text(f"SITE=https://x.example\nSERVIDOR_IP={IP}\n", encoding="utf-8")
    (tmp_path / "dados" / "supabase.txt").write_text(  # o banco antigo: nunca mais usado pelo redefinir_senha
        "DATABASE_URL=postgresql://postgres.antigo:segredo@pooler.supabase.com:6543/postgres\n", encoding="utf-8")
    chave = tmp_path / "ms_servidor"
    if com_chave:
        chave.write_text("chave de mentira\n", encoding="utf-8")
    monkeypatch.setattr(baixar_copias, "RAIZ", tmp_path)
    monkeypatch.setattr(baixar_copias, "CHAVE", chave)
    monkeypatch.setattr(redefinir_senha, "RAIZ", tmp_path)  # com o supabase.txt antigo ao lado
    monkeypatch.setattr(sys, "path", list(sys.path))  # o redefinir_senha acrescenta a pasta servidor/pc
    return chave


def _ssh_de_mentira(monkeypatch, codigo: int = 0) -> list:
    chamadas = []

    def rodar(comando, *args, **kwargs):
        chamadas.append(comando)
        return subprocess.CompletedProcess(comando, codigo)

    monkeypatch.setattr(redefinir_senha.subprocess, "run", rodar)
    return chamadas


def _respostas(monkeypatch, *respostas: str) -> list:
    perguntas = []
    fila = list(respostas)

    def responder(pergunta=""):
        perguntas.append(pergunta)
        return fila.pop(0)

    monkeypatch.setattr("builtins.input", responder)
    return perguntas


@pytest.mark.parametrize("resposta", ["1", ""], ids=["opcao-1", "enter-e-o-padrao"])
def test_opcao_1_troca_a_senha_no_servidor_e_nao_no_banco_antigo(cliente, tmp_path, monkeypatch, capsys, resposta):
    with sessao() as db:
        pessoa = Usuario(nome="Senha Daqui", email=f"daqui-{resposta or 'enter'}@redefinir.com.br",
                         senha_hash=resumir_senha("SenhaDaqui123"), perfil="vendedor", ativo=True)
        db.add(pessoa)
        db.flush()
        uid = pessoa.id
    chave = _computador(tmp_path, monkeypatch)
    chamadas = _ssh_de_mentira(monkeypatch)
    perguntas = _respostas(monkeypatch, resposta)
    banco_antes = os.environ["DATABASE_URL"]

    assert redefinir_senha.main([]) == 0
    assert len(perguntas) == 1 and "sistema na internet" in perguntas[0]  # as outras perguntas vêm do servidor
    assert len(chamadas) == 1
    comando = chamadas[0]
    assert Path(comando[0]).stem == "ssh" and "-t" in comando  # um terminal: as perguntas do servidor aparecem aqui
    assert comando[comando.index("-i") + 1] == str(chave) and "BatchMode=yes" in comando  # nunca pede a senha do root
    assert comando[-2:] == [f"root@{IP}", "bash /opt/prospeccao/servidor/redefinir_senha.sh"]
    assert (RAIZ / "servidor" / "redefinir_senha.sh").is_file()
    assert os.environ["DATABASE_URL"] == banco_antes  # o endereço do supabase.txt não foi usado
    assert f"Entrando no servidor do sistema ({IP})" in capsys.readouterr().out
    with sessao() as db:  # e nada mudou no banco daqui
        u = db.get(Usuario, uid)
        assert senha_confere("SenhaDaqui123", u.senha_hash) and not u.senha_provisoria


@pytest.mark.parametrize("com_ip, falta", [(False, "SERVIDOR_IP"), (True, "a chave do servidor")])
def test_opcao_1_sem_o_acesso_ao_servidor_nao_muda_nada(tmp_path, monkeypatch, capsys, com_ip, falta):
    _computador(tmp_path, monkeypatch, com_ip=com_ip, com_chave=False)

    def nao_pode(*args, **kwargs):
        raise AssertionError("sem o acesso, o ssh nem é chamado")

    monkeypatch.setattr(redefinir_senha.subprocess, "run", nao_pode)
    _respostas(monkeypatch, "1")
    assert redefinir_senha.main([]) == 1
    saida = capsys.readouterr().out
    assert falta in saida and "Nada foi mudado" in saida


def test_quando_o_ssh_nao_entra_avisa_que_nada_mudou(tmp_path, monkeypatch, capsys):
    _computador(tmp_path, monkeypatch)
    _ssh_de_mentira(monkeypatch, codigo=255)
    _respostas(monkeypatch, "1")
    assert redefinir_senha.main([]) == 255
    assert "Não consegui entrar no servidor" in capsys.readouterr().out


def test_opcao_2_continua_no_banco_deste_computador(cliente, tmp_path, monkeypatch, capsys):
    with sessao() as db:
        pessoa = Usuario(nome="Opcao Dois", email="opcao2@redefinir.com.br", senha_hash=resumir_senha("SenhaVelha123"),
                         perfil="vendedor", ativo=True)
        db.add(pessoa)
        db.flush()
        uid = pessoa.id
    _computador(tmp_path, monkeypatch)
    chamadas = _ssh_de_mentira(monkeypatch)
    _respostas(monkeypatch, "2", str(uid))
    monkeypatch.setattr("getpass.getpass", lambda *_: "SenhaNova123")
    assert redefinir_senha.main([]) == 0
    assert chamadas == []
    with sessao() as db:
        u = db.get(Usuario, uid)
        assert senha_confere("SenhaNova123", u.senha_hash) and u.senha_provisoria


def _modulo(caminho: str, nome: str):
    spec = importlib.util.spec_from_file_location(nome, RAIZ / caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_no_servidor_le_as_configuracoes_do_site_como_o_systemd(tmp_path):
    """O arquivo /etc/prospeccao/ambiente é gravado pelo preparar_migracao.py (+ as linhas do instalar_sistema.sh) para o
    systemd: sem aspas, com aspas simples ou duplas, e nada de trocar $NOME pelo valor de outra configuração."""
    linha = _modulo("servidor/pc/preparar_migracao.py", "preparar_migracao").linha_de_ambiente
    valores = {
        "SIMPLES": "abc-123_=/+",
        "COM_ESPACO": "MS Certificados <a@b.com>",
        "COM_ASPAS": "it's \"x\"",
        "COM_CIFRAO": "$HOME ${SECRET_KEY} #nao-e-comentario",
        "TUDO_JUNTO": "it's ${SECRET_KEY} \\ fim",
    }
    texto = "# configurações do site\n\n" + "\n".join(linha(c, v) for c, v in valores.items())
    texto += "\nDATABASE_URL=postgresql://prospeccao:0a1b2c3d@127.0.0.1:5432/prospeccao\nMODO_NUVEM=1\n"
    arquivo = tmp_path / "ambiente"
    arquivo.write_text(texto, encoding="utf-8", newline="\n")
    lido = redefinir_senha.ler_configuracoes(arquivo)
    assert lido == {**valores, "DATABASE_URL": "postgresql://prospeccao:0a1b2c3d@127.0.0.1:5432/prospeccao",
                    "MODO_NUVEM": "1"}


def test_no_servidor_sem_as_configuracoes_nao_abre_banco_nenhum(tmp_path, monkeypatch, capsys):
    """Sem o arquivo (ou sem o banco nele), o programa para: senão abriria um banco vazio no próprio servidor."""
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("não chega a perguntar nada"))
    assert redefinir_senha.main(["--aqui", "--configuracoes", str(tmp_path / "nao_existe")]) == 1
    assert "Não consegui ler as configurações do sistema" in capsys.readouterr().out
    sem_banco = tmp_path / "ambiente"
    sem_banco.write_text("MODO_NUVEM=1\nSECRET_KEY=x\n", encoding="utf-8")
    monkeypatch.setenv("MODO_NUVEM", "0")
    assert redefinir_senha.main(["--aqui", "--configuracoes", str(sem_banco)]) == 1
    assert "DATABASE_URL" in capsys.readouterr().out
    assert os.environ["MODO_NUVEM"] == "0"  # nada foi carregado


def test_conferir_so_abre_o_banco_com_as_configuracoes_do_arquivo(cliente, tmp_path, monkeypatch, capsys):
    """O --conferir é o que se roda depois de publicar (bash .../redefinir_senha.sh --conferir): não lê nem muda dado."""
    monkeypatch.setenv("PP_TESTE_REDEFINIR", "antes")  # o monkeypatch devolve o ambiente como era depois do teste
    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL"])
    arquivo = tmp_path / "ambiente"
    arquivo.write_text(f"DATABASE_URL={os.environ['DATABASE_URL']}\nPP_TESTE_REDEFINIR=carregado\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("não pergunta nada"))
    assert redefinir_senha.main(["--aqui", "--configuracoes", str(arquivo), "--conferir"]) == 0
    assert "O banco do sistema respondeu. Nada foi mudado." in capsys.readouterr().out
    assert os.environ["PP_TESTE_REDEFINIR"] == "carregado"


def test_roteiro_do_servidor_roda_como_o_sistema_e_recusa_sem_terminal():
    roteiro = (RAIZ / "servidor" / "redefinir_senha.sh").read_text(encoding="utf-8")
    assert "runuser -u prospeccao" in roteiro  # o usuário do site: nada no servidor fica com dono root
    assert "--aqui --configuracoes /etc/prospeccao/ambiente" in roteiro  # as configurações do site (prospeccao.service)
    assert "/etc/prospeccao/ambiente" in (RAIZ / "servidor" / "prospeccao.service").read_text(encoding="utf-8")
    bash = next((b for b in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash") or "") if b and Path(b).is_file()), "")
    if not bash:
        pytest.skip("sem bash neste computador")
    r = subprocess.run([bash, str(RAIZ / "servidor" / "redefinir_senha.sh")], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 1 and "ssh -t" in r.stdout  # sem terminal, para antes de mexer em qualquer coisa
