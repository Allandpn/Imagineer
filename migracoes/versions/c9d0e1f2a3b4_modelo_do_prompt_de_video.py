"""modelo do prompt de video

Uma coluna nova em `configuracao`: `modelo_video` (VD11), o modelo de texto que monta o prompt de video. Nula = usa o `modelo_prompt`.

Identificador desta migration: c9d0e1f2a3b4
Vem depois de: b8c9d0e1f2a3
Criada em: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula (nada muda para quem nao escolhe)."""
    op.add_column("configuracao", sa.Column("modelo_video", sa.String(length=200), nullable=True))


def reverter() -> None:
    """Remove a coluna; a escolha se perde (o prompt de video volta a usar o modelo do prompt de imagem)."""
    op.drop_column("configuracao", "modelo_video")


upgrade = aplicar
downgrade = reverter
