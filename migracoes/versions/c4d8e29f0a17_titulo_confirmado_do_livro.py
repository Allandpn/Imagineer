"""titulo confirmado do livro

Item 6.2/3.4a: título e autor viram mandatórios do ponto de vista do
usuário — a tela de importação (Etapa 7) só se dá por concluída quando os
dois estão preenchidos, pedindo ao usuário quando a extração não conseguir.
`titulo` já nunca fica nulo (cai para o nome do arquivo como fallback), mas
esse fallback é indistinguível de um título de verdade depois de gravado —
`titulo_confirmado` marca a diferença. `autor` continua aceitando nulo no
banco (o `is None` já sinaliza pendência sozinho); só título precisava de
uma coluna espelho.

Identificador desta migration: c4d8e29f0a17
Vem depois de: a92e5f1c8d3b
Criada em: 2026-09-28 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'c4d8e29f0a17'
down_revision: Union[str, Sequence[str], None] = 'a92e5f1c8d3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, com `True` por padrão — livros já importados
    antes desta mudança não ficam retroativamente marcados como pendentes."""
    op.add_column(
        'livros',
        sa.Column(
            'titulo_confirmado',
            sa.Boolean(),
            server_default=sa.text('true'),
            nullable=False,
        ),
    )


def reverter() -> None:
    """Remove a coluna, perdendo a distinção entre título real e fallback."""
    op.drop_column('livros', 'titulo_confirmado')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
