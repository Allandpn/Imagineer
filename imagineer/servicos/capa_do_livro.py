"""A capa de um livro (item 7.5b, CP1 a CP3): achar no EPUB, conferir que é imagem e reduzir.

**Onde procurar** (a ordem importa: do que o EPUB declara ao que se adivinha). Os 18 livros de validação mostraram
que cada editor faz de um jeito:

1. o metadado ``<meta name="cover" content="...">`` do OPF, cujo ``content`` costuma ser o **id** de um item da
   lista (``manifest``) — ou, em alguns livros, o **nome do arquivo**;
2. o item que a própria biblioteca (ebooklib) já marca como capa (``ITEM_COVER``);
3. a propriedade ``cover-image`` do EPUB 3;
4. por último, a primeira imagem cujo nome tem "cover" ou "capa".

Cada candidato só vale se **abrir como imagem de verdade**: o ``content`` de um ``meta`` às vezes aponta para a página
HTML da capa, e não para a figura. A capa é **reduzida** (lado maior 800 px, JPEG): é só para a vitrine da biblioteca,
e guardada no banco (dezenas de KB), junto do livro. Achar ou não achar capa **nunca** quebra a importação.
"""

import io
import zipfile
from pathlib import PurePosixPath

import ebooklib
from ebooklib import epub
from PIL import Image, UnidentifiedImageError

LADO_MAXIMO_DA_CAPA = 800
"""O maior lado, em pixels, da capa guardada."""

TIPO_DA_CAPA = "image/jpeg"


class CapaInvalida(Exception):
    """O arquivo mandado como capa não é uma imagem (nem um EPUB com capa)."""


def preparar_capa(conteudo: bytes) -> tuple[bytes, str]:
    """Confere que ``conteudo`` é uma imagem e a devolve reduzida, em JPEG: ``(bytes, tipo)``.

    Levanta:
        CapaInvalida: se os bytes não abrem como imagem.
    """
    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            imagem.load()
            pronta = imagem.convert("RGB")  # PNG com transparência e paleta viram RGB; JPEG não guarda alfa
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as erro:
        raise CapaInvalida("O arquivo não é uma imagem que dê para usar como capa.") from erro
    pronta.thumbnail((LADO_MAXIMO_DA_CAPA, LADO_MAXIMO_DA_CAPA))  # só reduz, nunca amplia
    saida = io.BytesIO()
    pronta.save(saida, format="JPEG", quality=85, optimize=True)
    return saida.getvalue(), TIPO_DA_CAPA


def capa_do_epub(epub_lido: epub.EpubBook) -> tuple[bytes, str] | None:
    """A capa de um EPUB já lido, pronta para guardar, ou ``None`` se não há (ou não se achou)."""
    for candidato in _candidatos(epub_lido):
        try:
            return preparar_capa(candidato.get_content())
        except (CapaInvalida, KeyError, AttributeError):
            continue  # a página HTML da capa, um item vazio...: tenta o próximo
    return _primeira_imagem_de_retrato(epub_lido)


def _primeira_imagem_de_retrato(epub_lido: epub.EpubBook) -> tuple[bytes, str] | None:
    """Último recurso (histórias em quadrinhos sem metadado de capa): a primeira imagem **em pé** e de bom tamanho.

    Exige ao menos 300 x 400 px para não tomar um logotipo ou um ornamento por capa.
    """
    for item in epub_lido.get_items_of_type(ebooklib.ITEM_IMAGE):
        try:
            with Image.open(io.BytesIO(item.get_content())) as imagem:
                largura, altura = imagem.size
            if altura > largura and largura >= 300 and altura >= 400:
                return preparar_capa(item.get_content())
        except (UnidentifiedImageError, OSError, ValueError, CapaInvalida):
            continue
    return None


def capa_de_um_arquivo(conteudo: bytes) -> tuple[bytes, str]:
    """A capa de um arquivo mandado pela pessoa: uma **imagem** ou um **EPUB** (de onde se tira a capa).

    Levanta:
        CapaInvalida: se não é imagem, ou se é um EPUB sem capa que se ache.
    """
    if zipfile.is_zipfile(io.BytesIO(conteudo)):
        try:
            epub_lido = epub.read_epub(io.BytesIO(conteudo))
        except Exception as erro:  # noqa: BLE001 - o ebooklib levanta tipos variados
            raise CapaInvalida(f"Não consegui ler o EPUB: {erro}") from erro
        achada = capa_do_epub(epub_lido)
        if achada is None:
            raise CapaInvalida("Não achei a capa neste EPUB.")
        return achada
    return preparar_capa(conteudo)


def _candidatos(epub_lido: epub.EpubBook):
    """Os itens que podem ser a capa, do mais provável ao menos, sem repetir."""
    vistos: set[str] = set()

    def novo(item) -> bool:
        if item is None or item.get_name() in vistos:
            return False
        vistos.add(item.get_name())
        return True

    # 1. o metadado "cover": o content é um id do manifesto ou um nome de arquivo
    for destino in _destinos_do_metadado_cover(epub_lido):
        item = epub_lido.get_item_with_id(destino) or epub_lido.get_item_with_href(destino)
        if item is None:
            nome = PurePosixPath(destino).name
            item = next((i for i in epub_lido.get_items() if PurePosixPath(i.get_name()).name == nome), None)
        if novo(item):
            yield item
    # 2. o que o ebooklib já reconhece como capa
    for item in epub_lido.get_items_of_type(ebooklib.ITEM_COVER):
        if novo(item):
            yield item
    # 3. EPUB 3: propriedade cover-image
    for item in epub_lido.get_items():
        if "cover-image" in (getattr(item, "properties", None) or []) and novo(item):
            yield item
    # 4. a primeira imagem com "cover" ou "capa" no nome
    for item in epub_lido.get_items_of_type(ebooklib.ITEM_IMAGE):
        nome = PurePosixPath(item.get_name()).name.lower()
        if ("cover" in nome or "capa" in nome) and novo(item):
            yield item


def _destinos_do_metadado_cover(epub_lido: epub.EpubBook) -> list[str]:
    destinos: list[str] = []
    for por_nome in epub_lido.metadata.values():
        for _valor, atributos in por_nome.get("meta", []):
            if atributos and atributos.get("name") == "cover" and atributos.get("content"):
                destinos.append(atributos["content"])
    return destinos
