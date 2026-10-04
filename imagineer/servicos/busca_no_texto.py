"""Procurar uma palavra ou frase nos textos dos capítulos (item 7.5b, LV5).

A busca é **sem acento, sem diferença de maiúsculas** e trata aspas tipográficas e quebras de linha como o
que o leitor digitaria (``"``, ``'``, espaço). É por **substring**: "ned" acha "Ned" e também "Nedson". Com
poucos livros isso basta; um índice de texto completo (FTS) fica para quando a biblioteca crescer.

O difícil é a **posição**: o app precisa saber *onde*, no texto original, está o achado. Normalizar pode mudar o
tamanho do texto (um "é" decomposto vira dois caracteres, um "İ" vira outro par), então a posição vem sempre de um
**mapa de volta ao original** — o mesmo cuidado de ``posicao_no_texto``. O caminho comum (texto já em forma
composta, que é o de quase todo EPUB) não muda o tamanho e dispensa o mapa, o que mantém a busca rápida mesmo com
megabytes de texto.
"""

import re
import unicodedata
from dataclasses import dataclass

from imagineer.servicos.posicao_no_texto import _inicio_do_paragrafo, _normalizar, tamanho_em_utf16

_MARCAS = re.compile("[̀-ͯ]")
"""Os acentos soltos (combinantes), que sobram depois de decompor o texto."""

_TABELA = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"',
        "\n": " ", "\r": " ", "\t": " ", " ": " ", " ": " ",
    }
)
"""Troca **um caractere por um caractere**: não muda o tamanho, então não precisa de mapa."""

TAMANHO_DO_CONTEXTO = 60
"""Quantos caracteres do texto original vão antes e depois do achado, no trecho mostrado."""


@dataclass(frozen=True)
class Achado:
    """Um lugar onde o termo aparece no texto de um capítulo."""

    posicao_no_texto: int
    """Onde o achado começa, em UTF-16 desde o início do capítulo."""
    inicio_do_paragrafo: int
    """Onde começa o parágrafo que o contém, em UTF-16: é o que o app usa para rolar até lá."""
    trecho: str
    """O texto em volta do achado (uma linha só, sem quebras)."""
    inicio_no_trecho: int
    fim_no_trecho: int
    """Onde o achado está dentro do ``trecho``, em UTF-16 (para o app destacá-lo)."""


def normalizar_termo(termo: str) -> str:
    """O termo digitado, na mesma forma do texto normalizado: sem acento, minúsculo, espaços juntos."""
    sem_marcas = _MARCAS.sub("", unicodedata.normalize("NFD", termo))
    return " ".join(sem_marcas.translate(_TABELA).lower().split())


def _texto_normalizado(texto: str) -> tuple[str, list[int] | None]:
    """O texto normalizado e, **só se o tamanho mudou**, o mapa de cada caractere de volta ao original.

    ``None`` no mapa quer dizer "o índice normalizado é o índice original" (o caminho rápido).
    """
    rapido = _MARCAS.sub("", unicodedata.normalize("NFD", texto)).translate(_TABELA).lower()
    if len(rapido) == len(texto):
        return rapido, None
    # Mudou o tamanho (texto decomposto, caracteres especiais): o caminho lento, caractere a caractere, com mapa.
    normalizado, origem = _normalizar(texto)
    return normalizado, origem


def procurar(texto: str, termo: str) -> list[Achado]:
    """Todos os achados de ``termo`` em ``texto``, na ordem em que aparecem (sem sobreposição)."""
    procurado = normalizar_termo(termo)
    if not procurado:
        return []
    normalizado, origem = _texto_normalizado(texto)

    achados: list[Achado] = []
    inicio = normalizado.find(procurado)
    while inicio != -1:
        fim = inicio + len(procurado)
        if origem is None:
            de, ate = inicio, fim
        else:
            de, ate = origem[inicio], origem[fim - 1] + 1
        achados.append(_montar_achado(texto, de, ate))
        inicio = normalizado.find(procurado, fim)
    return achados


def _montar_achado(texto: str, de: int, ate: int) -> Achado:
    comeco = max(0, de - TAMANHO_DO_CONTEXTO)
    final = min(len(texto), ate + TAMANHO_DO_CONTEXTO)
    recorte = texto[comeco:final].translate(_TABELA)  # uma linha só, sem mudar o tamanho
    return Achado(
        posicao_no_texto=tamanho_em_utf16(texto[:de]),
        inicio_do_paragrafo=tamanho_em_utf16(texto[: _inicio_do_paragrafo(texto, de)]),
        trecho=recorte,
        inicio_no_trecho=tamanho_em_utf16(texto[comeco:de]),
        fim_no_trecho=tamanho_em_utf16(texto[comeco:ate]),
    )
