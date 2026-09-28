"""Calcula a identidade vigente de um elemento num ponto da narrativa.

É o equivalente, para identidade, do que ``estados_de_elemento.py`` já faz para
aparência (item 3.4b) — mas com uma diferença de semântica importante, descrita
no item 3.3 da especificação: aparência é um retrato num ponto da narrativa
("última vale"), identidade é **cumulativa** ("soma tudo até aqui").

Por isso a consulta aqui não usa função de janela para pegar "o último
registro" — ela soma ``Elemento.descricao`` (a identidade inicial) com todos os
``HistoricoIdentidadeElemento`` cujo capítulo vem antes ou no mesmo ponto da
narrativa, em ordem crescente. O mesmo princípio de ``Capitulo.ordem`` (e não
ordem de processamento) resolve, de graça, o processamento fora de ordem: um
capítulo revelado só mais tarde nunca vaza para um ponto anterior da história,
mesmo que tenha sido processado antes cronologicamente (item 3.4f).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Elemento, HistoricoIdentidadeElemento


def identidade_vigente(sessao: Session, elemento: Elemento, ordem_limite: int) -> str | None:
    """A identidade conhecida do elemento até (e incluindo) certo capítulo.

    Args:
        elemento: o elemento cuja identidade interessa.
        ordem_limite: a ``ordem`` do capítulo sendo trabalhado. Incrementos de
            capítulos posteriores são ignorados, porque ainda não aconteceram
            na história.

    Devolve ``None`` só quando não há nada — nem identidade inicial, nem
    nenhum incremento até aqui.
    """
    partes = [elemento.descricao] if elemento.descricao else []

    incrementos = sessao.scalars(
        select(HistoricoIdentidadeElemento.descricao)
        .join(Capitulo, Capitulo.id == HistoricoIdentidadeElemento.capitulo_id)
        .where(
            HistoricoIdentidadeElemento.elemento_id == elemento.id,
            Capitulo.ordem <= ordem_limite,
        )
        .order_by(Capitulo.ordem.asc(), HistoricoIdentidadeElemento.id.asc())
    ).all()
    partes.extend(incrementos)

    return " ".join(partes) if partes else None
