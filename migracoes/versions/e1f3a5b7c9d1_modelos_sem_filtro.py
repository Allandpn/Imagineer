"""lista de modelos que permitem desligar o filtro de seguranca

O usuario pode, depois de uma recusa de conteudo, tentar o Replicate com o filtro opcional do modelo desligado
(item 7.5b, F12 a F18). So alguns modelos tem esse parametro, entao a lista dos que o permitem fica na
configuracao, mantida a mao como "modelos_de_imagem":

- "configuracao.modelos_sem_filtro": ids com prefixo (ex.: "replicate:black-forest-labs/flux-schnell"). Nasce vazia:
  nenhum modelo permite desligar o filtro ate o usuario inclui-lo.

Identificador desta migration: e1f3a5b7c9d1
Vem depois de: d0e2f4a6b8c0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'e1f3a5b7c9d1'
down_revision: Union[str, Sequence[str], None] = 'd0e2f4a6b8c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, vazia para a linha que já existe."""
    op.add_column(
        "configuracao",
        sa.Column("modelos_sem_filtro", sa.JSON(), nullable=False, server_default="[]"),
    )


def reverter() -> None:
    """Remove a coluna, perdendo a lista."""
    op.drop_column("configuracao", "modelos_sem_filtro")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
