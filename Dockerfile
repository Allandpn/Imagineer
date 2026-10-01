# python:3.12-slim: a versão 3.12 tem wheels prontas para ARM64 em todas as
# dependências do projeto, o que evita compilar bibliotecas no Raspberry Pi
# (compilar psycopg ou pydantic-core num Pi leva muitos minutos).
# A variante "slim" tem o Python completo, sem as ferramentas de build.
FROM python:3.12-slim

# Não gerar arquivos .pyc dentro do container e não bufferizar a saída —
# sem isso, os logs do uvicorn só aparecem em blocos, atrasados.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# As dependências são copiadas e instaladas antes do código de propósito:
# o Docker guarda essa camada em cache e só a refaz quando o requirements.txt
# muda. Sem isso, cada alteração de código reinstalaria tudo de novo.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# --host 0.0.0.0 é obrigatório dentro do container: o padrão (127.0.0.1) só
# aceitaria conexões de dentro dele próprio, e ninguém de fora conseguiria entrar.
# Ao subir, primeiro aplica as migrations pendentes ("alembic upgrade head") e só então inicia a API:
# o servidor sempre sobe com o banco no formato que o código espera, inclusive depois de o Raspberry
# Pi reiniciar ou de uma atualização (decisão registrada na Etapa 5). Num banco já atualizado o
# comando não faz nada. Se uma migration falhar, o container não sobe e o motivo aparece em
# "docker compose logs api". O "exec" faz o uvicorn receber os sinais de parada do Docker.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn imagineer.principal:aplicacao --host 0.0.0.0 --port 8000"]
