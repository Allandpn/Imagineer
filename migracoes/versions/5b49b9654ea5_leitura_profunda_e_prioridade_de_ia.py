"""leitura profunda e prioridade de ia

Item 4.4 (fase 2): descrever a aparência de vários elementos na mesma resposta
misturou atributos entre personagens num teste com IA real, e um modelo chegou
a inventar um elemento inteiro. A extração virou duas fases — identificação
(sem descrição de aparência) e leitura profunda (um elemento por vez, relendo
o capítulo de origem). `estados_elemento.confirmado_pela_leitura_profunda`
marca se um estado já passou pela fase 2, para o modo ECONOMIA de
`configuracao.prioridade_ia` (item 4.3) saber quando pode reaproveitar em vez
de gastar outra chamada de IA.

Identificador desta migration: 5b49b9654ea5
Vem depois de: a1305e333608
Criada em: 2026-09-27 09:38:56.018146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = '5b49b9654ea5'
down_revision: Union[str, Sequence[str], None] = 'a1305e333608'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta `prioridade_ia` e `confirmado_pela_leitura_profunda`.

    Os `server_default` garantem que linhas já existentes fiquem com o padrão
    seguro (ECONOMIA, e "ainda não lido profundamente") sem precisar de um
    UPDATE separado.
    """
    op.add_column(
        'configuracao',
        sa.Column(
            'prioridade_ia',
            sa.Enum('ECONOMIA', 'QUALIDADE', name='prioridade_ia', native_enum=False, create_constraint=True, length=20),
            server_default='ECONOMIA',
            nullable=False,
        ),
    )
    op.add_column(
        'estados_elemento',
        sa.Column(
            'confirmado_pela_leitura_profunda',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )


def reverter() -> None:
    """Remove as duas colunas, perdendo a prioridade escolhida e as marcações
    de quais estados já passaram pela leitura profunda."""
    op.drop_column('estados_elemento', 'confirmado_pela_leitura_profunda')
    op.drop_column('configuracao', 'prioridade_ia')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
