"""cria tabelas de elementos e estados de elemento

Parte (b) do item 3.4 da especificação: a separação entre a identidade de um
elemento (Elemento) e como ele está num ponto da narrativa (EstadoElemento).

Identificador desta migration: ed7da64a05d3
Vem depois de: 31f1de91a6a4
Criada em: 2026-09-26 21:51:08.808343

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'ed7da64a05d3'
down_revision: Union[str, Sequence[str], None] = '31f1de91a6a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria as tabelas de elementos e de estados de elemento.

    Ajuste feito à mão no código gerado: o Alembic emitiu a restrição CHECK do
    campo "tipo" como linhas explícitas, mas o próprio ``sa.Enum`` com
    ``create_constraint=True`` já a cria junto da coluna. Mantê-las causava
    "check constraint ck_elementos_tipo_elemento already exists". As linhas
    explícitas foram removidas; quem cria a restrição é o tipo da coluna.
    """
    op.create_table('elementos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('livro_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.Enum('PERSONAGEM', 'AMBIENTE', 'OBJETO', 'CRIATURA', 'GRUPO', 'VEICULO', 'EDIFICACAO', name='tipo_elemento', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('nome', sa.String(length=200), nullable=False),
    sa.Column('descricao', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['livro_id'], ['livros.id'], name=op.f('fk_elementos_livro_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_elementos')),
    sa.UniqueConstraint('livro_id', 'tipo', 'nome', name='uq_elemento_livro_tipo_nome')
    )
    op.create_index(op.f('ix_elementos_livro_id'), 'elementos', ['livro_id'], unique=False)
    op.create_table('estados_elemento',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('elemento_id', sa.Integer(), nullable=False),
    sa.Column('capitulo_id', sa.Integer(), nullable=False),
    sa.Column('descricao', sa.Text(), nullable=False),
    sa.Column('data_criacao', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['capitulo_id'], ['capitulos.id'], name=op.f('fk_estados_elemento_capitulo_id'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['elemento_id'], ['elementos.id'], name=op.f('fk_estados_elemento_elemento_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_estados_elemento'))
    )
    op.create_index(op.f('ix_estados_elemento_capitulo_id'), 'estados_elemento', ['capitulo_id'], unique=False)
    op.create_index(op.f('ix_estados_elemento_elemento_id'), 'estados_elemento', ['elemento_id'], unique=False)


def reverter() -> None:
    """Remove as duas tabelas.

    A ordem é a inversa da criação: os estados apontam para os elementos, então
    precisam sair primeiro, ou a chave estrangeira recusaria o DROP.
    """
    op.drop_index(op.f('ix_estados_elemento_elemento_id'), table_name='estados_elemento')
    op.drop_index(op.f('ix_estados_elemento_capitulo_id'), table_name='estados_elemento')
    op.drop_table('estados_elemento')
    op.drop_index(op.f('ix_elementos_livro_id'), table_name='elementos')
    op.drop_table('elementos')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
