"""Grava e apaga os arquivos de vídeo do catálogo em disco (item 4.8, VD16).

Como as imagens: só o caminho relativo vai para o banco; o arquivo mora em ``DIRETORIO_IMAGENS/videos/{frame_id}/{uuid}.ext``.
**A diferença é o tamanho**: o vídeo é gravado **aos pedaços**, direto em disco, e nunca inteiro na memória (o Raspberry Pi não aguentaria
200 MB de um upload).
"""

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from imagineer.servicos.catalogo_imagens import caminho_absoluto, remover_arquivo
from imagineer.servicos.upload import TAMANHO_DO_BLOCO

TIPOS_POR_EXTENSAO = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
"""O ``Content-Type`` de cada extensão aceita. Explícito, como o das imagens: o contêiner não tem ``/etc/mime.types``."""

_CAIXAS_DO_MP4_E_MOV = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"}
"""A primeira "caixa" de um MP4/MOV: o nome fica nos bytes 4 a 8. ``ftyp`` é o comum; os outros aparecem em arquivos do QuickTime."""

_ASSINATURA_DO_WEBM = bytes([0x1A, 0x45, 0xDF, 0xA3])
"""O início de um contêiner EBML (WebM e Matroska)."""


def tipo_do_video(caminho: Path) -> str | None:
    """O tipo de mídia pela extensão do arquivo, ou ``None`` se não for uma das aceitas."""
    return TIPOS_POR_EXTENSAO.get(caminho.suffix.lower())


def _recusar(detalhe: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detalhe)


def conteudo_confere_com_a_extensao(extensao: str, inicio: bytes) -> bool:
    """O começo do arquivo é de um vídeo do tipo que a extensão diz? Um ``.mp4`` que na verdade é outra coisa é recusado."""
    if extensao == ".webm":
        return inicio.startswith(_ASSINATURA_DO_WEBM)
    return len(inicio) >= 8 and inicio[4:8] in _CAIXAS_DO_MP4_E_MOV


async def gravar_video(frame_id: int, nome_original: str, arquivo: UploadFile, limite_em_bytes: int) -> tuple[str, int]:
    """Grava o vídeo em disco, aos pedaços, e devolve ``(caminho relativo, tamanho em bytes)``.

    422 para extensão não aceita, conteúdo que não é do tipo da extensão ou arquivo vazio; 413 se passar do limite (``limite_em_bytes``, o que o dono configurou, CT15). Em qualquer
    recusa **o arquivo parcial é apagado**: o disco não guarda vídeo sem dono.
    """
    extensao = Path(nome_original).suffix.lower()
    if extensao not in TIPOS_POR_EXTENSAO:
        raise _recusar(f"Extensão {extensao or '(nenhuma)'!r} não é aceita. Use uma destas: {', '.join(sorted(TIPOS_POR_EXTENSAO))}.")

    caminho_relativo = f"videos/{frame_id}/{uuid.uuid4().hex}{extensao}"
    destino = caminho_absoluto(caminho_relativo)
    destino.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    try:
        with destino.open("wb") as saida:
            while bloco := await arquivo.read(TAMANHO_DO_BLOCO):
                if total == 0 and not conteudo_confere_com_a_extensao(extensao, bloco[:16]):
                    raise _recusar("O conteúdo do arquivo não é de um vídeo do tipo que a extensão diz.")
                total += len(bloco)
                if total > limite_em_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"O vídeo passa do limite de {limite_em_bytes // (1024 * 1024)} MB.",
                    )
                saida.write(bloco)
        if total == 0:
            raise _recusar("O arquivo enviado está vazio.")
    except BaseException:
        destino.unlink(missing_ok=True)
        raise
    return caminho_relativo, total


def remover_video_do_disco(caminho_relativo: str) -> None:
    """Apaga o arquivo, sem reclamar se ele já não existir."""
    remover_arquivo(caminho_relativo)
