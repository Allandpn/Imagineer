"""texto em portugues do prompt

Uma coluna nova em prompts: `texto_pt`, a versao em portugues do prompt (nula = ainda sem traducao). O prompt de verdade continua
sendo o `texto`, em ingles (item 7.5b, PT1).

Identificador desta migration: f2b3c4d5e6a7
Vem depois de: e1a2b3c4d5f6
Criada em: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2b3c4d5e6a7'
down_revision: Union[str, Sequence[str], None] = 'e1a2b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula nos prompts existentes."""
    op.add_column("prompts", sa.Column("texto_pt", sa.Text(), nullable=True))


def reverter() -> None:
    """Remove a coluna; as traducoes guardadas se perdem (podem ser refeitas)."""
    op.drop_column("prompts", "texto_pt")


upgrade = aplicar
downgrade = reverter
