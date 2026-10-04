"""frames na lixeira

Duas colunas novas em frames: `apagado_em` (nulo = ativo, com indice) e `sugestao_de_cena_antes_id` (de qual cena sugerida o frame era a
confirmacao, para restaurar religar). Apagar um frame passa a so marcar a data (item 7.5b, LT3).

Identificador desta migration: b4d5e6f7a8c9
Vem depois de: a3c4d5e6f7b8
Criada em: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4d5e6f7a8c9'
down_revision: Union[str, Sequence[str], None] = 'a3c4d5e6f7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as colunas, nulas nos frames existentes (todos ativos)."""
    op.add_column("frames", sa.Column("apagado_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("frames", sa.Column("sugestao_de_cena_antes_id", sa.Integer(), nullable=True))
    op.create_index("ix_frames_apagado_em", "frames", ["apagado_em"])


def reverter() -> None:
    """Remove as colunas; o que estava na lixeira volta a aparecer como frame ativo."""
    op.drop_index("ix_frames_apagado_em", table_name="frames")
    op.drop_column("frames", "sugestao_de_cena_antes_id")
    op.drop_column("frames", "apagado_em")


upgrade = aplicar
downgrade = reverter
