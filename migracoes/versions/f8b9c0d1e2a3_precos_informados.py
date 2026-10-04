"""precos informados dos modelos de imagem

Uma coluna nova em configuracao (item 7.5b, PD5): `precos_informados`, o preco por imagem que a pessoa digitou para cada modelo.

Identificador desta migration: f8b9c0d1e2a3
Vem depois de: e7a8b9c0d1f2
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f8b9c0d1e2a3'
down_revision: Union[str, Sequence[str], None] = 'e7a8b9c0d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, vazia ({}) na configuracao que ja existe."""
    op.add_column("configuracao", sa.Column("precos_informados", sa.JSON(), server_default="{}", nullable=False))


def reverter() -> None:
    """Remove a coluna; os precos informados se perdem."""
    op.drop_column("configuracao", "precos_informados")


upgrade = aplicar
downgrade = reverter
