"""custo das chamadas de IA

Tabela nova usos_ia: uma linha por chamada bem-sucedida ao provedor de IA, com os tokens e o custo
em dolares que o OpenRouter informou (custo nulo = ele nao informou). Serve para metricas futuras.

Identificador desta migration: b2d4f6a8c0e1
Vem depois de: a1c3e5f7b9d2
Criada em: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'b2d4f6a8c0e1'
down_revision: Union[str, Sequence[str], None] = 'a1c3e5f7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria a tabela usos_ia."""
    op.create_table(
        "usos_ia",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("operacao", sa.String(length=40), nullable=False),
        sa.Column("modelo", sa.String(length=200), nullable=False),
        sa.Column("tokens_entrada", sa.Integer(), nullable=True),
        sa.Column("tokens_saida", sa.Integer(), nullable=True),
        sa.Column("custo", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("id_da_geracao", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usos_ia")),
    )


def reverter() -> None:
    """Remove a tabela; o histórico de custos se perde."""
    op.drop_table("usos_ia")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
