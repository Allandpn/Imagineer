"""limites do servidor compartilhado: tamanho de arquivo, narracao, armazenamento e cota (CT15 a CT20)

Tabela `limites` de uma linha so (`id = 1`), com os padroes decididos em 06/10/2026: video 50 MB, EPUB 60 MB, imagem 15 MB, narracao ate
100 mil caracteres por capitulo, 20 GB para a aplicacao toda e 5 GB por pessoa que nao e o dono.

Identificador desta migration: c3d4e5f6a7b9
Vem depois de: b2c3d4e5f6a8
Criada em: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b9'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria `limites` e a linha 1 com os padroes (os `server_default` preenchem as colunas)."""
    op.create_table(
        "limites",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("tamanho_maximo_do_video_mb", sa.Integer(), server_default="50", nullable=False),
        sa.Column("tamanho_maximo_do_epub_mb", sa.Integer(), server_default="60", nullable=False),
        sa.Column("tamanho_maximo_da_imagem_mb", sa.Integer(), server_default="15", nullable=False),
        sa.Column("caracteres_maximos_da_narracao", sa.Integer(), server_default="100000", nullable=False),
        sa.Column("armazenamento_total_em_gb", sa.Integer(), server_default="20", nullable=False),
        sa.Column("cota_por_pessoa_em_gb", sa.Integer(), server_default="5", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_limites")),
        sa.CheckConstraint("id = 1", name=op.f("ck_limites_linha_unica")),
    )
    op.execute("INSERT INTO limites (id) VALUES (1)")


def reverter() -> None:
    """Remove `limites`: os limites voltam a ser os fixos do codigo antigo."""
    op.drop_table("limites")


upgrade = aplicar
downgrade = reverter
