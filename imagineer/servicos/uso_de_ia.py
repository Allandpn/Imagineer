"""Grava o consumo de cada chamada à IA (item 4.3, "Custo das chamadas de IA").

O provedor avisa; este módulo grava. **Em sessão própria, com commit imediato**: a rota que chamou a
IA pode falhar depois (e desfazer a transação dela), mas a chamada já foi cobrada — o registro tem que
refletir o que foi gasto, não o que a rota conseguiu concluir.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.orm import sessionmaker

from imagineer.banco.sessao import CriadorDeSessao
from imagineer.ia.provedor import UsoDaChamada
from imagineer.modelos import UsoDeIA
from imagineer.servicos.precos_de_imagem import preco_estimado_da_imagem

_livro_do_gasto: ContextVar[int | None] = ContextVar("livro_do_gasto", default=None)
"""De que livro é o gasto que está sendo feito **agora** (CU3). Quem chama a IA de dentro de um livro o informa com
``gasto_do_livro``; ``gravar_uso`` lê aqui, porque o provedor não conhece livros."""


_coletor_de_custo: ContextVar[list | None] = ContextVar("coletor_de_custo", default=None)


@contextmanager
def coletando_o_custo() -> Iterator[list]:
    """Durante o bloco, o custo de cada chamada à IA anotada também vai para a lista devolvida (PT6): serve para uma rota dizer à
    pessoa quanto a chamada que ela acabou de pedir custou. Cada item é o custo (``Decimal``) ou ``None`` (sem custo informado)."""
    custos: list = []
    marca = _coletor_de_custo.set(custos)
    try:
        yield custos
    finally:
        _coletor_de_custo.reset(marca)


@contextmanager
def gasto_do_livro(livro_id: int | None) -> Iterator[None]:
    """Durante o bloco, as chamadas à IA são anotadas como gasto do livro ``livro_id`` (CU3)."""
    marca = _livro_do_gasto.set(livro_id)
    try:
        yield
    finally:
        _livro_do_gasto.reset(marca)


def gravar_uso(uso: UsoDaChamada, criador: sessionmaker = CriadorDeSessao) -> None:
    """Grava uma linha em ``usos_ia`` numa sessão própria.

    Args:
        uso: o que a chamada consumiu.
        criador: de onde sai a sessão; os testes passam um ligado ao banco de teste.
    """
    # CU2: o fornecedor não informou o custo de uma imagem: estima pelo preço da tabela (marcado como estimado).
    custo, estimado = uso.custo, False
    if custo is None and uso.operacao == "imagem":
        custo = preco_estimado_da_imagem(uso.modelo)
        estimado = custo is not None
    coletor = _coletor_de_custo.get()
    if coletor is not None:
        coletor.append(custo)
    with criador() as sessao:
        sessao.add(
            UsoDeIA(
                operacao=uso.operacao,
                modelo=uso.modelo,
                tokens_entrada=uso.tokens_entrada,
                tokens_saida=uso.tokens_saida,
                custo=custo,
                id_da_geracao=uso.id_da_geracao,
                provedor=uso.provedor,
                livro_id=_livro_do_gasto.get(),
                estimado=estimado,
            )
        )
        sessao.commit()
    logging.getLogger(__name__).info(
        "IA: %s com %s (%s), %s tokens de entrada, %s de saída, custo %s%s",
        uso.operacao, uso.modelo, uso.provedor, uso.tokens_entrada, uso.tokens_saida, custo, " (estimado)" if estimado else "",
    )
