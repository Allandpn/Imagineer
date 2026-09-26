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

Neste modo o PostgreSQL precisa estar acessível na `URL_BANCO` do `.env` — trocando `db` por `localhost` se o banco estiver rodando via `docker compose up db`.

## Testes

```bash
./venv/Scripts/python.exe -m pytest
```

Os testes não precisam de banco no ar: usam um SQLite em memória no lugar do PostgreSQL.

## Migrations do banco

```bash
# depois de criar ou alterar um modelo em imagineer/modelos/
./venv/Scripts/python.exe -m alembic revision --autogenerate -m "descricao da mudanca"
./venv/Scripts/python.exe -m alembic upgrade head
```
