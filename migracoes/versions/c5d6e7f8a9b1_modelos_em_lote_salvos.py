"""troca os modelos ':batch' ja salvos pelo mesmo modelo sem o sufixo (achado de 15/10/2026)

A variante ':batch' do OpenRouter e do processamento em lote e a conversa a recusa (404 em ingles). O servidor passou a recusa-la ao gravar, mas quem a
escolheu antes continua com o id salvo na configuracao, na troca de um livro ou na lista de modelos de imagem. Esta migracao troca cada um pelo mesmo
modelo sem o sufixo (que custa cerca do dobro). Ids assim nunca funcionaram: nada que valesse e desfeito. O historico (usos, prompts, imagens) nao e tocado.

Identificador desta migration: c5d6e7f8a9b1
Vem depois de: b4c5d6e7f8a0
Criada em: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op

from imagineer.servicos.correcao_de_modelos_em_lote import corrigir_modelos_em_lote


revision: str = 'c5d6e7f8a9b1'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Troca os ids ':batch' salvos (idempotente)."""
    corrigir_modelos_em_lote(op.get_bind())


def reverter() -> None:
    """Nada a desfazer: o sufixo ':batch' nunca funcionou na conversa, e voltar a grava-lo so recriaria o erro."""


upgrade = aplicar
downgrade = reverter
