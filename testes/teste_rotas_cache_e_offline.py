"""Testes do contrato de cache e leitura offline (itens 6.9 e 7.0a).

Compressão, cache imutável das imagens, tamanho em bytes, manifesto de mídias e os textos do
livro numa chamada. Reaproveitam os auxiliares dos testes de prompts e de sugestões.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from imagineer.modelos import Imagem

# A fixture autouse de pasta temporária de imagens e os auxiliares moram nos testes de prompts.
from testes.teste_rotas_prompts import (  # noqa: F401
    _diretorio_de_imagens,
    _elemento_com_estado,
    _frame,
    _importar_imagem,
    _livro,
    _montar_frame_completo,
)
from testes.teste_rotas_sugestoes import _livro_com_capitulos, _livro_importado


def _imagem_com_conteudo(cliente: TestClient, prompt_id: int, conteudo: bytes, nome: str = "g.png") -> dict:
    resposta = cliente.post(
        f"/prompts/{prompt_id}/imagens",
        files={"arquivo": (nome, conteudo, "image/png")},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _prompt_de_um_frame(cliente: TestClient, usar_provedor_falso) -> tuple[dict, dict]:
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    return livro, prompt


# --------------------------------------------------------------------------- #
# Compressão (item 6.9)
# --------------------------------------------------------------------------- #


def teste_resposta_grande_sai_comprimida_e_continua_igual(cliente: TestClient) -> None:
    """O texto de um capítulo chega a ~110 KB e comprime muito bem."""
    livro = _livro_importado(cliente, repeticoes=60)
    capitulo_id = livro["capitulos"][0]["id"]

    resposta = cliente.get(f"/capitulos/{capitulo_id}", headers={"Accept-Encoding": "gzip"})

    assert resposta.status_code == 200
    assert resposta.headers.get("content-encoding") == "gzip"
    # O cliente descomprime sozinho: o conteúdo chega íntegro.
    assert len(resposta.json()["texto"]) > 10_000


def teste_quem_nao_aceita_gzip_recebe_sem_compressao(cliente: TestClient) -> None:
    livro = _livro_importado(cliente, repeticoes=60)

    resposta = cliente.get(
        f"/capitulos/{livro['capitulos'][0]['id']}", headers={"Accept-Encoding": "identity"}
    )

    assert "content-encoding" not in resposta.headers
    assert len(resposta.json()["texto"]) > 10_000


def teste_resposta_pequena_nao_e_comprimida(cliente: TestClient) -> None:
    """Abaixo de ~1 KB o cabeçalho pesaria mais que o ganho."""
    resposta = cliente.get("/saude", headers={"Accept-Encoding": "gzip"})

    assert "content-encoding" not in resposta.headers


def teste_imagem_nao_e_comprimida_de_novo(cliente: TestClient, usar_provedor_falso) -> None:
    """PNG, JPEG e WebP já vêm comprimidos; recomprimir gastaria CPU sem ganho."""
    _, prompt = _prompt_de_um_frame(cliente, usar_provedor_falso)
    conteudo = b"\x89PNG" + bytes(range(256)) * 40  # > 1 KB
    imagem = _imagem_com_conteudo(cliente, prompt["id"], conteudo)

    resposta = cliente.get(f"/imagens/{imagem['id']}/arquivo", headers={"Accept-Encoding": "gzip"})

    assert resposta.status_code == 200
    assert "content-encoding" not in resposta.headers
    assert resposta.content == conteudo


# --------------------------------------------------------------------------- #
# Imagem: cache imutável e tamanho (item 6.9)
# --------------------------------------------------------------------------- #


def teste_arquivo_da_imagem_tem_cache_imutavel_e_etag(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O arquivo de uma imagem nunca muda (nome UUID, nunca sobrescrito): o cliente pode guardá-lo
    para sempre, sem revalidar."""
    _, prompt = _prompt_de_um_frame(cliente, usar_provedor_falso)
    imagem = _importar_imagem(cliente, prompt["id"])

    resposta = cliente.get(f"/imagens/{imagem['id']}/arquivo")

    assert resposta.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert resposta.headers.get("etag")


def teste_importar_imagem_grava_o_tamanho_em_bytes(cliente: TestClient, usar_provedor_falso) -> None:
    _, prompt = _prompt_de_um_frame(cliente, usar_provedor_falso)

    imagem = _imagem_com_conteudo(cliente, prompt["id"], b"x" * 12345)

    assert imagem["tamanho_em_bytes"] == 12345


# --------------------------------------------------------------------------- #
# GET /livros/{id}/midias — o manifesto (item 6.9)
# --------------------------------------------------------------------------- #


def _prompt_de_outro_livro(cliente: TestClient, livro_existente: dict) -> dict:
    """Um segundo livro, com frame e prompt, reaproveitando o perfil do primeiro (o nome de um
    perfil é único, então montar o frame completo duas vezes daria 409)."""
    perfil_id = cliente.get(f"/livros/{livro_existente['id']}").json()["perfil_renderizacao_padrao_id"]
    outro = _livro(cliente)
    cliente.patch(f"/livros/{outro['id']}", json={"perfil_renderizacao_padrao_id": perfil_id})
    capitulo = outro["capitulos"][0]
    ned = _elemento_com_estado(cliente, outro["id"], capitulo["id"], "Ned Stark")
    frame = _frame(cliente, capitulo["id"], [ned["estados"][0]["id"]])
    return cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()


def teste_midias_de_livro_sem_imagens_e_vazio(cliente: TestClient) -> None:
    livro = _livro(cliente)

    resposta = cliente.get(f"/livros/{livro['id']}/midias")

    assert resposta.status_code == 200
    assert resposta.json() == {"total_em_bytes": 0, "imagens": []}


def teste_midias_lista_cada_imagem_com_tamanho_e_total(
    cliente: TestClient, usar_provedor_falso
) -> None:
    livro, prompt = _prompt_de_um_frame(cliente, usar_provedor_falso)
    primeira = _imagem_com_conteudo(cliente, prompt["id"], b"a" * 1000)
    segunda = _imagem_com_conteudo(cliente, prompt["id"], b"b" * 2500)

    corpo = cliente.get(f"/livros/{livro['id']}/midias").json()

    # O total é o que o app mostra em "Baixar — N MB" antes de começar.
    assert corpo["total_em_bytes"] == 3500
    assert [m["imagem_id"] for m in corpo["imagens"]] == [primeira["id"], segunda["id"]]
    assert [m["tamanho_em_bytes"] for m in corpo["imagens"]] == [1000, 2500]
    assert all(m["prompt_id"] == prompt["id"] for m in corpo["imagens"])
    assert all(m["tipo_do_arquivo"] == "image/png" for m in corpo["imagens"])
    frame_id = cliente.get(f"/prompts/{prompt['id']}").json()["frame_id"]
    assert all(m["frame_id"] == frame_id for m in corpo["imagens"])


def teste_midias_so_traz_as_imagens_do_proprio_livro(
    cliente: TestClient, usar_provedor_falso
) -> None:
    livro_a, prompt_a = _prompt_de_um_frame(cliente, usar_provedor_falso)
    prompt_b = _prompt_de_outro_livro(cliente, livro_a)
    imagem_a = _imagem_com_conteudo(cliente, prompt_a["id"], b"a" * 100)
    _imagem_com_conteudo(cliente, prompt_b["id"], b"b" * 999)

    corpo = cliente.get(f"/livros/{livro_a['id']}/midias").json()

    assert [m["imagem_id"] for m in corpo["imagens"]] == [imagem_a["id"]]
    assert corpo["total_em_bytes"] == 100


def teste_midias_calcula_do_disco_o_tamanho_das_imagens_antigas_e_grava(
    cliente: TestClient, sessao_com_tabelas: Session, usar_provedor_falso
) -> None:
    """Imagens importadas antes da coluna não têm tamanho: calcula do arquivo, e grava."""
    livro, prompt = _prompt_de_um_frame(cliente, usar_provedor_falso)
    imagem = _imagem_com_conteudo(cliente, prompt["id"], b"z" * 777)
    sessao_com_tabelas.execute(update(Imagem).values(tamanho_em_bytes=None))
    sessao_com_tabelas.commit()

    corpo = cliente.get(f"/livros/{livro['id']}/midias").json()

    assert corpo["imagens"][0]["tamanho_em_bytes"] == 777
    assert corpo["total_em_bytes"] == 777
    sessao_com_tabelas.expire_all()
    gravado = sessao_com_tabelas.scalar(select(Imagem.tamanho_em_bytes).where(Imagem.id == imagem["id"]))
    assert gravado == 777  # a consulta seguinte já o encontra


def teste_midias_deixa_de_fora_a_imagem_cujo_arquivo_sumiu(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens: Path
) -> None:
    """Listá-la faria o download falhar no meio; `GET /imagens/{id}/arquivo` já responde 404."""
    livro, prompt = _prompt_de_um_frame(cliente, usar_provedor_falso)
    _imagem_com_conteudo(cliente, prompt["id"], b"a" * 100)
    _imagem_com_conteudo(cliente, prompt["id"], b"b" * 200)
    arquivos = sorted(p for p in _diretorio_de_imagens.rglob("*.png"))
    arquivos[0].unlink()

    corpo = cliente.get(f"/livros/{livro['id']}/midias").json()

    assert len(corpo["imagens"]) == 1
    assert corpo["total_em_bytes"] == corpo["imagens"][0]["tamanho_em_bytes"]


def teste_midias_de_livro_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.get("/livros/9999/midias").status_code == 404


# --------------------------------------------------------------------------- #
# GET /livros/{id}/textos — o texto de todos os capítulos (item 6.9)
# --------------------------------------------------------------------------- #


def teste_textos_traz_todos_os_capitulos_em_ordem_e_iguais_aos_individuais(
    cliente: TestClient,
) -> None:
    livro = _livro_com_capitulos(cliente, capitulos=3)

    textos = cliente.get(f"/livros/{livro['id']}/textos").json()

    assert [t["ordem"] for t in textos] == [1, 2, 3]
    assert [t["capitulo_id"] for t in textos] == [c["id"] for c in livro["capitulos"]]
    for item in textos:
        individual = cliente.get(f"/capitulos/{item['capitulo_id']}").json()
        assert item["texto"] == individual["texto"]  # exatamente o mesmo texto


def teste_textos_inclui_os_capitulos_arquivados(cliente: TestClient) -> None:
    """"Arquivado" é só organização; quem baixa o livro quer tudo."""
    livro = _livro_com_capitulos(cliente, capitulos=2)
    cliente.patch(f"/capitulos/{livro['capitulos'][0]['id']}", json={"ignorado": True})

    textos = cliente.get(f"/livros/{livro['id']}/textos").json()

    assert len(textos) == 2


def teste_detalhe_do_livro_continua_sem_o_texto_dos_capitulos(cliente: TestClient) -> None:
    """A promessa de latência: abrir o livro devolve só os metadados; o texto vem ao abrir o capítulo."""
    livro = _livro_com_capitulos(cliente, capitulos=2)

    detalhe = cliente.get(f"/livros/{livro['id']}").json()

    assert all("texto" not in capitulo for capitulo in detalhe["capitulos"])
    assert all("tamanho_do_texto" in capitulo for capitulo in detalhe["capitulos"])


def teste_textos_de_livro_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.get("/livros/9999/textos").status_code == 404
