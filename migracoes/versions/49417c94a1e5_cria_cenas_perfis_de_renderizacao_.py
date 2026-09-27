"""cria cenas, perfis de renderizacao, prompts e imagens

Parte (c) do item 3.4 da especificação: fecha o modelo do MVP. Cria as quatro
entidades restantes, a tabela que liga Cena a EstadoElemento, e as duas chaves
estrangeiras que ficaram pendentes das partes (a) e (b) por dependerem destas
tabelas — o motivo pelo qual o projeto usa Alembic desde o primeiro item.

Identificador desta migration: 49417c94a1e5
Vem depois de: ed7da64a05d3
Criada em: 2026-09-26 21:59:11.234532

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = '49417c94a1e5'
down_revision: Union[str, Sequence[str], None] = 'ed7da64a05d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria as tabelas da parte (c) e liga as pontas deixadas para trás.

    As duas últimas operações são as chaves estrangeiras pendentes:
    ``livros.perfil_renderizacao_padrao_id`` e
    ``estados_elemento.imagem_ancora_id``. Elas vêm no fim porque só podem
    existir depois das tabelas a que apontam.
    """
    op.create_table('perfis_renderizacao',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=100), nullable=False),
    sa.Column('estilo', sa.Text(), nullable=True),
    sa.Column('artista_referencia', sa.String(length=200), nullable=True),
    sa.Column('iluminacao', sa.String(length=200), nullable=True),
    sa.Column('paleta', sa.String(length=200), nullable=True),
    sa.Column('formato', sa.String(length=50), nullable=True),
    sa.Column('modelo_alvo', sa.String(length=100), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_perfis_renderizacao')),
    sa.UniqueConstraint('nome', name=op.f('uq_perfis_renderizacao_nome'))
    )
    op.create_table('cenas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('capitulo_id', sa.Integer(), nullable=False),
    sa.Column('titulo', sa.String(length=300), nullable=False),
    sa.Column('descricao', sa.Text(), nullable=True),
    sa.Column('horario', sa.String(length=100), nullable=True),
    sa.Column('clima', sa.String(length=100), nullable=True),
    sa.Column('humor', sa.String(length=100), nullable=True),
    sa.ForeignKeyConstraint(['capitulo_id'], ['capitulos.id'], name=op.f('fk_cenas_capitulo_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cenas'))
    )
    op.create_index(op.f('ix_cenas_capitulo_id'), 'cenas', ['capitulo_id'], unique=False)
    op.create_table('prompts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cena_id', sa.Integer(), nullable=False),
    sa.Column('perfil_renderizacao_id', sa.Integer(), nullable=True),
    sa.Column('modelo_ia', sa.String(length=200), nullable=True),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.Column('avaliacao', sa.Text(), nullable=True),
    sa.Column('data_criacao', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['cena_id'], ['cenas.id'], name=op.f('fk_prompts_cena_id'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['perfil_renderizacao_id'], ['perfis_renderizacao.id'], name=op.f('fk_prompts_perfil_renderizacao_id'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prompts'))
    )
    op.create_index(op.f('ix_prompts_cena_id'), 'prompts', ['cena_id'], unique=False)
    op.create_table('imagens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prompt_id', sa.Integer(), nullable=False),
    sa.Column('caminho_arquivo', sa.String(length=500), nullable=False),
    sa.Column('data_importacao', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['prompt_id'], ['prompts.id'], name=op.f('fk_imagens_prompt_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_imagens')),
    sa.UniqueConstraint('caminho_arquivo', name=op.f('uq_imagens_caminho_arquivo'))
    )
    op.create_index(op.f('ix_imagens_prompt_id'), 'imagens', ['prompt_id'], unique=False)
    op.create_table('cenas_estados_elemento',
    sa.Column('cena_id', sa.Integer(), nullable=False),
    sa.Column('estado_elemento_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['cena_id'], ['cenas.id'], name=op.f('fk_cenas_estados_elemento_cena_id'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['estado_elemento_id'], ['estados_elemento.id'], name=op.f('fk_cenas_estados_elemento_estado_elemento_id'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('cena_id', 'estado_elemento_id', name=op.f('pk_cenas_estados_elemento'))
    )
    op.add_column('estados_elemento', sa.Column('imagem_ancora_id', sa.Integer(), nullable=True))
    op.create_foreign_key(op.f('fk_estados_elemento_imagem_ancora_id'), 'estados_elemento', 'imagens', ['imagem_ancora_id'], ['id'], ondelete='SET NULL')
    op.add_column('livros', sa.Column('perfil_renderizacao_padrao_id', sa.Integer(), nullable=True))
    op.create_foreign_key(op.f('fk_livros_perfil_renderizacao_padrao_id'), 'livros', 'perfis_renderizacao', ['perfil_renderizacao_padrao_id'], ['id'], ondelete='SET NULL')


def reverter() -> None:
    """Desfaz tudo, voltando ao estado do fim da parte (b).

    A ordem é a inversa da criação: primeiro as colunas acrescentadas em
    tabelas que já existiam, depois as tabelas novas — as que apontam para
    outras saindo antes das apontadas.
    """
    op.drop_constraint(op.f('fk_livros_perfil_renderizacao_padrao_id'), 'livros', type_='foreignkey')
    op.drop_column('livros', 'perfil_renderizacao_padrao_id')
    op.drop_constraint(op.f('fk_estados_elemento_imagem_ancora_id'), 'estados_elemento', type_='foreignkey')
    op.drop_column('estados_elemento', 'imagem_ancora_id')
    op.drop_table('cenas_estados_elemento')
    op.drop_index(op.f('ix_imagens_prompt_id'), table_name='imagens')
    op.drop_table('imagens')
    op.drop_index(op.f('ix_prompts_cena_id'), table_name='prompts')
    op.drop_table('prompts')
    op.drop_index(op.f('ix_cenas_capitulo_id'), table_name='cenas')
    op.drop_table('cenas')
    op.drop_table('perfis_renderizacao')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
