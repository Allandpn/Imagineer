"""Os tratadores globais de erro (imagineer/erros.py): do erro do domínio para a resposta HTTP."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imagineer.erros import registrar_tratadores
from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ErroDoProvedorIA,
    ModeloNaoEscolhido,
    TextoLongoDemais,
)
from imagineer.servicos.trava_de_analise import AnaliseEmAndamento


def _cliente_que_levanta(erro: Exception) -> TestClient:
    aplicacao = FastAPI()
    registrar_tratadores(aplicacao)

    @aplicacao.get("/erro")
    def _levantar() -> None:
        raise erro

    return TestClient(aplicacao)


@pytest.mark.parametrize(
    ("erro", "codigo"),
    [
        (ChaveDeApiAusente("sem chave"), 422),  # filha de ErroDoProvedorIA, mas é problema de configuração
        (ModeloNaoEscolhido("sem modelo"), 422),
        (TextoLongoDemais("não cabe"), 422),
        (ErroDoProvedorIA("o OpenRouter caiu"), 502),  # o problema é do serviço de fora
    ],
)
def teste_erro_do_provedor_vira_o_codigo_certo_com_a_mensagem(erro: Exception, codigo: int) -> None:
    resposta = _cliente_que_levanta(erro).get("/erro")

    assert resposta.status_code == codigo
    assert resposta.json() == {"detail": str(erro)}  # o mesmo corpo de uma HTTPException


def teste_analise_em_andamento_vira_409() -> None:
    resposta = _cliente_que_levanta(AnaliseEmAndamento(7)).get("/erro")

    assert resposta.status_code == 409
    assert "em andamento" in resposta.json()["detail"]


def teste_a_aplicacao_de_verdade_tem_os_tratadores_registrados() -> None:
    from imagineer.principal import aplicacao

    registrados = set(aplicacao.exception_handlers)

    assert {ErroDoProvedorIA, ChaveDeApiAusente, ModeloNaoEscolhido, TextoLongoDemais, AnaliseEmAndamento} <= registrados
