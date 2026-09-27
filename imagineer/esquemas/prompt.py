"""Contratos das rotas de prompts e catálogo de imagens (Etapa 6.6)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ImagemResumo(BaseModel):
    """Uma imagem do catálogo, como a API a devolve.

    Não expõe ``caminho_arquivo``: o app busca os bytes por
    ``GET /imagens/{id}/arquivo``, e o layout do disco não é assunto dele.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    prompt_id: int
    data_importacao: datetime


class PromptResumo(BaseModel):
    """Um prompt na listagem de uma cena."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    cena_id: int
    perfil_renderizacao_id: int | None
    modelo_ia: str | None
    texto: str
    avaliacao: str | None
    data_criacao: datetime
    total_de_imagens: int = 0


class PromptDetalhe(PromptResumo):
    """O prompt com as imagens que saíram dele."""

    imagens: list[ImagemResumo]


class PromptNovo(BaseModel):
    """O que o app manda para montar um prompt a partir de uma cena (passo 8).

    Os dois campos são opcionais: na ausência de ``perfil_renderizacao_id``, vale
    o perfil padrão do livro; na ausência de ``modelo``, vale o ``modelo_prompt``
    da configuração (item 6.6).
    """

    perfil_renderizacao_id: int | None = None
    modelo: str | None = Field(default=None, max_length=200)


class PromptAjuste(BaseModel):
    """O que o app manda para anotar como a imagem ficou."""

    avaliacao: str = Field(min_length=1)
