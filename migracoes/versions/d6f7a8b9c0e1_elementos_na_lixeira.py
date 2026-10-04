"""elementos na lixeira

Tres colunas novas (item 7.5b, LT4): `elementos.apagado_em` (nulo = ativo, com indice), `sugestoes_elemento.elemento_antes_id` (de qual
elemento a sugestao era a confirmacao, para restaurar religar) e `frames.apagado_com_elemento_id` (o retrato que foi para a lixeira
junto com o elemento, para voltar junto).

Identificador desta migration: d6f7a8b9c0e1
Vem depois de: c5e6f7a8b9d0
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6f7a8b9c0e1'
down_revision: Union[str, Sequence[str], None] = 'c5e6f7a8b9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as colunas, nulas no que ja existe (tudo ativo)."""
    op.add_column("elementos", sa.Column("apagado_em", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_elementos_apagado_em", "elementos", ["apagado_em"])
    op.add_column("sugestoes_elemento", sa.Column("elemento_antes_id", sa.Integer(), nullable=True))
    op.add_column("frames", sa.Column("apagado_com_elemento_id", sa.Integer(), nullable=True))
    op.create_index("ix_frames_apagado_com_elemento_id", "frames", ["apagado_com_elemento_id"])


def reverter() -> None:
    """Remove as colunas; o que estava na lixeira volta a aparecer como ativo."""
    op.drop_index("ix_frames_apagado_com_elemento_id", table_name="frames")
    op.drop_column("frames", "apagado_com_elemento_id")
    op.drop_column("sugestoes_elemento", "elemento_antes_id")
    op.drop_index("ix_elementos_apagado_em", table_name="elementos")
    op.drop_column("elementos", "apagado_em")


upgrade = aplicar
downgrade = reverter
