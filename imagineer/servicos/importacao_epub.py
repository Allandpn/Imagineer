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
from ebooklib import ITEM_DOCUMENT, epub
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

PROPORCAO_MINIMA_DA_MEDIANA = 0.25
"""Abaixo desta fração da mediana, o capítulo é **sugerido** como ignorado.

Medido em cinco livros reais, comparando o menor capítulo narrativo de cada um
com a mediana do próprio livro: 78% (Odisseia), 46% (A Vontade de Muitos), 40%
(Mistborn) e 33% (Devoradores de Estrelas). O limite de 25% fica abaixo do menor
deles, com margem — então nenhum capítulo narrativo desses livros é sugerido só
por ser curto.

Note que o critério é **relativo à mediana do próprio livro**, não absoluto: a
mediana variou de 17 mil a 44 mil caracteres entre os cinco. Um limite fixo
serviria para um livro e falharia nos outros.
"""

_TAGS_DE_BLOCO = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "tr", "pre")

_ROTULOS_NAO_NARRATIVOS = (
    "abreviatura", "agradecimento", "anexo", "apendice", "apresentacao",
    "bibliografia", "citacao", "colofao", "copyright", "credito", "dedicatoria",
    "epigrafe", "errata", "ficha tecnica", "glossario", "indice", "introducao",
    "lugares", "mapa", "nota", "personagens", "posfacio", "prefacio",
    "publicidade", "sobre a autora", "sobre o autor", "sumario",
)
"""Títulos que costumam nomear material não-narrativo.

Comparados **sem acento e em minúsculas**, e só no começo do título — "Notas ao
Canto 1" casa com ``nota``, mas um capítulo chamado "A nota final" não casaria.
A lista vem dos cinco livros reais usados na validação; é uma heurística de
sugestão, não uma regra: o usuário confirma.
"""

_PADROES_NARRATIVOS = re.compile(
    r"^(capitulo|canto|prologo|epilogo|interludio|parte|livro)\b"
    # Sem \b no fim: o índice de "Flores para Algernon" escreve "Relatorio de
    # Progreso", com um "s" só, e o prefixo truncado precisa casar com as duas
    # grafias. Um \b aqui nunca casaria, porque entre "s" e "o" de "progreso"
    # não existe fronteira de palavra.
    r"|^relatorio de progres"
    r"|^[\divxlcIVXLC]+$"
)
"""Títulos que são narrativa com certeza suficiente para **proteger** o capítulo.

Vence qualquer sugestão de ignorar. É o que impede de esconder o ``PRÓLOGO`` do
Mistborn, que fica no primeiro nível do índice junto dos créditos, ou um
capítulo curto que ficou abaixo do limite de tamanho.
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
    nivel: int
    """0 para entradas na raiz do índice, 1+ para as aninhadas em seções."""


@dataclass
class _Pedaco:
    """Um trecho de texto encontrado no EPUB, antes de virar capítulo."""

    titulo: str | None
    texto: str
    nivel: int | None
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
        identificador_epub=_identificador_unico(epub_lido),
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

    indice_tem_niveis = any(entrada.nivel > 0 for entrada in entradas)

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

    return [
        CapituloExtraido(
            # A ordem é atribuída depois dos descartes: começa em 1 e não tem
            # lacunas. O que importa é a sequência de leitura do conteúdo, não a
            # posição original no arquivo.
            ordem=posicao,
            titulo=pedaco.titulo,
            texto=pedaco.texto,
            ignorado=_sugerir_ignorar(
                titulo=pedaco.titulo,
                tamanho=len(pedaco.texto),
                mediana=mediana,
                nivel=pedaco.nivel,
                indice_tem_niveis=indice_tem_niveis,
            ),
        )
        for posicao, pedaco in enumerate(pedacos, start=1)
    ]


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
                nivel=primeira.nivel if primeira else None,
            )
        ]

    return _dividir_por_ancoras(conteudo, entradas)


def _dividir_por_ancoras(
    conteudo: bytes, entradas: list[EntradaIndice]
) -> list[_Pedaco]:
    """Corta o documento nos pontos apontados pelas âncoras do índice.

    O corte é feito entre os **filhos diretos do corpo** do documento: para cada
    âncora, subimos da tag que tem o ``id`` até o ancestral que é filho do corpo,
    e é aí que o capítulo começa.

    Se duas âncoras caírem no mesmo filho do corpo, não há como separá-las e as
    duas entradas viram um pedaço só, com o título da primeira. Preferir juntar a
    arriscar perder texto é a mesma escolha que orienta o resto do módulo.
    """
    try:
        arvore = lxml.html.fromstring(conteudo)
    except Exception:  # noqa: BLE001 - HTML irrecuperável
        return [_Pedaco(titulo=entradas[0].titulo, texto="", nivel=entradas[0].nivel)]

    for elemento in arvore.xpath("//script|//style"):
        elemento.drop_tree()

    corpo = arvore.find("body")
    if corpo is None:
        corpo = arvore
    filhos = list(corpo)

    # Para cada entrada, em que posição dos filhos do corpo ela começa.
    inicios: list[tuple[int, EntradaIndice]] = []
    for entrada in entradas:
        if not entrada.ancora:
            inicios.append((0, entrada))
            continue
        encontrados = corpo.xpath(".//*[@id=$identificador]", identificador=entrada.ancora)
        if not encontrados:
            # Âncora declarada no índice mas ausente do documento: ignora a
            # entrada em vez de inventar um corte.
            continue
        ancestral = encontrados[0]
        while ancestral.getparent() is not None and ancestral.getparent() is not corpo:
            ancestral = ancestral.getparent()
        try:
            inicios.append((filhos.index(ancestral), entrada))
        except ValueError:
            continue

    if not inicios:
        return [
            _Pedaco(
                titulo=entradas[0].titulo,
                texto=_extrair_texto(conteudo),
                nivel=entradas[0].nivel,
            )
        ]

    # Ordena pela posição no documento — a ordem do índice não é garantia — e
    # descarta cortes repetidos, mantendo o primeiro título de cada posição.
    inicios.sort(key=lambda par: par[0])
    unicos: list[tuple[int, EntradaIndice]] = []
    for posicao, entrada in inicios:
        if unicos and unicos[-1][0] == posicao:
            continue
        unicos.append((posicao, entrada))

    pedacos: list[_Pedaco] = []

    # Texto antes do primeiro corte. Sem isso ele desapareceria — e ele não é um
    # capítulo novo, é o resto do capítulo do arquivo anterior, partido ao meio
    # por uma ferramenta de conversão. Marcado como continuação para ser colado
    # de volta em ``_juntar_continuacoes``.
    if unicos[0][0] > 0:
        pedacos.append(
            _Pedaco(
                titulo=None,
                texto=_texto_de(filhos[: unicos[0][0]]),
                nivel=unicos[0][1].nivel,
                continuacao=True,
            )
        )

    for indice, (posicao, entrada) in enumerate(unicos):
        fim = unicos[indice + 1][0] if indice + 1 < len(unicos) else len(filhos)
        pedacos.append(
            _Pedaco(
                titulo=entrada.titulo,
                texto=_texto_de(filhos[posicao:fim]),
                nivel=entrada.nivel,
            )
        )

    return pedacos


def _sugerir_ignorar(
    *,
    titulo: str | None,
    tamanho: int,
    mediana: float,
    nivel: int | None,
    indice_tem_niveis: bool,
) -> bool:
    """Diz se este capítulo **parece** não ser narrativa.

    É só uma sugestão: nada é descartado, e o usuário confirma ou desmarca. A
    validação em cinco livros reais mostrou que nenhum critério automático separa
    narrativa de apêndice com segurança, então a decisão fica com quem lê.

    Três sinais somam, e um protege:

    - **Título conhecido** de material não-narrativo ("Créditos", "Glossário",
      "Notas ao Canto 1").
    - **Tamanho** muito abaixo da mediana do próprio livro.
    - **Posição no índice**: num índice de dois níveis, o corpo do livro fica
      aninhado nas seções e o material pré/pós-textual fica na raiz. Só vale
      para documentos que *têm* entrada no índice — um documento sem entrada
      nenhuma pode muito bem ser narrativa, como as duas versões alternativas da
      cena final de *A Vontade de Muitos*.
    - **Proteção**: um título claramente narrativo vence todos os outros sinais.
    """
    normalizado = _normalizar(titulo)

    if normalizado and _PADROES_NARRATIVOS.match(normalizado):
        return False

    if normalizado.startswith(_ROTULOS_NAO_NARRATIVOS):
        return True

    if mediana > 0 and tamanho < mediana * PROPORCAO_MINIMA_DA_MEDIANA:
        return True

    return indice_tem_niveis and nivel == 0


# --------------------------------------------------------------------------- #
# Leitura do índice
# --------------------------------------------------------------------------- #


def _entradas_do_indice(epub_lido: epub.EpubBook) -> list[EntradaIndice]:
    """Achata o índice do EPUB numa lista ordenada de entradas.

    O TOC pode ser aninhado em seções, então a função é recursiva. O nível é
    preservado porque é um sinal útil: num índice de dois níveis, o corpo do
    livro fica aninhado e o material pré/pós-textual fica na raiz.
    """
    entradas: list[EntradaIndice] = []

    def percorrer(itens, nivel: int) -> None:
        for item in itens:
            # Uma seção do índice vem como (objeto da seção, lista de filhos).
            if isinstance(item, (tuple, list)):
                percorrer([item[0]], nivel)
                percorrer(item[1], nivel + 1)
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
                    nivel=nivel,
                )
            )

    percorrer(epub_lido.toc, 0)
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
