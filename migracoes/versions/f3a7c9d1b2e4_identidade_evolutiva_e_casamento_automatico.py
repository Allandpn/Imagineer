"""identidade evolutiva e casamento automatico

Item 3.4f: `HistoricoIdentidadeElemento` guarda o que um capítulo específico
acrescenta sobre a identidade de um Elemento — quem ele é, não sua aparência.
Diferente de `EstadoElemento` (aparência, "última vale"), é cumulativo: a
identidade vigente num ponto da narrativa soma `Elemento.descricao` com estes
registros, em ordem narrativa (ver `servicos/identidade_de_elemento.py`).
Resolve a pendência de prioridade alta da Etapa 8: a identidade do elemento
era escrita uma vez, na confirmação, e nunca mais revisitada.

Item 4.6: `sugestoes_elemento.casamento_automatico` sinaliza quando
`elemento_id` veio só do casamento automático por nome (item 6.7), nunca
revisado por uma pessoa — sem isso, um casamento errado podia ir direto para
um Frame de verdade (via confirmação em lote de uma cena sugerida) sem
nenhum ponto de checagem.

Identificador desta migration: f3a7c9d1b2e4
Vem depois de: eea9a38d1007
Criada em: 2026-09-28 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'f3a7c9d1b2e4'
down_revision: Union[str, Sequence[str], None] = 'eea9a38d1007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria `historico_identidade_elemento` e acrescenta `casamento_automatico`.

    Os `server_default` garantem que sugestões já existentes fiquem marcadas
    como "casamento não revisado ainda" (o estado mais conservador: ninguém
    olhou para elas de propósito), sem precisar de um UPDATE separado.
    """
    op.create_table(
        'historico_identidade_elemento',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('elemento_id', sa.Integer(), nullable=False),
        sa.Column('capitulo_id', sa.Integer(), nullable=False),
        sa.Column('descricao', sa.Text(), nullable=False),
        sa.Column(
            'confirmado_pela_leitura_profunda',
            sa.Boolean(),
            server_default=sa.text('true'),
            nullable=False,
        ),
        sa.Column(
            'data_criacao',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['capitulo_id'], ['capitulos.id'],
            name=op.f('fk_historico_identidade_elemento_capitulo_id'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['elemento_id'], ['elementos.id'],
            name=op.f('fk_historico_identidade_elemento_elemento_id'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_historico_identidade_elemento')),
    )
    op.create_index(
        op.f('ix_historico_identidade_elemento_elemento_id'),
        'historico_identidade_elemento', ['elemento_id'], unique=False,
    )
    op.create_index(
        op.f('ix_historico_identidade_elemento_capitulo_id'),
        'historico_identidade_elemento', ['capitulo_id'], unique=False,
    )

    op.add_column(
        'sugestoes_elemento',
        sa.Column(
            'casamento_automatico',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )


def reverter() -> None:
    """Desfaz a mudança: apaga o histórico de identidade e a sinalização de
    casamento automático, voltando ao estado anterior."""
    op.drop_column('sugestoes_elemento', 'casamento_automatico')

    op.drop_index(
        op.f('ix_historico_identidade_elemento_capitulo_id'),
        table_name='historico_identidade_elemento',
    )
    op.drop_index(
        op.f('ix_historico_identidade_elemento_elemento_id'),
        table_name='historico_identidade_elemento',
    )
    op.drop_table('historico_identidade_elemento')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
