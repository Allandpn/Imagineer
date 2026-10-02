"""origem da imagem

O app separa as imagens importadas das geradas (item 7.5b, T2): as geradas aparecem em destaque e as importadas
numa secao propria no fim. O banco so sabia que uma imagem pertence a um prompt. Uma coluna nova em imagens:

- "origem": IMPORTADA (padrao) ou GERADA. O "server_default" faz as imagens que ja existem ficarem IMPORTADA sem
  um UPDATE separado (o banco nao distingue as geradas nos testes de 01/10; sao poucas).

Identificador desta migration: c9d1e3f5a7b9
Vem depois de: b8c0d2e4f6a8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'c9d1e3f5a7b9'
down_revision: Union[str, Sequence[str], None] = 'b8c0d2e4f6a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna de origem na tabela de imagens."""
    op.add_column(
        "imagens",
        sa.Column(
            "origem",
            sa.Enum("IMPORTADA", "GERADA", name="origem_da_imagem", native_enum=False, create_constraint=True, length=20),
            server_default="IMPORTADA",
            nullable=False,
        ),
    )


def reverter() -> None:
    """Remove a coluna, perdendo a distinção entre imagens importadas e geradas."""
    op.drop_column("imagens", "origem")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
