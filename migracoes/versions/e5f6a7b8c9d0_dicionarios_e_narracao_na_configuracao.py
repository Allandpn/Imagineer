"""preferencias dos dicionarios e configuracao da narracao

Seis colunas novas em `configuracao` (RL26, RL29): a ordem e os dicionarios desligados, e os campos da narracao por IA (motor, modo,
voz e instrucoes), que ficam guardados para quando a narracao existir. Todas com valor padrao: nada muda para quem nao mexe.

Identificador desta migration: e5f6a7b8c9d0
Vem depois de: d4e5f6a7b8c9
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as colunas, todas com padrao. Sem CHECK nos enums: uma opcao nova depois nao exige mexer em restricao."""
    op.add_column("configuracao", sa.Column("ordem_dos_dicionarios", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("configuracao", sa.Column("dicionarios_desativados", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("configuracao", sa.Column("narracao_motor", sa.String(length=20), nullable=False, server_default="APARELHO"))
    op.add_column("configuracao", sa.Column("narracao_modo", sa.String(length=20), nullable=False, server_default="UMA_VOZ"))
    op.add_column("configuracao", sa.Column("narracao_voz", sa.String(length=100), nullable=True))
    op.add_column("configuracao", sa.Column("narracao_instrucoes", sa.Text(), nullable=True))


def reverter() -> None:
    """Remove as colunas; as preferencias e a configuracao da narracao se perdem."""
    for coluna in ("narracao_instrucoes", "narracao_voz", "narracao_modo", "narracao_motor", "dicionarios_desativados", "ordem_dos_dicionarios"):
        op.drop_column("configuracao", coluna)


upgrade = aplicar
downgrade = reverter
