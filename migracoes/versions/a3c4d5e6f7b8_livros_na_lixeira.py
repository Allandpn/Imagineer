"""livros na lixeira

Uma coluna nova em livros: `apagado_em` (nulo = ativo), com indice. Apagar um livro passa a so marcar a data; ele some de tudo e
volta ao restaurar (item 7.5b, LT2).

Identificador desta migration: a3c4d5e6f7b8
Vem depois de: f2b3c4d5e6a7
Criada em: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c4d5e6f7b8'
down_revision: Union[str, Sequence[str], None] = 'f2b3c4d5e6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula nos livros existentes (todos ativos)."""
    op.add_column("livros", sa.Column("apagado_em", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_livros_apagado_em", "livros", ["apagado_em"])


def reverter() -> None:
    """Remove a coluna; o que estava na lixeira volta a aparecer como livro ativo."""
    op.drop_index("ix_livros_apagado_em", table_name="livros")
    op.drop_column("livros", "apagado_em")


upgrade = aplicar
downgrade = reverter
