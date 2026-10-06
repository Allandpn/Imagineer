"""O Video: um vídeo importado para um frame (item 4.8, VD16)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base


class Video(Base):
    """Um vídeo que a pessoa gerou fora (no Gemini, por exemplo) e importou para a cena.

    **Não é uma ``Imagem``**: o catálogo de imagens carrega miniatura, dimensões, canônica, lixeira e geração por IA, e nada disso vale
    para vídeo. Só o caminho relativo do arquivo vai para o banco (como nas imagens); o arquivo mora em ``DIRETORIO_IMAGENS/videos/``.
    Apagar o vídeo apaga também o arquivo (sem lixeira: um vídeo pesa).
    """

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)

    frame_id: Mapped[int] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), index=True)

    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompts.id", ondelete="SET NULL"))
    """O prompt de vídeo de onde o vídeo veio, se a pessoa disse; nulo = importado sem ligar a um prompt (ou o prompt foi apagado)."""

    caminho_arquivo: Mapped[str] = mapped_column(String(500))
    tamanho_em_bytes: Mapped[int] = mapped_column()
    nome_original: Mapped[str] = mapped_column(String(300), default="")

    data_importacao: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Video id={self.id} frame={self.frame_id}>"
