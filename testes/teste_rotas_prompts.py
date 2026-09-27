"""Testes das rotas de prompts e catálogo de imagens (Etapa 6.6)."""

import io

import pytest
from ebooklib import epub
from fastapi.testclient import TestClient

from imagineer import configuracao as modulo_de_configuracao
from imagineer.ia.falso import MODELO_FALSO, ProvedorFalso
from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA, PromptMontado

TEXTO_LONGO = "Este é um parágrafo com texto suficiente para não ser descartado. " * 3


@pytest.fixture(autouse=True)
def _diretorio_de_imagens(tmp_path, monkeypatch):
    """Usa uma pasta temporária como DIRETORIO_IMAGENS, em vez do caminho real.

    Sem isto, o catálogo tentaria gravar em ``/dados/imagens`` — inexistente numa
    máquina de desenvolvimento e proibido de criar em produção às cegas.
    """
    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("DIRETORIO_IMAGENS", str(tmp_path))
    try:
        yield tmp_path
    finally:
        obter.cache_clear()


def _epub(*, titulo: str = "A Guerra dos Tronos", identificador: str = "urn:isbn:1") -> bytes:
    livro = epub.EpubBook()
    livro.set_identifier(identificador)
    livro.set_title(titulo)
    livro.set_language("pt-BR")

    item = epub.EpubHtml(title="Capítulo 1", file_name="c1.xhtml", lang="pt-BR")
    item.content = f"<p>{TEXTO_LONGO * 6}</p>"
    livro.add_item(item)

    livro.toc = (item,)
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    livro.spine = ["nav", item]

    buffer = io.BytesIO()
    epub.write_epub(buffer, livro)
    return buffer.getvalue()


def _livro(cliente: TestClient, **kwargs) -> dict:
    resposta = cliente.post(
        "/livros", files={"arquivo": ("l.epub", _epub(**kwargs), "application/epub+zip")}
    )
    assert resposta.status_code == 201
    return resposta.json()["livro"]


def _elemento_com_estado(cliente: TestClient, livro_id: int, capitulo_id: int, nome: str) -> dict:
    resposta = cliente.post(
        f"/livros/{livro_id}/elementos",
        json={
            "tipo": "PERSONAGEM",
            "nome": nome,
            "estado_inicial": {"capitulo_id": capitulo_id, "descricao": f"{nome} está assim."},
        },
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _cena(cliente: TestClient, capitulo_id: int, estados_ids: list[int] | None = None) -> dict:
    resposta = cliente.post(
        f"/capitulos/{capitulo_id}/cenas",
        json={"titulo": "No pátio", "estados_ids": estados_ids or []},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _perfil(cliente: TestClient, **kwargs) -> dict:
    corpo = {"nome": "Aquarela sombria", "estilo": "aquarela"} | kwargs
    resposta = cliente.post("/perfis-renderizacao", json=corpo)
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _montar_cena_completa(
    cliente: TestClient, usar_provedor_falso, provedor: ProvedorFalso | None = None
) -> tuple[dict, dict]:
    """Livro, capítulo, elemento com estado, cena com ele e perfil padrão do livro."""
    usar_provedor_falso(provedor or ProvedorFalso(prompt="uma pintura de teste"))
    livro = _livro(cliente)
    capitulo = livro["capitulos"][0]
    ned = _elemento_com_estado(cliente, livro["id"], capitulo["id"], "Ned Stark")
    cena = _cena(cliente, capitulo["id"], [ned["estados"][0]["id"]])
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})
    cliente.put("/configuracao", json={"modelo_prompt": MODELO_FALSO})
    return livro, cena


# --------------------------------------------------------------------------- #
# Criar prompt
# --------------------------------------------------------------------------- #


def teste_criar_prompt_usa_perfil_padrao_do_livro_e_modelo_da_configuracao(
    cliente: TestClient, usar_provedor_falso
) -> None:
    provedor = ProvedorFalso(prompt="uma pintura de teste")
    _, cena = _montar_cena_completa(cliente, usar_provedor_falso, provedor)

    resposta = cliente.post(f"/cenas/{cena['id']}/prompts", json={})

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["texto"] == "uma pintura de teste"
    assert corpo["modelo_ia"] == MODELO_FALSO
    assert corpo["imagens"] == []

    chamada = provedor.chamadas_de_prompt[0]
    assert "Ned Stark: Ned Stark está assim." in chamada["elementos"]
    assert "Aquarela sombria" in chamada["perfil_renderizacao"]
    assert "aquarela" in chamada["perfil_renderizacao"]


def teste_criar_prompt_sem_perfil_e_sem_padrao_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro(cliente)
    cena = _cena(cliente, livro["capitulos"][0]["id"])

    resposta = cliente.post(f"/cenas/{cena['id']}/prompts", json={})

    assert resposta.status_code == 422


def teste_criar_prompt_sem_modelo_responde_422(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(ProvedorFalso())
    livro = _livro(cliente)
    cena = _cena(cliente, livro["capitulos"][0]["id"])
    perfil = _perfil(cliente)
    cliente.patch(f"/livros/{livro['id']}", json={"perfil_renderizacao_padrao_id": perfil["id"]})

    resposta = cliente.post(f"/cenas/{cena['id']}/prompts", json={})

    assert resposta.status_code == 422


def teste_criar_prompt_com_perfil_e_modelo_explicitos_no_pedido(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(prompt="outra pintura"))
    livro = _livro(cliente)
    cena = _cena(cliente, livro["capitulos"][0]["id"])
    perfil = _perfil(cliente, nome="Traço a nanquim")

    resposta = cliente.post(
        f"/cenas/{cena['id']}/prompts",
        json={"perfil_renderizacao_id": perfil["id"], "modelo": MODELO_FALSO},
    )

    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["perfil_renderizacao_id"] == perfil["id"]


def teste_criar_prompt_com_chave_ausente_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ChaveDeApiAusente("sem chave")))
    livro = _livro(cliente)
    cena = _cena(cliente, livro["capitulos"][0]["id"])
    perfil = _perfil(cliente)

    resposta = cliente.post(
        f"/cenas/{cena['id']}/prompts",
        json={"perfil_renderizacao_id": perfil["id"], "modelo": MODELO_FALSO},
    )

    assert resposta.status_code == 422


def teste_criar_prompt_com_erro_de_rede_responde_502(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso(erro=ErroDoProvedorIA("o serviço caiu")))
    livro = _livro(cliente)
    cena = _cena(cliente, livro["capitulos"][0]["id"])
    perfil = _perfil(cliente)

    resposta = cliente.post(
        f"/cenas/{cena['id']}/prompts",
        json={"perfil_renderizacao_id": perfil["id"], "modelo": MODELO_FALSO},
    )

    assert resposta.status_code == 502


def teste_criar_prompt_de_cena_inexistente_responde_404(
    cliente: TestClient, usar_provedor_falso
) -> None:
    usar_provedor_falso(ProvedorFalso())
    assert cliente.post("/cenas/999/prompts", json={}).status_code == 404


# --------------------------------------------------------------------------- #
# Histórico, ajuste e remoção de prompts
# --------------------------------------------------------------------------- #


def teste_listar_prompts_da_cena(cliente: TestClient, usar_provedor_falso) -> None:
    _, cena = _montar_cena_completa(cliente, usar_provedor_falso)
    cliente.post(f"/cenas/{cena['id']}/prompts", json={})
    cliente.post(f"/cenas/{cena['id']}/prompts", json={})

    resposta = cliente.get(f"/cenas/{cena['id']}/prompts")

    assert resposta.status_code == 200
    assert len(resposta.json()) == 2


def teste_ajustar_prompt_anota_avaliacao(cliente: TestClient, usar_provedor_falso) -> None:
    _, cena = _montar_cena_completa(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/cenas/{cena['id']}/prompts", json={}).json()

    resposta = cliente.patch(f"/prompts/{prompt['id']}", json={"avaliacao": "Ficou ótima."})

    assert resposta.status_code == 200
    assert resposta.json()["avaliacao"] == "Ficou ótima."


def teste_remover_prompt_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.delete("/prompts/999").status_code == 404


# --------------------------------------------------------------------------- #
# Catálogo de imagens
# --------------------------------------------------------------------------- #


def _importar_imagem(cliente: TestClient, prompt_id: int, nome: str = "resultado.png") -> dict:
    resposta = cliente.post(
        f"/prompts/{prompt_id}/imagens",
        files={"arquivo": (nome, b"conteudo-fake-da-imagem", "image/png")},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def teste_importar_imagem_e_baixar_o_arquivo(cliente: TestClient, usar_provedor_falso) -> None:
    _, cena = _montar_cena_completa(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/cenas/{cena['id']}/prompts", json={}).json()

    imagem = _importar_imagem(cliente, prompt["id"])
    assert imagem["prompt_id"] == prompt["id"]

    baixado = cliente.get(f"/imagens/{imagem['id']}/arquivo")
    assert baixado.status_code == 200
    assert baixado.content == b"conteudo-fake-da-imagem"

    detalhe = cliente.get(f"/prompts/{prompt['id']}").json()
    assert len(detalhe["imagens"]) == 1


def teste_importar_imagem_com_extensao_invalida_responde_422(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, cena = _montar_cena_completa(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/cenas/{cena['id']}/prompts", json={}).json()

    resposta = cliente.post(
        f"/prompts/{prompt['id']}/imagens",
        files={"arquivo": ("resultado.txt", b"nao e imagem", "text/plain")},
    )

    assert resposta.status_code == 422


def teste_importar_imagem_de_prompt_inexistente_responde_404(cliente: TestClient) -> None:
    resposta = cliente.post(
        "/prompts/999/imagens",
        files={"arquivo": ("resultado.png", b"x", "image/png")},
    )
    assert resposta.status_code == 404


def teste_remover_imagem_apaga_o_arquivo_do_disco(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens
) -> None:
    _, cena = _montar_cena_completa(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/cenas/{cena['id']}/prompts", json={}).json()
    imagem = _importar_imagem(cliente, prompt["id"])

    arquivos_antes = list(_diretorio_de_imagens.rglob("*.png"))
    assert len(arquivos_antes) == 1

    resposta = cliente.delete(f"/imagens/{imagem['id']}")

    assert resposta.status_code == 204
    assert list(_diretorio_de_imagens.rglob("*.png")) == []
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 404


def teste_remover_prompt_apaga_as_imagens_e_os_arquivos(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens
) -> None:
    _, cena = _montar_cena_completa(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/cenas/{cena['id']}/prompts", json={}).json()
    _importar_imagem(cliente, prompt["id"])
    _importar_imagem(cliente, prompt["id"], nome="outra.png")

    resposta = cliente.delete(f"/prompts/{prompt['id']}")

    assert resposta.status_code == 204
    assert list(_diretorio_de_imagens.rglob("*.png")) == []
    assert cliente.get(f"/prompts/{prompt['id']}").status_code == 404


def teste_remover_imagem_inexistente_responde_404(cliente: TestClient) -> None:
    assert cliente.delete("/imagens/999").status_code == 404
