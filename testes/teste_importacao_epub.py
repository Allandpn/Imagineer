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


def teste_titulo_confirmado_falso_quando_usa_o_nome_do_arquivo() -> None:
    """Item 6.2: o fallback pro nome do arquivo não conta como título real —
    o usuário ainda precisa confirmar/preencher."""
    extraido = extrair_epub(_montar_epub(titulo=None), "meu-livro-favorito.epub")

    assert extraido.titulo_confirmado is False


def teste_titulo_confirmado_verdadeiro_quando_vem_do_epub() -> None:
    extraido = extrair_epub(_montar_epub(titulo="Título de Verdade"), "arquivo.epub")

    assert extraido.titulo_confirmado is True


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


def teste_indice_com_filho_solto_nao_quebra_o_parsing() -> None:
    """Achado importando um EPUB real (conversão de terceiros): o `.toc` que o
    ebooklib devolve na leitura pode trazer uma entrada solta — um `Link`, ou
    uma seção com um único filho não embrulhado em lista — em vez de sempre
    vir dentro de uma lista, como os EPUBs montados pelo próprio ebooklib (os
    outros testes deste arquivo) sempre produzem na escrita.

    Não dá pra reproduzir isso escrevendo com `epub.write_epub` e lendo de
    volta: a própria escrita do ebooklib sempre normaliza pra lista. Por
    isso este teste chama `_entradas_do_indice` diretamente, com um objeto
    que imita o `.toc` malformado — exceção à regra deste arquivo de só
    testar pela função pública `extrair_epub`, justificada porque o bug
    mora especificamente em como a função interpreta a forma do `.toc`.
    """
    from types import SimpleNamespace

    from imagineer.servicos.importacao_epub import _entradas_do_indice

    epub_falso = SimpleNamespace(
        # O toc inteiro é um único Link solto, não uma lista com um Link.
        toc=epub.Link("c1.xhtml", "Capítulo Único", "c1")
    )
    entradas = _entradas_do_indice(epub_falso)
    assert [e.titulo for e in entradas] == ["Capítulo Único"]

    epub_falso_aninhado = SimpleNamespace(
        toc=(
            # A seção tem um filho só, entregue solto — não dentro de uma
            # lista/tupla de filhos, como as outras seções deste arquivo têm.
            (epub.Section("Parte 1"), epub.Link("c2.xhtml", "Capítulo 2", "c2")),
        )
    )
    entradas_aninhadas = _entradas_do_indice(epub_falso_aninhado)
    assert [e.titulo for e in entradas_aninhadas] == ["Capítulo 2"]


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

    A mediana variou de 7 mil a 44 mil caracteres entre os nove livros reais —
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


def teste_secao_aninhada_de_apendice_nao_esconde_os_capitulos_da_raiz() -> None:
    """A posição no índice **não** é usada para sugerir. Aqui está o porquê.

    Caso real, *O Processo*: o índice tem uma única seção aninhada, "Fragmentos",
    que é o apêndice com os trechos inacabados — e os doze capítulos do romance
    estão todos na raiz. Uma versão anterior deste serviço tratava "está na raiz
    de um índice aninhado" como sinal de material pré/pós-textual, e escondeu o
    livro inteiro.

    O sinal valia em três dos nove livros de validação e se invertia em outros
    três, contribuindo com exatamente um item que os outros critérios não pegavam.
    Foi removido: esconder um romance é muito pior que deixar um item para o
    usuário desmarcar.
    """
    livro = epub.EpubBook()
    livro.set_identifier("urn:teste:processo")
    livro.set_title("O Processo")
    livro.set_language("pt-BR")

    def documento(nome: str) -> epub.EpubHtml:
        item = epub.EpubHtml(title="", file_name=nome, lang="pt-BR")
        item.content = f"<p>{TEXTO_LONGO * 6}</p>"
        livro.add_item(item)
        return item

    detencao = documento("c1.xhtml")
    interrogatorio = documento("c2.xhtml")
    catedral = documento("c3.xhtml")
    fragmentos = documento("frag.xhtml")
    fragmentos.content = (
        f'<div><h2 id="f1">A amiga de B.</h2><p>{TEXTO_LONGO}</p>'
        f'<h2 id="f2">O procurador</h2><p>{TEXTO_LONGO}</p></div>'
    )

    livro.toc = (
        epub.Link("c1.xhtml", "Detenção", "c1"),
        epub.Link("c2.xhtml", "Primeiro interrogatório", "c2"),
        epub.Link("c3.xhtml", "Na catedral", "c3"),
        (
            epub.Section("Fragmentos"),
            (
                epub.Link("frag.xhtml#f1", "A amiga de B.", "f1"),
                epub.Link("frag.xhtml#f2", "O procurador", "f2"),
            ),
        ),
    )
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", detencao, interrogatorio, catedral, fragmentos]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    extraido = extrair_epub(buffer.getvalue(), "processo.epub")

    por_titulo = {c.titulo: c.ignorado for c in extraido.capitulos}
    # Os capítulos do romance estão na raiz do índice e precisam ser mantidos.
    assert por_titulo["Detenção"] is False
    assert por_titulo["Primeiro interrogatório"] is False
    assert por_titulo["Na catedral"] is False


def teste_documento_embrulhado_em_div_unica_ainda_divide_por_ancoras() -> None:
    """O corte acontece no ancestral comum das âncoras, não no ``<body>``.

    Caso real, *O Processo*: o documento de fragmentos estava inteiro dentro de um
    único ``<div>``, então todas as âncoras caíam no mesmo filho do corpo. Cortar
    entre os filhos do corpo dava uma fatia só, e os fragmentos não se separavam.
    """
    dados = _montar_epub_com_ancoras(
        documentos=[
            (
                "frag.xhtml",
                "<div>"
                f'<h2 id="f1">Primeiro</h2><p>Texto um. {TEXTO_LONGO}</p>'
                f'<h2 id="f2">Segundo</h2><p>Texto dois. {TEXTO_LONGO}</p>'
                f'<h2 id="f3">Terceiro</h2><p>Texto três. {TEXTO_LONGO}</p>'
                "</div>",
            )
        ],
        indice=[
            ("Primeiro", "frag.xhtml#f1"),
            ("Segundo", "frag.xhtml#f2"),
            ("Terceiro", "frag.xhtml#f3"),
        ],
    )

    extraido = extrair_epub(dados, "frag.epub")

    assert [c.titulo for c in extraido.capitulos] == ["Primeiro", "Segundo", "Terceiro"]
    assert "Texto dois" not in extraido.capitulos[0].texto
    assert "Texto dois" in extraido.capitulos[1].texto


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


def teste_sugere_ignorar_anuncio_de_outro_livro_da_editora() -> None:
    """E-books comerciais terminam com páginas de "compre agora e leia".

    Elas não têm entrada no índice e nada no título as denuncia — porque não têm
    título. O ISBN é o que as distingue de narrativa: um número de 13 dígitos
    começando em 978 ou 979 não aparece em prosa.

    Caso real: eram 6 das 12 páginas indesejadas que passavam nos nove livros de
    validação.
    """
    anuncio = (
        "<p>Mensageira da sorte</p><p>Nia, Fernanda</p>"
        "<p>9788592783839</p><p>426</p>"
        "<p>Compre agora e leia (Publicidade)</p>"
        f"<p>{TEXTO_LONGO}</p>"
    )
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 10}</p>", "Capítulo 1"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Capítulo 2"),
                (anuncio, None),
            ]
        ),
        "com-anuncio.epub",
    )

    # Procurado pelo conteudo, e nao por titulo: desde que existe titulo de
    # reserva tirado da primeira linha, a pagina de anuncio ganha como titulo o
    # nome do livro anunciado.
    anuncios = [c for c in extraido.capitulos if "Mensageira" in c.texto]
    assert len(anuncios) == 1
    assert anuncios[0].ignorado is True
    assert anuncios[0].titulo == "Mensageira da sorte"


def teste_numero_de_treze_digitos_que_nao_e_isbn_nao_conta() -> None:
    """O prefixo importa: só 978 e 979 são faixas de ISBN.

    Sem checar o prefixo, qualquer número comprido no texto — uma data, um código
    — marcaria um capítulo como anúncio.
    """
    from imagineer.servicos.importacao_epub import _parece_anuncio_de_editora

    assert _parece_anuncio_de_editora("ISBN 9788592783839 do livro") is True
    assert _parece_anuncio_de_editora("ISBN 9798592783839 do livro") is True
    assert _parece_anuncio_de_editora("o código 1234567890123 apareceu") is False
    assert _parece_anuncio_de_editora("Era uma noite escura e sem estrelas.") is False


def teste_isbn_nao_confunde_numero_mais_longo() -> None:
    """Um número de 20 dígitos não contém um ISBN de 13.

    As bordas do padrão existem para isso: sem elas, qualquer sequência longa de
    dígitos que comece com 978 em algum ponto casaria.
    """
    from imagineer.servicos.importacao_epub import _parece_anuncio_de_editora

    assert _parece_anuncio_de_editora("codigo 97885927838391234567") is False


# --------------------------------------------------------------------------- #
# Coletaneas de contos e livros em ingles
# --------------------------------------------------------------------------- #


def teste_titulo_numerado_protege_conto_muito_curto() -> None:
    """Numa coletânea, os contos têm tamanhos absurdamente diferentes.

    Caso real: em *Os 100 Melhores Contos de Humor*, as fábulas de Esopo têm
    600 caracteres e a mediana da antologia é 9 mil — 7%, bem abaixo do limite.
    Três fábulas eram sugeridas como ignoradas.

    O que as salva é a forma do título: as coletâneas numeram as histórias
    ("3 - AS MÃOS, OS PÉS E O VENTRE", "36. O NÚMERO TRÊS"), e um título que
    começa com número e separador é um item de uma sequência — capítulo ou conto.
    """
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 20}</p>", "1 - UM CONTO LONGO"),
                (f"<p>{TEXTO_LONGO * 20}</p>", "2. OUTRO CONTO LONGO"),
                (f"<p>{TEXTO_LONGO * 20}</p>", "3 — MAIS UM LONGO"),
                # Uma fábula curta, do tamanho de uma de Esopo: acima do mínimo
                # para não ser descartada, mas muito abaixo da mediana do livro.
                (
                    "<p>Um leão, uma raposa e um asno foram caçar juntos e "
                    "combinaram dividir em partes iguais o que conseguissem. "
                    "O asno fez três partes e chamou o leão para escolher.</p>",
                    "4 - O LEÃO",
                ),
            ]
        ),
        "coletanea.epub",
    )

    por_titulo = {c.titulo: c.ignorado for c in extraido.capitulos}
    assert por_titulo["4 - O LEÃO"] is False


def teste_protege_titulo_numerado_com_varios_separadores() -> None:
    """Coletâneas numeram de formas diferentes; todas contam."""
    from imagineer.servicos.importacao_epub import _PADROES_NARRATIVOS, _normalizar

    for titulo in ("3 - AS MÃOS", "36. O NÚMERO TRÊS", "12) O RELÓGIO", "7 – O GOLEM"):
        assert _PADROES_NARRATIVOS.match(_normalizar(titulo)), titulo

    # Um número solto no meio do título não protege: só o começo conta.
    assert not _PADROES_NARRATIVOS.match(_normalizar("Notas ao capítulo 3"))


def teste_rotulos_em_ingles_tambem_valem() -> None:
    """Um livro em inglês precisa dos rótulos dele.

    Caso real: no *Sherlock Holmes Handbook*, "Introduction", "About the Author" e
    "Acknowledgments" passavam porque a lista de rótulos era só em português.
    """
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 10}</p>", "Introduction"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Chapter 1"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Chapter 2"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Acknowledgments"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "About the Author"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Index"),
            ]
        ),
        "handbook.epub",
    )

    por_titulo = {c.titulo: c.ignorado for c in extraido.capitulos}
    assert por_titulo["Introduction"] is True
    assert por_titulo["Acknowledgments"] is True
    assert por_titulo["About the Author"] is True
    assert por_titulo["Index"] is True
    assert por_titulo["Chapter 1"] is False
    assert por_titulo["Chapter 2"] is False


def teste_titulo_numerado_e_protegido_mesmo_parecendo_apendice() -> None:
    """Um "1. Prefácio" é mantido, e isso é deliberado.

    A comparação de rótulo é por prefixo, então um título que começa com número
    nunca casa com "prefacio" — e a proteção por título numerado o mantém. Deixar
    passar um prefácio numerado é o erro seguro; esconder o conto "4 - O LEÃO"
    numa coletânea não é.

    Nos quinze livros de validação nenhum apêndice vinha numerado, então o caso é
    teórico. O que **não** é teórico é o contrário: as fábulas de Esopo.
    """
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 10}</p>", "1. Prefácio"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "2. Primeiro capítulo"),
                # Sem número, o rótulo pega normalmente.
                (f"<p>{TEXTO_LONGO * 10}</p>", "Prefácio"),
            ]
        ),
        "numerado.epub",
    )

    por_titulo = {c.titulo: c.ignorado for c in extraido.capitulos}
    assert por_titulo["1. Prefácio"] is False
    assert por_titulo["2. Primeiro capítulo"] is False
    assert por_titulo["Prefácio"] is True


# --------------------------------------------------------------------------- #
# Titulo de reserva e livro so de imagem
# --------------------------------------------------------------------------- #


def teste_titulo_vem_do_texto_quando_falta_no_indice() -> None:
    """Muitos livros põem o nome do capítulo no corpo, não no índice.

    Caso real: em *Tress, a garota do Mar Esmeralda*, 80 dos 84 capítulos não têm
    entrada no índice — mas o primeiro parágrafo de cada um é o nome dele
    ("A GAROTA", "O JARDINEIRO").
    """
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>A GAROTA</p><p>{TEXTO_LONGO}</p>", None),
                (f"<p>O JARDINEIRO</p><p>{TEXTO_LONGO}</p>", None),
            ],
            com_indice=False,
        ),
        "tress.epub",
    )

    assert [c.titulo for c in extraido.capitulos] == ["A GAROTA", "O JARDINEIRO"]


def teste_titulo_do_indice_tem_precedencia_sobre_o_texto() -> None:
    """O índice é a fonte preferida; o texto é só reserva."""
    extraido = extrair_epub(
        _montar_epub(capitulos=[(f"<p>OUTRA COISA</p><p>{TEXTO_LONGO}</p>", "Do índice")]),
        "livro.epub",
    )

    assert extraido.capitulos[0].titulo == "Do índice"


def teste_primeira_frase_da_narrativa_nao_vira_titulo() -> None:
    """Uma frase não é título, e virar título seria pior que ficar sem.

    Duas condições separam "A GAROTA" de uma frase: o tamanho e a pontuação
    final. Sem elas, um capítulo que começa com diálogo ganharia como título
    "— Levante-se." ou o primeiro parágrafo inteiro da história.
    """
    frase_longa = (
        "A sensação de queimação desanuvia, tão devagar que nem sei ao certo "
        "quando ela de fato termina."
    )
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{frase_longa}</p><p>{TEXTO_LONGO}</p>", None),
                (f"<p>— Levante-se.</p><p>{TEXTO_LONGO}</p>", None),
            ],
            com_indice=False,
        ),
        "livro.epub",
    )

    assert [c.titulo for c in extraido.capitulos] == [None, None]


def teste_titulo_de_reserva_tambem_alimenta_a_sugestao() -> None:
    """Se o texto começa com "Créditos", isso vale como se viesse do índice."""
    extraido = extrair_epub(
        _montar_epub(
            capitulos=[
                (f"<p>{TEXTO_LONGO * 10}</p>", "Capítulo 1"),
                (f"<p>{TEXTO_LONGO * 10}</p>", "Capítulo 2"),
                (f"<p>Créditos</p><p>{TEXTO_LONGO * 10}</p>", None),
            ]
        ),
        "livro.epub",
    )

    creditos = [c for c in extraido.capitulos if c.titulo == "Créditos"]
    assert len(creditos) == 1
    assert creditos[0].ignorado is True


def teste_livro_so_de_imagem_recebe_mensagem_explicativa() -> None:
    """Uma história em quadrinhos é um EPUB válido sem texto para extrair.

    Caso real: *Persépolis 2* tem 192 páginas e 192 imagens, e zero caractere de
    texto — o texto está desenhado dentro dos quadros. Dizer apenas "nenhum
    capítulo encontrado" deixaria o usuário procurando um defeito que não existe.
    """
    livro = epub.EpubBook()
    livro.set_identifier("urn:teste:hq")
    livro.set_title("Uma HQ")
    livro.set_language("pt-BR")

    paginas = []
    for numero in range(1, 5):
        imagem = epub.EpubImage(
            uid=f"img{numero}",
            file_name=f"pagina{numero}.png",
            media_type="image/png",
            content=b"\x89PNG\r\n\x1a\n",
        )
        livro.add_item(imagem)
        pagina = epub.EpubHtml(title="", file_name=f"p{numero}.xhtml", lang="pt-BR")
        pagina.content = f'<div><img src="pagina{numero}.png"/></div>'
        livro.add_item(pagina)
        paginas.append(pagina)

    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", *paginas]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)

    with pytest.raises(ArquivoEpubInvalido) as erro:
        extrair_epub(buffer.getvalue(), "hq.epub")

    mensagem = str(erro.value)
    assert "livro de imagens" in mensagem
    assert "quadrinhos" in mensagem
