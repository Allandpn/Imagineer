"""Contrato dos custos de IA (item 7.5b, CU4): quanto se gastou, e onde. Tudo em **dólares**."""

from decimal import Decimal

from pydantic import BaseModel, Field


class GastoAgrupado(BaseModel):
    """O gasto de um grupo (um provedor, uma operação, um livro ou um modelo)."""

    nome: str = Field(description="Quem é o grupo: `openrouter`, `imagem`, o título do livro, o id do modelo...")
    livro_id: int | None = Field(default=None, description="Só na quebra por livro; nulo = \"sem livro\".")
    total: Decimal = Field(description="O que se gastou, em dólares (só as chamadas com custo conhecido).")
    chamadas: int
    sem_custo: int = Field(description="Quantas chamadas do grupo ficaram sem custo (o fornecedor não informou e a tabela não tem o modelo).")


class CustosDoMes(BaseModel):
    mes: str = Field(description="`AAAA-MM`.")
    total: Decimal
    estimado: Decimal = Field(description="Quanto do `total` veio da tabela de preços (fal.ai, Replicate), e não do fornecedor.")
    chamadas: int
    sem_custo: int
    por_provedor: list[GastoAgrupado]
    por_operacao: list[GastoAgrupado]
    por_livro: list[GastoAgrupado]
    por_modelo: list[GastoAgrupado]
    meses_com_gasto: list[str] = Field(description="Os meses que têm alguma chamada registrada, do mais novo ao mais antigo.")
