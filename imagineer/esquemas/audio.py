"""Contratos das rotas da narração por voz de IA (itens NA3 a NA5)."""

import enum
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SituacaoDaNarracao(enum.Enum):
    """A situação da narração de um capítulo **com o modelo e a voz de agora** (NA5)."""

    NAO_GERADO = "NAO_GERADO"
    GERANDO = "GERANDO"
    PRONTO = "PRONTO"
    FALHOU = "FALHOU"


class EstimativaDaNarracao(BaseModel):
    """Quanto vai custar narrar o capítulo, **antes** de gerar (NA3)."""

    caracteres: int = Field(description="Quantos caracteres o capítulo tem.")
    minutos: float = Field(description="A duração estimada da fala (900 caracteres por minuto).")
    custo_estimado: Decimal | None = Field(
        description="O custo estimado em **dólares**: caracteres × o preço por caractere do catálogo do OpenRouter. "
        "Nulo = não dá para estimar (o modelo cobra por token ou por segundo, ou o catálogo não respondeu)."
    )
    modelo: str = Field(description="O modelo de voz que seria usado (`configuracao.modelo_narracao`).")
    voz: str | None = Field(description="A voz de agora (`configuracao.narracao_voz`); nula = a padrão do modelo.")
    ja_gerado: bool = Field(description="`true`: já existe um áudio `PRONTO` com o modelo e a voz de agora — gerar de novo é opcional (`refazer`).")


class ModeloDeNarracao(BaseModel):
    """Um modelo de voz que a pessoa pode escolher em Configurações → Narração (NA1)."""

    id: str = Field(description="O id do OpenRouter, como `microsoft/mai-voice-2.1-flash`; é o que se grava em `modelo_narracao`.")
    nome: str
    vozes: list[str] = Field(description="As vozes que o modelo aceita (o que se grava em `narracao_voz`). Vazia = o modelo não lista vozes.")
    preco_por_caractere: Decimal | None = Field(description="Dólares por caractere; zero = gratuito; nulo = o modelo cobra por token ou por segundo (sem estimativa).")
    gratuito: bool


class PedidoDeNarracao(BaseModel):
    """O corpo de `POST /capitulos/{id}/audio`. O modelo e a voz vêm da configuração, não daqui (NA5)."""

    refazer: bool = Field(default=False, description="`true`: gera de novo mesmo que já exista um áudio `PRONTO` (gasta de novo).")


class EstadoDaNarracao(BaseModel):
    """A situação do áudio de um capítulo (NA5)."""

    model_config = ConfigDict(from_attributes=True)

    situacao: SituacaoDaNarracao
    audio_id: int | None = Field(default=None, description="O id do áudio; nulo se `NAO_GERADO`.")
    modelo: str | None = None
    voz: str | None = Field(default=None, description="A voz usada; nula = a padrão do modelo.")
    caracteres: int | None = None
    tamanho_em_bytes: int | None = None
    custo: Decimal | None = Field(default=None, description="O custo **estimado** em dólares dos trechos já feitos.")
    erro: str | None = Field(default=None, description="Por que falhou, em português (só se `FALHOU`).")
    criado_em: datetime | None = None
