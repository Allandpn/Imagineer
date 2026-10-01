"""descartar sugestoes e desfazer casamento

Duas colunas novas em sugestoes_elemento (descartada, casamento_desfeito) e uma em sugestoes_cena
(descartada). Descartar tira a sugestao das pendentes e ela sobrevive a uma reanalise; desfazer o
casamento passa a valer de verdade (o casamento automatico nao religa a sugestao sozinho).

Identificador desta migration: f9a4c6e8b0d3
Vem depois de: e7f2b4c6d8a1
Criada em: 2026-09-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'f9a4c6e8b0d3'
down_revision: Union[str, Sequence[str], None] = 'e7f2b4c6d8a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta as colunas, todas falsas nas sugestoes existentes."""
    for tabela, coluna in [
        ("sugestoes_elemento", "descartada"),
        ("sugestoes_elemento", "casamento_desfeito"),
        ("sugestoes_cena", "descartada"),
    ]:
        op.add_column(
            tabela,
            sa.Column(coluna, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def reverter() -> None:
    """Remove as colunas; o que foi descartado volta a ser pendente."""
    op.drop_column("sugestoes_cena", "descartada")
    op.drop_column("sugestoes_elemento", "casamento_desfeito")
    op.drop_column("sugestoes_elemento", "descartada")


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
