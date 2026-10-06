"""cota de armazenamento por pessoa (CT23)

Coluna `usuarios.cota_em_gb`, nula = vale o padrao de `limites.cota_por_pessoa_em_gb`. O dono nao tem cota, seja qual for o valor.

Identificador desta migration: d4e5f6a7b8c0
Vem depois de: c3d4e5f6a7b9
Criada em: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c0'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona a coluna (nula para todos: todo mundo continua no padrao)."""
    op.add_column("usuarios", sa.Column("cota_em_gb", sa.Integer(), nullable=True))


def reverter() -> None:
    """Remove a coluna: as cotas individuais se perdem, e todos voltam ao padrao."""
    op.drop_column("usuarios", "cota_em_gb")


upgrade = aplicar
downgrade = reverter
