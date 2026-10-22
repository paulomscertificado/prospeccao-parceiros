# Instalação e primeiros passos

## 1. Como instalar (computador Windows)

Pré-requisito: Python 3.12 ou mais novo, instalado com **"Add Python to PATH"**.

1. Copie a pasta `prospeccao-parceiros` para o computador.
2. Dois cliques em `instalar.bat`. Ele:
   - cria a pasta `.venv` com as bibliotecas (`requirements.txt`);
   - cria o arquivo `.env` a partir do `.env.example`.
3. Dois cliques em `iniciar.bat` → abre `http://localhost:8001`.
4. Crie a conta de administrador no primeiro acesso.

Instalação manual (Linux/Mac ou terminal):

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python iniciar.py
```

Dados de demonstração (fictícios): `popular_demo.bat` ou `python -m app.seed`.
Testes: `testar.bat` ou `python -m pytest -q testes`.

## 2. Como configurar o banco de dados

- **Padrão (sem configurar nada):** SQLite, arquivo `dados/banco.db`. Ideal para 1 computador e
  equipes pequenas. Backup = copiar a pasta `dados/`.
- **PostgreSQL (produção / vários usuários ao mesmo tempo):** no `.env`:
  ```
  DATABASE_URL=postgresql+psycopg://usuario:senha@servidor:5432/prospeccao
  ```
  Instale o driver com `pip install -r requirements-producao.txt`. As tabelas são criadas sozinhas
  na primeira vez que o sistema abre. O `docker-compose.yml` já sobe um PostgreSQL pronto (ver `deploy.md`).

O schema está em `app/modelos.py` (e `app/base_receita.py` para a base da Receita); descrição em `arquitetura.md`.
Migrações: no MVP as tabelas são criadas com `create_all`. Ao mudar colunas em produção, use Alembic
(`pip install alembic`, `alembic init`) apontando para `app.banco.Base.metadata`.

## 7. Como criar usuários

Configurações > **Usuários** (só administrador):
- Preencha nome, e-mail, perfil e senha inicial → **Criar**. Passe a senha à pessoa por um canal seguro;
  ela troca em **Minha conta**.
- Perfil **Parceiro**: escolha também o parceiro (escritório) ligado ao login. Ele verá só o portal.
- Desativar: desmarque "Ativo" e salve (a pessoa sai na hora).
- Esqueceu a senha e não há outro admin: `redefinir_senha.bat`.

## 8. Como importar leads

Leads > **Importar CSV/Excel**. A primeira linha deve ter os nomes das colunas:

| Coluna | Obrigatória | Observação |
|---|---|---|
| Empresa | sim | também aceita "Razão social", "Escritório" |
| Nome | | nome do responsável |
| CNPJ | | validado (inclusive o novo CNPJ alfanumérico) |
| Telefone, WhatsApp | | validados (DDD + número) |
| Email | | validado |
| Site, Instagram, LinkedIn | | |
| Cidade, Estado (UF) | | UF validada |

O sistema mostra quantos foram importados, quais eram duplicados (mesmo CNPJ, domínio do site, telefone ou
e-mail) e quais linhas têm erro, com o motivo. Informe a **origem** (ex.: "Lista do evento CRC-PE") e a
**base legal** — ficam gravadas em cada lead.

## 9. Como criar uma campanha

1. **Prospecção**: busque "100 escritórios em São Paulo" (ou filtre em **Leads**).
2. Marque os leads (os de maior score vêm primeiro).
3. Escolha a cadência e a data de início → **Iniciar campanha**. Opcional: "Personalizar a 1ª mensagem com IA".
4. As tarefas aparecem na **Agenda** com a mensagem já personalizada ({{nome}}, {{empresa}}, {{cidade}}...).
5. Em cada tarefa: **Copiar mensagem / Abrir no WhatsApp**, depois **Feito**. Se o lead responder,
   **Respondeu** (as tentativas seguintes são canceladas).
6. Acompanhe os resultados em Cadências > **Campanhas** e no Dashboard.

Cadências e templates são editados em **Cadências** (administrador e gestor).
