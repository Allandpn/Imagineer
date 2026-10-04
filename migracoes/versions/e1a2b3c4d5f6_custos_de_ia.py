"""custos de ia

Tres colunas novas em usos_ia: o provedor (openrouter, fal ou replicate), o livro do gasto (nulo = sem livro) e se o custo foi
estimado por tabela de precos (item 7.5b, CU1). Nas linhas que ja existem: provedor openrouter, sem livro, nao estimado.

Identificador desta migration: e1a2b3c4d5f6
Vem depois de: d9f1a3b5c7e0
Criada em: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1a2b3c4d5f6'
down_revision: Union[str, Sequence[str], None] = 'd9f1a3b5c7e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as colunas, com valores que descrevem o que ja existia."""
    op.add_column("usos_ia", sa.Column("provedor", sa.String(length=20), nullable=False, server_default="openrouter"))
    op.add_column("usos_ia", sa.Column("livro_id", sa.Integer(), nullable=True))
    op.add_column("usos_ia", sa.Column("estimado", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_usos_ia_livro_id", "usos_ia", ["livro_id"])
    op.create_foreign_key("fk_usos_ia_livro_id", "usos_ia", "livros", ["livro_id"], ["id"], ondelete="SET NULL")


def reverter() -> None:
    """Remove as colunas; a quebra por provedor, por livro e a marca de estimado se perdem."""
    op.drop_constraint("fk_usos_ia_livro_id", "usos_ia", type_="foreignkey")
    op.drop_index("ix_usos_ia_livro_id", table_name="usos_ia")
    op.drop_column("usos_ia", "estimado")
    op.drop_column("usos_ia", "livro_id")
    op.drop_column("usos_ia", "provedor")


upgrade = aplicar
downgrade = reverter
