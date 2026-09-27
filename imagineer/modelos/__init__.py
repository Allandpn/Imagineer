"""Modelos SQLAlchemy — as tabelas do banco (Etapa 3 da especificação).

Importar os modelos aqui tem um efeito prático: basta ``import imagineer.modelos``
para que todas as tabelas fiquem registradas na ``Base.metadata``. É disso que
o Alembic depende para gerar migrations sozinho, e os testes para criar o banco.

Sem estes imports, um modelo em arquivo próprio seria invisível — existiria no
disco, mas nunca no mapa de tabelas.
"""

from imagineer.modelos.capitulo import Capitulo
from imagineer.modelos.configuracao import Configuracao, PrioridadeIA
from imagineer.modelos.elemento import Elemento, EstadoElemento, TipoElemento
from imagineer.modelos.frame import Frame, TipoDeFrame, frames_estados_elemento
from imagineer.modelos.livro import Livro
from imagineer.modelos.perfil_renderizacao import PerfilRenderizacao
from imagineer.modelos.prompt import Imagem, Prompt
from imagineer.modelos.sugestao import (
    SugestaoDeElemento,
    SugestaoDeFrame,
    sugestoes_participante,
)

__all__ = [
    "Capitulo",
    "Configuracao",
    "Elemento",
    "EstadoElemento",
    "Frame",
    "Imagem",
    "Livro",
    "PerfilRenderizacao",
    "PrioridadeIA",
    "Prompt",
    "SugestaoDeElemento",
    "SugestaoDeFrame",
    "TipoDeFrame",
    "TipoElemento",
    "frames_estados_elemento",
    "sugestoes_participante",
]
