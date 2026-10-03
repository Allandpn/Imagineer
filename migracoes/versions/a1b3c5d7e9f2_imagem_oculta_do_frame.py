"""imagem oculta do frame

O capitulo pode deixar de mostrar a imagem de um frame sem apagar nada (item 7.5b, OC1 a OC3): "frames.imagem_oculta", falso por padrao.

Identificador desta migration: a1b3c5d7e9f2
Vem depois de: e7a9c1d3f5b7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'a1b3c5d7e9f2'
down_revision: Union[str, Sequence[str], None] = 'e7a9c1d3f5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, falsa nas linhas que ja existem."""
    op.add_column("frames", sa.Column("imagem_oculta", sa.Boolean(), server_default=sa.false(), nullable=False))


def reverter() -> None:
    """Remove a coluna."""
    op.drop_column("frames", "imagem_oculta")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
