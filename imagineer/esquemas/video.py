"""Contratos das rotas de vídeos (item 4.8, VD16 a VD20; Etapa 6.11)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VideoResumo(BaseModel):
    """Um vídeo importado, como a API o devolve. Não expõe o caminho do arquivo: o app o busca por ``GET /videos/{id}/arquivo``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    frame_id: int
    prompt_id: int | None = Field(default=None, description="O prompt de vídeo de onde veio, se a pessoa disse.")
    nome_original: str = ""
    tamanho_em_bytes: int
    data_importacao: datetime
    no_texto: bool = Field(default=False, description="O texto do capítulo mostra **este** vídeo no lugar da imagem (VD17).")


class VideoNoTextoNovo(BaseModel):
    """O que o app manda para escolher o que o texto mostra: um vídeo do frame, ou ``null`` para voltar à imagem (VD17)."""

    video_id: int | None = None
