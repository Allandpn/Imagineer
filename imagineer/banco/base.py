"""Base declarativa do SQLAlchemy.

Todo modelo (tabela) do sistema vai herdar de ``Base``. O papel dela é reunir,
num só lugar, o mapa de todas as tabelas do projeto — o ``Base.metadata``.

Esse mapa é o que o Alembic compara com o banco real para descobrir, sozinho,
quais migrations precisam ser geradas. Por isso a ``Base`` mora num módulo
separado da sessão: o Alembic precisa dela sem precisar abrir conexão.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Classe-mãe de todos os modelos do Imagineer."""
