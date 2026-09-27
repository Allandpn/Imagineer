"""cria tabela de configuracao da ia

Item 3.4d: uma linha unica com a configuracao da integracao com IA. A restricao
CHECK (id = 1) impede uma segunda linha aparecer por acidente -- sem ela, dois
registros de configuracao conviveriam e o sistema leria um deles sem avisar.

A linha nao e semeada aqui: o servico a cria sob demanda, o que mantem o sistema
funcionando num banco recem-criado.

Identificador desta migration: a1305e333608
Vem depois de: d227b80cd78c
Criada em: 2026-09-27 00:22:11.969645

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'a1305e333608'
down_revision: Union[str, Sequence[str], None] = 'd227b80cd78c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria a tabela de configuracao."""
    op.create_table('configuracao',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('chave_api_openrouter', sa.String(length=200), nullable=True),
    sa.Column('modelo_extracao', sa.String(length=200), nullable=True),
    sa.Column('modelo_prompt', sa.String(length=200), nullable=True),
    sa.CheckConstraint('id = 1', name=op.f('ck_configuracao_linha_unica')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_configuracao'))
    )


def reverter() -> None:
    """Remove a tabela, perdendo a chave e os modelos cadastrados."""
    op.drop_table('configuracao')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
