"""modelo de leitura e modelo reserva na configuracao (item 4.10, LM12 e LM13)

Colunas `configuracao.modelo_leitura` e `configuracao.modelo_reserva`, nulas: configuracao antiga continua valida (`modelo_leitura` vazio cai
em `modelo_extracao`, e sem `modelo_reserva` nada muda).

Identificador desta migration: f7a8b9c0d1e3
Vem depois de: e6f7a8b9c0d2
Criada em: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7a8b9c0d1e3'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona as duas colunas (nulas para todas as configuracoes que ja existem)."""
    op.add_column("configuracao", sa.Column("modelo_leitura", sa.String(length=200), nullable=True))
    op.add_column("configuracao", sa.Column("modelo_reserva", sa.String(length=200), nullable=True))


def reverter() -> None:
    """Remove as colunas: o modelo de leitura e o reserva escolhidos se perdem."""
    op.drop_column("configuracao", "modelo_reserva")
    op.drop_column("configuracao", "modelo_leitura")


upgrade = aplicar
downgrade = reverter
