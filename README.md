# Imagineer

Sistema pessoal que gera **prompts de imagem a partir de e-books (EPUB)**, pensado para quem tem afantasia — a dificuldade de visualizar mentalmente personagens, ambientes e cenas durante a leitura.

O sistema não gera a imagem: ele monta o prompt, mantendo a **consistência visual** de cada personagem, ambiente e objeto ao longo da história. O usuário gera a imagem numa IA externa e a importa de volta, formando um catálogo visual do livro.

A especificação completa está em [`ESPECIFICACAO.md`](ESPECIFICACAO.md).

## Como está organizado

```
imagineer/
├── principal.py     # cria a API e registra as rotas
├── configuracao.py  # leitura das variáveis de ambiente
├── banco/           # conexão e sessão do SQLAlchemy
├── modelos/         # tabelas do banco
├── esquemas/        # contratos de entrada e saída da API
├── rotas/           # endpoints HTTP
├── servicos/        # regras de negócio
└── ia/              # integração com provedores de IA
```

O porquê de cada pasta está explicado no item 1.5 da especificação.

## Subindo com Docker

É o jeito recomendado, e o mesmo usado no Raspberry Pi.

```bash
cp .env.exemplo .env      # ajuste a senha do banco
docker compose up --build
```

Depois:

- API: <http://localhost:8000/saude>
- Documentação automática: <http://localhost:8000/docs>

## Rodando sem Docker (desenvolvimento)

```bash
python -m venv venv
./venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source venv/bin/activate && pip install -r requirements.txt  # Linux/macOS

./venv/Scripts/python.exe -m uvicorn imagineer.principal:aplicacao --reload
```

Neste modo o PostgreSQL precisa estar acessível na `URL_BANCO` do `.env` — trocando `db` por `127.0.0.1` se o banco estiver rodando via `docker compose up db`.

> Use `127.0.0.1`, não `localhost`. No Windows, `localhost` resolve para IPv6 (`::1`) antes de IPv4, e o Docker publica a porta apenas em IPv4. A conexão acaba funcionando, mas só depois de esperar o timeout expirar — e sem timeout definido, parece que travou.

## Testes

```bash
./venv/Scripts/python.exe -m pytest
```

Os testes não precisam de banco no ar: usam um SQLite em memória no lugar do PostgreSQL.

## Migrations do banco

As migrations precisam alcançar o PostgreSQL. Com a stack no ar, o banco está em `127.0.0.1:5432` e o `.env` local já aponta para lá.

```bash
# depois de criar ou alterar um modelo em imagineer/modelos/
./venv/Scripts/python.exe -m alembic revision --autogenerate -m "descricao da mudanca"
./venv/Scripts/python.exe -m alembic upgrade head

# confere se algum modelo mudou sem a migration correspondente
./venv/Scripts/python.exe -m alembic check

# desfaz a última migration
./venv/Scripts/python.exe -m alembic downgrade -1
```

Não rode dois comandos do Alembic ao mesmo tempo contra o mesmo banco: o segundo fica esperando o primeiro liberar a tabela.

### Modelos já criados

| Tabela | Item da especificação |
|---|---|
| `livros`, `capitulos` | 3.4 (a) |
| `elementos`, `estados_elemento` | 3.4 (b) |
| `cenas`, `cenas_estados_elemento`, `perfis_renderizacao`, `prompts`, `imagens` | 3.4 (c) |

O modelo do MVP está completo.

### Serviços já implementados

| Serviço | Item | O que faz |
|---|---|---|
| `servicos/importacao_epub.py` | 2.2 | Lê um EPUB e o estrutura em Livro + Capítulos |

Nenhuma rota de domínio existe ainda — só `/saude`. A importação já funciona, mas ainda só é alcançável de dentro do Python.
