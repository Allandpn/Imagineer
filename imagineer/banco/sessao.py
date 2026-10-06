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

from fastapi import Depends, Request
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


def obter_usuario(request: Request):
    """Quem fez o pedido (CT2). Dependência do FastAPI: em modo ``pessoal`` é sempre o dono; em ``tailscale``, quem o cabeçalho do proxy disser.

    Os imports ficam aqui dentro porque ``servicos.identidade`` precisa deste módulo (``CriadorDeSessao``): importar lá em cima faria um círculo.
    """
    from imagineer.servicos.identidade import resolver_usuario

    return resolver_usuario(request, CriadorDeSessao)


def obter_sessao_anonima() -> Generator[Session, None, None]:
    """Uma sessão **sem usuário**, para a rota que não pode exigir identidade: ``/saude`` (o monitoramento e o healthcheck do contêiner chamam sem cabeçalho)."""
    sessao = CriadorDeSessao()
    try:
        yield sessao
    finally:
        sessao.close()


def obter_sessao(usuario=Depends(obter_usuario)) -> Generator[Session, None, None]:
    """Fornece uma sessão de banco para um request e a fecha no final.

    Usada nas rotas como ``sessao: Session = Depends(obter_sessao)``. O ``yield``
    entrega a sessão para a rota; o ``finally`` roda depois que a resposta foi
    montada, garantindo o fechamento mesmo se a rota levantar uma exceção.

    **A sessão já nasce com o usuário do pedido** (CT6): é o que faz ``obter_ou_404`` e as listagens filtrarem por dono sem ninguém passar parâmetro.
    """
    from imagineer.servicos.acesso import definir_usuario

    sessao = CriadorDeSessao()
    definir_usuario(sessao, usuario.id)
    try:
        yield sessao
    finally:
        sessao.close()
