"""Conexão com o banco e o ciclo de vida das sessões.

Dois conceitos que vale distinguir:

- **engine**: o pool de conexões com o PostgreSQL. Existe um só, criado na
  subida da aplicação e reaproveitado por todos os requests.
- **sessão**: a conversa com o banco dentro de *um* request. Guarda o que foi
  lido e o que ainda não foi gravado. Cada request precisa da sua, e ela
  precisa ser fechada no fim — senão a conexão nunca volta para o pool.

A função ``obter_sessao`` resolve exatamente isso e é usada como dependência
do FastAPI (``Depends``), que cuida de abrir antes e fechar depois.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from imagineer.configuracao import obter_configuracoes

_configuracoes = obter_configuracoes()

motor = create_engine(
    _configuracoes.url_banco,
    # Verifica se a conexão ainda está viva antes de usá-la. Importante num
    # servidor que roda 24/7: conexões ociosas podem ser derrubadas pelo banco
    # ou pela rede, e sem isso o primeiro request depois disso falharia.
    pool_pre_ping=True,
)

CriadorDeSessao = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


def obter_sessao() -> Generator[Session, None, None]:
    """Fornece uma sessão de banco para um request e a fecha no final.

    Usada nas rotas como ``sessao: Session = Depends(obter_sessao)``. O ``yield``
    entrega a sessão para a rota; o ``finally`` roda depois que a resposta foi
    montada, garantindo o fechamento mesmo se a rota levantar uma exceção.
    """
    sessao = CriadorDeSessao()
    try:
        yield sessao
    finally:
        sessao.close()
