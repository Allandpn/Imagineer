"""acrescenta tamanho em bytes na imagem

O app vai poder baixar um livro inteiro para ler offline (item 7.0a), e antes de comecar precisa dizer
quanto vai ocupar ("Baixar -- 240 MB"). Para isso o servidor passa a guardar o tamanho de cada
arquivo de imagem (item 6.9). A coluna aceita nulo: as imagens importadas antes desta migration
ficam sem valor, e o manifesto de midias o calcula a partir do arquivo em disco na primeira vez.

Identificador desta migration: d6e1a3b5c7f2
Vem depois de: c5d8e2f4a6b1
Criada em: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'd6e1a3b5c7f2'
down_revision: Union[str, Sequence[str], None] = 'c5d8e2f4a6b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula nas imagens que ja existem."""
    op.add_column("imagens", sa.Column("tamanho_em_bytes", sa.Integer(), nullable=True))


def reverter() -> None:
    """Remove a coluna; o tamanho volta a ser calculado do arquivo quando preciso."""
    op.drop_column("imagens", "tamanho_em_bytes")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
