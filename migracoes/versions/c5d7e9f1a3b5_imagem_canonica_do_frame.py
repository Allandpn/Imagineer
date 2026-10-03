"""imagem canonica do frame

Entre as variacoes de imagem de um frame (retrato ou cena), o usuario escolhe a que o representa e que o capitulo mostra
(item 7.5b, CAN1 a CAN4). Uma coluna nova, nula nos frames existentes (sem escolha: vale a mais recente):

- "frames.imagem_canonica_id": FK para "imagens", ON DELETE SET NULL.

Identificador desta migration: c5d7e9f1a3b5
Vem depois de: b4c6d8e0f2a4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'c5d7e9f1a3b5'
down_revision: Union[str, Sequence[str], None] = 'b4c6d8e0f2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna e a chave estrangeira; nenhum frame existente tem escolha."""
    op.add_column("frames", sa.Column("imagem_canonica_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_frames_imagem_canonica_id", "frames", "imagens", ["imagem_canonica_id"], ["id"], ondelete="SET NULL"
    )


def reverter() -> None:
    """Remove a coluna, perdendo as escolhas."""
    op.drop_constraint("fk_frames_imagem_canonica_id", "frames", type_="foreignkey")
    op.drop_column("frames", "imagem_canonica_id")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
