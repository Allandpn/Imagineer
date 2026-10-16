"""narrador do livro em primeira pessoa

Uma coluna nova em livros (item 4.9, FL17): `narrador_elemento_id`, o personagem que narra o livro em primeira pessoa (nulo = terceira pessoa).
A chave estrangeira aponta para `elementos`, que por sua vez aponta para `livros`: por isso e criada a parte, com nome.

Identificador desta migration: d6e7f8a9b1c2
Vem depois de: c5d6e7f8a9b1
Criada em: 2026-10-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6e7f8a9b1c2'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna (vazia nos livros que ja existem) e a chave para elementos."""
    with op.batch_alter_table("livros") as lote:
        lote.add_column(sa.Column("narrador_elemento_id", sa.Integer(), nullable=True))
        lote.create_foreign_key("fk_livros_narrador_elemento_id_elementos", "elementos", ["narrador_elemento_id"], ["id"], ondelete="SET NULL")


def reverter() -> None:
    """Remove a chave e a coluna; quem era narrador volta a ser terceira pessoa."""
    with op.batch_alter_table("livros") as lote:
        lote.drop_constraint("fk_livros_narrador_elemento_id_elementos", type_="foreignkey")
        lote.drop_column("narrador_elemento_id")


upgrade = aplicar
downgrade = reverter
