"""capitulo lido

Uma coluna nova em capitulos: `lido_em`, a hora em que a pessoa chegou ao fim do capitulo ou o marcou como lido (nula = nao
lido). Os capitulos que ja existem ficam nao lidos (item 7.5b, LE1).

Identificador desta migration: d9f1a3b5c7e0
Vem depois de: c8e0f2a4b6d9
Criada em: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9f1a3b5c7e0'
down_revision: Union[str, Sequence[str], None] = 'c8e0f2a4b6d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula nos capitulos existentes."""
    op.add_column("capitulos", sa.Column("lido_em", sa.DateTime(timezone=True), nullable=True))


def reverter() -> None:
    """Remove a coluna; o que estava lido se perde."""
    op.drop_column("capitulos", "lido_em")


upgrade = aplicar
downgrade = reverter
