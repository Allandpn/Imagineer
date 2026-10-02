"""registro de que o filtro de seguranca foi desligado

O usuario pode pedir, depois de uma recusa, que o Replicate gere sem o filtro opcional do modelo (item 7.5b, F12 a F18).
O prompt e a imagem guardam que isso aconteceu (F16), para nunca haver duvida de como a imagem nasceu:

- "prompts.sem_filtro_de_seguranca": a ultima tentativa desse prompt foi com o filtro desligado.
- "imagens.sem_filtro_de_seguranca": a imagem foi gerada com o filtro desligado.

Identificador desta migration: f2a4b6c8d0e2
Vem depois de: e1f3a5b7c9d1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'f2a4b6c8d0e2'
down_revision: Union[str, Sequence[str], None] = 'e1f3a5b7c9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as duas colunas, falsas para o que já existe."""
    op.add_column("prompts", sa.Column("sem_filtro_de_seguranca", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("imagens", sa.Column("sem_filtro_de_seguranca", sa.Boolean(), nullable=False, server_default=sa.false()))


def reverter() -> None:
    """Remove as colunas, perdendo o registro."""
    op.drop_column("imagens", "sem_filtro_de_seguranca")
    op.drop_column("prompts", "sem_filtro_de_seguranca")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
