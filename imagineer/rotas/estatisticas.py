"""Rotas do tempo de leitura e das estatísticas (RL16, RL17)."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.leitura import (
    EstatisticasDeLeitura,
    TempoDeLeituraNovo,
    TempoDeLeituraResposta,
    TempoDoDia,
    TempoDoLivro,
)
from imagineer.modelos import Livro, TempoDeLeitura
from imagineer.rotas._comum import buscar_livro
from imagineer.servicos.acesso import usuario_ou_dono

rotas_de_livro = APIRouter(prefix="/livros", tags=["Estatísticas"])
rotas_de_estatisticas = APIRouter(prefix="/estatisticas", tags=["Estatísticas"])

DIAS_DAS_ESTATISTICAS = 90
"""Quantos dias para trás a lista de dias alcança."""


@rotas_de_livro.post(
    "/{livro_id}/leitura/tempo",
    response_model=TempoDeLeituraResposta,
    summary="Soma segundos de leitura a um dia do livro",
)
def somar_tempo_de_leitura(
    livro_id: int, novo: TempoDeLeituraNovo, sessao: Session = Depends(obter_sessao)
) -> TempoDeLeitura:
    """**Soma** ``segundos`` ao dia do livro (cria o registro do dia se ainda não há) e devolve o total do dia.

    O dia é o do aparelho; só se recusa um dia **mais de 1 dia no futuro** (um aparelho com o relógio errado não
    deve sujar as estatísticas com dias que não existem). Não sobe a ``revisao`` do livro.
    """
    buscar_livro(sessao, livro_id)
    if novo.dia > date.today() + timedelta(days=1):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Esse dia está no futuro.")

    for _tentativa in range(2):
        registro = sessao.scalar(
            select(TempoDeLeitura).where(TempoDeLeitura.livro_id == livro_id, TempoDeLeitura.dia == novo.dia)
        )
        if registro is None:
            registro = TempoDeLeitura(livro_id=livro_id, dia=novo.dia, segundos=0)
            sessao.add(registro)
        registro.segundos += novo.segundos
        try:
            sessao.commit()
        except IntegrityError:
            # Dois envios do mesmo dia ao mesmo tempo: o outro criou o registro antes. Tenta de novo, agora somando nele.
            sessao.rollback()
            continue
        sessao.refresh(registro)
        return registro
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Não consegui somar o tempo agora; tente de novo.")


@rotas_de_estatisticas.get("/leitura", response_model=EstatisticasDeLeitura, summary="Tempo de leitura por dia e por livro")
def estatisticas_de_leitura(sessao: Session = Depends(obter_sessao)) -> EstatisticasDeLeitura:
    """O tempo dos últimos 90 dias (todos os livros somados) e o resumo de cada livro; livros na lixeira ficam fora."""
    desde = date.today() - timedelta(days=DIAS_DAS_ESTATISTICAS)
    dono = usuario_ou_dono(sessao)  # CT6-c: só o tempo e os livros da própria pessoa

    por_dia = sessao.execute(
        select(TempoDeLeitura.dia, func.sum(TempoDeLeitura.segundos))
        .join(Livro, Livro.id == TempoDeLeitura.livro_id)
        .where(Livro.usuario_id == dono, Livro.apagado_em.is_(None), TempoDeLeitura.dia > desde)
        .group_by(TempoDeLeitura.dia)
        .order_by(TempoDeLeitura.dia)
    ).all()

    por_livro = sessao.execute(
        select(
            Livro.id,
            Livro.titulo,
            func.sum(TempoDeLeitura.segundos),
            func.count(TempoDeLeitura.id),
            func.max(TempoDeLeitura.dia),
        )
        .join(TempoDeLeitura, TempoDeLeitura.livro_id == Livro.id)
        .where(Livro.usuario_id == dono, Livro.apagado_em.is_(None))
        .group_by(Livro.id, Livro.titulo)
        .order_by(func.max(TempoDeLeitura.dia).desc(), Livro.id)
    ).all()

    return EstatisticasDeLeitura(
        dias=[TempoDoDia(dia=dia, segundos=int(total)) for dia, total in por_dia],
        livros=[
            TempoDoLivro(livro_id=id_, titulo=titulo, segundos=int(total), dias_lidos=dias, ultimo_dia=ultimo)
            for id_, titulo, total, dias, ultimo in por_livro
        ],
    )
