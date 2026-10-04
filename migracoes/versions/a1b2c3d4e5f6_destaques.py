"""destaques do leitor

Tabela nova (RL9 a RL13): os trechos que a pessoa destaca no texto, com cor, nota e, se quiser, um elemento ligado.

Identificador desta migration: a1b2c3d4e5f6
Vem depois de: f8b9c0d1e2a3
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f8b9c0d1e2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria a tabela e os indices."""
    op.create_table(
        "destaques",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("livro_id", sa.Integer(), sa.ForeignKey("livros.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capitulo_id", sa.Integer(), sa.ForeignKey("capitulos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inicio", sa.Integer(), nullable=False),
        sa.Column("fim", sa.Integer(), nullable=False),
        sa.Column("trecho", sa.Text(), nullable=False),
        sa.Column("cor", sa.String(20), nullable=False),
        sa.Column("nota", sa.String(1000), nullable=True),
        sa.Column("elemento_id", sa.Integer(), sa.ForeignKey("elementos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_destaques_livro_id", "destaques", ["livro_id"])
    op.create_index("ix_destaques_capitulo_id", "destaques", ["capitulo_id"])
    op.create_index("ix_destaques_elemento_id", "destaques", ["elemento_id"])


def reverter() -> None:
    """Apaga a tabela; os destaques se perdem."""
    op.drop_table("destaques")


upgrade = aplicar
downgrade = reverter
