"""momentos do estado do elemento (item 4.9, FL3 e FL4)

Coluna `estados_elemento.momentos` (JSON, nula): a linha do tempo do elemento dentro do capitulo de origem. Nula = estado antigo ou digitado a
mao, que se comporta exatamente como antes. Nenhum dado existente e reescrito.

Identificador desta migration: a8b9c0d1e2f4
Vem depois de: f7a8b9c0d1e3
Criada em: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b9c0d1e2f4'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona a coluna (nula para todos os estados que ja existem)."""
    op.add_column("estados_elemento", sa.Column("momentos", sa.JSON(), nullable=True))


def reverter() -> None:
    """Remove a coluna: as linhas do tempo ja lidas se perdem; a `descricao` de cada estado continua."""
    op.drop_column("estados_elemento", "momentos")


upgrade = aplicar
downgrade = reverter
