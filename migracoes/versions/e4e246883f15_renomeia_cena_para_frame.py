"""renomeia cena para frame

Feedback validando o sistema com IA real: um prompt de "personagem" (retrato
solo) citou outro elemento por engano, porque a mesma entidade "Cena" servia
tanto para um retrato quanto para uma cena de verdade, sem nada que
distinguisse a intenção. `Cena` vira `Frame`, com um campo `tipo`
(PERSONAGEM | CENA) que muda como o prompt é montado — um retrato usa só a
descrição do elemento, uma cena declara quem/onde/o quê.

De quebra, uma cena passa a ter sua própria leitura profunda
(`contexto_do_livro` + `confirmado_pela_leitura_profunda`, espelhando os
campos já existentes em `EstadoElemento`): confere o que o usuário escreveu
contra o capítulo, mas sem sobrescrever — a palavra do usuário continua tendo
prioridade (item 4.4).

Os nomes de tabela/coluna/restrição são renomeados explicitamente (não
recriados) para preservar os dados já existentes e não deixar a convenção de
nomes da Base (item 5) inconsistente com o resto do banco.

Identificador desta migration: e4e246883f15
Vem depois de: 5b49b9654ea5
Criada em: 2026-09-27 12:54:12.115987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'e4e246883f15'
down_revision: Union[str, Sequence[str], None] = '5b49b9654ea5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Renomeia cenas -> frames (tabela, colunas e restrições) e acrescenta
    tipo, contexto_do_livro e confirmado_pela_leitura_profunda."""
    # Tabela principal.
    op.rename_table('cenas', 'frames')
    op.execute('ALTER TABLE frames RENAME CONSTRAINT pk_cenas TO pk_frames')
    op.execute(
        'ALTER TABLE frames RENAME CONSTRAINT fk_cenas_capitulo_id TO fk_frames_capitulo_id'
    )
    op.execute('ALTER INDEX ix_cenas_capitulo_id RENAME TO ix_frames_capitulo_id')

    # Tabela de associação com os estados de elemento.
    op.rename_table('cenas_estados_elemento', 'frames_estados_elemento')
    op.alter_column('frames_estados_elemento', 'cena_id', new_column_name='frame_id')
    op.execute(
        'ALTER TABLE frames_estados_elemento '
        'RENAME CONSTRAINT pk_cenas_estados_elemento TO pk_frames_estados_elemento'
    )
    op.execute(
        'ALTER TABLE frames_estados_elemento RENAME CONSTRAINT '
        'fk_cenas_estados_elemento_cena_id TO fk_frames_estados_elemento_frame_id'
    )
    op.execute(
        'ALTER TABLE frames_estados_elemento RENAME CONSTRAINT '
        'fk_cenas_estados_elemento_estado_elemento_id TO '
        'fk_frames_estados_elemento_estado_elemento_id'
    )

    # Referência em prompts.
    op.alter_column('prompts', 'cena_id', new_column_name='frame_id')
    op.execute('ALTER TABLE prompts RENAME CONSTRAINT fk_prompts_cena_id TO fk_prompts_frame_id')
    op.execute('ALTER INDEX ix_prompts_cena_id RENAME TO ix_prompts_frame_id')

    # Campos novos. Linhas existentes são todas cenas de verdade (não havia
    # retrato solo antes desta migration), então o padrão CENA é o correto.
    op.add_column(
        'frames',
        sa.Column(
            'tipo',
            sa.Enum('PERSONAGEM', 'CENA', name='tipo_de_frame', native_enum=False, create_constraint=True, length=20),
            server_default='CENA',
            nullable=False,
        ),
    )
    op.add_column('frames', sa.Column('contexto_do_livro', sa.Text(), nullable=True))
    op.add_column(
        'frames',
        sa.Column(
            'confirmado_pela_leitura_profunda',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )


def reverter() -> None:
    """Desfaz o rename e remove os campos novos, voltando a cenas/Cena."""
    op.drop_column('frames', 'confirmado_pela_leitura_profunda')
    op.drop_column('frames', 'contexto_do_livro')
    op.drop_column('frames', 'tipo')

    op.execute('ALTER INDEX ix_prompts_frame_id RENAME TO ix_prompts_cena_id')
    op.execute('ALTER TABLE prompts RENAME CONSTRAINT fk_prompts_frame_id TO fk_prompts_cena_id')
    op.alter_column('prompts', 'frame_id', new_column_name='cena_id')

    op.execute(
        'ALTER TABLE frames_estados_elemento RENAME CONSTRAINT '
        'fk_frames_estados_elemento_estado_elemento_id TO '
        'fk_cenas_estados_elemento_estado_elemento_id'
    )
    op.execute(
        'ALTER TABLE frames_estados_elemento RENAME CONSTRAINT '
        'fk_frames_estados_elemento_frame_id TO fk_cenas_estados_elemento_cena_id'
    )
    op.execute(
        'ALTER TABLE frames_estados_elemento '
        'RENAME CONSTRAINT pk_frames_estados_elemento TO pk_cenas_estados_elemento'
    )
    op.alter_column('frames_estados_elemento', 'frame_id', new_column_name='cena_id')
    op.rename_table('frames_estados_elemento', 'cenas_estados_elemento')

    op.execute('ALTER INDEX ix_frames_capitulo_id RENAME TO ix_cenas_capitulo_id')
    op.execute(
        'ALTER TABLE frames RENAME CONSTRAINT fk_frames_capitulo_id TO fk_cenas_capitulo_id'
    )
    op.execute('ALTER TABLE frames RENAME CONSTRAINT pk_frames TO pk_cenas')
    op.rename_table('frames', 'cenas')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
