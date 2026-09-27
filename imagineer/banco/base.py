"""Base declarativa do SQLAlchemy.

Todo modelo (tabela) do sistema herda de ``Base``. O papel dela é reunir, num
só lugar, o mapa de todas as tabelas do projeto — o ``Base.metadata``.

Esse mapa é o que o Alembic compara com o banco real para descobrir, sozinho,
quais migrations precisam ser geradas. Por isso a ``Base`` mora num módulo
separado da sessão: o Alembic precisa dela sem precisar abrir conexão.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Padrão de nomes para índices e restrições.
#
# Sem isso, o PostgreSQL inventa os nomes (e o SQLite simplesmente não nomeia).
# O problema aparece depois: para *remover* ou alterar uma restrição, a
# migration precisa citá-la pelo nome — e um nome inventado pelo banco é
# diferente em cada ambiente. Com esta convenção, o nome é sempre derivado da
# tabela e da coluna, igual em qualquer lugar.
#
# Definido antes da primeira migration de propósito: mudar depois exigiria
# renomear restrições já criadas no banco.
CONVENCAO_DE_NOMES = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",       # índice
    "uq": "uq_%(table_name)s_%(column_0_name)s",       # unicidade
    "ck": "ck_%(table_name)s_%(constraint_name)s",     # verificação
    "fk": "fk_%(table_name)s_%(column_0_name)s",       # chave estrangeira
    "pk": "pk_%(table_name)s",                         # chave primária
}


class Base(DeclarativeBase):
    """Classe-mãe de todos os modelos do Imagineer."""

    metadata = MetaData(naming_convention=CONVENCAO_DE_NOMES)
