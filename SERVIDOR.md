# Servidor do Imagineer — subir e atualizar

Este guia cobre o dia a dia do servidor: **subir**, **atualizar** (com ou sem mudança no banco) e **voltar atrás**, no PC e no Raspberry Pi. A instalação inicial do Pi (Docker, Tailscale, levar os dados do PC) está no [`README.md`](README.md).

## A regra que explica tudo

Existem dois modos de rodar o servidor, e **só um deles aplica as migrations sozinho**:

| Modo | Aplica as migrations sozinho? | Onde se usa |
|---|---|---|
| **Docker** (`docker compose up`) | **Sim.** O container roda `alembic upgrade head` e só então inicia a API | Raspberry Pi; PC quando se quer testar como no Pi |
| **Sem Docker** (`uvicorn` no `venv`) | **Não.** É preciso rodar `alembic upgrade head` à mão | Desenvolvimento no PC |

Uma **migration** é um arquivo em `migracoes/versions/` que descreve uma mudança no banco (coluna nova, tabela nova). Ela vai no Git junto com o código. O banco **nunca** é alterado à mão: quem muda o formato dele é a migration, e o que está aplicado fica registrado na tabela `alembic_version`.

Dentro do Docker o código fica **dentro da imagem** (não há pasta compartilhada com o PC). Por isso, depois de qualquer mudança de código é preciso **reconstruir a imagem** (`--build`). Só reiniciar não basta: o container reiniciaria com o código antigo.

---

## 1. Subir o servidor

### No Raspberry Pi (ou no PC, com Docker)

```bash
cd ~/Imagineer                        # no PC: a pasta do projeto
docker compose up -d --build
curl http://localhost:8000/saude      # {"situacao":"ok","banco":"conectado"}
```

- `-d` deixa rodando em segundo plano; `--build` reconstrói a imagem com o código atual.
- Se a `PORTA_API` do `.env` não for 8000, use a porta dela na URL.
- Com `restart: unless-stopped`, tudo volta sozinho quando o Pi reinicia.
- Ver o log: `docker compose logs --tail 50 api`. Se uma migration falhar, o container não sobe e o motivo aparece aqui.

### No PC, sem Docker (desenvolvimento)

O banco continua rodando no Docker; só a API roda no `venv`:

```bash
docker compose up -d db               # só o banco
./venv/Scripts/python.exe -m alembic upgrade head
./venv/Scripts/python.exe -m uvicorn imagineer.principal:aplicacao --reload
```

- O `URL_BANCO` do `.env` local precisa usar `127.0.0.1` (não `localhost`, e não `db`).
- O `--reload` reinicia a API quando o código muda, mas **não** aplica migration: depois de um `git pull` ou de criar uma migration, rode o `upgrade head` à mão.
- Para o tablet alcançar este servidor, o PC precisa estar na mesma rede (ou no Tailscale) e o uvicorn precisa de `--host 0.0.0.0`.

---

## 2. Atualizar quando **não** há mudança no banco

Só mudou código (rotas, regras, prompts da IA).

**No PC**, depois de commitar:

```bash
git push
```

**No Pi:**

```bash
cd ~/Imagineer && git pull && docker compose up -d --build
```

O `alembic upgrade head` roda no início do container e, sem migration nova, **não faz nada**. É seguro rodar sempre.

**Sem Docker no PC:** o `--reload` já pega o código novo; não precisa de mais nada.

## 3. Atualizar quando **há** mudança no banco

Você sabe que há mudança quando o commit traz um arquivo novo em `migracoes/versions/`.

### 3.1 Criando a mudança (no PC, em desenvolvimento)

1. Altere o modelo em `imagineer/modelos/`.
2. Gere a migration, **com o banco local no ar**:
   ```bash
   ./venv/Scripts/python.exe -m alembic revision --autogenerate -m "descricao da mudanca"
   ```
3. **Leia o arquivo gerado.** O Alembic acerta quase sempre, mas não é infalível (por exemplo, não entende renomear uma coluna: ele apaga e cria outra, perdendo os dados). Confira também se `down_revision` aponta para a migration anterior.
4. Aplique no banco local e teste:
   ```bash
   ./venv/Scripts/python.exe -m alembic upgrade head
   ./venv/Scripts/python.exe -m alembic check     # "No new upgrade operations detected" = modelo e banco batem
   ./venv/Scripts/python.exe -m alembic heads     # deve listar UMA só linha (uma única "ponta")
   ./venv/Scripts/python.exe -m pytest
   ```
5. Commite o modelo **e** a migration juntos, no mesmo commit.

> Se `alembic heads` listar duas linhas, duas migrations saíram da mesma anterior (acontece ao trabalhar em duas branches). O Alembic se recusa a continuar até serem unidas; me peça para resolver, não improvise no banco.

### 3.2 Aplicando no Pi

1. **Faça um backup antes** (a migration muda o banco de verdade, e o `pg_dump` é o seu desfazer):
   ```bash
   cd ~/Imagineer
   docker compose exec -T db pg_dump -U imagineer -d imagineer --clean --if-exists > backup-antes-$(date +%F).sql
   ```
2. Atualize como no item 2 — o mesmo comando aplica a migration:
   ```bash
   git pull && docker compose up -d --build
   ```
3. **Confira** que subiu e que o banco está na versão certa:
   ```bash
   docker compose logs --tail 30 api                 # procure "Running upgrade ... -> ..." e nenhum erro
   docker compose exec api alembic current           # deve mostrar a mesma versão de "alembic heads" no PC
   curl http://localhost:8000/saude
   ```

O PostgreSQL executa cada migration dentro de uma transação: se ela falhar no meio, **nada é aplicado**, o banco fica como estava e o container não sobe (a API antiga já foi parada pelo `up`). Corrija o problema no PC, faça um novo commit e repita.

### 3.3 Sem Docker no PC

Depois de um `git pull` que traga migration nova:

```bash
./venv/Scripts/python.exe -m alembic upgrade head
```

---

## 4. Voltar atrás

**Código ruim, banco intacto** — volte o Git e reconstrua:

```bash
git log --oneline -5                  # ache o commit bom
git checkout <commit-bom>             # (ou: git revert <commit-ruim>, que é o jeito que mantém o histórico)
docker compose up -d --build
```

> Cuidado: se o commit ruim **tinha migration** e ela já foi aplicada, o banco está *à frente* do código antigo, e o container antigo pode não subir (o Alembic não acha a versão que o banco registra). Nesse caso, desfaça a migration **antes** de voltar o código (abaixo).

**Desfazer a última migration** (o `downgrade` apaga o que a migration criou, **com os dados dessas colunas**):

```bash
docker compose exec api alembic downgrade -1       # com o container no ar
docker compose run --rm api alembic downgrade -1   # se o container não sobe
```

**Restaurar o backup** (o desfazer que funciona sempre; perde o que foi gravado depois do backup):

```bash
docker compose exec -T db psql -U imagineer -d imagineer < backup-antes-AAAA-MM-DD.sql
docker compose restart api
```

---

## 5. Outras situações comuns

| Situação | Comando |
|---|---|
| Mudou só o `.env` (chave da IA, senha, portas) | `docker compose up -d` (recria o container com os valores novos; `restart` **não** relê o `.env`) |
| Parar tudo, **mantendo** os dados | `docker compose down` |
| Parar e **apagar o banco e as imagens** | `docker compose down -v` — **nunca** no Pi sem backup |
| Ver o que está rodando | `docker compose ps` |
| Ver a versão do banco | `docker compose exec api alembic current` |
| Backup das imagens | `docker compose cp api:/dados/imagens ./backup-imagens` |

O backup do banco **e** o das imagens são independentes: o banco guarda só a referência de cada imagem, e o arquivo mora no volume `imagens`. Guarde os dois fora do Pi.

## Lista rápida

- **Só código:** `git push` → no Pi, `git pull && docker compose up -d --build`.
- **Com migration:** teste no PC (`upgrade head`, `check`, `heads`, `pytest`) → `git push` → no Pi, **backup**, `git pull && docker compose up -d --build` → conferir `logs` e `alembic current`.
- **Nunca** altere tabelas à mão no banco do Pi, e **nunca** edite uma migration que já foi aplicada em algum lugar: crie uma nova.
