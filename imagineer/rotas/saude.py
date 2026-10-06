"""Endpoint de saúde: confirma que a aplicação está de pé e falando com o banco.

Existe por dois motivos práticos:

1. Durante o desenvolvimento, é a prova mais rápida de que a stack inteira
   subiu — API, container e PostgreSQL.
2. No Raspberry Pi, que roda 24/7, é o endereço que um monitoramento pode
   consultar de tempo em tempo para saber se o serviço continua saudável.

Ele consulta o banco de propósito: uma API que responde mas não alcança o
banco está quebrada na prática, e um "ok" cego esconderia isso.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao_anonima

rotas = APIRouter(tags=["Saúde"])


@rotas.get("/saude", summary="Verifica a saúde da aplicação")
def verificar_saude(sessao: Session = Depends(obter_sessao_anonima)) -> dict[str, str]:
    """Responde se a API está no ar e se a conexão com o banco funciona.

    **Não exige identidade** (CT2): o monitoramento chama sem o cabeçalho do Tailscale, e a rota não devolve dado de ninguém.

    O ``SELECT 1`` é a consulta mais barata possível: não lê tabela nenhuma,
    só obriga o banco a responder, provando que a conexão está viva.
    """
    try:
        sessao.execute(text("SELECT 1"))
        situacao_banco = "conectado"
    except SQLAlchemyError:
        situacao_banco = "indisponivel"

    return {
        "situacao": "ok" if situacao_banco == "conectado" else "degradado",
        "banco": situacao_banco,
    }
