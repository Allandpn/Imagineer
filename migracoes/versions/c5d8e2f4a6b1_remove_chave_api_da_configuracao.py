"""remove chave api da configuracao

A chave de API do OpenRouter deixa de ser guardada no banco (item 4.3): a chave
do servidor vem so da variavel de ambiente, e a de cada usuario chega por header
(X-Chave-API-OpenRouter) a cada chamada, sem ser persistida. Guardar a chave de
qualquer usuario no servidor nao escala para mais de uma pessoa no mesmo backend,
e a chave dentro de um backup de banco e um vazamento esperando acontecer.

Identificador desta migration: c5d8e2f4a6b1
Vem depois de: c4d8e29f0a17
Criada em: 2026-09-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'c5d8e2f4a6b1'
down_revision: Union[str, Sequence[str], None] = 'c4d8e29f0a17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Apaga a coluna, descartando qualquer chave que estivesse cadastrada."""
    op.drop_column("configuracao", "chave_api_openrouter")


def reverter() -> None:
    """Recria a coluna vazia — a chave apagada não volta."""
    op.add_column(
        "configuracao",
        sa.Column("chave_api_openrouter", sa.String(length=200), nullable=True),
    )


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
