"""videos

O video no app (item 4.8, VD12 a VD20): `prompts.oculto` (esconder um prompt de video da lista, sem apagar), a tabela `videos` (o video
importado para um frame; apagar o frame apaga o registro, o prompt de origem vira nulo se for apagado) e `frames.video_do_texto_id` (qual
video o texto mostra no lugar da imagem; SET NULL se o video for apagado).

Identificador desta migration: e1f2a3b4c5d6
Vem depois de: d0e1f2a3b4c5
Criada em: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria a coluna do prompt, a tabela dos videos e a coluna do frame (a chave do frame para o video vem depois da tabela)."""
    op.add_column("prompts", sa.Column("oculto", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("frame_id", sa.Integer(), sa.ForeignKey("frames.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("caminho_arquivo", sa.String(length=500), nullable=False),
        sa.Column("tamanho_em_bytes", sa.Integer(), nullable=False),
        sa.Column("nome_original", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("data_importacao", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_videos_frame_id", "videos", ["frame_id"])
    op.add_column("frames", sa.Column("video_do_texto_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_frames_video_do_texto_id", "frames", "videos", ["video_do_texto_id"], ["id"], ondelete="SET NULL")


def reverter() -> None:
    """Desfaz tudo; os registros de video se perdem (os arquivos ficam no disco: apague a pasta `videos/` se quiser)."""
    op.drop_constraint("fk_frames_video_do_texto_id", "frames", type_="foreignkey")
    op.drop_column("frames", "video_do_texto_id")
    op.drop_index("ix_videos_frame_id", table_name="videos")
    op.drop_table("videos")
    op.drop_column("prompts", "oculto")


upgrade = aplicar
downgrade = reverter
