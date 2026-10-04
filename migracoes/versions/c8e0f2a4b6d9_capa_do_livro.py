"""capa do livro

Duas colunas novas em livros: a capa (imagem reduzida, bytes) e o tipo dela. Nulas nos livros que ja existem: a capa
vem na importacao de um EPUB novo ou de `POST /livros/{id}/capa` (item 7.5b, CP1 a CP3).

Identificador desta migration: c8e0f2a4b6d9
Vem depois de: b2c4d6e8f0a1
Criada em: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8e0f2a4b6d9'
down_revision: Union[str, Sequence[str], None] = 'b2c4d6e8f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as colunas, nulas nos livros existentes."""
    op.add_column("livros", sa.Column("capa", sa.LargeBinary(), nullable=True))
    op.add_column("livros", sa.Column("capa_tipo", sa.String(length=50), nullable=True))


def reverter() -> None:
    """Remove as colunas; as capas guardadas se perdem."""
    op.drop_column("livros", "capa_tipo")
    op.drop_column("livros", "capa")


upgrade = aplicar
downgrade = reverter
