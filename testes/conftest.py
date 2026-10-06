"""Preparação compartilhada pelos testes.

Três coisas acontecem aqui, e a ordem importa:

1. Definimos as variáveis de ambiente **antes** de importar a aplicação. O
   módulo ``imagineer.banco.sessao`` cria o motor de conexão no momento em que
   é importado, então ele precisa encontrar a ``URL_BANCO`` já definida.
2. Zeramos as duas variáveis da chave do OpenRouter (item 4.3), também antes de
   qualquer import. Sem isso, os testes que esperam "nenhuma chave configurada"
   quebrariam sempre que o `.env` do projeto tivesse uma chave de verdade — o
   que acontece ao testar a integração de ponta a ponta manualmente. Os testes
   não deveriam depender do que está no ambiente de quem os roda.
3. Trocamos o banco real por um SQLite em memória. Assim os testes rodam sem
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

# Sobrescreve (não só "setdefault"): o `.env` do projeto tem prioridade sobre
# uma variável de ambiente ausente, então só zerar não bastaria se o arquivo
# tiver uma chave de verdade. Os testes que precisam de uma chave a definem
# explicitamente via `monkeypatch`.
os.environ["CHAVE_API_OPENROUTER"] = ""
os.environ["IMAGINEER_KEY_OPEN_ROUTER"] = ""
# Mesmo isolamento para os outros fornecedores de imagem (a conta do Allan tem essas variáveis).
for _variavel in ("FAL_KEY", "CHAVE_API_FAL", "IMAGINEER_KEY_FAL_AI", "REPLICATE_API_TOKEN", "CHAVE_API_REPLICATE", "IMAGINEER_KEY_REPLICATE"):
    os.environ[_variavel] = ""

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


@pytest.fixture(autouse=True)
def _sem_rede_nos_precos_de_imagem(monkeypatch):
    """Nenhum teste vai ao fal.ai ou ao Replicate (PD1): a leitura de preços e de listas devolve vazio, e o cache começa limpo."""
    from imagineer.servicos import precos_de_imagem

    precos_de_imagem.limpar_cache()
    monkeypatch.setattr(precos_de_imagem, "_get", lambda *a, **k: {})
    monkeypatch.setattr(precos_de_imagem, "_chave_do_fal", lambda: "")
    monkeypatch.setattr(precos_de_imagem, "_chave_do_replicate", lambda: "")
    yield
    precos_de_imagem.limpar_cache()


@pytest.fixture
def usar_provedor_falso():
    """Substitui o provedor de IA da aplicação por um falso, e desfaz no fim.

    A troca é feita por ``dependency_overrides`` do FastAPI, o mesmo mecanismo que
    troca o banco. É o que permite exercitar as rotas que usam IA sem rede, sem
    chave de API e sem um modelo remoto que pode estar em fila.
    """
    from imagineer.rotas.configuracao import obter_provedor

    def trocar(provedor):
        aplicacao.dependency_overrides[obter_provedor] = lambda: provedor
        return provedor

    try:
        yield trocar
    finally:
        aplicacao.dependency_overrides.pop(obter_provedor, None)


@pytest.fixture
def usar_criador_de_sessao_de_teste(sessao_com_tabelas: Session):
    """Troca o criador de sessões do **segundo plano** (a narração, NA5) por um ligado ao **mesmo** banco de teste.

    Sem isso, a geração em segundo plano abriria uma sessão no banco de verdade. O provedor de IA continua sendo trocado por
    ``usar_provedor_falso``."""
    from imagineer.rotas.audio import obter_criador_de_sessao

    aplicacao.dependency_overrides[obter_criador_de_sessao] = lambda: sessionmaker(bind=sessao_com_tabelas.get_bind())
    try:
        yield
    finally:
        aplicacao.dependency_overrides.pop(obter_criador_de_sessao, None)


@pytest.fixture
def cliente(sessao_com_tabelas: Session) -> TestClient:
    """Cliente HTTP de teste, com o banco real substituído pelo SQLite.

    Usa o banco **com as tabelas criadas**, porque as rotas de domínio (livros,
    capítulos) leem e gravam de verdade. As rotas que não tocam em tabela, como
    ``/saude``, funcionam igual.
    """

    def obter_sessao_de_teste():
        yield sessao_com_tabelas

    aplicacao.dependency_overrides[obter_sessao] = obter_sessao_de_teste
    try:
        yield TestClient(aplicacao)
    finally:
        # Limpa a substituição para não vazar de um teste para o outro.
        aplicacao.dependency_overrides.clear()
