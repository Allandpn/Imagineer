"""marcador e pins

Duas tabelas novas (item 3.4h): marcadores (um por livro; a posicao de leitura automatica, em que o
lido_em mais recente vence) e pins (varios por livro; posicoes marcadas a mao, com nota opcional).
As duas apagam em cascata com o livro e com o capitulo.

Identificador desta migration: c3e5a7b9d1f2
Vem depois de: b2d4f6a8c0e1
Criada em: 2026-10-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'c3e5a7b9d1f2'
down_revision: Union[str, Sequence[str], None] = 'b2d4f6a8c0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria marcadores e pins."""
    op.create_table(
        "marcadores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("livro_id", sa.Integer(), nullable=False),
        sa.Column("capitulo_id", sa.Integer(), nullable=False),
        sa.Column("posicao_no_texto", sa.Integer(), nullable=False),
        sa.Column("lido_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["livro_id"], ["livros.id"], name=op.f("fk_marcadores_livro_id_livros"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capitulo_id"], ["capitulos.id"], name=op.f("fk_marcadores_capitulo_id_capitulos"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marcadores")),
        sa.UniqueConstraint("livro_id", name="uq_marcador_livro"),
    )
    op.create_table(
        "pins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("livro_id", sa.Integer(), nullable=False),
        sa.Column("capitulo_id", sa.Integer(), nullable=False),
        sa.Column("posicao_no_texto", sa.Integer(), nullable=False),
        sa.Column("nota", sa.String(length=1000), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["livro_id"], ["livros.id"], name=op.f("fk_pins_livro_id_livros"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capitulo_id"], ["capitulos.id"], name=op.f("fk_pins_capitulo_id_capitulos"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pins")),
    )
    op.create_index(op.f("ix_pins_livro_id"), "pins", ["livro_id"], unique=False)


def reverter() -> None:
    """Remove as duas tabelas; marcadores e pins se perdem."""
    op.drop_index(op.f("ix_pins_livro_id"), table_name="pins")
    op.drop_table("pins")
    op.drop_table("marcadores")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
