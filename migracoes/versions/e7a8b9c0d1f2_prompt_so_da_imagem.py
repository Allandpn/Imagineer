"""prompt so da imagem

Uma coluna nova em prompts (item 7.5b, PI1): `so_imagem`, verdadeira no prompt criado so para guardar uma imagem importada sem prompt.

Identificador desta migration: e7a8b9c0d1f2
Vem depois de: d6f7a8b9c0e1
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7a8b9c0d1f2'
down_revision: Union[str, Sequence[str], None] = 'd6f7a8b9c0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, falsa nos prompts que ja existem."""
    op.add_column("prompts", sa.Column("so_imagem", sa.Boolean(), server_default=sa.false(), nullable=False))


def reverter() -> None:
    """Remove a coluna; o prompt so da imagem passa a parecer um prompt comum (com o texto \"Imagem importada, sem prompt.\")."""
    op.drop_column("prompts", "so_imagem")


upgrade = aplicar
downgrade = reverter
