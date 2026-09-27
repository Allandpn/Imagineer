"""Importação e estruturação de EPUB (item 2.2 da especificação).

Transforma o arquivo enviado pelo app em um Livro com Capítulos — os passos 1 a
4 do fluxo da Etapa 2.

O módulo tem duas metades, de propósito:

- ``extrair_epub`` lê os bytes e devolve o que encontrou, **sem tocar no banco**.
  É onde mora toda a complexidade do parsing, e onde os testes precisam variar
  muito (arquivo sem índice, sem autor, com capítulo vazio) — testar isso não
  deveria exigir um banco no ar.
- ``importar_epub`` chama a extração e grava.
"""

import io
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import lxml.html
from ebooklib import ITEM_DOCUMENT, epub
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Livro

MINIMO_DE_CARACTERES = 100
"""Abaixo disso, o documento é descartado como página sem conteúdo.

O limite é baixo de propósito: pega capas, folhas de rosto e páginas de créditos
— que todo EPUB tem em quantidade — sem risco de descartar um capítulo curto de
verdade.
"""

_TAGS_DE_BLOCO = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "tr", "pre")


class ArquivoEpubInvalido(Exception):
    """O arquivo enviado não é um EPUB que dê para ler.

    Existe para que a rota de upload possa responder com uma mensagem clara. Sem
    ela, um arquivo corrompido viraria um erro 500 sem explicação, com o traço
    de pilha do ``zipfile`` no log.
    """


@dataclass
class CapituloExtraido:
    """Um capítulo encontrado no EPUB, antes de ir para o banco."""

    ordem: int
    titulo: str | None
    texto: str


@dataclass
class LivroExtraido:
    """A estrutura completa encontrada no EPUB, antes de ir para o banco."""

    titulo: str
    autor: str | None
    idioma: str | None
    identificador_epub: str | None
    nome_arquivo: str
    capitulos: list[CapituloExtraido] = field(default_factory=list)


def extrair_epub(conteudo: bytes, nome_arquivo: str) -> LivroExtraido:
    """Lê os bytes de um EPUB e devolve a estrutura encontrada.

    Não grava nada: é função pura sobre os bytes de entrada.

    Levanta:
        ArquivoEpubInvalido: se o arquivo não puder ser lido como EPUB, ou se
            não sobrar nenhum capítulo aproveitável depois dos descartes.
    """
    try:
        # read_epub aceita um objeto de arquivo, então os bytes do upload passam
        # adiante como estão — sem precisar gravar um arquivo temporário.
        epub_lido = epub.read_epub(io.BytesIO(conteudo))
    except Exception as erro:  # noqa: BLE001 - o ebooklib levanta tipos variados
        raise ArquivoEpubInvalido(
            f"Não foi possível ler {nome_arquivo!r} como EPUB: {erro}"
        ) from erro

    capitulos = _extrair_capitulos(epub_lido)
    if not capitulos:
        raise ArquivoEpubInvalido(
            f"O arquivo {nome_arquivo!r} é um EPUB válido, mas nenhum capítulo com "
            "texto foi encontrado nele."
        )

    return LivroExtraido(
        titulo=_primeiro_metadado(epub_lido, "title") or _titulo_do_nome(nome_arquivo),
        autor=_primeiro_metadado(epub_lido, "creator"),
        idioma=_primeiro_metadado(epub_lido, "language"),
        identificador_epub=_primeiro_metadado(epub_lido, "identifier"),
        nome_arquivo=nome_arquivo,
        capitulos=capitulos,
    )


def importar_epub(sessao: Session, conteudo: bytes, nome_arquivo: str) -> Livro:
    """Extrai a estrutura do EPUB e grava o Livro com seus Capítulos.

    Devolve o Livro já gravado, com o ``id`` preenchido.
    """
    extraido = extrair_epub(conteudo, nome_arquivo)

    livro = Livro(
        titulo=extraido.titulo,
        autor=extraido.autor,
        idioma=extraido.idioma,
        identificador_epub=extraido.identificador_epub,
        nome_arquivo=extraido.nome_arquivo,
    )
    livro.capitulos = [
        Capitulo(ordem=c.ordem, titulo=c.titulo, texto=c.texto)
        for c in extraido.capitulos
    ]

    sessao.add(livro)
    sessao.commit()
    return livro


def livros_com_mesmo_identificador(
    sessao: Session, identificador_epub: str | None
) -> list[Livro]:
    """Devolve os livros já cadastrados com este ``dc:identifier``.

    Serve para o app **avisar** que o livro parece já ter sido importado — não
    para impedir (item 3.4a). Um identificador nulo nunca casa com nada: EPUBs
    sem identificador não são "o mesmo livro" só por isso.
    """
    if not identificador_epub:
        return []

    return list(
        sessao.scalars(
            select(Livro).where(Livro.identificador_epub == identificador_epub)
        ).all()
    )


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _extrair_capitulos(epub_lido: epub.EpubBook) -> list[CapituloExtraido]:
    """Percorre o spine montando a lista de capítulos com texto.

    A ordem e o conteúdo vêm do **spine**; os títulos vêm do **índice (TOC)**.
    Cada fonte resolve metade do problema: o spine é a ordem de leitura e está
    sempre presente, mas não traz títulos; o TOC traz títulos, mas é opcional,
    pode ser aninhado e pode apontar para uma âncora dentro de um arquivo.
    """
    titulos_por_arquivo = _titulos_do_indice(epub_lido)

    capitulos: list[CapituloExtraido] = []
    for idref, _linear in epub_lido.spine:
        item = epub_lido.get_item_with_id(idref)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue

        # Documentos de navegação fazem parte da mecânica do formato, não da
        # obra — e aparecem no spine como se fossem capítulos.
        if isinstance(item, (epub.EpubNav, epub.EpubNcx)):
            continue

        texto = _extrair_texto(item.get_content())
        if len(texto) < MINIMO_DE_CARACTERES:
            continue

        capitulos.append(
            CapituloExtraido(
                # A ordem é atribuída depois dos descartes: começa em 1 e não
                # tem lacunas. O que importa é a sequência de leitura do
                # conteúdo, não a posição original no arquivo.
                ordem=len(capitulos) + 1,
                titulo=titulos_por_arquivo.get(_caminho_sem_ancora(item.file_name)),
                texto=texto,
            )
        )

    return capitulos


def _titulos_do_indice(epub_lido: epub.EpubBook) -> dict[str, str]:
    """Achata o índice do EPUB num mapa de caminho do arquivo para título.

    O TOC pode ser aninhado em seções, então a função é recursiva. Só o primeiro
    título de cada arquivo é guardado: quando várias entradas apontam para
    âncoras do mesmo arquivo, a primeira é a do começo dele.
    """
    titulos: dict[str, str] = {}

    def percorrer(itens) -> None:
        for item in itens:
            # Uma seção do índice vem como (objeto da seção, lista de filhos).
            if isinstance(item, (tuple, list)):
                secao, filhos = item[0], item[1]
                percorrer([secao])
                percorrer(filhos)
                continue

            href = getattr(item, "href", None)
            titulo = getattr(item, "title", None)
            if not href or not titulo:
                continue
            titulos.setdefault(_caminho_sem_ancora(href), titulo.strip())

    percorrer(epub_lido.toc)
    return titulos


def _caminho_sem_ancora(href: str) -> str:
    """Normaliza um caminho do EPUB para servir de chave de comparação.

    Descarta a âncora, porque o TOC costuma apontar para um ponto dentro do
    arquivo: ``capitulo3.xhtml#inicio`` precisa casar com ``capitulo3.xhtml``.
    Descarta também a pasta, porque o TOC e o manifesto podem escrever o mesmo
    arquivo com prefixos diferentes (``Text/cap3.xhtml`` e ``cap3.xhtml``).
    """
    return PurePosixPath(href.split("#")[0]).name


def _extrair_texto(conteudo: bytes) -> str:
    """Converte o HTML de um documento do EPUB em texto simples.

    Preserva as quebras de parágrafo, porque é este texto que a IA vai ler: um
    capítulo inteiro numa única linha contínua perde a estrutura da narrativa.
    """
    try:
        arvore = lxml.html.fromstring(conteudo)
    except Exception:  # noqa: BLE001 - documento vazio ou HTML irrecuperável
        return ""

    for elemento in arvore.xpath("//script|//style"):
        elemento.drop_tree()

    # Insere as quebras no "tail" de cada elemento (o texto que vem depois do
    # fechamento da tag). É o que mantém a separação entre parágrafos quando o
    # texto de toda a árvore é concatenado.
    for elemento in arvore.xpath("//br"):
        elemento.tail = "\n" + (elemento.tail or "")
    for elemento in arvore.xpath("|".join(f"//{tag}" for tag in _TAGS_DE_BLOCO)):
        elemento.tail = "\n\n" + (elemento.tail or "")

    texto = arvore.text_content().replace("\xa0", " ")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _primeiro_metadado(epub_lido: epub.EpubBook, campo: str) -> str | None:
    """Devolve o primeiro valor de um campo Dublin Core, ou None se não houver.

    O ``get_metadata`` devolve uma lista de pares (valor, atributos), porque um
    EPUB pode declarar vários autores ou identificadores. Para o MVP, o primeiro
    basta.
    """
    valores = epub_lido.get_metadata("DC", campo)
    if not valores:
        return None

    valor = (valores[0][0] or "").strip()
    return valor or None


def _titulo_do_nome(nome_arquivo: str) -> str:
    """Usa o nome do arquivo como título, para EPUBs sem ``dc:title``.

    Só o título tem valor de reserva, porque é obrigatório no modelo e é o que
    identifica o livro na tela. Um livro sem título na lista seria inutilizável;
    um livro sem autor, não.
    """
    return PurePosixPath(nome_arquivo).stem or nome_arquivo
