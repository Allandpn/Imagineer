# Imagineer

Sistema pessoal que gera **prompts de imagem a partir de e-books (EPUB)**, pensado para quem tem afantasia — a dificuldade de visualizar mentalmente personagens, ambientes e cenas durante a leitura.

O sistema não gera a imagem: ele monta o prompt, mantendo a **consistência visual** de cada personagem, ambiente e objeto ao longo da história. O usuário gera a imagem numa IA externa e a importa de volta, formando um catálogo visual do livro.

A especificação completa está em [`ESPECIFICACAO.md`](ESPECIFICACAO.md).

O manual técnico de casos de uso e rotas (o que cada endpoint faz, campos obrigatórios/opcionais, fluxo de interação) está publicado em: <https://claude.ai/artifact/TQm1FKkVvBfKPBxPmoFtfU>. É atualizado junto com o código — se algo divergir, a especificação é a fonte de verdade.

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

## Raspberry Pi: servidor 24/7

O mesmo `docker compose` roda no Raspberry Pi (as imagens `python:3.12-slim` e `postgres:16-alpine` têm versão ARM64).
O app acessa o Pi pelo **Tailscale**, de qualquer lugar, sem abrir porta no roteador.

**1. Preparar o Pi** (uma vez; Raspberry Pi OS de 64 bits)

```bash
curl -fsSL https://get.docker.com | sh          # instala o Docker
sudo usermod -aG docker $USER                    # depois, saia e entre de novo no SSH
curl -fsSL https://tailscale.com/install.sh | sh # instala o Tailscale
sudo tailscale up                                # abre um link: entre com a mesma conta dos outros aparelhos
tailscale ip -4                                  # o endereço 100.x.y.z do Pi: é o que vai no app
```

**2. Baixar e subir**

```bash
git clone https://github.com/Allandpn/Imagineer.git && cd Imagineer
cp .env.exemplo .env && nano .env     # SENHA_BANCO (invente uma) e CHAVE_API_OPENROUTER
docker compose up -d --build          # a primeira vez demora; as migrations rodam sozinhas
curl http://localhost:8000/saude      # {"situacao":"ok","banco":"conectado"}
```

O `restart: unless-stopped` do compose faz tudo voltar sozinho quando o Pi reinicia.

**3. Levar os dados do PC** (opcional: sem isso o Pi começa vazio)

No PC, na pasta do projeto, com a stack rodando:

```bash
docker compose exec -T db pg_dump -U imagineer -d imagineer --clean --if-exists > backup-banco.sql
docker compose cp api:/dados/imagens ./backup-imagens
scp -r backup-banco.sql backup-imagens usuario@IP-DO-PI:~/Imagineer/
```

No Pi, na pasta do projeto (a stack já deve ter subido uma vez):

```bash
docker compose exec -T db psql -U imagineer -d imagineer < backup-banco.sql
docker compose cp backup-imagens/. api:/dados/imagens
docker compose restart api
```

**4. Atualizar depois de novos commits**

```bash
cd ~/Imagineer && git pull && docker compose up -d --build
```

**5. No app:** em Configuração, `http://100.x.y.z:8000` e **Testar**.

**Cuidados.** O servidor não tem login: a proteção é o Tailscale (só os aparelhos da sua conta entram) — não compartilhe
aparelhos nem convide pessoas para a sua rede sem limitar o acesso. O banco só aceita conexões do próprio Pi
(`127.0.0.1:5432`). Faça backup de vez em quando (o comando `pg_dump` acima) e guarde-o fora do Pi.

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
| `servicos/importacao_epub.py` | 2.2 | Lê um EPUB e o estrutura em Livro + Capítulos, sugerindo o que não é narrativa. Validado contra dezoito livros publicados, sem esconder nenhum capítulo |
| `servicos/estados_de_elemento.py` | 3.4b, 6.3 | Descobre o estado vigente de cada elemento num ponto da narrativa |
| `servicos/configuracao_ia.py` | 4.3 | Resolve de onde vem a chave de API e monta o provedor de IA |
| `ia/openrouter.py` | 4.1, 4.2 | Conversa com o OpenRouter: lista modelos, extrai elementos, monta prompt |
| `ia/falso.py` | 4.2 | Provedor falso, para testes e para usar o sistema sem chave |

### Rotas disponíveis

| Método e caminho | O que faz |
|---|---|
| `GET /saude` | Confirma que a API está no ar e falando com o banco |
| `POST /livros` | Importa um arquivo EPUB (`multipart/form-data`, campo `arquivo`) |
| `GET /livros` | Lista a biblioteca |
| `GET /livros/{id}` | O livro com a lista de capítulos, sem o texto |
| `DELETE /livros/{id}` | Remove o livro e tudo que depende dele |
| `GET /capitulos/{id}` | O capítulo com o texto |
| `PATCH /capitulos/{id}` | Ajusta `titulo` e `ignorado` |
| `GET /livros/{id}/elementos` | Os elementos do livro, com o estado mais recente de cada |
| `POST /livros/{id}/elementos` | Cadastra um elemento, opcionalmente com o primeiro estado |
| `GET /elementos/{id}` | O elemento com todos os seus estados |
| `PATCH /elementos/{id}` | Ajusta nome, tipo e descrição |
| `DELETE /elementos/{id}` | Remove o elemento e seus estados |
| `POST /elementos/{id}/estados` | Registra um novo estado a partir de um capítulo |
| `PATCH /estados/{id}` | Ajusta a descrição ou define a imagem-âncora |
| `DELETE /estados/{id}` | Remove um estado |
| `GET /capitulos/{id}/estados-vigentes` | Como estava cada elemento neste ponto da narrativa |
| `PATCH /livros/{id}` | Corrige metadados e define o perfil de renderização padrão |
| `GET /capitulos/{id}/cenas` | As cenas de um capítulo |
| `POST /capitulos/{id}/cenas` | Cria uma cena |
| `GET /cenas/{id}` | A cena com quem aparece nela, em seus estados |
| `PATCH /cenas/{id}` | Ajusta título, descrição e atributos situacionais |
| `PUT /cenas/{id}/estados` | Define a lista completa de quem aparece na cena |
| `DELETE /cenas/{id}` | Remove a cena, sem apagar os estados |
| `GET /perfis-renderizacao` | Lista os perfis de estilo, compartilhados entre livros |
| `POST /perfis-renderizacao` | Cria um perfil |
| `GET /perfis-renderizacao/{id}` | Abre um perfil |
| `PATCH /perfis-renderizacao/{id}` | Ajusta um perfil |
| `DELETE /perfis-renderizacao/{id}` | Remove um perfil, sem apagar livros nem prompts |
| `GET /configuracao` | Modelos escolhidos e se o servidor tem chave (nunca a chave) |
| `PUT /configuracao` | Escolhe os modelos e a prioridade de IA (a chave vem do `.env` ou do header `X-Chave-API-OpenRouter`) |
| `GET /configuracao/modelos` | Modelos disponíveis, com filtros `somente_gratuitos` e `contexto_minimo` |

O desenho completo da API, incluindo as rotas ainda não implementadas, está na Etapa 6 da especificação.

Exemplo de importação:

```bash
curl -X POST http://localhost:8000/livros -F "arquivo=@meu-livro.epub"
```
