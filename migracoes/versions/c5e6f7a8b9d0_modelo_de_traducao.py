"""modelo da traducao na configuracao

A traducao dos prompts (portugues <-> ingles) ganha um modelo proprio, escolhido pelo app (MT1). Opcional: vazio = como antes
(o da suavizacao, senao o de extracao, senao o de prompt).

Identificador desta migration: c5e6f7a8b9d0
Vem depois de: b4d5e6f7a8c9
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5e6f7a8b9d0'
down_revision: Union[str, Sequence[str], None] = 'b4d5e6f7a8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula na configuracao que ja existe."""
    op.add_column("configuracao", sa.Column("modelo_traducao", sa.String(length=200), nullable=True))


def reverter() -> None:
    """Remove a coluna; a traducao volta a usar o modelo da suavizacao."""
    op.drop_column("configuracao", "modelo_traducao")


upgrade = aplicar
downgrade = reverter
