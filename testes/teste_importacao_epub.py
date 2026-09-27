"""Testes da importação de EPUB (item 2.2 da especificação).

Os EPUBs de teste são construídos aqui mesmo, com o próprio ``ebooklib``, em vez
de guardar arquivos no repositório. Duas razões: cada teste declara exatamente a
situação que quer exercitar (sem índice, sem autor, capítulo vazio), e não é
preciso versionar arquivos binários para isso.
"""

import io

import pytest
from ebooklib import epub
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Livro
from imagineer.servicos.importacao_epub import (
    ArquivoEpubInvalido,
    extrair_epub,
    importar_epub,
    livros_com_mesmo_identificador,
)

TEXTO_LONGO = "Este é um parágrafo com texto suficiente para não ser descartado. " * 3


def _montar_epub(
    *,
    titulo: str | None = "A Guerra dos Tronos",
    autor: str | None = "George R. R. Martin",
    idioma: str | None = "pt-BR",
    identificador: str | None = "urn:isbn:9788580410150",
    capitulos: list[tuple[str, str | None]] | None = None,
    com_indice: bool = True,
) -> bytes:
    """Gera os bytes de um EPUB sob medida para um teste.

    ``capitulos`` é uma lista de (conteúdo HTML, título no índice). Um título
    ``None`` cria um capítulo que existe no spine mas não aparece no índice.
    """
    if capitulos is None:
        capitulos = [
            (f"<h1>Bran</h1><p>{TEXTO_LONGO}</p>", "Bran"),
            (f"<h1>Catelyn</h1><p>{TEXTO_LONGO}</p>", "Catelyn"),
        ]

    livro = epub.EpubBook()
    # Sempre define o identificador, ainda que vazio: o formato EPUB exige o
    # elemento, e o ebooklib inventa um UUID se ele não existir. Passar vazio é
    # o que reproduz o caso real de um arquivo convertido sem identificador.
    livro.set_identifier(identificador or "")
    if titulo:
        livro.set_title(titulo)
    if idioma:
        livro.set_language(idioma)
    if autor:
        livro.add_author(autor)

    itens = []
    entradas_do_indice = []
    for indice, (html, titulo_do_indice) in enumerate(capitulos, start=1):
        item = epub.EpubHtml(
            title=titulo_do_indice or "", file_name=f"c{indice}.xhtml", lang=idioma
        )
        item.content = html
        livro.add_item(item)
        itens.append(item)
        if titulo_do_indice:
            entradas_do_indice.append(item)

    livro.toc = tuple(entradas_do_indice) if com_indice else ()
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", *itens]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Extração dos metadados
# --------------------------------------------------------------------------- #


def teste_extrai_os_metadados_do_epub() -> None:
    """Os quatro metadados Dublin Core chegam ao objeto extraído."""
    extraido = extrair_epub(_montar_epub(), "guerra.epub")

    assert extraido.titulo == "A Guerra dos Tronos"
    assert extraido.autor == "George R. R. Martin"
    assert extraido.idioma == "pt-BR"
    assert extraido.identificador_epub == "urn:isbn:9788580410150"
    assert extraido.nome_arquivo == "guerra.epub"


def teste_sem_titulo_usa_o_nome_do_arquivo() -> None:
    """O título é obrigatório no modelo, então tem valor de reserva.

    Um livro sem título na lista do app seria inutilizável — diferente de um
    livro sem autor, que só fica com um campo vazio.
    """
    extraido = extrair_epub(_montar_epub(titulo=None), "meu-livro-favorito.epub")

    assert extraido.titulo == "meu-livro-favorito"


def teste_campos_ausentes_ficam_nulos() -> None:
    """Autor, idioma e identificador não têm reserva: ficam nulos.

    O identificador vazio é o caso realista: o formato EPUB exige o elemento,
    então ele existe no arquivo mas sem valor — é o que se vê em arquivos
    convertidos. O serviço trata isso como ausência.
    """
    extraido = extrair_epub(
        _montar_epub(autor=None, idioma=None, identificador=None), "sem-dados.epub"
    )

    assert extraido.autor is None
    assert extraido.idioma is None
    assert extraido.identificador_epub is None


# --------------------------------------------------------------------------- #
# Extração dos capítulos
# --------------------------------------------------------------------------- #


def teste_capitulos_saem_na_ordem_do_spine_com_titulos_do_indice() -> None:
    """A ordem vem do spine; os títulos, do índice."""
    extraido = extrair_epub(_montar_epub(), "guerra.epub")

    assert [c.ordem for c in extraido.capitulos] == [1, 2]
    assert [c.titulo for c in extraido.capitulos] == ["Bran", "Catelyn"]


def teste_documento_de_navegacao_nao_vira_capitulo() -> None:
    """O ``nav.xhtml`` está no spine, mas é mecânica do formato, não a obra."""
    extraido = extrair_epub(_montar_epub(), "guerra.epub")

    assert len(extraido.capitulos) == 2
    assert all("Índice" not in (c.titulo or "") for c in extraido.capitulos)


def teste_capitulo_fora_do_indice_fica_sem_titulo() -> None:
    """O modelo aceita título nulo justamente porque o índice é incompleto."""
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO}</p>", "Com título"),
                (f"<p>{TEXTO_LONGO}</p>", None),
            ]
        ),
        "guerra.epub",
    )

    assert [c.titulo for c in extraido.capitulos] == ["Com título", None]


def teste_epub_sem_indice_ainda_importa_os_capitulos() -> None:
    """Sem índice nenhum, o spine sozinho já dá ordem e conteúdo."""
    extraido = extrair_epub(
        _montar_epub(
            com_indice=False,
            capitulos=[
                (f"<p>{TEXTO_LONGO}</p>", None),
                (f"<p>{TEXTO_LONGO}</p>", None),
            ],
        ),
        "sem-indice.epub",
    )

    assert len(extraido.capitulos) == 2
    assert [c.ordem for c in extraido.capitulos] == [1, 2]
    assert all(c.titulo is None for c in extraido.capitulos)


def teste_paginas_sem_texto_util_sao_descartadas() -> None:
    """Capa e folha de rosto não são capítulos.

    O limite de caracteres é baixo o bastante para pegar estas páginas sem
    ameaçar um capítulo curto de verdade.
    """
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                ("<p>Capa</p>", "Capa"),
                ("<p>Todos os direitos reservados.</p>", "Créditos"),
                (f"<p>{TEXTO_LONGO}</p>", "Capítulo de verdade"),
            ]
        ),
        "guerra.epub",
    )

    assert [c.titulo for c in extraido.capitulos] == ["Capítulo de verdade"]


def teste_ordem_nao_tem_lacunas_depois_dos_descartes() -> None:
    """A ordem é atribuída depois de descartar, começando em 1.

    Se ela viesse da posição no arquivo, a numeração pularia justamente as
    páginas descartadas — e a listagem no app teria buracos.
    """
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                ("<p>Capa</p>", "Capa"),
                (f"<p>{TEXTO_LONGO}</p>", "Primeiro"),
                ("<p>Página vazia</p>", None),
                (f"<p>{TEXTO_LONGO}</p>", "Segundo"),
            ]
        ),
        "guerra.epub",
    )

    assert [(c.ordem, c.titulo) for c in extraido.capitulos] == [
        (1, "Primeiro"),
        (2, "Segundo"),
    ]


# --------------------------------------------------------------------------- #
# Conversão do HTML em texto
# --------------------------------------------------------------------------- #


def teste_texto_preserva_as_quebras_de_paragrafo() -> None:
    """Um capítulo numa única linha contínua perderia a estrutura da narrativa."""
    html = (
        "<h1>O Título</h1>"
        "<p>Primeiro parágrafo, longo o bastante para passar do limite mínimo.</p>"
        "<p>Segundo parágrafo, também com bastante texto para não ser cortado.</p>"
    )
    extraido = extrair_epub(
        _montar_epub(capitulos=[(html, "Cap")]), "guerra.epub"
    )

    texto = extraido.capitulos[0].texto
    assert texto.startswith("O Título\n\nPrimeiro parágrafo")
    assert "\n\nSegundo parágrafo" in texto


def teste_texto_descarta_script_e_style() -> None:
    """Código e folhas de estilo não fazem parte da obra."""
    html = (
        "<style>p { color: red }</style>"
        "<script>alert('oi')</script>"
        f"<p>{TEXTO_LONGO}</p>"
    )
    extraido = extrair_epub(_montar_epub(capitulos=[(html, "Cap")]), "guerra.epub")

    texto = extraido.capitulos[0].texto
    assert "color: red" not in texto
    assert "alert" not in texto
    assert "Este é um parágrafo" in texto


def teste_texto_normaliza_espacos_e_linhas_em_branco() -> None:
    """O HTML de EPUBs vem cheio de indentação e linhas em branco do próprio arquivo."""
    html = f"<p>Muitos     espaços    aqui.</p>\n\n\n\n<p>{TEXTO_LONGO}</p>"
    extraido = extrair_epub(_montar_epub(capitulos=[(html, "Cap")]), "guerra.epub")

    texto = extraido.capitulos[0].texto
    assert "Muitos espaços aqui." in texto
    assert "\n\n\n" not in texto


def teste_quebra_de_linha_simples_no_br() -> None:
    """``<br>`` separa versos ou linhas, não parágrafos."""
    html = f"<p>Primeira linha<br/>Segunda linha</p><p>{TEXTO_LONGO}</p>"
    extraido = extrair_epub(_montar_epub(capitulos=[(html, "Cap")]), "guerra.epub")

    assert "Primeira linha\nSegunda linha" in extraido.capitulos[0].texto


# --------------------------------------------------------------------------- #
# Erros
# --------------------------------------------------------------------------- #


def teste_arquivo_que_nao_e_epub_da_erro_claro() -> None:
    """Um arquivo corrompido não pode virar erro 500 sem explicação."""
    with pytest.raises(ArquivoEpubInvalido) as erro:
        extrair_epub(b"isto nao e um epub", "qualquer-coisa.txt")

    assert "qualquer-coisa.txt" in str(erro.value)


def teste_epub_valido_sem_capitulo_aproveitavel_da_erro() -> None:
    """Importar um livro vazio não serviria para nada.

    Melhor falhar na importação, com mensagem, do que descobrir o problema
    depois, na tela do app.
    """
    with pytest.raises(ArquivoEpubInvalido) as erro:
        extrair_epub(
            _montar_epub(capitulos=[("<p>Capa</p>", "Capa")]), "so-capa.epub"
        )

    assert "nenhum capítulo" in str(erro.value)


# --------------------------------------------------------------------------- #
# Gravação no banco
# --------------------------------------------------------------------------- #


def teste_importar_grava_livro_e_capitulos(sessao_com_tabelas: Session) -> None:
    """A importação completa deixa o livro e os capítulos no banco."""
    livro = importar_epub(sessao_com_tabelas, _montar_epub(), "guerra.epub")

    assert livro.id is not None
    assert livro.titulo == "A Guerra dos Tronos"
    assert livro.data_importacao is not None
    assert [c.ordem for c in livro.capitulos] == [1, 2]
    assert [c.titulo for c in livro.capitulos] == ["Bran", "Catelyn"]
    assert "Este é um parágrafo" in livro.capitulos[0].texto


def teste_importar_duas_vezes_cria_dois_livros(sessao_com_tabelas: Session) -> None:
    """Nada impede reimportar: o identificador avisa, não bloqueia (item 3.4a)."""
    dados = _montar_epub()
    importar_epub(sessao_com_tabelas, dados, "guerra.epub")
    importar_epub(sessao_com_tabelas, dados, "guerra.epub")

    assert len(sessao_com_tabelas.query(Livro).all()) == 2
    assert len(sessao_com_tabelas.query(Capitulo).all()) == 4


def teste_identificador_encontra_o_livro_ja_importado(
    sessao_com_tabelas: Session,
) -> None:
    """É como o app avisa "este livro parece já ter sido importado"."""
    livro = importar_epub(sessao_com_tabelas, _montar_epub(), "guerra.epub")

    encontrados = livros_com_mesmo_identificador(
        sessao_com_tabelas, "urn:isbn:9788580410150"
    )

    assert [l.id for l in encontrados] == [livro.id]


def teste_identificador_nulo_nao_casa_com_nada(sessao_com_tabelas: Session) -> None:
    """Dois EPUBs sem identificador não são "o mesmo livro" só por isso."""
    importar_epub(
        sessao_com_tabelas, _montar_epub(identificador=None), "sem-id.epub"
    )

    assert livros_com_mesmo_identificador(sessao_com_tabelas, None) == []
    assert livros_com_mesmo_identificador(sessao_com_tabelas, "") == []


# --------------------------------------------------------------------------- #
# Um EPUB parecido com os de verdade
# --------------------------------------------------------------------------- #


def teste_epub_realista_com_indice_aninhado_subpastas_e_ancoras() -> None:
    """Exercita de uma vez o que costuma quebrar o parsing de EPUB.

    Este arquivo tem, de propósito: documentos em subpasta (``Text/``), capa,
    folha de rosto e página de créditos, índice **aninhado** em partes, e uma
    entrada do índice apontando para uma **âncora** no meio de um capítulo.

    Os EPUBs montados pelos outros testes são simples demais para pegar esses
    casos, e é neles que um parsing ingênuo produz capítulos duplicados, títulos
    trocados ou capas viradas capítulo.
    """
    livro = epub.EpubBook()
    livro.set_identifier("urn:isbn:9788580410150")
    livro.set_title("A Guerra dos Tronos")
    livro.set_language("pt-BR")
    livro.add_author("George R. R. Martin")

    def documento(nome: str, html: str, titulo: str = "") -> epub.EpubHtml:
        item = epub.EpubHtml(title=titulo, file_name=nome, lang="pt-BR")
        item.content = html
        livro.add_item(item)
        return item

    capa = documento("Text/capa.xhtml", "<p>Capa</p>", "Capa")
    rosto = documento("Text/rosto.xhtml", "<p>A Guerra dos Tronos</p>", "Folha de rosto")
    prologo = documento("Text/prologo.xhtml", f"<h1>Prólogo</h1><p>{TEXTO_LONGO}</p>")
    cap1 = documento(
        "Text/cap01.xhtml",
        f'<h1>Bran</h1><p>{TEXTO_LONGO}</p><h2 id="meio">Parte 2</h2><p>{TEXTO_LONGO}</p>',
    )
    cap2 = documento("Text/cap02.xhtml", f"<h1>Catelyn</h1><p>{TEXTO_LONGO}</p>")
    creditos = documento("Text/creditos.xhtml", "<p>Todos os direitos reservados</p>", "Créditos")

    livro.toc = (
        epub.Link("Text/capa.xhtml", "Capa", "capa"),
        (
            epub.Section("Primeira Parte"),
            (
                epub.Link("Text/prologo.xhtml", "Prólogo", "prologo"),
                epub.Link("Text/cap01.xhtml", "Bran", "c1"),
                epub.Link("Text/cap01.xhtml#meio", "Bran — parte 2", "c1b"),
            ),
        ),
        (epub.Section("Segunda Parte"), (epub.Link("Text/cap02.xhtml", "Catelyn", "c2"),)),
    )
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", capa, rosto, prologo, cap1, cap2, creditos]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)

    extraido = extrair_epub(buffer.getvalue(), "guerra-dos-tronos.epub")

    # Capa, folha de rosto, créditos e o documento de navegação ficaram de fora.
    # O arquivo cap01.xhtml aparece DUAS vezes no índice — uma para o começo e
    # uma para a âncora "#meio" — então ele é dividido em dois capítulos.
    assert [(c.ordem, c.titulo) for c in extraido.capitulos] == [
        (1, "Prólogo"),
        (2, "Bran"),
        (3, "Bran — parte 2"),
        (4, "Catelyn"),
    ]

    # O índice aninhado foi achatado e os títulos casaram apesar do prefixo de
    # pasta usado no href.
    assert extraido.capitulos[0].titulo == "Prólogo"

    # A divisão corta no ponto certo: o texto antes da âncora fica no primeiro
    # pedaço, e o de depois no segundo. Nada é duplicado nem perdido.
    assert "Parte 2" not in extraido.capitulos[1].texto
    assert extraido.capitulos[2].texto.startswith("Parte 2")


# --------------------------------------------------------------------------- #
# Casos descobertos rodando contra um EPUB real
# --------------------------------------------------------------------------- #


def teste_usa_o_identificador_declarado_e_nao_o_primeiro_da_lista() -> None:
    """Um EPUB pode listar vários identificadores; vale o que ele declara.

    Caso real: um livro publicado listava cinco ``dc:identifier`` — ASIN, ISBN,
    id do Calibre, UUID e um ASIN em forma de URN — e o declarado no atributo
    ``unique-identifier`` do pacote era o **último**. Pegar o primeiro faria a
    detecção de livro repetido depender da ordem em que o arquivo foi escrito.
    """
    livro = epub.EpubBook()
    # add_metadata acrescenta identificadores sem mexer no declarado.
    livro.add_metadata("DC", "identifier", "asin:PRIMEIRO-DA-LISTA")
    livro.add_metadata("DC", "identifier", "calibre:12345")
    # set_identifier define qual é o identificador único do livro.
    livro.set_identifier("urn:isbn:O-DECLARADO")
    livro.set_title("Livro com vários identificadores")
    item = epub.EpubHtml(title="Cap", file_name="c1.xhtml")
    item.content = f"<p>{TEXTO_LONGO}</p>"
    livro.add_item(item)
    livro.toc = (item,)
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", item]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    extraido = extrair_epub(buffer.getvalue(), "varios-ids.epub")

    assert extraido.identificador_epub == "urn:isbn:O-DECLARADO"


def teste_sumario_em_xhtml_nao_vira_capitulo() -> None:
    """Um "Sumário" como documento comum não é declarado como navegação.

    Caso real: o livro trazia, depois do último capítulo, uma página de sumário
    em XHTML comum — 86 links e 99,3% do texto dentro deles. Ela não é um
    ``EpubNav``, então a checagem de tipo não a pegava, e ela entrava no catálogo
    como se fosse um capítulo.
    """
    links = "".join(
        f'<p><a href="c{i}.xhtml">Capítulo {i}</a></p>' for i in range(1, 30)
    )
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO}</p>", "Capítulo de verdade"),
                (f"<h1>Sumário</h1>{links}", "Sumário"),
            ]
        ),
        "com-sumario.epub",
    )

    assert [c.titulo for c in extraido.capitulos] == ["Capítulo de verdade"]


def teste_capitulo_com_poucas_notas_de_rodape_nao_e_descartado() -> None:
    """O outro lado do critério: link não é sinal de página de navegação.

    A exigência de vários links, e de que eles dominem o texto, é o que impede
    de descartar um capítulo legítimo que cita uma nota de rodapé.
    """
    html = (
        f"<p>{TEXTO_LONGO}</p>"
        '<p>Como já foi dito <a href="nota1.xhtml">[1]</a> e também '
        '<a href="nota2.xhtml">[2]</a>.</p>'
        f"<p>{TEXTO_LONGO}</p>"
    )
    extraido = extrair_epub(_montar_epub(capitulos=[(html, "Com notas")]), "notas.epub")

    assert [c.titulo for c in extraido.capitulos] == ["Com notas"]


def teste_texto_nao_deixa_retorno_de_carro_sobrando() -> None:
    """Quebras de linha do Windows não podem vazar para o texto do capítulo.

    Caso real: o livro usava ``\r\n`` no HTML, e o texto extraído saía com um
    ``\r`` solto no meio dos parágrafos — que iria assim para o prompt da IA.
    """
    html = f"<p>Primeiro parágrafo.</p>\r\n<p>{TEXTO_LONGO}</p>\r\n"
    extraido = extrair_epub(_montar_epub(capitulos=[(html, "Cap")]), "crlf.epub")

    assert "\r" not in extraido.capitulos[0].texto


# --------------------------------------------------------------------------- #
# Divisao por ancoras do indice
# --------------------------------------------------------------------------- #


def _montar_epub_com_ancoras(
    *, documentos: list[tuple[str, str]], indice: list[tuple[str, str]]
) -> bytes:
    """Gera um EPUB com controle total sobre índice e âncoras.

    ``documentos`` é uma lista de (nome do arquivo, HTML). ``indice`` é uma lista
    de (título, href) — o href pode conter âncora, como ``c1.xhtml#meio``.
    """
    livro = epub.EpubBook()
    livro.set_identifier("urn:teste:ancoras")
    livro.set_title("Livro com âncoras")
    livro.set_language("pt-BR")

    itens = []
    for nome, html in documentos:
        item = epub.EpubHtml(title="", file_name=nome, lang="pt-BR")
        item.content = html
        livro.add_item(item)
        itens.append(item)

    livro.toc = tuple(
        epub.Link(href, titulo, f"id{i}") for i, (titulo, href) in enumerate(indice)
    )
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", *itens]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    return buffer.getvalue()


def teste_arquivo_unico_com_varias_ancoras_vira_varios_capitulos() -> None:
    """Quando o índice é mais fino que os arquivos, ele manda nas fronteiras.

    Caso real: em *Flores para Algernon* um único arquivo continha 11 relatórios
    de progresso, e importá-lo inteiro produzia um capítulo de 131 mil
    caracteres em vez de 11 capítulos.
    """
    html = (
        f'<p id="r1">Primeiro relatório. {TEXTO_LONGO}</p>'
        f'<p id="r2">Segundo relatório. {TEXTO_LONGO}</p>'
        f'<p id="r3">Terceiro relatório. {TEXTO_LONGO}</p>'
    )
    dados = _montar_epub_com_ancoras(
        documentos=[("tudo.xhtml", html)],
        indice=[
            ("Relatório 1", "tudo.xhtml#r1"),
            ("Relatório 2", "tudo.xhtml#r2"),
            ("Relatório 3", "tudo.xhtml#r3"),
        ],
    )

    extraido = extrair_epub(dados, "algernon.epub")

    assert [c.titulo for c in extraido.capitulos] == [
        "Relatório 1",
        "Relatório 2",
        "Relatório 3",
    ]
    # Cada capítulo ficou com o seu próprio texto, sem vazar para o vizinho.
    assert extraido.capitulos[0].texto.startswith("Primeiro relatório")
    assert "Segundo relatório" not in extraido.capitulos[0].texto
    assert extraido.capitulos[1].texto.startswith("Segundo relatório")


def teste_texto_antes_da_primeira_ancora_volta_para_o_capitulo_anterior() -> None:
    """O Calibre parte arquivos grandes no meio de um capítulo.

    Caso real: em *Flores para Algernon* o arquivo ``..._split_001`` começava com
    42 mil caracteres do relatório anterior, e só depois vinha a primeira
    âncora. Sem juntar, aquele texto viraria um capítulo sem título e o relatório
    apareceria partido em dois.
    """
    dados = _montar_epub_com_ancoras(
        documentos=[
            ("parte0.xhtml", f'<p id="c1">Começo do capítulo um. {TEXTO_LONGO}</p>'),
            (
                "parte1.xhtml",
                f"<p>Fim do capítulo um. {TEXTO_LONGO}</p>"
                f'<p id="c2">Começo do capítulo dois. {TEXTO_LONGO}</p>',
            ),
        ],
        indice=[
            ("Capítulo 1", "parte0.xhtml#c1"),
            ("Capítulo 2", "parte1.xhtml#c2"),
        ],
    )

    extraido = extrair_epub(dados, "partido.epub")

    assert [c.titulo for c in extraido.capitulos] == ["Capítulo 1", "Capítulo 2"]
    # As duas metades do capítulo um ficaram juntas, na ordem certa.
    primeiro = extraido.capitulos[0].texto
    assert primeiro.startswith("Começo do capítulo um")
    assert "Fim do capítulo um" in primeiro
    assert primeiro.index("Começo do capítulo um") < primeiro.index("Fim do capítulo um")


def teste_ancora_declarada_mas_ausente_do_documento_e_ignorada() -> None:
    """Um índice pode apontar para um id que não existe no arquivo.

    Melhor ignorar a entrada do que inventar um corte no lugar errado.
    """
    dados = _montar_epub_com_ancoras(
        documentos=[("doc.xhtml", f'<p id="existe">Texto real. {TEXTO_LONGO}</p>')],
        indice=[
            ("Existe", "doc.xhtml#existe"),
            ("Fantasma", "doc.xhtml#nao-existe"),
        ],
    )

    extraido = extrair_epub(dados, "fantasma.epub")

    assert [c.titulo for c in extraido.capitulos] == ["Existe"]
    assert "Texto real" in extraido.capitulos[0].texto


# --------------------------------------------------------------------------- #
# Sugestao de capitulo ignorado
# --------------------------------------------------------------------------- #


def teste_sugere_ignorar_titulos_de_material_nao_narrativo() -> None:
    """Créditos, glossário e notas do tradutor não são narrativa."""
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 10}</p>", "Capítulo 1"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Capítulo 2"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Notas ao Canto 1"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Glossário"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Créditos"),
            ]
        ),
        "livro.epub",
    )

    sugeridos = {c.titulo for c in extraido.capitulos if c.ignorado}
    assert sugeridos == {"Notas ao Canto 1", "Glossário", "Créditos"}


def teste_titulo_narrativo_protege_capitulo_curto() -> None:
    """Um capítulo curto de verdade não pode ser sugerido como ignorado.

    Esconder narrativa é o pior dos dois erros: listar um glossário é um
    incômodo, perder um prólogo é perder parte do livro.
    """
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 20}</p>", "Capítulo 1"),
                (f"<p>{TEXTO_LONGO * 20}</p>", "Capítulo 2"),
                # Bem abaixo do limite de tamanho, mas claramente narrativa.
                (f"<p>{TEXTO_LONGO}</p>", "Capítulo 3"),
                (f"<p>{TEXTO_LONGO}</p>", "PRÓLOGO"),
                (f"<p>{TEXTO_LONGO}</p>", "15"),
            ]
        ),
        "livro.epub",
    )

    por_titulo = {c.titulo: c.ignorado for c in extraido.capitulos}
    assert por_titulo["Capítulo 3"] is False
    assert por_titulo["PRÓLOGO"] is False
    assert por_titulo["15"] is False


def teste_sugere_ignorar_o_que_e_muito_curto_para_o_livro() -> None:
    """O critério é relativo à mediana do próprio livro, não absoluto.

    A mediana variou de 17 mil a 44 mil caracteres entre os cinco livros reais —
    um limite fixo serviria para um e falharia nos outros.
    """
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 20}</p>", "Capítulo 1"),
                (f"<p>{TEXTO_LONGO * 20}</p>", "Capítulo 2"),
                (f"<p>{TEXTO_LONGO * 20}</p>", "Capítulo 3"),
                (f"<p>{TEXTO_LONGO}</p>", "Alguma coisa curta"),
            ]
        ),
        "livro.epub",
    )

    por_titulo = {c.titulo: c.ignorado for c in extraido.capitulos}
    assert por_titulo["Alguma coisa curta"] is True
    assert por_titulo["Capítulo 1"] is False


def teste_em_indice_de_dois_niveis_a_raiz_e_sugerida_como_ignorada() -> None:
    """Num índice aninhado, o corpo do livro fica nas seções e o resto na raiz.

    Caso real: em *A Vontade de Muitos* os 74 capítulos estavam aninhados em três
    partes, e capa, créditos, glossário e personagens ficavam na raiz.
    """
    livro = epub.EpubBook()
    livro.set_identifier("urn:teste:niveis")
    livro.set_title("Livro com partes")
    livro.set_language("pt-BR")

    def documento(nome: str) -> epub.EpubHtml:
        item = epub.EpubHtml(title="", file_name=nome, lang="pt-BR")
        item.content = f"<p>{TEXTO_LONGO * 6}</p>"
        livro.add_item(item)
        return item

    apresentacao = documento("apres.xhtml")
    cap1 = documento("c1.xhtml")
    cap2 = documento("c2.xhtml")

    livro.toc = (
        epub.Link("apres.xhtml", "O funcionamento do verso homérico", "ap"),
        (
            epub.Section("PARTE I"),
            (
                epub.Link("c1.xhtml", "Canto 1", "c1"),
                epub.Link("c2.xhtml", "Canto 2", "c2"),
            ),
        ),
    )
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", apresentacao, cap1, cap2]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    extraido = extrair_epub(buffer.getvalue(), "niveis.epub")

    por_titulo = {c.titulo: c.ignorado for c in extraido.capitulos}
    # Está na raiz do índice e o título não está na lista de rótulos conhecidos —
    # só a posição no índice o denuncia.
    assert por_titulo["O funcionamento do verso homérico"] is True
    assert por_titulo["Canto 1"] is False
    assert por_titulo["Canto 2"] is False


def teste_documento_sem_entrada_no_indice_nao_e_sugerido_pela_posicao() -> None:
    """Não ter entrada no índice não é sinal de que não seja narrativa.

    Caso real: em *A Vontade de Muitos*, duas versões alternativas da cena final
    não tinham entrada no índice — e são narrativa.
    """
    livro = epub.EpubBook()
    livro.set_identifier("urn:teste:sem-entrada")
    livro.set_title("Livro")
    livro.set_language("pt-BR")

    def documento(nome: str) -> epub.EpubHtml:
        item = epub.EpubHtml(title="", file_name=nome, lang="pt-BR")
        item.content = f"<p>{TEXTO_LONGO * 6}</p>"
        livro.add_item(item)
        return item

    cap1 = documento("c1.xhtml")
    cap2 = documento("c2.xhtml")
    orfao = documento("orfao.xhtml")

    livro.toc = (
        (
            epub.Section("PARTE I"),
            (
                epub.Link("c1.xhtml", "Capítulo 1", "c1"),
                epub.Link("c2.xhtml", "Capítulo 2", "c2"),
            ),
        ),
    )
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", cap1, cap2, orfao]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    extraido = extrair_epub(buffer.getvalue(), "orfao.epub")

    sem_titulo = [c for c in extraido.capitulos if c.titulo is None]
    assert len(sem_titulo) == 1
    assert sem_titulo[0].ignorado is False


def teste_sugestao_chega_ao_banco(sessao_com_tabelas: Session) -> None:
    """A sugestão é gravada no capítulo, para o app mostrar já marcada."""
    livro = importar_epub(
        sessao_com_tabelas,
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 10}</p>", "Capítulo 1"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Capítulo 2"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Créditos"),
            ]
        ),
        "livro.epub",
    )

    por_titulo = {c.titulo: c.ignorado for c in livro.capitulos}
    assert por_titulo == {"Capítulo 1": False, "Capítulo 2": False, "Créditos": True}
