"""dossie da cena e ficha do prompt (item 4.9, FL5, FL8 e FL13.2)

Colunas `frames.dossie` (JSON) e `frames.dossie_entrada` (texto curto, um hash do que entrou no dossie) e `prompts.ficha` (JSON): o que foi lido da cena
e o registro do que entrou em cada prompt. Todas nulas: frame antigo e prompt antigo se comportam como antes. Nenhum dado existente e reescrito.

Identificador desta migration: b9c0d1e2f3a5
Vem depois de: a8b9c0d1e2f4
Criada em: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b9c0d1e2f3a5'
down_revision: Union[str, Sequence[str], None] = 'a8b9c0d1e2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona as tres colunas (nulas para tudo o que ja existe)."""
    op.add_column("frames", sa.Column("dossie", sa.JSON(), nullable=True))
    op.add_column("frames", sa.Column("dossie_entrada", sa.String(length=40), nullable=True))
    op.add_column("prompts", sa.Column("ficha", sa.JSON(), nullable=True))


def reverter() -> None:
    """Remove as colunas: os dossies ja lidos e as fichas dos prompts se perdem; `contexto_do_livro` e o texto de cada prompt continuam."""
    op.drop_column("prompts", "ficha")
    op.drop_column("frames", "dossie_entrada")
    op.drop_column("frames", "dossie")


upgrade = aplicar
downgrade = reverter
