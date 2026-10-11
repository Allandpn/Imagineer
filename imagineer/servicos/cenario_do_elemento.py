"""O cenário de um elemento que não é pessoa, e de onde ele herda quando o capítulo não o descreve (item 4.11, AF5)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.ia.cenario import TIPOS_QUE_LEEM_CENARIO, linhas_do_cenario
from imagineer.modelos import Capitulo, EstadoElemento


def le_cenario(estado: EstadoElemento) -> bool:
    """Este elemento lê cenário? Objeto, lugar, edificação, criatura e veículo sim; pessoa e grupo não (o retrato deles é neutro, FL1)."""
    return estado.elemento.tipo.name in TIPOS_QUE_LEEM_CENARIO


def cenario_anterior_do_elemento(sessao: Session, estado: EstadoElemento) -> dict | None:
    """O cenário do estado **anterior** do mesmo elemento (o de um capítulo antes, o mais próximo que tem cenário); ``None`` se não há (AF5).

    "Antes" é pela ordem da narrativa (``Capitulo.ordem``), não pela data de criação; no mesmo capítulo vale o estado criado antes (``id`` menor).
    """
    ordem_do_estado = sessao.get(Capitulo, estado.capitulo_id).ordem
    consulta = (
        select(EstadoElemento)
        .join(Capitulo, Capitulo.id == EstadoElemento.capitulo_id)
        .where(
            EstadoElemento.elemento_id == estado.elemento_id,
            EstadoElemento.id != estado.id,
            (Capitulo.ordem < ordem_do_estado) | ((Capitulo.ordem == ordem_do_estado) & (EstadoElemento.id < estado.id)),
        )
        .order_by(Capitulo.ordem.desc(), EstadoElemento.id.desc())
    )
    # Filtra em Python: uma coluna JSON gravada com ``None`` guarda o JSON ``null`` (que o SQL não chama de NULL).
    return next((anterior.cenario for anterior in sessao.scalars(consulta) if anterior.cenario), None)


def linhas_do_cenario_do_estado(estado: EstadoElemento) -> list[str]:
    """As linhas "Rótulo: texto" do cenário do estado, para o pedido de montagem do prompt (AF6); vazia se o elemento não lê cenário ou não tem."""
    return linhas_do_cenario(estado.cenario) if le_cenario(estado) else []
