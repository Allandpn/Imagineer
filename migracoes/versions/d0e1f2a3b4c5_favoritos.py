"""favoritos

Tabela nova (RL31 a RL38): os itens que a pessoa favoritou num livro (o proprio livro, um paragrafo, um elemento, uma cena ou uma
imagem). Um por alvo; apagar de vez o alvo apaga o favorito (ON DELETE CASCADE).

Identificador desta migration: d0e1f2a3b4c5
Vem depois de: c9d0e1f2a3b4
Criada em: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria a tabela e os indices das chaves."""
    op.create_table(
        "favoritos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("livro_id", sa.Integer(), sa.ForeignKey("livros.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tipo", sa.String(length=12), nullable=False),
        sa.Column("capitulo_id", sa.Integer(), sa.ForeignKey("capitulos.id", ondelete="CASCADE"), nullable=True),
        sa.Column("posicao", sa.Integer(), nullable=True),
        sa.Column("trecho", sa.Text(), nullable=True),
        sa.Column("elemento_id", sa.Integer(), sa.ForeignKey("elementos.id", ondelete="CASCADE"), nullable=True),
        sa.Column("frame_id", sa.Integer(), sa.ForeignKey("frames.id", ondelete="CASCADE"), nullable=True),
        sa.Column("imagem_id", sa.Integer(), sa.ForeignKey("imagens.id", ondelete="CASCADE"), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for coluna in ("livro_id", "capitulo_id", "elemento_id", "frame_id", "imagem_id"):
        op.create_index(f"ix_favoritos_{coluna}", "favoritos", [coluna])


def reverter() -> None:
    """Apaga a tabela; os favoritos se perdem."""
    op.drop_table("favoritos")


upgrade = aplicar
downgrade = reverter
