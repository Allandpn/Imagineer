"""modelos de IA por livro (item 7.5g, MV1)

Coluna `livros.modelos` (JSON, nula): as trocas de modelo que o livro faz sobre a configuracao global, com as mesmas chaves dela
(`modelo_extracao`, `modelo_prompt`, `modelo_imagem`, `modelo_narracao`, `narracao_voz`...). Chave ausente ou vazia = vale o global.
Nula em todos os livros que ja existem: nada muda para eles. Nenhum dado existente e reescrito.

Identificador desta migration: e2f3a4b5c6d8
Vem depois de: d1e2f3a4b5c7
Criada em: 2026-10-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f3a4b5c6d8'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Adiciona a coluna (nula para todos os livros que ja existem)."""
    op.add_column("livros", sa.Column("modelos", sa.JSON(), nullable=True))


def reverter() -> None:
    """Remove a coluna: as trocas de modelo por livro se perdem (a configuracao global nao muda)."""
    op.drop_column("livros", "modelos")


upgrade = aplicar
downgrade = reverter
