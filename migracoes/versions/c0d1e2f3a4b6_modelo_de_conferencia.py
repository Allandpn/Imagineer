"""modelo de conferencia da imagem na configuracao (item 4.9, FL13.1)

Coluna `configuracao.modelo_conferencia` (nula): o modelo COM VISAO que compara uma imagem gerada com a lista do que deveria aparecer. Nula = a
conferencia nao esta disponivel para essa pessoa. Nenhum dado existente e reescrito.

Identificador desta migration: c0d1e2f3a4b6
Vem depois de: b9c0d1e2f3a5
Criada em: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c0d1e2f3a4b6'
down_revision: Union[str, Sequence[str], None] = 'b9c0d1e2f3a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona a coluna (nula para todas as configuracoes que ja existem)."""
    op.add_column("configuracao", sa.Column("modelo_conferencia", sa.String(length=200), nullable=True))


def reverter() -> None:
    """Remove a coluna: o modelo de conferencia escolhido se perde."""
    op.drop_column("configuracao", "modelo_conferencia")


upgrade = aplicar
downgrade = reverter
