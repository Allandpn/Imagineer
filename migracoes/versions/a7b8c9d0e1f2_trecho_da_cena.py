"""trecho do livro em que a cena acontece

Uma coluna `trecho` (texto, nula) em `sugestoes_cena` e em `frames` (FD7): a citacao literal do capitulo que narra o momento da cena.
Nula nas cenas que ja existem: continuam funcionando como antes.

Identificador desta migration: a7b8c9d0e1f2
Vem depois de: f6a7b8c9d0e1
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna nas duas tabelas, nula."""
    op.add_column("sugestoes_cena", sa.Column("trecho", sa.Text(), nullable=True))
    op.add_column("frames", sa.Column("trecho", sa.Text(), nullable=True))


def reverter() -> None:
    """Remove as colunas; os trechos guardados se perdem (as cenas continuam)."""
    op.drop_column("frames", "trecho")
    op.drop_column("sugestoes_cena", "trecho")


upgrade = aplicar
downgrade = reverter
