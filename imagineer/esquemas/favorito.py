"""Contratos das rotas de favoritos (RL31 a RL38)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from imagineer.modelos.favorito import TipoDeFavorito


class FavoritoNovo(BaseModel):
    """O que o app manda para favoritar. O **alvo** depende do tipo: `LIVRO` não tem alvo (é o próprio livro); `PARAGRAFO` pede `capitulo_id` e
    `posicao`; `ELEMENTO` pede `elemento_id`; `CENA`, `frame_id`; `IMAGEM`, `imagem_id`."""

    model_config = ConfigDict(extra="forbid")

    tipo: TipoDeFavorito
    capitulo_id: int | None = None
    posicao: int | None = Field(
        default=None,
        ge=0,
        description="Só no parágrafo: onde ele **começa**, em UTF-16 desde o início do texto do capítulo (item 3.4g).",
    )
    elemento_id: int | None = None
    frame_id: int | None = None
    imagem_id: int | None = None


class FavoritoResposta(BaseModel):
    """Um favorito, já com o texto que a lista mostra e o necessário para levar ao lugar."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    livro_id: int
    tipo: TipoDeFavorito
    rotulo: str = Field(description="O que a lista mostra: o título do livro, o começo do parágrafo, o nome do elemento, o título da cena ou da imagem.")
    capitulo_id: int | None = None
    ordem_do_capitulo: int | None = None
    titulo_do_capitulo: str | None = None
    posicao: int | None = None
    elemento_id: int | None = None
    frame_id: int | None = None
    imagem_id: int | None = None
    criado_em: datetime
