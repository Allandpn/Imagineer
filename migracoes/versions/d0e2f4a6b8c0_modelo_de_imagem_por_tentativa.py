"""modelo de imagem por tentativa e lista de modelos

O usuario precisa saber qual modelo de imagem tentou cada prompt e poder escolher outro depois de uma recusa
(item 7.5b, Z1 a Z11). Tres colunas novas:

- "prompts.modelo_imagem": o modelo da ultima tentativa de gerar a imagem do prompt (nulo se nunca tentado).
- "imagens.modelo": o modelo que gerou a imagem (nulo se foi importada ou e anterior a esta coluna).
- "configuracao.modelos_de_imagem": a lista de modelos que o usuario pode escolher no app. O "server_default" faz a
  linha que ja existe tambem receber a lista padrao.

Identificador desta migration: d0e2f4a6b8c0
Vem depois de: c9d1e3f5a7b9
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'd0e2f4a6b8c0'
down_revision: Union[str, Sequence[str], None] = 'c9d1e3f5a7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODELOS_PADRAO = '["meta/muse-image", "bytedance-seed/seedream-5-0-flash", "google/gemini-2.5-flash-image"]'


def aplicar() -> None:
    """Acrescenta as três colunas."""
    op.add_column("prompts", sa.Column("modelo_imagem", sa.String(length=200), nullable=True))
    op.add_column("imagens", sa.Column("modelo", sa.String(length=200), nullable=True))
    op.add_column(
        "configuracao",
        sa.Column("modelos_de_imagem", sa.JSON(), nullable=False, server_default=MODELOS_PADRAO),
    )


def reverter() -> None:
    """Remove as colunas, perdendo o modelo de cada tentativa e a lista de modelos."""
    op.drop_column("configuracao", "modelos_de_imagem")
    op.drop_column("imagens", "modelo")
    op.drop_column("prompts", "modelo_imagem")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
