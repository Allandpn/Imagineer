"""Contrato da pesquisa no texto (item 7.5b, LV5)."""

from pydantic import BaseModel, Field


class OcorrenciaNoTexto(BaseModel):
    """Um lugar onde o termo aparece, com o capítulo e o livro em que está."""

    livro_id: int
    livro_titulo: str
    capitulo_id: int
    capitulo_ordem: int
    capitulo_titulo: str | None
    posicao_no_texto: int = Field(description="Onde o achado começa, em UTF-16 desde o início do capítulo (item 3.4g).")
    inicio_do_paragrafo: int = Field(description="Onde começa o parágrafo do achado (UTF-16): para onde o app rola.")
    trecho: str = Field(description="O texto em volta do achado, numa linha só.")
    inicio_no_trecho: int = Field(description="Onde o achado começa dentro do trecho (UTF-16).")
    fim_no_trecho: int = Field(description="Onde o achado termina dentro do trecho (UTF-16).")


class ResultadoDaBusca(BaseModel):
    termo: str
    total: int = Field(description="Quantas ocorrências existem no escopo pedido (mesmo as que não vieram na lista).")
    ocorrencias: list[OcorrenciaNoTexto]
    truncado: bool = Field(description="`true` quando há mais ocorrências do que o `limite` pedido.")
