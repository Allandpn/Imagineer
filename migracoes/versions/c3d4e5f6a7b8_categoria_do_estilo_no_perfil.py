"""categoria de estilo no perfil de renderizacao

Uma coluna nova em perfis_renderizacao (BT1): `categoria_estilo`, a familia de estilo do perfil, que escolhe o bloco tecnico fixo
colado ao fim do prompt. Nula nos perfis que ja existem: continuam funcionando como antes, sem bloco.

Identificador desta migration: c3d4e5f6a7b8
Vem depois de: b2c3d4e5f6a7
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula. Sem CHECK: acrescentar uma categoria nova depois nao exige mexer em restricao."""
    op.add_column("perfis_renderizacao", sa.Column("categoria_estilo", sa.String(length=40), nullable=True))


def reverter() -> None:
    """Remove a coluna; as categorias escolhidas se perdem (os perfis continuam, sem bloco tecnico)."""
    op.drop_column("perfis_renderizacao", "categoria_estilo")


upgrade = aplicar
downgrade = reverter
