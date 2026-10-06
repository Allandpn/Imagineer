"""audios de capitulo: a narracao por voz de IA (NA4)

Tabela nova `audios_de_capitulo`: um MP3 por (capitulo, voz, instrucoes), gerado pelo servidor. So o caminho relativo do arquivo vai
para o banco. Nada muda para quem nao usa a narracao por IA.

Identificador desta migration: a1b2c3d4e5f7
Vem depois de: f2a3b4c5d6e7
Criada em: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria a tabela. Sem CHECK na situacao: um estado novo depois nao exige mexer em restricao."""
    op.create_table(
        "audios_de_capitulo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capitulo_id", sa.Integer(), sa.ForeignKey("capitulos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("motor", sa.String(length=20), nullable=False, server_default="openai"),
        sa.Column("modelo", sa.String(length=100), nullable=False),
        sa.Column("voz", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("instrucoes_hash", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("situacao", sa.String(length=20), nullable=False),
        sa.Column("erro", sa.Text(), nullable=True),
        sa.Column("arquivo", sa.String(length=500), nullable=True),
        sa.Column("tamanho_em_bytes", sa.Integer(), nullable=True),
        sa.Column("caracteres", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("custo", sa.Numeric(12, 8), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audios_de_capitulo_capitulo_id", "audios_de_capitulo", ["capitulo_id"])


def reverter() -> None:
    """Remove a tabela; os arquivos de audio ficam no disco (apague a pasta `audios/` se quiser)."""
    op.drop_index("ix_audios_de_capitulo_capitulo_id", table_name="audios_de_capitulo")
    op.drop_table("audios_de_capitulo")


upgrade = aplicar
downgrade = reverter
