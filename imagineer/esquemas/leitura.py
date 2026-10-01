"""Contratos do marcador e dos pins (item 6.10)."""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

LIMITE_DA_NOTA = 1000


class MarcadorGravacao(BaseModel):
    """O que ``PUT /livros/{id}/marcador`` recebe."""

    capitulo_id: int
    posicao_no_texto: int = Field(
        ge=0, description="Deslocamento em UTF-16 desde o início do texto do capítulo (item 3.4g)."
    )
    lido_em: AwareDatetime = Field(
        description=(
            "Quando a pessoa chegou ali, segundo o aparelho (com fuso). É o que decide qual marcador "
            "vale entre dois aparelhos; um valor no futuro é limitado ao relógio do servidor."
        )
    )


class MarcadorResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    livro_id: int
    capitulo_id: int
    posicao_no_texto: int
    lido_em: datetime


class MarcadorDoLivro(BaseModel):
    """O que ``GET /livros/{id}/marcador`` devolve: ``marcador`` nulo = ainda não leu nada."""

    marcador: MarcadorResposta | None


class MarcadorGravado(BaseModel):
    """O que ``PUT /livros/{id}/marcador`` devolve: o marcador que **ficou valendo**."""

    marcador: MarcadorResposta
    aceito: bool = Field(
        description=(
            "False quando já havia um marcador mais recente (outro aparelho leu depois): nada foi "
            "gravado e `marcador` é o que continua valendo."
        )
    )


def _nota_limpa(nota: str | None) -> str | None:
    """Tira os espaços das pontas; texto em branco vira nulo (um pin sem nota)."""
    if nota is None:
        return None
    nota = nota.strip()
    return nota or None


class PinNovo(BaseModel):
    """O que ``POST /livros/{id}/pins`` recebe."""

    capitulo_id: int
    posicao_no_texto: int = Field(ge=0, description="UTF-16, como no marcador.")
    nota: str | None = Field(default=None, max_length=LIMITE_DA_NOTA)

    _limpar_nota = field_validator("nota")(_nota_limpa)


class PinAjuste(BaseModel):
    """O que ``PATCH /pins/{id}`` recebe: a nova nota (``null`` apaga a nota)."""

    nota: str | None = Field(max_length=LIMITE_DA_NOTA)

    _limpar_nota = field_validator("nota")(_nota_limpa)


class PinResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    livro_id: int
    capitulo_id: int
    posicao_no_texto: int
    nota: str | None
    criado_em: datetime
