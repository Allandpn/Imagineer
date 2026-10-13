"""vestimenta caracteristica do elemento (pendencia PD9)

Coluna `elementos.vestimenta` (texto, nula): a roupa que o elemento veste na maior parte do livro. Nula em todos os elementos que ja existem: nada muda
para eles ate a IA preenche-la (ao gerar o retrato) ou a pessoa digitar na ficha.

Identificador desta migration: b4c5d6e7f8a0
Vem depois de: a3b4c5d6e7f9
Criada em: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4c5d6e7f8a0'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona a coluna (nula para todos os elementos que ja existem)."""
    op.add_column("elementos", sa.Column("vestimenta", sa.Text(), nullable=True))


def reverter() -> None:
    """Remove a coluna: a roupa caracteristica se perde (a IA a le de novo no proximo retrato)."""
    op.drop_column("elementos", "vestimenta")


upgrade = aplicar
downgrade = reverter
