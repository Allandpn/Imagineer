"""A capa do livro (item 7.5b, CP1 a CP3): extrair do EPUB, guardar, servir e definir depois."""

import io

import pytest
from ebooklib import epub
from fastapi.testclient import TestClient
from PIL import Image

from imagineer.servicos.capa_do_livro import CapaInvalida, capa_de_um_arquivo, capa_do_epub, preparar_capa
from testes.teste_rotas_sugestoes import _livro_com_capitulos


def _imagem(largura: int = 600, altura: int = 900, cor=(200, 30, 30), formato: str = "PNG") -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (largura, altura), cor).save(saida, format=formato)
    return saida.getvalue()


def _epub_com_capa(capa: bytes | None, identificador: str = "urn:isbn:1") -> bytes:
    """Um EPUB de duas partes, com a capa declarada do jeito padrão (metadado `cover` + item de capa) quando `capa` vem."""
    livro = epub.EpubBook()
    livro.set_identifier(identificador)
    livro.set_title("A Guerra dos Tronos")
    livro.set_language("pt-BR")
    if capa is not None:
        livro.set_cover("cover.jpg", capa)
    itens = []
    for numero in (1, 2):
        item = epub.EpubHtml(title=f"Capítulo {numero}", file_name=f"c{numero}.xhtml", lang="pt-BR")
        item.content = "<p>" + "Este é um parágrafo com texto suficiente para não ser descartado. " * 18 + "</p>"
        livro.add_item(item)
        itens.append(item)
    livro.toc = tuple(itens)
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", *itens]
    saida = io.BytesIO()
    epub.write_epub(saida, livro)
    return saida.getvalue()


def _importar(cliente: TestClient, conteudo: bytes) -> dict:
    resposta = cliente.post("/livros", files={"arquivo": ("livro.epub", conteudo, "application/epub+zip")})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["livro"]


# --------------------------------------------------------------------------- #
# O serviço
# --------------------------------------------------------------------------- #


def teste_preparar_capa_reduz_e_vira_jpeg() -> None:
    conteudo, tipo = preparar_capa(_imagem(2000, 3000))

    guardada = Image.open(io.BytesIO(conteudo))
    assert tipo == "image/jpeg" and guardada.format == "JPEG"
    assert guardada.size == (533, 800)  # reduziu para o lado maior de 800, mantendo a proporção


def teste_preparar_capa_nao_amplia_imagem_pequena() -> None:
    conteudo, _ = preparar_capa(_imagem(200, 300))

    assert Image.open(io.BytesIO(conteudo)).size == (200, 300)


def teste_arquivo_que_nao_e_imagem_e_recusado() -> None:
    with pytest.raises(CapaInvalida):
        preparar_capa(b"isto nao e uma imagem")


def teste_capa_de_um_arquivo_aceita_imagem_e_epub() -> None:
    assert capa_de_um_arquivo(_imagem())[1] == "image/jpeg"
    assert capa_de_um_arquivo(_epub_com_capa(_imagem()))[1] == "image/jpeg"


def teste_epub_sem_capa_nao_da_capa_e_o_arquivo_de_epub_sem_capa_e_recusado() -> None:
    sem_capa = _epub_com_capa(None)
    assert capa_do_epub(epub.read_epub(io.BytesIO(sem_capa))) is None
    with pytest.raises(CapaInvalida):
        capa_de_um_arquivo(sem_capa)


# --------------------------------------------------------------------------- #
# As rotas
# --------------------------------------------------------------------------- #


def teste_importar_epub_com_capa_guarda_e_serve(cliente: TestClient) -> None:
    livro = _importar(cliente, _epub_com_capa(_imagem(1200, 1800)))

    assert livro["tem_capa"] is True
    resposta = cliente.get(f"/livros/{livro['id']}/capa")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/jpeg"
    assert "max-age" in resposta.headers["cache-control"]
    assert Image.open(io.BytesIO(resposta.content)).size == (533, 800)


def teste_livro_sem_capa_tem_tem_capa_falso_e_404(cliente: TestClient) -> None:
    livro = _importar(cliente, _epub_com_capa(None))

    assert livro["tem_capa"] is False
    assert cliente.get(f"/livros/{livro['id']}/capa").status_code == 404
    assert cliente.get("/livros/999/capa").status_code == 404


def teste_a_listagem_mostra_tem_capa_sem_ler_a_imagem(cliente: TestClient) -> None:
    _importar(cliente, _epub_com_capa(_imagem(), identificador="urn:isbn:10"))
    _importar(cliente, _epub_com_capa(None, identificador="urn:isbn:11"))

    assert sorted(l["tem_capa"] for l in cliente.get("/livros").json()) == [False, True]


def teste_definir_a_capa_de_um_livro_existente_por_imagem_ou_por_epub(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente)
    assert livro["tem_capa"] is False

    por_imagem = cliente.post(f"/livros/{livro['id']}/capa", files={"arquivo": ("c.png", _imagem(), "image/png")})
    assert por_imagem.status_code == 200, por_imagem.text
    assert por_imagem.json()["tem_capa"] is True
    antes = cliente.get(f"/livros/{livro['id']}/capa").content

    por_epub = cliente.post(
        f"/livros/{livro['id']}/capa",
        files={"arquivo": ("l.epub", _epub_com_capa(_imagem(cor=(10, 10, 200))), "application/epub+zip")},
    )
    assert por_epub.status_code == 200, por_epub.text
    assert cliente.get(f"/livros/{livro['id']}/capa").content != antes  # trocou


def teste_definir_a_capa_recusa_o_que_nao_e_imagem_e_livro_inexistente(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente)

    ruim = cliente.post(f"/livros/{livro['id']}/capa", files={"arquivo": ("x.txt", b"texto", "text/plain")})
    assert ruim.status_code == 422
    assert cliente.post("/livros/999/capa", files={"arquivo": ("c.png", _imagem(), "image/png")}).status_code == 404


def teste_definir_a_capa_sobe_a_revisao_do_livro(cliente: TestClient) -> None:
    livro = _livro_com_capitulos(cliente)
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    cliente.post(f"/livros/{livro['id']}/capa", files={"arquivo": ("c.png", _imagem(), "image/png")})

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] > antes  # o app relê e troca a URL da capa
