"""Modelos SQLAlchemy — as tabelas do banco (Etapa 3 da especificação).

Importar os modelos aqui tem um efeito prático: basta ``import imagineer.modelos``
para que todas as tabelas fiquem registradas na ``Base.metadata``. É disso que
o Alembic depende para gerar migrations sozinho, e os testes para criar o banco.

Sem estes imports, um modelo em arquivo próprio seria invisível — existiria no
disco, mas nunca no mapa de tabelas.
"""

from imagineer.modelos.capitulo import Capitulo
from imagineer.modelos.livro import Livro

__all__ = ["Capitulo", "Livro"]
