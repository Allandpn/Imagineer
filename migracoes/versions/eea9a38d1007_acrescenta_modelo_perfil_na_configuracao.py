"""acrescenta modelo perfil na configuracao

A sugestao de perfil de renderizacao por IA (item 6.5) acontece uma vez por
livro, nao uma vez por capitulo como as outras chamadas -- por isso ganha um
campo de modelo proprio, em vez de reaproveitar "modelo_extracao": vale a pena
escolher um modelo mais caro so aqui, sem afetar o custo das chamadas mais
frequentes.

Identificador desta migration: eea9a38d1007
Vem depois de: e23888d9bc1f
Criada em: 2026-09-27 22:20:40.734336

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'eea9a38d1007'
down_revision: Union[str, Sequence[str], None] = 'e23888d9bc1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna "modelo_perfil" na tabela de configuração."""
    op.add_column("configuracao", sa.Column("modelo_perfil", sa.String(length=200), nullable=True))


def reverter() -> None:
    """Remove a coluna, perdendo o modelo escolhido para sugestão de perfil."""
    op.drop_column("configuracao", "modelo_perfil")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
