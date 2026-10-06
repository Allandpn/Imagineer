"""Modelos SQLAlchemy — as tabelas do banco (Etapa 3 da especificação).

Importar os modelos aqui tem um efeito prático: basta ``import imagineer.modelos``
para que todas as tabelas fiquem registradas na ``Base.metadata``. É disso que
o Alembic depende para gerar migrations sozinho, e os testes para criar o banco.

Sem estes imports, um modelo em arquivo próprio seria invisível — existiria no
disco, mas nunca no mapa de tabelas.
"""

from imagineer.modelos.capitulo import Capitulo
from imagineer.modelos.configuracao import CategoriaEstilo, Configuracao, ModoDeNarracao, MotorDeNarracao, PrioridadeIA
from imagineer.modelos.elemento import (
    Elemento,
    EstadoElemento,
    HistoricoIdentidadeElemento,
    TipoElemento,
)
from imagineer.modelos.favorito import Favorito, TipoDeFavorito
from imagineer.modelos.frame import Frame, TipoDeFrame, frames_estados_elemento, frames_estados_vinculados
from imagineer.modelos.leitura import Destaque, Marcador, Pin, TempoDeLeitura
from imagineer.modelos.livro import Livro
from imagineer.modelos.perfil_renderizacao import PerfilRenderizacao
from imagineer.modelos.prompt import Imagem, OrigemDaImagem, Prompt, SituacaoDaGeracao, TipoDePrompt
from imagineer.modelos.sugestao import (
    SugestaoDeCena,
    SugestaoDeElemento,
    sugestoes_participante,
)
from imagineer.modelos.uso_ia import UsoDeIA
from imagineer.modelos.audio_de_capitulo import AudioDeCapitulo, SituacaoDoAudio
from imagineer.modelos.video import Video

__all__ = [
    "Capitulo",
    "CategoriaEstilo",
    "Configuracao",
    "Destaque",
    "Elemento",
    "EstadoElemento",
    "Frame",
    "HistoricoIdentidadeElemento",
    "Imagem",
    "Livro",
    "Marcador",
    "PerfilRenderizacao",
    "Pin",
    "ModoDeNarracao",
    "MotorDeNarracao",
    "PrioridadeIA",
    "OrigemDaImagem",
    "Favorito",
    "Prompt",
    "TipoDeFavorito",
    "TipoDePrompt",
    "SituacaoDaGeracao",
    "SugestaoDeCena",
    "SugestaoDeElemento",
    "TempoDeLeitura",
    "TipoDeFrame",
    "TipoElemento",
    "UsoDeIA",
    "AudioDeCapitulo",
    "SituacaoDoAudio",
    "Video",
    "frames_estados_elemento",
    "frames_estados_vinculados",
    "sugestoes_participante",
]
