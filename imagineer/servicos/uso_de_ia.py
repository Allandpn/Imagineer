"""Grava o consumo de cada chamada à IA (item 4.3, "Custo das chamadas de IA").

O provedor avisa; este módulo grava. **Em sessão própria, com commit imediato**: a rota que chamou a
IA pode falhar depois (e desfazer a transação dela), mas a chamada já foi cobrada — o registro tem que
refletir o que foi gasto, não o que a rota conseguiu concluir.
"""

import logging

from sqlalchemy.orm import sessionmaker

from imagineer.banco.sessao import CriadorDeSessao
from imagineer.ia.provedor import UsoDaChamada
from imagineer.modelos import UsoDeIA


def gravar_uso(uso: UsoDaChamada, criador: sessionmaker = CriadorDeSessao) -> None:
    """Grava uma linha em ``usos_ia`` numa sessão própria.

    Args:
        uso: o que a chamada consumiu.
        criador: de onde sai a sessão; os testes passam um ligado ao banco de teste.
    """
    with criador() as sessao:
        sessao.add(
            UsoDeIA(
                operacao=uso.operacao,
                modelo=uso.modelo,
                tokens_entrada=uso.tokens_entrada,
                tokens_saida=uso.tokens_saida,
                custo=uso.custo,
                id_da_geracao=uso.id_da_geracao,
            )
        )
        sessao.commit()
    logging.getLogger(__name__).info(
        "IA: %s com %s, %s tokens de entrada, %s de saída, custo %s",
        uso.operacao, uso.modelo, uso.tokens_entrada, uso.tokens_saida, uso.custo,
    )
