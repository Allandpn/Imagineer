"""Quanto custa ler um capítulo, pela tabela de preços do catálogo (item 4.10, LM14 e LM15).

Ler um capítulo é uma **rajada de leituras** do mesmo texto (uma por elemento e uma por cena). Sem cache, cada uma paga o capítulo inteiro; com o
capítulo no prefixo do pedido (E3), a primeira o **escreve** no cache e as outras o **leem** a uma fração do preço. Este módulo faz essa conta com
os preços do catálogo **ao vivo** — nunca com uma tabela fixa, porque os preços mudam toda semana.

É uma **estimativa** (pode variar até 50%): a contagem de tokens é aproximada e o cache pode não acertar (capítulo curto, rajada lenta). O custo
real aparece em "Custos", pelo consumo que o OpenRouter informa.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from imagineer.ia.catalogo_de_texto import Capacidades
from imagineer.ia.openrouter import estimar_tokens

TOKENS_DO_CAPITULO_TIPICO = 12000
"""Um capítulo típico dos livros de validação. Os maiores têm ~28 mil tokens."""

LEITURAS_DO_CAPITULO_TIPICO = 9
"""Seis elementos e três cenas, na conta da tabela do item 4.10."""

SAIDA_POR_LEITURA_TIPICA = 1200
"""Tokens que cada leitura devolve, na conta da tabela do item 4.10."""

AVISO_DA_ESTIMATIVA = "Estimativa (pode variar até 50%); o custo real aparece em Custos."

AVISO_SEM_PRECO = (
    "O catálogo do OpenRouter não informa o preço deste modelo agora (ou o modelo saiu do catálogo): não há como estimar o custo. "
    "O custo real aparece em Custos."
)

SAIDA_DO_ESTADO = 700
SAIDA_DA_IDENTIDADE = 150
SAIDA_DO_DOSSIE = 900
SAIDA_DA_EXTRACAO = 2500
"""Tokens que cada tipo de leitura costuma devolver (LM15). Constantes, e não medição: a estimativa é grosseira de propósito."""


def custo_das_leituras(
    capacidades: Capacidades, tokens_do_capitulo: int, saidas: Sequence[int]
) -> tuple[Decimal | None, Decimal | None]:
    """O custo (em US$) de ler o capítulo ``len(saidas)`` vezes: ``(sem cache, com cache)``.

    ``saidas`` traz os tokens que **cada** leitura devolve. Sem cache, toda leitura paga o capítulo à tarifa de entrada. Com cache, a
    **primeira** paga a tarifa de *escrita* do cache e as demais a de *leitura*; o que o catálogo não informa cai na tarifa de entrada
    (nunca um desconto inventado). ``(None, None)`` se o modelo não tem preço de entrada ou de saída no catálogo: não se estima o que não
    se sabe. Sem leituras, o custo é zero.
    """
    entrada, saida = capacidades.preco_entrada, capacidades.preco_saida
    if entrada is None or saida is None:
        return None, None
    if not saidas:
        return Decimal(0), Decimal(0)

    escrita = capacidades.preco_cache_escrita if capacidades.preco_cache_escrita is not None else entrada
    leitura = capacidades.preco_cache_leitura if capacidades.preco_cache_leitura is not None else entrada

    sem_cache = Decimal(0)
    com_cache = Decimal(0)
    for posicao, tokens_de_saida in enumerate(saidas):
        custo_da_saida = saida * tokens_de_saida
        sem_cache += entrada * tokens_do_capitulo + custo_da_saida
        tarifa_do_capitulo = escrita if posicao == 0 else leitura
        com_cache += tarifa_do_capitulo * tokens_do_capitulo + custo_da_saida
    return sem_cache, com_cache


def custo_do_capitulo_tipico(capacidades: Capacidades) -> tuple[Decimal | None, Decimal | None]:
    """``custo_das_leituras`` para o capítulo típico: 12 mil tokens, 9 leituras de 1.200 tokens de saída. Para comparar modelos lado a lado."""
    return custo_das_leituras(
        capacidades, TOKENS_DO_CAPITULO_TIPICO, [SAIDA_POR_LEITURA_TIPICA] * LEITURAS_DO_CAPITULO_TIPICO
    )


@dataclass(frozen=True)
class EstimativaDeLeitura:
    """Quanto custa ler um capítulo, em US$. Os custos são ``None`` quando o catálogo não tem o preço do modelo."""

    tokens_do_capitulo: int
    leituras: int
    """Quantas chamadas à IA a leitura faz: uma de estado e uma de identidade por elemento, uma de dossiê por cena (e a extração, se ainda não foi feita)."""
    custo_sem_cache: Decimal | None
    custo_com_cache: Decimal | None
    aviso: str


def estimar_leitura(
    texto_do_capitulo: str,
    capacidades: Capacidades | None,
    elementos: int,
    cenas: int,
    *,
    com_extracao: bool = False,
    capacidades_da_extracao: Capacidades | None = None,
) -> EstimativaDeLeitura:
    """Estima o custo de ler o capítulo ``elementos`` + ``cenas`` vezes, com os preços de ``capacidades`` (o modelo de **leitura**).

    - ``leituras`` = ``elementos`` x (estado + identidade) + ``cenas`` x dossiê, e mais **uma** de extração se ``com_extracao`` (a análise do
      capítulo ainda não foi feita).
    - A **extração é uma chamada só**, de outro modelo (``capacidades_da_extracao``; sem ele, o mesmo da leitura), e não tem com quem dividir
      o cache: entra nos dois custos pelo preço **sem** cache. Dar a ela a tarifa de *escrita* do cache, que costuma custar mais que a
      entrada comum, a encareceria sem que ninguém a lesse de novo.
    - **Nunca chama a IA**: é só a conta sobre o texto e o catálogo.
    """
    tokens = estimar_tokens(texto_do_capitulo)
    saidas = [SAIDA_DO_ESTADO, SAIDA_DA_IDENTIDADE] * elementos + [SAIDA_DO_DOSSIE] * cenas
    leituras = len(saidas) + (1 if com_extracao else 0)

    if capacidades is None:
        return EstimativaDeLeitura(tokens, leituras, None, None, AVISO_SEM_PRECO)

    sem_cache, com_cache = custo_das_leituras(capacidades, tokens, saidas)
    if com_extracao and sem_cache is not None:
        da_extracao, _ = custo_das_leituras(capacidades_da_extracao or capacidades, tokens, [SAIDA_DA_EXTRACAO])
        if da_extracao is None:
            sem_cache = com_cache = None
        else:
            sem_cache += da_extracao
            com_cache += da_extracao

    aviso = AVISO_DA_ESTIMATIVA if sem_cache is not None else AVISO_SEM_PRECO
    return EstimativaDeLeitura(tokens, leituras, sem_cache, com_cache, aviso)
