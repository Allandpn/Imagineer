"""cria tabelas de livros e capitulos

Primeira migration do projeto: cria as duas tabelas da parte (a) do item 3.4
da especificação. Antes dela o banco está vazio.

Identificador desta migration: 31f1de91a6a4
Vem depois de: nenhuma (é a primeira)
Criada em: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None por ser a primeira).
revision: str = '31f1de91a6a4'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria as tabelas de livros e capítulos."""
    op.create_table('livros',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=500), nullable=False),
    sa.Column('autor', sa.String(length=300), nullable=True),
    sa.Column('idioma', sa.String(length=20), nullable=True),
    sa.Column('identificador_epub', sa.String(length=200), nullable=True),
    sa.Column('nome_arquivo', sa.String(length=500), nullable=False),
    sa.Column('data_importacao', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_livros'))
    )
    op.create_index(op.f('ix_livros_identificador_epub'), 'livros', ['identificador_epub'], unique=False)
    op.create_table('capitulos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('livro_id', sa.Integer(), nullable=False),
    sa.Column('ordem', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=500), nullable=True),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['livro_id'], ['livros.id'], name=op.f('fk_capitulos_livro_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_capitulos')),
    sa.UniqueConstraint('livro_id', 'ordem', name='uq_capitulo_livro_ordem')
    )
    op.create_index(op.f('ix_capitulos_livro_id'), 'capitulos', ['livro_id'], unique=False)


def reverter() -> None:
    """Remove as duas tabelas, voltando o banco ao estado vazio.

    A ordem é a inversa da criação: capítulos primeiro, porque apontam para
    livros. Tentar remover livros antes violaria a chave estrangeira.
    """
    op.drop_index(op.f('ix_capitulos_livro_id'), table_name='capitulos')
    op.drop_table('capitulos')
    op.drop_index(op.f('ix_livros_identificador_epub'), table_name='livros')
    op.drop_table('livros')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
