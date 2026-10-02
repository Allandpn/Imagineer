"""Modelos SQLAlchemy — as tabelas do banco (Etapa 3 da especificação).

Importar os modelos aqui tem um efeito prático: basta ``import imagineer.modelos``
para que todas as tabelas fiquem registradas na ``Base.metadata``. É disso que
o Alembic depende para gerar migrations sozinho, e os testes para criar o banco.

Sem estes imports, um modelo em arquivo próprio seria invisível — existiria no
disco, mas nunca no mapa de tabelas.
"""

from imagineer.modelos.capitulo import Capitulo
from imagineer.modelos.configuracao import CategoriaEstilo, Configuracao, PrioridadeIA
from imagineer.modelos.elemento import (
    Elemento,
    EstadoElemento,
    HistoricoIdentidadeElemento,
    TipoElemento,
)
from imagineer.modelos.frame import Frame, TipoDeFrame, frames_estados_elemento
from imagineer.modelos.leitura import Marcador, Pin
from imagineer.modelos.livro import Livro
from imagineer.modelos.perfil_renderizacao import PerfilRenderizacao
from imagineer.modelos.prompt import Imagem, Prompt, SituacaoDaGeracao
from imagineer.modelos.sugestao import (
    SugestaoDeCena,
    SugestaoDeElemento,
    sugestoes_participante,
)
from imagineer.modelos.uso_ia import UsoDeIA

__all__ = [
    "Capitulo",
    "CategoriaEstilo",
    "Configuracao",
    "Elemento",
    "EstadoElemento",
    "Frame",
    "HistoricoIdentidadeElemento",
    "Imagem",
    "Livro",
    "Marcador",
    "PerfilRenderizacao",
    "Pin",
    "PrioridadeIA",
    "Prompt",
    "SituacaoDaGeracao",
    "SugestaoDeCena",
    "SugestaoDeElemento",
    "TipoDeFrame",
    "TipoElemento",
    "UsoDeIA",
    "frames_estados_elemento",
    "sugestoes_participante",
]
