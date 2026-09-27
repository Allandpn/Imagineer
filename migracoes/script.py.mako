"""${message}

Identificador desta migration: ${up_revision}
Vem depois de: ${down_revision | comma,n}
Criada em: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def aplicar() -> None:
    """Aplica a mudança no banco."""
    ${upgrades if upgrades else "pass"}


def reverter() -> None:
    """Desfaz a mudança, voltando o banco ao estado anterior."""
    ${downgrades if downgrades else "pass"}


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
