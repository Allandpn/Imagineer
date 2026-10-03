"""posicao manual das sugestoes

O usuario pode pôr à mão o artefato de um elemento ou de uma cena no paragrafo que quiser (item 7.5b, PM1 a PM4):
"sugestoes_elemento.posicao_manual" e "sugestoes_cena.posicao_manual", nulas por padrao.

Identificador desta migration: b2c4d6e8f0a1
Vem depois de: a1b3c5d7e9f2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'b2c4d6e8f0a1'
down_revision: Union[str, Sequence[str], None] = 'a1b3c5d7e9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna nas duas tabelas, nula nas linhas que ja existem."""
    op.add_column("sugestoes_elemento", sa.Column("posicao_manual", sa.Integer(), nullable=True))
    op.add_column("sugestoes_cena", sa.Column("posicao_manual", sa.Integer(), nullable=True))


def reverter() -> None:
    """Remove as duas colunas, perdendo as posicoes postas a mao."""
    op.drop_column("sugestoes_cena", "posicao_manual")
    op.drop_column("sugestoes_elemento", "posicao_manual")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
