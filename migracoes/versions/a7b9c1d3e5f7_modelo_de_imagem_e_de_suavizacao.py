"""modelo de imagem e de suavizacao na configuracao

O incremento 12 passa a gerar a imagem pelo app, e isso precisa de dois modelos
que a configuracao ainda nao tinha:

- "modelo_imagem": o modelo que gera a imagem a partir do prompt. Nao aceita
  nulo (sem ele nao ha o que chamar) e nasce "meta/muse-image" -- o padrao
  escolhido pelo Allan em 01/10/2026. O "server_default" faz a linha que ja
  existe no banco tambem receber o valor, nao so as linhas novas.
- "modelo_suavizacao": o modelo de texto que reescreve um prompt recusado pelo
  provedor de imagem. Opcional: vazio significa "usa o modelo_prompt".

Identificador desta migration: a7b9c1d3e5f7
Vem depois de: f6a8d0e2b4c5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'a7b9c1d3e5f7'
down_revision: Union[str, Sequence[str], None] = 'f6a8d0e2b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODELO_DE_IMAGEM_PADRAO = "meta/muse-image"


def aplicar() -> None:
    """Acrescenta as duas colunas de modelo na tabela de configuração."""
    op.add_column(
        "configuracao",
        sa.Column(
            "modelo_imagem",
            sa.String(length=200),
            nullable=False,
            server_default=MODELO_DE_IMAGEM_PADRAO,
        ),
    )
    op.add_column("configuracao", sa.Column("modelo_suavizacao", sa.String(length=200), nullable=True))


def reverter() -> None:
    """Remove as colunas, perdendo os modelos escolhidos para imagem e suavização."""
    op.drop_column("configuracao", "modelo_suavizacao")
    op.drop_column("configuracao", "modelo_imagem")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
