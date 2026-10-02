"""elementos vinculados ao sujeito de um retrato

O retrato de um elemento que nao e personagem pode levar outros elementos junto (a espada de quem a carrega, o lugar onde
a criatura esta), como os participantes de uma cena (item 7.5b, V1 a V10). Uma tabela de ligacao nova, separada da dos
estados do frame, para o retrato continuar com exatamente UM estado (o sujeito):

- "frames_estados_vinculados": (frame_id, estado_elemento_id), as duas com ON DELETE CASCADE.

Identificador desta migration: b4c6d8e0f2a4
Vem depois de: a3b5c7d9e1f3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'b4c6d8e0f2a4'
down_revision: Union[str, Sequence[str], None] = 'a3b5c7d9e1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria a tabela de ligação, vazia: nenhum frame existente tem vinculados."""
    op.create_table(
        "frames_estados_vinculados",
        sa.Column("frame_id", sa.Integer(), nullable=False),
        sa.Column("estado_elemento_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["frame_id"], ["frames.id"], name="fk_frames_estados_vinculados_frame_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["estado_elemento_id"],
            ["estados_elemento.id"],
            name="fk_frames_estados_vinculados_estado_elemento_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("frame_id", "estado_elemento_id", name="pk_frames_estados_vinculados"),
    )


def reverter() -> None:
    """Remove a tabela, perdendo os vínculos."""
    op.drop_table("frames_estados_vinculados")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
