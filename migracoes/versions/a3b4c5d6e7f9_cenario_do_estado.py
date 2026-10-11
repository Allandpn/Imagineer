"""cenario e fotografia do estado do elemento (item 4.11, AF5)

Coluna `estados_elemento.cenario` (JSON, nula): o cenario e a fotografia em que um elemento que nao e pessoa (objeto, lugar, edificacao, criatura,
veiculo) aparece naquele capitulo - ambiente, clima, iluminacao, hora e estacao, atmosfera, enquadramento e lente, cada um com a origem. Nula em todos
os estados que ja existem: nada muda para eles.

Identificador desta migration: a3b4c5d6e7f9
Vem depois de: e2f3a4b5c6d8
Criada em: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3b4c5d6e7f9'
down_revision: Union[str, Sequence[str], None] = 'e2f3a4b5c6d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona a coluna (nula para todos os estados que ja existem)."""
    op.add_column("estados_elemento", sa.Column("cenario", sa.JSON(), nullable=True))


def reverter() -> None:
    """Remove a coluna: o cenario lido se perde (sera lido de novo na proxima leitura profunda)."""
    op.drop_column("estados_elemento", "cenario")


upgrade = aplicar
downgrade = reverter
