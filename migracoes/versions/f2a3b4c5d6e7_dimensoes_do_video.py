"""dimensoes do video

`videos.largura` e `videos.altura` (item 4.8, VD17): o tamanho do video, para o capitulo desenha-lo como uma imagem (paisagem na largura da area
de leitura, retrato na metade). Nulas nos videos ja importados; o servidor as calcula do arquivo na primeira leitura dos artefatos.

Identificador desta migration: f2a3b4c5d6e7
Vem depois de: e1f2a3b4c5d6
Criada em: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as duas colunas, nulas."""
    op.add_column("videos", sa.Column("largura", sa.Integer(), nullable=True))
    op.add_column("videos", sa.Column("altura", sa.Integer(), nullable=True))


def reverter() -> None:
    """Remove as colunas."""
    op.drop_column("videos", "altura")
    op.drop_column("videos", "largura")


upgrade = aplicar
downgrade = reverter
