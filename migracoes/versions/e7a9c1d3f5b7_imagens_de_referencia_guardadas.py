"""imagens de referencia guardadas no servidor

O que foi escolhido como referencia e o historico do que cada imagem usou deixam de viver so no app (item 7.5b, RS1, RS2):

- "frames.imagens_de_referencia": a escolha vigente para a proxima geracao (lista de ids, vazia por padrao);
- "imagens.imagens_de_referencia": as referencias usadas quando aquela imagem foi gerada (vazia nas existentes).

Identificador desta migration: e7a9c1d3f5b7
Vem depois de: d6e8f0a2b4c6
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'e7a9c1d3f5b7'
down_revision: Union[str, Sequence[str], None] = 'd6e8f0a2b4c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as duas colunas, com lista vazia nas linhas que ja existem."""
    op.add_column("frames", sa.Column("imagens_de_referencia", sa.JSON(), server_default="[]", nullable=False))
    op.add_column("imagens", sa.Column("imagens_de_referencia", sa.JSON(), server_default="[]", nullable=False))


def reverter() -> None:
    """Remove as duas colunas, perdendo a escolha e o historico."""
    op.drop_column("imagens", "imagens_de_referencia")
    op.drop_column("frames", "imagens_de_referencia")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
