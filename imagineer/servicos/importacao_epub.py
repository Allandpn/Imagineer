"""Importação e estruturação de EPUB (item 2.2 da especificação).

Transforma o arquivo enviado pelo app em um Livro com Capítulos — os passos 1 a
4 do fluxo da Etapa 2.

O módulo tem duas metades, de propósito:

- ``extrair_epub`` lê os bytes e devolve o que encontrou, **sem tocar no banco**.
  É onde mora toda a complexidade do parsing, e onde os testes precisam variar
  muito (arquivo sem índice, sem autor, capítulo vazio) — testar isso não
  deveria exigir um banco no ar.
- ``importar_epub`` chama a extração e grava.

Um princípio orienta as decisões daqui: **nunca descartar narrativa em
silêncio**. Listar um glossário como capítulo é um incômodo; perder um prólogo é
perder parte do livro. Então o que é claramente mecânica do formato é descartado,
e o que é duvidoso entra marcado como sugestão de ignorar, para o usuário
confirmar.
"""

import copy
import io
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import lxml.html
from ebooklib import ITEM_DOCUMENT, ITEM_IMAGE, epub
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Livro

MINIMO_DE_CARACTERES = 100
"""Abaixo disso, o documento é descartado como página sem conteúdo.

O limite é baixo de propósito: pega capas e páginas praticamente vazias sem
risco de descartar um capítulo curto de verdade. Material pré e pós-textual com
texto real **não** é descartado aqui — é apenas sugerido como ignorado.
"""

PROPORCAO_DE_LINKS_PARA_NAVEGACAO = 0.6
MINIMO_DE_LINKS_PARA_NAVEGACAO = 5
"""Quando um documento é considerado uma página de navegação, e não um capítulo.

Muitos EPUBs trazem um "Sumário" como documento XHTML comum dentro do spine.
Ele não é declarado como documento de navegação do formato, então a checagem de
tipo não o pega — e ele entraria no catálogo como se fosse um capítulo.

O critério é a proporção do texto que está dentro de links. Medido num livro
real de 85 documentos: a página de sumário tinha **99,3%** do texto em 86 links,
enquanto o segundo maior índice era 20,5% (um único link de e-mail) e 81 dos 85
documentos não tinham link nenhum. O limite de 60% fica confortavelmente no
meio dessa distância, e a exigência de pelo menos 5 links evita descartar um
capítulo curto que por acaso contenha uma nota de rodapé.
"""

PROPORCAO_MINIMA_DA_MEDIANA = 0.10
"""Abaixo desta fração da mediana, o capítulo é **sugerido** como ignorado.

O valor saiu de uma varredura sobre os nove primeiros livros de validação --
aqueles cuja classificação entre narrativa e apêndice foi feita à mão -- contando
quantos capítulos narrativos cada limite escondia e quantos apêndices deixava
passar:

| Limite | Narrativa escondida | Apêndice mantido |
|--------|---------------------|------------------|
| 5%     | 0                   | 19               |
| **10%**| **0**               | **14**           |
| 12%    | 1                   | 11               |
| 15%    | 2                   | 10               |
| 25%    | 2                   | 5                |

Subir de 10% para 25% troca nove incômodos por dois fragmentos de *O Processo*
escondidos — e esconder narrativa é muito pior que deixar um item para o usuário
desmarcar. Daí 10%. Os seis livros acrescentados depois confirmaram o limite: com
ele, nenhum dos quinze esconde narrativa.

O critério é **relativo à mediana do próprio livro**, não absoluto: a mediana
variou de mil caracteres (*Robert Frost: Selected Early Poems*, poemas curtos) a
89 mil (*Treasure Island*, que sai como um capítulo só) entre os dezoito. Um
limite fixo serviria para um livro e falharia nos outros.
"""

_PREFIXOS_DE_ISBN = ("978", "979")
"""Prefixos de ISBN-13, usados para reconhecer anúncios de outros livros.

E-books comerciais costumam terminar com páginas de "compre agora e leia",
listando outros títulos da editora com título, autor, ISBN e número de páginas.
Elas não têm entrada no índice e são curtas, mas nada no título as denuncia —
porque não têm título. O ISBN é o que as distingue de narrativa: um número de 13
dígitos começando em 978 ou 979 não aparece em prosa.

Quando o critério foi criado, essas páginas eram 6 dos 12 apêndices que
passavam nos nove primeiros livros de validação.
"""

MAXIMO_DO_TITULO_DE_RESERVA = 80
"""Tamanho máximo da primeira linha para ela servir de título do capítulo.

Muitos livros põem o título do capítulo no corpo do texto e não no índice. Em
*Tress, a garota do Mar Esmeralda*, 80 dos 84 capítulos não têm entrada no
índice — mas o primeiro parágrafo de cada um é o nome dele ("A GAROTA",
"O JARDINEIRO"). O mesmo vale para a coletânea de poemas de Robert Frost, onde o
índice aponta para a nota editorial e o poema em si fica sem rótulo.

Medido nos dezoito livros de validação: dos 116 capítulos sem título no índice,
103 (89%) ganham um título sensato assim.
"""

_TAGS_DE_BLOCO = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "tr", "pre")

_ROTULOS_NAO_NARRATIVOS = (
    # Portugues
    "abreviatura", "agradecimento", "anexo", "apendice", "apresentacao",
    "bibliografia", "citacao", "colofao", "copyright", "credito", "cronologia",
    "dedicatoria", "epigrafe", "errata", "ficha tecnica", "folha de rosto",
    "glossario", "indice", "informacoes sobre", "introducao", "lugares", "mapa",
    "nota", "obras da autora", "obras do autor", "outras leituras",
    "personagens", "posfacio", "pos-escrito", "prefacio", "publicidade",
    "sobre a autora", "sobre o autor", "sumario",
    # Ingles
    "about the author", "acknowledgment", "afterword", "appendix",
    "bibliography", "colophon", "contents", "dedication", "epigraph",
    "foreword", "glossary", "index", "introduction", "note", "preface",
)
"""Títulos que costumam nomear material não-narrativo.

Comparados **sem acento e em minúsculas**, e só no começo do título — "Notas ao
Canto 1" casa com ``nota``, mas um capítulo chamado "A nota final" não casaria.
A lista vem dos dezoito livros reais usados na validação, e tem os equivalentes
em inglês porque um deles é em inglês — os rótulos em português não pegariam
"Acknowledgments" nem "About the Author". É uma heurística de sugestão, não uma
regra: o usuário confirma.
"""

_PADROES_NARRATIVOS = re.compile(
    r"^(capitulo|canto|prologo|epilogo|interludio|parte|livro)\b"
    # Os mesmos em ingles, para livros como o manual de Sherlock Holmes.
    r"|^(chapter|prologue|epilogue|interlude|part|book)\b"
    # Titulo que COMECA com numero e separador: "3 - AS MAOS, OS PES E O VENTRE",
    # "36. O NUMERO TRES". E como as coletaneas de contos numeram as historias, e
    # sem isto as fabulas de Esopo -- de 600 caracteres numa antologia cuja
    # mediana e 9 mil -- eram sugeridas como ignoradas.
    r"|^[0-9]+ *[-.):\u2013\u2014]"
    # Sem \b no fim: o índice de "Flores para Algernon" escreve "Relatorio de
    # Progreso", com um "s" só, e o prefixo truncado precisa casar com as duas
    # grafias. Um \b aqui nunca casaria, porque entre "s" e "o" de "progreso"
    # não existe fronteira de palavra.
    r"|^relatorio de progres"
    r"|^[\divxlcIVXLC]+$"
)
"""Títulos que são narrativa com certeza suficiente para **proteger** o capítulo.

Vence a sugestão por tamanho. É o que impede de esconder o capítulo 26 de *O
apanhador no campo de centeio*, que tem 11% da mediana do livro e é o desfecho da
obra, ou as fábulas de Esopo numa coletânea de contos.

Na prática não há conflito com os rótulos: a comparação de rótulo é por prefixo,
então um título que começa com número — "1. Prefácio" — não casa com nenhum
rótulo e acaba protegido. É o erro seguro: deixar passar um prefácio numerado
incomoda, esconder o conto "4 - O LEÃO" de uma coletânea não.
"""


class ArquivoEpubInvalido(Exception):
    """O arquivo enviado não é um EPUB que dê para ler.

    Existe para que a rota de upload possa responder com uma mensagem clara. Sem
    ela, um arquivo corrompido viraria um erro 500 sem explicação, com o traço
    de pilha do ``zipfile`` no log.
    """


@dataclass
class EntradaIndice:
    """Uma entrada do índice do EPUB, já achatada."""

    arquivo: str
    """Nome do arquivo, sem pasta e sem âncora."""

    ancora: str | None
    """O ``id`` dentro do arquivo, quando a entrada aponta para um ponto dele."""

    titulo: str | None


@dataclass
class _Pedaco:
    """Um trecho de texto encontrado no EPUB, antes de virar capítulo."""

    titulo: str | None
    texto: str
    continuacao: bool = False
    """Este trecho é a continuação do capítulo anterior, não um capítulo novo.

    Acontece quando uma ferramenta de conversão (o Calibre faz isso) parte um
    arquivo grande no meio de um capítulo: o arquivo seguinte começa com o resto
    do capítulo anterior, e só depois vem a âncora do próximo.
    """


@dataclass
class CapituloExtraido:
    """Um capítulo encontrado no EPUB, antes de ir para o banco."""

    ordem: int
    titulo: str | None
    texto: str
    ignorado: bool = False
    """Sugestão da importação de que isto não é narrativa. O usuário confirma."""


@dataclass
class LivroExtraido:
    """A estrutura completa encontrada no EPUB, antes de ir para o banco."""

    titulo: str
    titulo_confirmado: bool
    """Se `titulo` veio de verdade do `dc:title` (`True`) ou é só o nome do
    arquivo usado como fallback (`False` — item 3.4a/6.2)."""
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
        raise ArquivoEpubInvalido(_motivo_de_nao_achar_capitulo(epub_lido, nome_arquivo))

    titulo_do_epub = _primeiro_metadado(epub_lido, "title")

    return LivroExtraido(
        titulo=titulo_do_epub or _titulo_do_nome(nome_arquivo),
        titulo_confirmado=titulo_do_epub is not None,
        autor=_primeiro_metadado(epub_lido, "creator"),
        idioma=_primeiro_metadado(epub_lido, "language"),
        identificador_epub=_identificador_unico(epub_lido),
        nome_arquivo=nome_arquivo,
        capitulos=capitulos,
    )


def _motivo_de_nao_achar_capitulo(epub_lido: epub.EpubBook, nome_arquivo: str) -> str:
    """Monta a mensagem de erro explicando por que o livro não rendeu capítulos.

    Vale distinguir o livro **só de imagem** do arquivo simplesmente vazio: uma
    história em quadrinhos é um EPUB perfeitamente válido em que cada página é uma
    imagem, e o texto está desenhado dentro dela. *Persepólis 2* tem 192
    documentos e 192 imagens, e zero caractere de texto. Dizer apenas "nenhum
    capítulo encontrado" deixaria o usuário procurando um defeito que não existe.
    """
    documentos = [
        item
        for item in epub_lido.get_items_of_type(ITEM_DOCUMENT)
        if not isinstance(item, (epub.EpubNav, epub.EpubNcx))
    ]
    imagens = list(epub_lido.get_items_of_type(ITEM_IMAGE))

    if documentos and len(imagens) >= len(documentos) / 2:
        return (
            f"O arquivo {nome_arquivo!r} parece ser um livro de imagens — uma história "
            f"em quadrinhos ou um livro digitalizado: são {len(documentos)} páginas e "
            f"{len(imagens)} imagens, sem texto para extrair. O Imagineer trabalha a "
            "partir do texto do livro, então não há o que importar daqui."
        )

    return (
        f"O arquivo {nome_arquivo!r} é um EPUB válido, mas nenhum capítulo com texto "
        "foi encontrado nele."
    )


def importar_epub(sessao: Session, conteudo: bytes, nome_arquivo: str) -> Livro:
    """Extrai a estrutura do EPUB e grava o Livro com seus Capítulos.

    Devolve o Livro já gravado, com o ``id`` preenchido.
    """
    extraido = extrair_epub(conteudo, nome_arquivo)

    livro = Livro(
        titulo=extraido.titulo,
        titulo_confirmado=extraido.titulo_confirmado,
        autor=extraido.autor,
        idioma=extraido.idioma,
        identificador_epub=extraido.identificador_epub,
        nome_arquivo=extraido.nome_arquivo,
    )
    livro.capitulos = [
        Capitulo(ordem=c.ordem, titulo=c.titulo, texto=c.texto, ignorado=c.ignorado)
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
# Extração dos capítulos
# --------------------------------------------------------------------------- #


def _extrair_capitulos(epub_lido: epub.EpubBook) -> list[CapituloExtraido]:
    """Percorre o spine montando a lista de capítulos com texto.

    A ordem e o conteúdo vêm do **spine**; os títulos e as fronteiras de capítulo
    vêm do **índice (TOC)**. Cada fonte resolve metade do problema: o spine é a
    ordem de leitura e está sempre presente, mas não traz títulos; o TOC traz
    títulos, mas é opcional e pode ser aninhado.

    Quando o índice aponta para **várias âncoras do mesmo arquivo**, o arquivo é
    dividido nesses pontos — porque aí as fronteiras de capítulo são as âncoras,
    não os arquivos (ver ``_dividir_por_ancoras``).
    """
    entradas = _entradas_do_indice(epub_lido)
    por_arquivo: dict[str, list[EntradaIndice]] = {}
    for entrada in entradas:
        por_arquivo.setdefault(entrada.arquivo, []).append(entrada)

    # Primeira passada: junta os pedaços de texto com o título e o nível de cada
    # um. A sugestão de ignorar só pode ser calculada depois, quando a mediana
    # de tamanho do livro inteiro for conhecida.
    pedacos: list[_Pedaco] = []
    for idref, _linear in epub_lido.spine:
        item = epub_lido.get_item_with_id(idref)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue

        # Documentos de navegação fazem parte da mecânica do formato, não da
        # obra — e aparecem no spine como se fossem capítulos.
        if isinstance(item, (epub.EpubNav, epub.EpubNcx)):
            continue

        conteudo = item.get_content()

        # Um "Sumário" em XHTML comum não é declarado como documento de
        # navegação, então a checagem de tipo acima não o pega.
        if _parece_pagina_de_navegacao(conteudo):
            continue

        deste_arquivo = por_arquivo.get(_caminho_sem_ancora(item.file_name), [])
        pedacos.extend(_dividir_documento(conteudo, deste_arquivo))

    pedacos = _juntar_continuacoes(pedacos)
    pedacos = [p for p in pedacos if len(p.texto) >= MINIMO_DE_CARACTERES]
    if not pedacos:
        return []

    mediana = statistics.median([len(p.texto) for p in pedacos])

    capitulos = []
    for posicao, pedaco in enumerate(pedacos, start=1):
        # O título de reserva é resolvido antes da sugestão, de propósito: se o
        # texto começa com "Créditos" ou "Prefácio", essa informação vale tanto
        # quanto se viesse do índice.
        titulo = pedaco.titulo or _titulo_do_texto(pedaco.texto)
        capitulos.append(
            CapituloExtraido(
                # A ordem é atribuída depois dos descartes: começa em 1 e não tem
                # lacunas. O que importa é a sequência de leitura do conteúdo, não
                # a posição original no arquivo.
                ordem=posicao,
                titulo=titulo,
                texto=pedaco.texto,
                ignorado=_sugerir_ignorar(
                    titulo=titulo, texto=pedaco.texto, mediana=mediana
                ),
            )
        )
    return capitulos


def _juntar_continuacoes(pedacos: list[_Pedaco]) -> list[_Pedaco]:
    """Cola no capítulo anterior os trechos que são continuação dele.

    O Calibre parte arquivos grandes em pedaços numerados (``..._split_000``,
    ``_split_001``), e o corte cai no meio de um capítulo. Em *Flores para
    Algernon*, o arquivo seguinte começava com 42 mil caracteres do relatório
    anterior antes da primeira âncora — que sem isto viraria um capítulo sem
    título, e o relatório apareceria partido em dois.
    """
    juntados: list[_Pedaco] = []
    for pedaco in pedacos:
        if pedaco.continuacao and juntados:
            anterior = juntados[-1]
            anterior.texto = f"{anterior.texto}\n\n{pedaco.texto}".strip()
            continue
        juntados.append(pedaco)
    return juntados


def _dividir_documento(conteudo: bytes, entradas: list[EntradaIndice]) -> list[_Pedaco]:
    """Transforma um documento do EPUB em um ou mais pedaços de capítulo.

    Na maioria dos livros há no máximo uma entrada de índice por arquivo, e o
    documento inteiro é um capítulo. Mas quando o índice aponta para **várias
    âncoras do mesmo arquivo**, as fronteiras de capítulo são as âncoras: em
    *Flores para Algernon*, um único arquivo continha 11 relatórios de progresso,
    e importá-lo inteiro produzia um capítulo de 131 mil caracteres em vez de 11.
    """
    # Basta UMA entrada com âncora para valer a pena examinar as posições: se a
    # âncora não estiver no começo do documento, o texto antes dela é resto do
    # capítulo anterior e precisa ser marcado como continuação. Atalhar quando há
    # só uma entrada faria esse texto ser atribuído ao capítulo errado.
    com_ancora = [entrada for entrada in entradas if entrada.ancora]
    if not com_ancora:
        primeira = entradas[0] if entradas else None
        return [
            _Pedaco(
                titulo=primeira.titulo if primeira else None,
                texto=_extrair_texto(conteudo),
            )
        ]

    return _dividir_por_ancoras(conteudo, entradas)


def _dividir_por_ancoras(
    conteudo: bytes, entradas: list[EntradaIndice]
) -> list[_Pedaco]:
    """Corta o documento nos pontos apontados pelas âncoras do índice.

    O corte acontece entre os filhos de um **contêiner**, que é o ancestral comum
    mais profundo de todas as âncoras. Na maioria dos livros esse contêiner é o
    próprio ``<body>``, mas em *O Processo* o documento inteiro estava embrulhado
    num único ``<div>``: cortar entre os filhos do corpo daria uma fatia só, e o
    capítulo de fragmentos não se dividiria nos seus 11 trechos.

    Nada de texto é perdido: o que estiver fora do contêiner entra na primeira
    fatia (se vier antes) ou na última (se vier depois).
    """
    try:
        arvore = lxml.html.fromstring(conteudo)
    except Exception:  # noqa: BLE001 - HTML irrecuperável
        return [_Pedaco(titulo=entradas[0].titulo, texto="")]

    for elemento in arvore.xpath("//script|//style"):
        elemento.drop_tree()

    corpo = arvore.find("body")
    if corpo is None:
        corpo = arvore

    # Localiza o elemento de cada âncora. Uma âncora declarada no índice mas
    # ausente do documento é simplesmente ignorada — melhor do que inventar um
    # corte no lugar errado.
    elementos: dict[int, object] = {}
    for entrada in entradas:
        if not entrada.ancora:
            continue
        achados = corpo.xpath(".//*[@id=$identificador]", identificador=entrada.ancora)
        if achados:
            elementos[id(entrada)] = achados[0]

    if not elementos:
        return [_Pedaco(titulo=entradas[0].titulo, texto=_extrair_texto(conteudo))]

    container = _container_de_corte(list(elementos.values()), corpo)
    filhos = list(container)

    # Para cada entrada, em que posição dos filhos do contêiner ela começa.
    inicios: list[tuple[int, EntradaIndice]] = []
    for entrada in entradas:
        elemento = elementos.get(id(entrada))
        if elemento is None:
            # Entrada sem âncora: representa o começo do arquivo.
            if not entrada.ancora:
                inicios.append((0, entrada))
            continue
        alvo = elemento
        while alvo.getparent() is not None and alvo.getparent() is not container:
            alvo = alvo.getparent()
        try:
            inicios.append((filhos.index(alvo), entrada))
        except ValueError:
            continue

    if not inicios:
        return [_Pedaco(titulo=entradas[0].titulo, texto=_extrair_texto(conteudo))]

    # Ordena pela posição no documento — a ordem do índice não é garantia — e
    # descarta cortes repetidos. Quando duas entradas caem na mesma posição,
    # prevalece a que tem âncora, por ser a mais específica: em *O Processo*, a
    # seção "Fragmentos" e o primeiro fragmento começam no mesmo ponto, e o
    # título útil é o do fragmento.
    inicios.sort(key=lambda par: par[0])
    unicos: list[tuple[int, EntradaIndice]] = []
    for posicao, entrada in inicios:
        if unicos and unicos[-1][0] == posicao:
            if entrada.ancora and not unicos[-1][1].ancora:
                unicos[-1] = (posicao, entrada)
            continue
        unicos.append((posicao, entrada))

    # O que está fora do contêiner precisa ir para algum lugar, ou desaparece.
    antes_do_container, depois_do_container = _vizinhos_do_container(container, corpo)

    pedacos: list[_Pedaco] = []

    # Texto antes do primeiro corte. Ele não é um capítulo novo: é o resto do
    # capítulo do arquivo anterior, partido ao meio por uma ferramenta de
    # conversão. Marcado como continuação para ser colado de volta em
    # ``_juntar_continuacoes``.
    inicio_do_miolo = filhos[: unicos[0][0]]
    if antes_do_container or inicio_do_miolo:
        texto_inicial = _texto_de(antes_do_container + inicio_do_miolo)
        if texto_inicial:
            pedacos.append(_Pedaco(titulo=None, texto=texto_inicial, continuacao=True))

    for indice, (posicao, entrada) in enumerate(unicos):
        ultimo = indice + 1 == len(unicos)
        fim = len(filhos) if ultimo else unicos[indice + 1][0]
        recorte = filhos[posicao:fim] + (depois_do_container if ultimo else [])
        pedacos.append(_Pedaco(titulo=entrada.titulo, texto=_texto_de(recorte)))

    return pedacos


def _container_de_corte(elementos: list, padrao):
    """O elemento cujos filhos servem de fatias para o corte.

    É o ancestral comum mais profundo de todas as âncoras. Usar sempre o
    ``<body>`` não serve: quando o documento está embrulhado num único ``<div>``,
    todas as âncoras caem no mesmo filho do corpo e o corte não acontece.
    """
    cadeias = [list(elemento.iterancestors()) for elemento in elementos]
    if not cadeias or not cadeias[0]:
        return padrao

    comuns = set(cadeias[0])
    for cadeia in cadeias[1:]:
        comuns &= set(cadeia)

    # A cadeia vai do pai para a raiz, então o primeiro comum é o mais profundo.
    for candidato in cadeias[0]:
        if candidato in comuns:
            return candidato
    return padrao


def _vizinhos_do_container(container, corpo) -> tuple[list, list]:
    """Devolve o que está no corpo antes e depois do contêiner de corte.

    Quando o contêiner não é o próprio corpo, esse conteúdo ficaria fora de todas
    as fatias e desapareceria da importação.
    """
    if container is corpo:
        return [], []

    ancestral = container
    while ancestral.getparent() is not None and ancestral.getparent() is not corpo:
        ancestral = ancestral.getparent()

    irmaos = list(corpo)
    if ancestral not in irmaos:
        return [], []

    posicao = irmaos.index(ancestral)
    return irmaos[:posicao], irmaos[posicao + 1 :]


def _sugerir_ignorar(
    *, titulo: str | None, texto: str, mediana: float
) -> bool:
    """Diz se este capítulo **parece** não ser narrativa.

    É só uma sugestão: nada é descartado, e o usuário confirma ou desmarca. A
    validação em dezoito livros reais mostrou que nenhum critério automático separa
    narrativa de apêndice com segurança, então a decisão fica com quem lê.

    Três sinais sugerem, e um protege — nesta ordem de precedência:

    - **Título conhecido** de material não-narrativo ("Créditos", "Glossário",
      "Notas ao Canto 1").
    - **Anúncio de outro livro da editora**, reconhecido pelo ISBN no texto.
    - **Tamanho** muito abaixo da mediana do próprio livro.
    - **Proteção**: um título claramente narrativo vence os dois. É o que salva o
      capítulo 26 de *O apanhador no campo de centeio*, que tem 11% da mediana do
      livro e é o desfecho da obra.

    Um terceiro sinal foi testado e **descartado**: a posição no índice. A ideia
    era que, num índice de dois níveis, o corpo do livro ficaria aninhado nas
    seções e o material pré/pós-textual na raiz — o que vale em três dos nove
    livros. Mas em *O Processo* a única seção aninhada é "Fragmentos", o apêndice,
    e os doze capítulos reais estão na raiz: o sinal se inverte e esconde o
    romance inteiro. Ele contribuía com exatamente um item nos nove primeiros
    livros de validação, e o
    risco era esse. Ver item 2.2 da especificação.
    """
    normalizado = _normalizar(titulo)

    # A ordem importa. O rótulo e o ISBN são os sinais mais confiáveis, então vêm
    # primeiro; a proteção por título narrativo existe para vencer o critério de
    # tamanho, que é o mais frouxo dos três.
    if normalizado.startswith(_ROTULOS_NAO_NARRATIVOS):
        return True

    if _parece_anuncio_de_editora(texto):
        return True

    if normalizado and _PADROES_NARRATIVOS.match(normalizado):
        return False

    return mediana > 0 and len(texto) < mediana * PROPORCAO_MINIMA_DA_MEDIANA


def _parece_anuncio_de_editora(texto: str) -> bool:
    """Diz se o texto é uma página de "compre agora e leia" de outro livro.

    Reconhecida pelo ISBN: um número de 13 dígitos começando em 978 ou 979 não
    aparece em prosa narrativa, mas aparece em toda página que lista um livro com
    seus dados de catálogo.
    """
    for numero in re.findall(r"(?<![0-9])[0-9]{13}(?![0-9])", texto):
        if numero.startswith(_PREFIXOS_DE_ISBN):
            return True
    return False


# --------------------------------------------------------------------------- #
# Leitura do índice
# --------------------------------------------------------------------------- #


def _entradas_do_indice(epub_lido: epub.EpubBook) -> list[EntradaIndice]:
    """Achata o índice do EPUB numa lista ordenada de entradas.

    O TOC pode ser aninhado em seções, então a função é recursiva. O aninhamento
    é achatado e descartado: ele parecia um bom sinal para separar corpo de
    apêndice, mas em *O Processo* significa o contrário (ver
    ``_sugerir_ignorar``).
    """
    entradas: list[EntradaIndice] = []

    def percorrer(itens) -> None:
        # Achado importando um EPUB real: o `.toc` do ebooklib às vezes
        # entrega uma entrada solta (um `Link`) em vez de uma lista com uma
        # entrada — sem normalizar aqui, `for item in itens` tenta iterar
        # direto sobre o `Link`, que não é iterável, e a importação quebra
        # com 500. `percorrer` é chamada tanto para o índice inteiro quanto,
        # recursivamente, para a seção e os filhos de cada entrada aninhada
        # — a normalização aqui cobre os três casos de uma vez.
        if not isinstance(itens, (list, tuple)):
            itens = [itens]
        for item in itens:
            # Uma seção do índice vem como (objeto da seção, lista de filhos).
            if isinstance(item, (tuple, list)):
                secao, filhos = item
                percorrer(secao)
                percorrer(filhos)
                continue

            href = getattr(item, "href", None)
            if not href:
                continue
            titulo = getattr(item, "title", None)
            arquivo, _, ancora = href.partition("#")
            entradas.append(
                EntradaIndice(
                    arquivo=_caminho_sem_ancora(arquivo),
                    ancora=ancora or None,
                    titulo=titulo.strip() if titulo else None,
                )
            )

    percorrer(epub_lido.toc)
    return entradas


def _caminho_sem_ancora(href: str) -> str:
    """Normaliza um caminho do EPUB para servir de chave de comparação.

    Descarta a âncora, porque o TOC costuma apontar para um ponto dentro do
    arquivo. Descarta também a pasta, porque o TOC e o manifesto podem escrever
    o mesmo arquivo com prefixos diferentes (``Text/cap3.xhtml`` e
    ``cap3.xhtml``).
    """
    return PurePosixPath(href.split("#")[0]).name


# --------------------------------------------------------------------------- #
# Conversão de HTML em texto
# --------------------------------------------------------------------------- #


def _extrair_texto(conteudo: bytes) -> str:
    """Converte o HTML de um documento do EPUB em texto simples."""
    try:
        arvore = lxml.html.fromstring(conteudo)
    except Exception:  # noqa: BLE001 - documento vazio ou HTML irrecuperável
        return ""

    for elemento in arvore.xpath("//script|//style"):
        elemento.drop_tree()

    return _texto_da_arvore(arvore)


def _texto_de(elementos: list) -> str:
    """Extrai o texto de um recorte de elementos, usado ao dividir por âncoras.

    Os elementos são copiados para um contêiner temporário porque a extração
    marca as quebras de parágrafo alterando a árvore — e alterar a original
    estragaria os recortes seguintes.
    """
    container = lxml.html.Element("div")
    for elemento in elementos:
        container.append(copy.deepcopy(elemento))
    return _texto_da_arvore(container)


def _texto_da_arvore(arvore) -> str:
    """Converte uma árvore HTML em texto simples, preservando parágrafos.

    Preservar as quebras importa porque é este texto que a IA vai ler: um
    capítulo inteiro numa única linha contínua perde a estrutura da narrativa.
    """
    # Insere as quebras no "tail" de cada elemento (o texto que vem depois do
    # fechamento da tag). É o que mantém a separação entre parágrafos quando o
    # texto de toda a árvore é concatenado.
    for elemento in arvore.xpath("//br"):
        elemento.tail = "\n" + (elemento.tail or "")
    for elemento in arvore.xpath("|".join(f"//{tag}" for tag in _TAGS_DE_BLOCO)):
        elemento.tail = "\n\n" + (elemento.tail or "")

    texto = arvore.text_content().replace("\xa0", " ")
    # Normaliza as quebras de linha do Windows e do Mac clássico antes de
    # qualquer outra coisa. Sem isso, um "\r\n" do arquivo original deixa o "\r"
    # sobrando no meio do texto, que iria assim para o prompt da IA.
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _parece_pagina_de_navegacao(conteudo: bytes) -> bool:
    """Diz se um documento é um sumário disfarçado de capítulo.

    O critério é a proporção do texto que está dentro de links: uma página de
    sumário é quase só links, um capítulo praticamente não tem nenhum. Ver
    ``PROPORCAO_DE_LINKS_PARA_NAVEGACAO`` para os números medidos num livro real.
    """
    try:
        arvore = lxml.html.fromstring(conteudo)
    except Exception:  # noqa: BLE001 - documento vazio ou HTML irrecuperável
        return False

    for elemento in arvore.xpath("//script|//style"):
        elemento.drop_tree()

    links = arvore.xpath("//a")
    if len(links) < MINIMO_DE_LINKS_PARA_NAVEGACAO:
        return False

    # Conta sem espaços: a indentação do HTML não deve pesar na proporção.
    def sem_espacos(texto: str) -> int:
        return len("".join(texto.split()))

    total = sem_espacos(arvore.text_content())
    if total == 0:
        return False

    dentro_de_links = sum(sem_espacos(link.text_content()) for link in links)
    return dentro_de_links / total >= PROPORCAO_DE_LINKS_PARA_NAVEGACAO


# --------------------------------------------------------------------------- #
# Metadados
# --------------------------------------------------------------------------- #


def _identificador_unico(epub_lido: epub.EpubBook) -> str | None:
    """Devolve o identificador que o EPUB declara como sendo o do livro.

    Um EPUB pode listar vários ``dc:identifier`` — ASIN, ISBN, id do Calibre,
    UUID — e o pacote aponta, pelo atributo ``unique-identifier``, qual deles
    identifica a obra. **Não é necessariamente o primeiro da lista**: num livro
    real, o declarado era o último dos cinco.

    Pegar o primeiro faria a detecção de livro repetido depender da ordem em que
    o arquivo foi escrito: duas conversões do mesmo livro poderiam listar os
    identificadores em ordem diferente e deixar de casar.
    """
    declarado = (getattr(epub_lido, "uid", None) or "").strip()
    if declarado:
        return declarado

    # Sem declaração, o primeiro é o melhor palpite disponível.
    return _primeiro_metadado(epub_lido, "identifier")


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


def _titulo_do_texto(texto: str) -> str | None:
    """Tira um título da primeira linha do capítulo, quando ela parece um título.

    Muitos livros põem o nome do capítulo no corpo do texto e não no índice. Ver
    ``MAXIMO_DO_TITULO_DE_RESERVA`` para os números medidos.

    Duas condições evitam transformar a primeira frase da narrativa em título:
    a linha precisa ser curta, e não pode terminar em pontuação de frase. É o que
    separa "A GAROTA" de "— Levante-se." ou de um parágrafo que começa a história.
    """
    primeira = texto.split("\n", 1)[0].strip()
    if not primeira or len(primeira) > MAXIMO_DO_TITULO_DE_RESERVA:
        return None
    if primeira[-1] in ".,;:!?":
        return None
    return primeira


def _titulo_do_nome(nome_arquivo: str) -> str:
    """Usa o nome do arquivo como título, para EPUBs sem ``dc:title``.

    Só o título tem valor de reserva, porque é obrigatório no modelo e é o que
    identifica o livro na tela. Um livro sem título na lista seria inutilizável;
    um livro sem autor, não.
    """
    return PurePosixPath(nome_arquivo).stem or nome_arquivo


def _normalizar(texto: str | None) -> str:
    """Põe o texto em minúsculas e sem acentos, para comparar títulos.

    Necessário porque os rótulos de comparação são escritos sem acento: assim
    "Prefácio", "PREFACIO" e "prefacio" casam todos com ``prefacio``.
    """
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.strip().lower()
