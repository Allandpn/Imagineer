"""situacao da geracao do prompt

O incremento 12 gera a imagem pelo app, e um prompt pode ser recusado pelo provedor (moderacao).
Tres colunas novas em prompts (item 3.4c, S5):

- "situacao_da_geracao": NAO_TENTADO (padrao), RECUSADO ou COM_SUCESSO. O "server_default" faz os
  prompts que ja existem ficarem NAO_TENTADO sem um UPDATE separado.
- "motivo_da_recusa": a mensagem do provedor quando RECUSADO (nula nos outros casos).
- "prompt_original_id": no prompt suavizado, o prompt de onde ele saiu. SET NULL: apagar o original
  nao apaga o suavizado.

Identificador desta migration: b8c0d2e4f6a8
Vem depois de: a7b9c1d3e5f7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
revision: str = 'b8c0d2e4f6a8'
down_revision: Union[str, Sequence[str], None] = 'a7b9c1d3e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as três colunas na tabela de prompts."""
    op.add_column(
        "prompts",
        sa.Column(
            "situacao_da_geracao",
            sa.Enum(
                "NAO_TENTADO",
                "RECUSADO",
                "COM_SUCESSO",
                name="situacao_da_geracao",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="NAO_TENTADO",
            nullable=False,
        ),
    )
    op.add_column("prompts", sa.Column("motivo_da_recusa", sa.Text(), nullable=True))
    op.add_column("prompts", sa.Column("prompt_original_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_prompts_prompt_original_id"), "prompts", ["prompt_original_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_prompts_prompt_original_id_prompts"),
        "prompts",
        "prompts",
        ["prompt_original_id"],
        ["id"],
        ondelete="SET NULL",
    )


def reverter() -> None:
    """Remove as colunas, perdendo a situação, o motivo e o vínculo com o original."""
    op.drop_constraint(op.f("fk_prompts_prompt_original_id_prompts"), "prompts", type_="foreignkey")
    op.drop_index(op.f("ix_prompts_prompt_original_id"), table_name="prompts")
    op.drop_column("prompts", "prompt_original_id")
    op.drop_column("prompts", "motivo_da_recusa")
    op.drop_column("prompts", "situacao_da_geracao")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
