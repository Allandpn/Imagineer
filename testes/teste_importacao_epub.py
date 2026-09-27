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

    # Capa, folha de rosto, créditos e o documento de navegação ficaram de fora;
    # sobraram os três capítulos de verdade, numerados sem lacunas.
    assert [(c.ordem, c.titulo) for c in extraido.capitulos] == [
        (1, "Prólogo"),
        (2, "Bran"),
        (3, "Catelyn"),
    ]

    # O índice aninhado foi achatado e os títulos casaram apesar do prefixo de
    # pasta usado no href.
    assert extraido.capitulos[0].titulo == "Prólogo"

    # A entrada de âncora NÃO virou um capítulo à parte nem trocou o título do
    # capítulo: "Bran — parte 2" aponta para dentro do mesmo arquivo.
    assert "Bran — parte 2" not in [c.titulo for c in extraido.capitulos]
    assert extraido.capitulos[1].texto.count("Bran") == 1
    assert "Parte 2" in extraido.capitulos[1].texto
