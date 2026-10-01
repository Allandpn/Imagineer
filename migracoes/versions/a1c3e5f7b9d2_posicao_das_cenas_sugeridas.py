"""posicao das cenas sugeridas

Duas colunas novas em sugestoes_cena: trecho_ancora (a citacao que a IA devolve, do comeco do momento)
e posicao_no_texto (o deslocamento achado pelo servidor a partir da citacao, em UTF-16). Ambas nulas:
as cenas ja analisadas ficam sem posicao ate o capitulo ser reanalisado (item 3.4g).

Identificador desta migration: a1c3e5f7b9d2
Vem depois de: f9a4c6e8b0d3
Criada em: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'a1c3e5f7b9d2'
down_revision: Union[str, Sequence[str], None] = 'f9a4c6e8b0d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as duas colunas, nulas nas cenas existentes."""
    op.add_column("sugestoes_cena", sa.Column("trecho_ancora", sa.String(length=300), nullable=True))
    op.add_column("sugestoes_cena", sa.Column("posicao_no_texto", sa.Integer(), nullable=True))


def reverter() -> None:
    """Remove as colunas; as cenas perdem a posição."""
    op.drop_column("sugestoes_cena", "posicao_no_texto")
    op.drop_column("sugestoes_cena", "trecho_ancora")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
