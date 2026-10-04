"""iluminacao dos perfis de fabrica so como convencao

Reescreve os textos dos 10 perfis de fabrica (FD4): o campo `iluminacao` passa a descrever so a convencao de renderizacao da luz
(contraste, dureza da sombra, volume), nunca a fonte (vela, luar, meio-dia), que vem da cena. Chama de novo a semeadura idempotente
(PF6): os perfis de fabrica sao travados, entao reescrever o texto deles nao apaga nada de ninguem. Perfis proprios nao sao tocados.

Identificador desta migration: f6a7b8c9d0e1
Vem depois de: e5f6a7b8c9d0
Criada em: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Reescreve os textos dos perfis de fabrica com os de hoje."""
    # Importado aqui dentro: a migracao so precisa da funcao no momento de rodar.
    from imagineer.servicos.perfis_de_fabrica import garantir_perfis_de_fabrica

    garantir_perfis_de_fabrica(op.get_bind())


def reverter() -> None:
    """Nao ha o que desfazer: o texto anterior nao e guardado, e a semeadura sempre escreve o de hoje."""


upgrade = aplicar
downgrade = reverter
