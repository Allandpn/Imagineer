"""posicao do frame

Coluna nova frames.posicao_no_texto (nula): onde, no texto do capitulo, a pessoa escolheu pôr o frame
("Ilustrar aqui", item 3.4g). Os frames existentes ficam sem posicao.

Identificador desta migration: d4f6b8c0e2a3
Vem depois de: c3e5a7b9d1f2
Criada em: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'd4f6b8c0e2a3'
down_revision: Union[str, Sequence[str], None] = 'c3e5a7b9d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula nos frames existentes."""
    op.add_column("frames", sa.Column("posicao_no_texto", sa.Integer(), nullable=True))


def reverter() -> None:
    """Remove a coluna; os frames perdem a posição escolhida."""
    op.drop_column("frames", "posicao_no_texto")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
