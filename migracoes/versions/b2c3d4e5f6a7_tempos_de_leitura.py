"""tempos de leitura

Tabela nova (RL16, RL17): os segundos lidos de cada livro em cada dia, um registro por livro e dia.

Identificador desta migration: b2c3d4e5f6a7
Vem depois de: a1b2c3d4e5f6
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria a tabela, a restricao de um registro por livro e dia e o indice do livro."""
    op.create_table(
        "tempos_de_leitura",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("livro_id", sa.Integer(), sa.ForeignKey("livros.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dia", sa.Date(), nullable=False),
        sa.Column("segundos", sa.Integer(), nullable=False),
        sa.UniqueConstraint("livro_id", "dia", name="uq_tempo_de_leitura_livro_dia"),
    )
    op.create_index("ix_tempos_de_leitura_livro_id", "tempos_de_leitura", ["livro_id"])


def reverter() -> None:
    """Apaga a tabela; o tempo registrado se perde."""
    op.drop_table("tempos_de_leitura")


upgrade = aplicar
downgrade = reverter
