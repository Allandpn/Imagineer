"""O capítulo anterior de um capítulo, de onde a leitura herda o cenário quando o capítulo atual não o descreve (item 4.11, AF3)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.ia.cenario import fim_do_capitulo
from imagineer.modelos import Capitulo


def capitulo_anterior(sessao: Session, capitulo: Capitulo) -> Capitulo | None:
    """O capítulo do mesmo livro que vem logo antes (``ordem`` menor), pulando os ignorados (capa, direitos autorais...); ``None`` se é o primeiro."""
    consulta = (
        select(Capitulo)
        .where(Capitulo.livro_id == capitulo.livro_id, Capitulo.ordem < capitulo.ordem, Capitulo.ignorado.is_(False))
        .order_by(Capitulo.ordem.desc())
        .limit(1)
    )
    return sessao.scalars(consulta).first()


def fim_do_capitulo_anterior(sessao: Session, capitulo: Capitulo) -> str | None:
    """Os últimos caracteres do capítulo anterior, para a leitura herdar o cenário (AF3.b); ``None`` se não há capítulo anterior com texto."""
    anterior = capitulo_anterior(sessao, capitulo)
    return fim_do_capitulo(anterior.texto) if anterior is not None else None
