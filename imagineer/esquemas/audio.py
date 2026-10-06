"""Contratos das rotas da narração por voz de IA (itens NA3 a NA5)."""

import enum
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SituacaoDaNarracao(enum.Enum):
    """A situação da narração de um capítulo **com a voz e as instruções de agora** (NA5)."""

    NAO_GERADO = "NAO_GERADO"
    GERANDO = "GERANDO"
    PRONTO = "PRONTO"
    FALHOU = "FALHOU"


class EstimativaDaNarracao(BaseModel):
    """Quanto vai custar narrar o capítulo, **antes** de gerar (NA3)."""

    caracteres: int = Field(description="Quantos caracteres o capítulo tem.")
    minutos: float = Field(description="A duração estimada da fala (900 caracteres por minuto).")
    custo_estimado: Decimal = Field(description="O custo estimado em **dólares**. Estimado: a OpenAI não informa o custo (NA3).")
    modelo: str = Field(description="O modelo de voz que seria usado.")
    voz: str | None = Field(description="A voz de agora (`configuracao.narracao_voz`); nula = a padrão do fornecedor.")
    ja_gerado: bool = Field(description="`true`: já existe um áudio `PRONTO` com a voz e as instruções de agora — gerar de novo é opcional (`refazer`).")


class PedidoDeNarracao(BaseModel):
    """O corpo de `POST /capitulos/{id}/audio`. A voz e as instruções vêm da configuração, não daqui (NA5)."""

    refazer: bool = Field(default=False, description="`true`: gera de novo mesmo que já exista um áudio `PRONTO` (gasta de novo).")


class EstadoDaNarracao(BaseModel):
    """A situação do áudio de um capítulo (NA5)."""

    model_config = ConfigDict(from_attributes=True)

    situacao: SituacaoDaNarracao
    audio_id: int | None = Field(default=None, description="O id do áudio; nulo se `NAO_GERADO`.")
    modelo: str | None = None
    voz: str | None = Field(default=None, description="A voz usada; nula = a padrão do fornecedor.")
    caracteres: int | None = None
    tamanho_em_bytes: int | None = None
    custo: Decimal | None = Field(default=None, description="O custo **estimado** em dólares dos trechos já feitos.")
    erro: str | None = Field(default=None, description="Por que falhou, em português (só se `FALHOU`).")
    criado_em: datetime | None = None
