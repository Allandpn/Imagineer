"""Como os erros da aplicação viram respostas HTTP, num lugar só (item "Sem exception handler global", Etapa 8).

Antes, cada rota que chamava a IA repetia o mesmo ``try/except`` para traduzir o erro do provedor em
``HTTPException`` (quatro cópias idênticas). Agora os serviços e o provedor **levantam o erro do
domínio** (``ErroDoProvedorIA``, ``ModeloNaoEscolhido``...) e a tradução para HTTP mora aqui:

| Erro | Resposta | Por quê |
|---|---|---|
| ``ChaveDeApiAusente``, ``ModeloNaoEscolhido``, ``TextoLongoDemais`` | **422** | o problema é a configuração ou o pedido: o usuário resolve |
| qualquer outro ``ErroDoProvedorIA`` (rede, resposta fora do formato) | **502** | o problema é do serviço de fora, não do pedido nem nosso |
| ``AnaliseEmAndamento`` | **409** | já há uma análise deste capítulo rodando (item 6.7) |

O corpo é o mesmo de uma ``HTTPException`` (``{"detail": "..."}``): para o app nada mudou. O Starlette
escolhe o tratador **mais específico** pela hierarquia das classes, então ``ChaveDeApiAusente`` (filha de
``ErroDoProvedorIA``) cai no 422 e não no 502.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ErroDoProvedorIA,
    ModeloNaoEscolhido,
    TextoLongoDemais,
)
from imagineer.servicos.trava_de_analise import AnaliseEmAndamento


def _resposta(codigo: int, mensagem: str) -> JSONResponse:
    return JSONResponse(status_code=codigo, content={"detail": mensagem})


def registrar_tratadores(aplicacao: FastAPI) -> None:
    """Liga os tratadores de erro do domínio à aplicação."""

    @aplicacao.exception_handler(ErroDoProvedorIA)
    def _erro_do_provedor(_: Request, erro: ErroDoProvedorIA) -> JSONResponse:
        return _resposta(status.HTTP_502_BAD_GATEWAY, str(erro))

    @aplicacao.exception_handler(ChaveDeApiAusente)
    @aplicacao.exception_handler(ModeloNaoEscolhido)
    @aplicacao.exception_handler(TextoLongoDemais)
    def _configuracao_ou_pedido_invalido(_: Request, erro: ErroDoProvedorIA) -> JSONResponse:
        return _resposta(status.HTTP_422_UNPROCESSABLE_CONTENT, str(erro))

    @aplicacao.exception_handler(AnaliseEmAndamento)
    def _analise_em_andamento(_: Request, __: AnaliseEmAndamento) -> JSONResponse:
        return _resposta(
            status.HTTP_409_CONFLICT, "Já há uma análise deste capítulo em andamento. Aguarde terminar."
        )
