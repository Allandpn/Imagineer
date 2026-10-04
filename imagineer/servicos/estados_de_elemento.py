"""Descobre o estado vigente de cada elemento num ponto da narrativa.

É a consulta descrita no item 3.4b da especificação, e a pergunta central do
sistema: ao trabalhar o capítulo 40, como estava cada personagem naquele ponto?

A ordenação é por ``Capitulo.ordem`` — a ordem **narrativa** — e não por
``data_criacao`` nem pelo id do estado. O motivo é concreto: o usuário pode
processar capítulos fora de ordem, ou revisitar um capítulo antigo, então a ordem
de cadastro não corresponde à ordem da história. O id serve apenas de desempate
entre dois estados do mesmo capítulo, onde o maior é o mais adiante.

Esta lógica vivia como protótipo nos testes do item 3.4b. Saiu de lá quando a
Etapa 6.3 precisou expô-la como rota.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Elemento, EstadoElemento


def estado_vigente_por_elemento(
    sessao: Session, livro_id: int, ordem_limite: int | None = None
) -> dict[int, EstadoElemento]:
    """Mapeia cada elemento do livro para o estado que vigora até certo ponto.

    Args:
        livro_id: o livro cujos elementos interessam.
        ordem_limite: a ``ordem`` do capítulo sendo trabalhado. Estados de
            capítulos posteriores são ignorados, porque ainda não aconteceram na
            história. ``None`` significa "sem limite" — devolve o estado mais
            recente de cada elemento.

    Elementos que ainda não têm estado nenhum simplesmente não aparecem no
    resultado. Quem chama trata a ausência como "primeira aparição".
    """
    consulta = _consulta_do_estado_vigente(livro_id, ordem_limite)
    return {estado.elemento_id: estado for estado in sessao.scalars(consulta)}


def _consulta_do_estado_vigente(livro_id: int, ordem_limite: int | None) -> Select:
    """Monta a consulta que pega um estado por elemento, numa ida só ao banco.

    Usa função de janela em vez de uma consulta por elemento: numeramos os estados
    de cada elemento em ordem narrativa decrescente e ficamos com o número 1. Com
    50 elementos, a alternativa ingênua seriam 50 consultas.
    """
    numeracao = (
        func.row_number()
        .over(
            partition_by=EstadoElemento.elemento_id,
            order_by=(Capitulo.ordem.desc(), EstadoElemento.id.desc()),
        )
        .label("posicao")
    )

    filtros = [Elemento.livro_id == livro_id, Elemento.apagado_em.is_(None)]
    if ordem_limite is not None:
        filtros.append(Capitulo.ordem <= ordem_limite)

    numerados = (
        select(EstadoElemento.id.label("estado_id"), numeracao)
        .join(Capitulo, Capitulo.id == EstadoElemento.capitulo_id)
        .join(Elemento, Elemento.id == EstadoElemento.elemento_id)
        .where(*filtros)
        .subquery()
    )

    return (
        select(EstadoElemento)
        .join(numerados, numerados.c.estado_id == EstadoElemento.id)
        .where(numerados.c.posicao == 1)
    )
