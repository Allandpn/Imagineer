"""orientacao da analise

Coluna nova capitulos.orientacao_da_analise (nula): o que o usuario pediu a IA para procurar na
reanalise do capitulo ("falta a cena em que X chega ao porto"). Fica guardada para as reanalises
seguintes (item 6.7, M1).

Identificador desta migration: e5a7c9d1f3b4
Vem depois de: d4f6b8c0e2a3
Criada em: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'e5a7c9d1f3b4'
down_revision: Union[str, Sequence[str], None] = 'd4f6b8c0e2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula nos capítulos existentes."""
    op.add_column("capitulos", sa.Column("orientacao_da_analise", sa.String(length=1000), nullable=True))


def reverter() -> None:
    """Remove a coluna; a orientação guardada se perde."""
    op.drop_column("capitulos", "orientacao_da_analise")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
