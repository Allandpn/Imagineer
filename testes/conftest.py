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
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from imagineer.banco.sessao import obter_sessao
from imagineer.principal import aplicacao


@pytest.fixture
def sessao_de_teste() -> Session:
    """Uma sessão ligada a um SQLite em memória, descartada no fim do teste."""
    motor = create_engine(
        "sqlite://",
        # O TestClient executa a API numa thread separada da do teste, e o
        # SQLite recusa usar a mesma conexão em duas threads. Estes dois ajustes
        # liberam isso: "check_same_thread" desliga a checagem, e o StaticPool
        # obriga todos a usarem a *mesma* conexão — necessário porque um banco
        # "em memória" vive dentro da conexão: outra conexão veria outro banco,
        # vazio.
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
