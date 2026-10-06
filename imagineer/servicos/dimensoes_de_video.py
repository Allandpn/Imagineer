"""O tamanho de um vídeo, lido do próprio arquivo, sem ``ffmpeg`` (item 4.8, VD17).

Só o **MP4/MOV/M4V** (a família ISO/QuickTime): o tamanho está no atom ``tkhd`` de cada trilha, dentro de ``moov > trak``. O WebM (EBML)
fica sem tamanho e o app o trata como paisagem. Só se leem os **cabeçalhos** dos atoms (``seek`` por cima do conteúdo), então um vídeo de
200 MB custa uns poucos bytes de leitura; só o ``tkhd`` é lido por inteiro (84 a 92 bytes).
"""

import struct
from pathlib import Path

from imagineer.modelos import Video

_CONTEUDO_DE = {b"moov", b"trak"}
"""Os atoms que só contêm outros atoms e por onde se desce até o ``tkhd``."""

_MAXIMO_DE_ATOMS = 2000
"""Trava de segurança contra um arquivo corrompido que faria o laço rodar sem fim."""


def _ler_atoms(arquivo, inicio: int, fim: int):
    """Os atoms entre ``inicio`` e ``fim``: ``(nome, inicio do conteúdo, fim do atom)``."""
    posicao = inicio
    for _ in range(_MAXIMO_DE_ATOMS):
        if posicao + 8 > fim:
            return
        arquivo.seek(posicao)
        cabecalho = arquivo.read(8)
        if len(cabecalho) < 8:
            return
        tamanho, nome = struct.unpack(">I4s", cabecalho)
        miolo = posicao + 8
        if tamanho == 1:  # tamanho de 64 bits logo depois do nome
            estendido = arquivo.read(8)
            if len(estendido) < 8:
                return
            tamanho = struct.unpack(">Q", estendido)[0]
            miolo += 8
        elif tamanho == 0:  # vai até o fim do arquivo
            tamanho = fim - posicao
        if tamanho < 8 or posicao + tamanho > fim:
            return
        yield nome, miolo, posicao + tamanho
        posicao += tamanho


def _tkhd(arquivo, miolo: int, fim: int) -> tuple[int, int] | None:
    """``(largura, altura)`` de um ``tkhd`` **com a rotação aplicada** (90 e 270 graus trocam os lados); ``None`` se é trilha sem imagem."""
    arquivo.seek(miolo)
    dados = arquivo.read(min(fim - miolo, 100))
    if not dados:
        return None
    versao = dados[0]
    # versão 0: criação, modificação (4+4), id da trilha (4), reservado (4), duração (4); versão 1: 8+8, 4, 4, 8.
    deslocamento = 4 + (8 + 8 + 4 + 4 + 8 if versao == 1 else 4 + 4 + 4 + 4 + 4)
    deslocamento += 8 + 2 + 2 + 2 + 2  # reservado (8), camada, grupo, volume, reservado
    if len(dados) < deslocamento + 36 + 8:
        return None
    a, b = struct.unpack(">ii", dados[deslocamento:deslocamento + 8])  # a primeira linha da matriz de transformação
    largura, altura = struct.unpack(">II", dados[deslocamento + 36:deslocamento + 44])
    largura, altura = largura >> 16, altura >> 16  # ponto fixo 16.16
    if largura == 0 or altura == 0:
        return None
    if a == 0 and abs(b) == 0x10000:  # girado 90 ou 270 graus: o que o player mostra tem os lados trocados
        largura, altura = altura, largura
    return largura, altura


def ler_dimensoes_do_video(caminho: Path) -> tuple[int, int] | None:
    """``(largura, altura)`` do vídeo, ou ``None`` se o formato não é MP4/MOV/M4V ou o arquivo não tem a informação."""
    try:
        tamanho = caminho.stat().st_size
        with caminho.open("rb") as arquivo:
            for nome, miolo, fim in _ler_atoms(arquivo, 0, tamanho):
                if nome != b"moov":
                    continue
                for nome_filho, miolo_filho, fim_filho in _ler_atoms(arquivo, miolo, fim):
                    if nome_filho not in _CONTEUDO_DE:
                        continue
                    for nome_neto, miolo_neto, fim_neto in _ler_atoms(arquivo, miolo_filho, fim_filho):
                        if nome_neto == b"tkhd":
                            dimensoes = _tkhd(arquivo, miolo_neto, fim_neto)
                            if dimensoes is not None:
                                return dimensoes
    except (OSError, struct.error):
        return None
    return None


def garantir_dimensoes_do_video(video: Video, caminho: Path) -> bool:
    """Preenche ``largura``/``altura`` de um vídeo que ainda não as tem, a partir do arquivo. ``True`` se mudou algo.

    Não faz commit: quem chama decide (a leitura dos artefatos já grava o que calculou). Sem arquivo ou sem informação, deixa nulo.
    """
    if video.largura is not None and video.altura is not None:
        return False
    if not caminho.is_file():
        return False
    dimensoes = ler_dimensoes_do_video(caminho)
    if dimensoes is None:
        return False
    video.largura, video.altura = dimensoes
    return True
