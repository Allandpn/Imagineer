"""tokens de cache e de raciocinio no uso de IA (item 4.10, LM7)

Colunas `usos_ia.tokens_em_cache` e `usos_ia.tokens_de_raciocinio`, nulas: linha antiga e provedor que nao informa ficam nulos (nunca zero).

Identificador desta migration: e6f7a8b9c0d2
Vem depois de: d4e5f6a7b8c0
Criada em: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7a8b9c0d2'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona as duas colunas (nulas para todas as linhas que ja existem)."""
    op.add_column("usos_ia", sa.Column("tokens_em_cache", sa.Integer(), nullable=True))
    op.add_column("usos_ia", sa.Column("tokens_de_raciocinio", sa.Integer(), nullable=True))


def reverter() -> None:
    """Remove as colunas: os tokens de cache e de raciocinio ja gravados se perdem."""
    op.drop_column("usos_ia", "tokens_de_raciocinio")
    op.drop_column("usos_ia", "tokens_em_cache")


upgrade = aplicar
downgrade = reverter
