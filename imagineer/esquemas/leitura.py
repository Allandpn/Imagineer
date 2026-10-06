"""Contratos do marcador e dos pins (item 6.10)."""

from datetime import date, datetime
from typing import Literal

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
    trecho: str = Field(default="", description="O começo do parágrafo que começa na posição (até 300 caracteres, em um espaço só), para a lista (PN3).")
    ordem_do_capitulo: int | None = None
    titulo_do_capitulo: str | None = None


CORES_DE_DESTAQUE = ("AMARELO", "VERDE", "AZUL", "ROSA")
LIMITE_DO_DESTAQUE = 5000
"""O maior trecho que se destaca, em unidades UTF-16."""


class DestaqueNovo(BaseModel):
    """O que ``POST /livros/{id}/destaques`` recebe. O trecho em si **não** vem: o servidor o copia do capítulo."""

    capitulo_id: int
    inicio: int = Field(ge=0, description="UTF-16 desde o início do texto do capítulo.")
    fim: int = Field(gt=0, description="UTF-16, exclusivo; maior que `inicio`.")
    cor: Literal["AMARELO", "VERDE", "AZUL", "ROSA"] = "AMARELO"
    nota: str | None = Field(default=None, max_length=LIMITE_DA_NOTA)
    elemento_id: int | None = None

    _limpar_nota = field_validator("nota")(_nota_limpa)


class DestaqueAjuste(BaseModel):
    """O que ``PATCH /destaques/{id}`` recebe: **só os campos enviados mudam** (`nota` ou `elemento_id` nulos desfazem)."""

    cor: Literal["AMARELO", "VERDE", "AZUL", "ROSA"] | None = None
    nota: str | None = Field(default=None, max_length=LIMITE_DA_NOTA)
    elemento_id: int | None = None

    _limpar_nota = field_validator("nota")(_nota_limpa)


class DestaqueResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    livro_id: int
    capitulo_id: int
    inicio: int
    fim: int
    trecho: str
    cor: str
    nota: str | None
    elemento_id: int | None
    criado_em: datetime


LIMITE_DE_SEGUNDOS_POR_ENVIO = 3600


class TempoDeLeituraNovo(BaseModel):
    """O que ``POST /livros/{id}/leitura/tempo`` recebe: segundos a **somar** ao dia."""

    dia: date = Field(description="O dia segundo o aparelho (AAAA-MM-DD).")
    segundos: int = Field(gt=0, le=LIMITE_DE_SEGUNDOS_POR_ENVIO)


class TempoDeLeituraResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    livro_id: int
    dia: date
    segundos: int


class TempoDoDia(BaseModel):
    dia: date
    segundos: int


class TempoDoLivro(BaseModel):
    livro_id: int
    titulo: str
    segundos: int
    dias_lidos: int
    ultimo_dia: date


class EstatisticasDeLeitura(BaseModel):
    """O que ``GET /estatisticas/leitura`` devolve: o tempo dos últimos 90 dias e o resumo de cada livro."""

    dias: list[TempoDoDia]
    livros: list[TempoDoLivro]
