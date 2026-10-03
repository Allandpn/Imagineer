"""lixeira de imagens

Apagar uma imagem passa a so marca-la (item 7.5b, LX3); o arquivo fica no disco ate o usuario apagar de vez. Uma coluna nova,
nula nas imagens existentes (todas ativas):

- "imagens.apagada_em": quando foi movida para a lixeira, com indice (a lixeira lista pelas que tem data).

Identificador desta migration: d6e8f0a2b4c6
Vem depois de: c5d7e9f1a3b5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'd6e8f0a2b4c6'
down_revision: Union[str, Sequence[str], None] = 'c5d7e9f1a3b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna e o indice; nenhuma imagem existente esta na lixeira."""
    op.add_column("imagens", sa.Column("apagada_em", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_imagens_apagada_em"), "imagens", ["apagada_em"], unique=False)


def reverter() -> None:
    """Remove a coluna: o que estava na lixeira volta a aparecer como ativo."""
    op.drop_index(op.f("ix_imagens_apagada_em"), table_name="imagens")
    op.drop_column("imagens", "apagada_em")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
