"""imagens de referencia na geracao da cena

O usuario escolhe, na cena, quais imagens dos personagens vao junto como referencia visual (item 7.5b, W1 a W12):

- "configuracao.modelos_com_referencia": dicionario {id do modelo: nome do parametro que recebe a LISTA de imagens}.
  Nasce vazio: nenhum modelo aceita referencia ate o usuario inclui-lo.
- "prompts.imagens_de_referencia": os ids das imagens enviadas como referencia na ULTIMA tentativa (lista vazia = nenhuma).

Identificador desta migration: a3b5c7d9e1f3
Vem depois de: f2a4b6c8d0e2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'a3b5c7d9e1f3'
down_revision: Union[str, Sequence[str], None] = 'f2a4b6c8d0e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as duas colunas, vazias para o que já existe."""
    op.add_column("configuracao", sa.Column("modelos_com_referencia", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("prompts", sa.Column("imagens_de_referencia", sa.JSON(), nullable=False, server_default="[]"))


def reverter() -> None:
    """Remove as colunas, perdendo o dicionário e o registro das referências."""
    op.drop_column("prompts", "imagens_de_referencia")
    op.drop_column("configuracao", "modelos_com_referencia")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
