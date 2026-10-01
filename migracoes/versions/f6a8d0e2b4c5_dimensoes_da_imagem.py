"""dimensoes da imagem

Duas colunas novas em imagens: largura e altura, em pixels (nulas). Lidas na importacao; nas imagens
antigas, calculadas na primeira leitura. O app decide o layout da imagem no texto por elas (retrato em
duas colunas, paisagem na largura da tela), ja que a ferramenta de imagem externa nem sempre respeita o
formato pedido no prompt (item 7.5b, I1).

Identificador desta migration: f6a8d0e2b4c5
Vem depois de: e5a7c9d1f3b4
Criada em: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'f6a8d0e2b4c5'
down_revision: Union[str, Sequence[str], None] = 'e5a7c9d1f3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as colunas, nulas nas imagens existentes."""
    op.add_column("imagens", sa.Column("largura", sa.Integer(), nullable=True))
    op.add_column("imagens", sa.Column("altura", sa.Integer(), nullable=True))


def reverter() -> None:
    """Remove as colunas; as dimensões se perdem (são recalculadas na primeira leitura)."""
    op.drop_column("imagens", "altura")
    op.drop_column("imagens", "largura")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
