"""Testes do endpoint de saúde (item 1.5)."""

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from imagineer.banco.sessao import obter_sessao_anonima
from imagineer.principal import aplicacao


def teste_saude_responde_ok_com_banco_conectado(cliente: TestClient) -> None:
    """Com o banco respondendo, a situação geral é "ok"."""
    resposta = cliente.get("/saude")

    assert resposta.status_code == 200
    assert resposta.json() == {"situacao": "ok", "banco": "conectado"}


def teste_saude_reporta_degradado_quando_o_banco_falha() -> None:
    """Se o banco não responde, a API continua no ar mas se declara degradada.

    Este é o caso que justifica o endpoint consultar o banco: sem isso, a
    resposta seria um "ok" que esconde metade do sistema fora do ar.
    """

    class SessaoQueFalha:
        """Sessão falsa que simula o banco indisponível."""

        def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception("banco fora do ar"))

    def obter_sessao_quebrada():
        yield SessaoQueFalha()

    aplicacao.dependency_overrides[obter_sessao_anonima] = obter_sessao_quebrada
    try:
        resposta = TestClient(aplicacao).get("/saude")
    finally:
        aplicacao.dependency_overrides.clear()

    assert resposta.status_code == 200
    assert resposta.json() == {"situacao": "degradado", "banco": "indisponivel"}
