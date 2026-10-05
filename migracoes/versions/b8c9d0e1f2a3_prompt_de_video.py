"""prompt de video

Duas colunas novas em `prompts` (item 4.8, VD6): `tipo` (IMAGEM por padrao: os prompts que ja existiam continuam de imagem) e
`imagem_partida_id` (a imagem que sera o primeiro quadro de um prompt de VIDEO; nula nos demais; SET NULL se a imagem for apagada).

Identificador desta migration: b8c9d0e1f2a3
Vem depois de: a7b8c9d0e1f2
Criada em: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as colunas. Sem CHECK em `tipo`: um tipo novo depois nao exige mexer em restricao (quem valida e a API)."""
    op.add_column("prompts", sa.Column("tipo", sa.String(length=10), nullable=False, server_default="IMAGEM"))
    op.add_column("prompts", sa.Column("imagem_partida_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_prompts_imagem_partida_id", "prompts", "imagens", ["imagem_partida_id"], ["id"], ondelete="SET NULL"
    )


def reverter() -> None:
    """Remove as colunas; os prompts de video ficam como prompts de imagem comuns (o texto continua, mas e de video): apague-os antes."""
    op.drop_constraint("fk_prompts_imagem_partida_id", "prompts", type_="foreignkey")
    op.drop_column("prompts", "imagem_partida_id")
    op.drop_column("prompts", "tipo")


upgrade = aplicar
downgrade = reverter
