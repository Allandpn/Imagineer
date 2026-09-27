"""Preparação compartilhada pelos testes.

Duas coisas acontecem aqui, e a ordem importa:

1. Definimos as variáveis de ambiente **antes** de importar a aplicação. O
   módulo ``imagineer.banco.sessao`` cria o motor de conexão no momento em que
   é importado, então ele precisa encontrar a ``URL_BANCO`` já definida.
2. Trocamos o banco real por um SQLite em memória. Assim os testes rodam sem
   depender do Docker nem de um PostgreSQL no ar — e cada teste começa com o
   banco limpo, porque o "em memória" deixa de existir quando o teste termina.

A troca usa ``dependency_overrides``, o mecanismo do FastAPI para substituir
uma dependência durante os testes. É o que permite testar a rota de verdade,
sem mexer no código dela.
"""

import os

# Precisa vir antes de qualquer "import imagineer..." — ver explicação acima.
# O endereço é fictício: nos testes ninguém abre conexão com ele.
os.environ.setdefault("URL_BANCO", "postgresql+psycopg://teste:teste@localhost:5432/teste")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from imagineer.banco.base import Base
from imagineer.banco.sessao import obter_sessao
from imagineer.principal import aplicacao

# Importar os modelos registra as tabelas na Base.metadata — é o que permite
# criar o banco de teste com create_all mais abaixo.
import imagineer.modelos  # noqa: F401


def _criar_motor_sqlite_em_memoria():
    """Cria um motor SQLite em memória que se comporta como o PostgreSQL.

    Dois ajustes tornam o SQLite parecido o bastante com o banco de produção:

    - ``check_same_thread`` + ``StaticPool``: o TestClient executa a API numa
      thread separada da do teste, e o SQLite recusa usar a mesma conexão em
      duas threads. O StaticPool obriga todos a usarem a *mesma* conexão, o que
      é necessário porque um banco "em memória" vive dentro da conexão — outra
      conexão veria outro banco, vazio.
    - ``PRAGMA foreign_keys=ON``: o SQLite **ignora** chaves estrangeiras por
      padrão. Sem isso, um teste de ON DELETE CASCADE passaria sem provar nada.
    """
    motor = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(motor, "connect")
    def _ativar_chaves_estrangeiras(conexao_dbapi, _registro):
        cursor = conexao_dbapi.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return motor


@pytest.fixture
def sessao_com_tabelas() -> Session:
    """Sessão ligada a um banco de teste com todas as tabelas já criadas.

    Usa ``create_all`` em vez de rodar as migrations: o teste valida os
    *modelos*, e o banco nasce direto do ``Base.metadata``. Que as migrations
    produzem o mesmo resultado é verificado à parte, rodando o Alembic contra
    o PostgreSQL de verdade.
    """
    motor = _criar_motor_sqlite_em_memoria()
    Base.metadata.create_all(motor)
    criador = sessionmaker(bind=motor)
    sessao = criador()
    try:
        yield sessao
    finally:
        sessao.close()
        motor.dispose()


@pytest.fixture
def sessao_de_teste() -> Session:
    """Uma sessão ligada a um SQLite em memória, descartada no fim do teste."""
    motor = _criar_motor_sqlite_em_memoria()
    criador = sessionmaker(bind=motor)
    sessao = criador()
    try:
        yield sessao
    finally:
        sessao.close()
        motor.dispose()


@pytest.fixture
def cliente(sessao_de_teste: Session) -> TestClient:
    """Cliente HTTP de teste, com o banco real substituído pelo SQLite."""

    def obter_sessao_de_teste():
        yield sessao_de_teste

    aplicacao.dependency_overrides[obter_sessao] = obter_sessao_de_teste
    try:
        yield TestClient(aplicacao)
    finally:
        # Limpa a substituição para não vazar de um teste para o outro.
        aplicacao.dependency_overrides.clear()
