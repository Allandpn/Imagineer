"""Contratos das rotas de elementos e estados (Etapa 6.3)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from imagineer.modelos import TipoElemento


class EstadoResumo(BaseModel):
    """Um estado de elemento como a API o devolve."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    elemento_id: int
    capitulo_id: int
    descricao: str
    imagem_ancora_id: int | None
    data_criacao: datetime


class EstadoNovo(BaseModel):
    """O que o app manda para registrar um estado.

    O capítulo é obrigatório porque todo estado nasce de um ponto da narrativa
    (item 3.4b) — é ele que define quando o estado passa a valer.
    """

    capitulo_id: int
    descricao: str = Field(min_length=1)


class EstadoAjuste(BaseModel):
    """Os campos ajustáveis de um estado. Só o que vem é aplicado."""

    descricao: str | None = Field(default=None, min_length=1)
    imagem_ancora_id: int | None = None


class ElementoResumo(BaseModel):
    """Um elemento na listagem, com o estado que vigora no ponto consultado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    livro_id: int
    tipo: TipoElemento
    nome: str
    descricao: str | None
    total_de_estados: int
    estado_vigente: EstadoResumo | None = Field(
        default=None,
        description=(
            "O estado em vigor no ponto consultado, ou nulo se o elemento ainda "
            "não tinha aparecido — o que significa primeira aparição."
        ),
    )


class ElementoDetalhe(BaseModel):
    """O elemento com todos os seus estados, em ordem narrativa."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    livro_id: int
    tipo: TipoElemento
    nome: str
    descricao: str | None
    estados: list[EstadoResumo]


class ElementoNovo(BaseModel):
    """O que o app manda para cadastrar um elemento confirmado pelo usuário.

    O ``estado_inicial`` é opcional mas esperado no caminho normal: no passo 7 do
    fluxo, o usuário confirma que o personagem existe **e** como ele está naquele
    capítulo. Em dois pedidos separados, uma falha no meio deixaria um elemento
    sem estado nenhum.
    """

    tipo: TipoElemento
    nome: str = Field(min_length=1, max_length=200)
    descricao: str | None = None
    estado_inicial: EstadoNovo | None = None


class ElementoAjuste(BaseModel):
    """Os campos ajustáveis de um elemento. Só o que vem é aplicado."""

    tipo: TipoElemento | None = None
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    descricao: str | None = None


class ElementoSugerido(BaseModel):
    """Um elemento sugerido pela IA (passo 6, item 4.4).

    Não é gravado no banco por esta rota — o app mostra a sugestão e o usuário
    confirma pelas rotas de cadastro já existentes (`POST /elementos`,
    `POST /elementos/{id}/estados`).
    """

    tipo: TipoElemento
    nome: str
    descricao: str | None
    estado_sugerido: str | None = Field(
        description="Como o elemento parece estar neste capítulo, segundo a IA."
    )
    manter_estado_atual: bool = Field(
        description="A IA acha que o estado conhecido continua valendo (item 4.4)."
    )
    elemento_id: int | None = Field(
        default=None,
        description=(
            "O elemento já cadastrado a que esta sugestão corresponde, se algum "
            "bateu por tipo e nome. Nulo significa elemento novo."
        ),
    )


class SugestoesDeCapitulo(BaseModel):
    """O que `POST /capitulos/{id}/sugestoes` devolve."""

    modelo: str
    elementos: list[ElementoSugerido]
