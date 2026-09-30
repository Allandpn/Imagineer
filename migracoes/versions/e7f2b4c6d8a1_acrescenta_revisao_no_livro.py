"""acrescenta revisao no livro

Um contador por livro que sobe a cada mudanca no que o leitor mostra (item 6.9). O app o usa para
saber, ao abrir um livro, se precisa reler a lista de capitulos ou se pode usar a copia do aparelho
(item 7.0a). Comeca em zero nos livros que ja existem.

Identificador desta migration: e7f2b4c6d8a1
Vem depois de: d6e1a3b5c7f2
Criada em: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'e7f2b4c6d8a1'
down_revision: Union[str, Sequence[str], None] = 'd6e1a3b5c7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, zerada nos livros existentes."""
    op.add_column(
        "livros",
        sa.Column("revisao", sa.Integer(), nullable=False, server_default="0"),
    )


def reverter() -> None:
    """Remove a coluna; os apps voltam a reler a lista a cada abertura."""
    op.drop_column("livros", "revisao")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
