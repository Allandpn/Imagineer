"""acrescenta capitulo ignorado

Descoberto validando a importacao contra cinco livros reais (ver item 2.2):
todo EPUB traz, misturado aos capitulos, material que nao e narrativa --
creditos, glossario, notas do tradutor, anuncios da editora. Nenhum criterio
automatico separa isso de um capitulo legitimo sem arriscar esconder narrativa,
entao a importacao passa a apenas SUGERIR, marcando esta coluna, e o usuario
confirma.

O server_default garante que os capitulos ja importados fiquem como nao
ignorados, sem precisar de um UPDATE separado.

Identificador desta migration: d227b80cd78c
Vem depois de: 49417c94a1e5
Criada em: 2026-09-26 22:36:42.992703

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'd227b80cd78c'
down_revision: Union[str, Sequence[str], None] = '49417c94a1e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna "ignorado" na tabela de capitulos."""
    op.add_column('capitulos', sa.Column('ignorado', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def reverter() -> None:
    """Remove a coluna, perdendo quais capitulos estavam marcados."""
    op.drop_column('capitulos', 'ignorado')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
