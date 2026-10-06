"""Rotas dos vídeos de um frame (item 4.8, VD16 a VD20; Etapa 6.11).

O vídeo é gerado **fora** (no Gemini) e importado aqui: o servidor guarda o arquivo, serve com ``Range`` para o player do app tocar em
fluxo e guarda qual vídeo o texto do capítulo mostra no lugar da imagem.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.frame import ImagemCanonicaDoFrame
from imagineer.esquemas.video import VideoNoTextoNovo, VideoResumo
from imagineer.modelos import Frame, Prompt, TipoDePrompt, Video
from imagineer.rotas._comum import buscar_frame as _buscar_frame
from imagineer.rotas._comum import obter_ou_404
from imagineer.servicos.catalogo_de_videos import gravar_video, remover_video_do_disco, tipo_do_video
from imagineer.servicos.catalogo_imagens import caminho_absoluto
from imagineer.servicos.dimensoes_de_video import garantir_dimensoes_do_video

rotas_de_frame = APIRouter(prefix="/frames", tags=["Vídeos"])
rotas = APIRouter(prefix="/videos", tags=["Vídeos"])


def _buscar_video(sessao: Session, video_id: int) -> Video:
    return obter_ou_404(sessao, Video, video_id, "vídeo")


def _resumo(video: Video, frame: Frame) -> VideoResumo:
    resumo = VideoResumo.model_validate(video)
    resumo.no_texto = frame.video_do_texto_id == video.id
    return resumo


def _situacao_do_frame(frame: Frame) -> ImagemCanonicaDoFrame:
    return ImagemCanonicaDoFrame(
        frame_id=frame.id,
        imagem_canonica_id=frame.imagem_canonica_id,
        imagem_oculta=frame.imagem_oculta,
        video_do_texto_id=frame.video_do_texto_id,
    )


@rotas_de_frame.get("/{frame_id}/videos", response_model=list[VideoResumo], summary="Os vídeos importados do frame")
def listar_videos(frame_id: int, sessao: Session = Depends(obter_sessao)) -> list[VideoResumo]:
    """Do mais novo ao mais antigo."""
    frame = _buscar_frame(sessao, frame_id)
    videos = sessao.scalars(select(Video).where(Video.frame_id == frame.id).order_by(Video.id.desc()))
    return [_resumo(video, frame) for video in videos]


@rotas_de_frame.post(
    "/{frame_id}/videos",
    response_model=VideoResumo,
    status_code=status.HTTP_201_CREATED,
    summary="Importa um vídeo para o frame",
)
async def importar_video(
    frame_id: int,
    arquivo: UploadFile = File(description="O vídeo (.mp4, .m4v, .mov ou .webm), até 200 MB"),
    prompt_id: int | None = Form(default=None, description="O prompt de vídeo de onde ele veio (opcional); tem de ser deste frame."),
    sessao: Session = Depends(obter_sessao),
) -> VideoResumo:
    """Grava o arquivo aos pedaços (nunca inteiro na memória) e confere a extensão e o começo do conteúdo."""
    frame = _buscar_frame(sessao, frame_id)
    if prompt_id is not None:
        prompt = sessao.get(Prompt, prompt_id)
        if prompt is None or prompt.frame_id != frame.id or prompt.tipo != TipoDePrompt.VIDEO:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="O prompt informado não é um prompt de vídeo deste frame.",
            )
    caminho, tamanho = await gravar_video(frame.id, arquivo.filename or "", arquivo)
    video = Video(frame_id=frame.id, prompt_id=prompt_id, caminho_arquivo=caminho, tamanho_em_bytes=tamanho, nome_original=(arquivo.filename or "")[:300])
    garantir_dimensoes_do_video(video, caminho_absoluto(caminho))  # VD17: o tamanho, para o capítulo desenhar o vídeo como uma imagem
    sessao.add(video)
    try:
        sessao.commit()
    except Exception:
        sessao.rollback()
        remover_video_do_disco(caminho)  # o banco recusou: o arquivo não fica sem dono
        raise
    sessao.refresh(video)
    return _resumo(video, frame)


@rotas_de_frame.put(
    "/{frame_id}/video-no-texto",
    response_model=ImagemCanonicaDoFrame,
    summary="Escolhe o vídeo que o texto mostra (ou volta à imagem)",
)
def definir_video_no_texto(frame_id: int, corpo: VideoNoTextoNovo, sessao: Session = Depends(obter_sessao)) -> ImagemCanonicaDoFrame:
    """``{"video_id": 7}`` faz o texto mostrar o vídeo no lugar da imagem; ``{"video_id": null}`` volta à imagem. O vídeo tem de ser **do frame**."""
    frame = _buscar_frame(sessao, frame_id)
    if corpo.video_id is not None:
        video = sessao.get(Video, corpo.video_id)
        if video is None or video.frame_id != frame.id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Este vídeo não é deste frame.")
    frame.video_do_texto_id = corpo.video_id
    sessao.commit()
    sessao.refresh(frame)
    return _situacao_do_frame(frame)


@rotas.get("/{video_id}/arquivo", summary="Devolve o arquivo do vídeo (aceita pedaços, `Range`)")
def baixar_video(video_id: int, sessao: Session = Depends(obter_sessao)) -> FileResponse:
    """O arquivo do vídeo. O ``FileResponse`` responde ``206`` a um pedido ``Range``, que é o que o player precisa para tocar em fluxo e pular
    no meio. **Cache imutável**, como o da imagem: o nome do arquivo é gerado e nunca sobrescrito."""
    video = _buscar_video(sessao, video_id)
    caminho = caminho_absoluto(video.caminho_arquivo)
    if not caminho.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="O arquivo deste vídeo não está mais no disco.")
    return FileResponse(
        caminho,
        media_type=tipo_do_video(caminho) or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@rotas.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga o vídeo e o arquivo")
def apagar_video(video_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga o registro **e o arquivo** (sem lixeira). Se era o vídeo do texto, o frame volta a mostrar a imagem (``ON DELETE SET NULL``)."""
    video = _buscar_video(sessao, video_id)
    caminho = video.caminho_arquivo
    frame = sessao.get(Frame, video.frame_id)
    if frame is not None and frame.video_do_texto_id == video.id:
        frame.video_do_texto_id = None
    sessao.delete(video)
    sessao.commit()
    remover_video_do_disco(caminho)
