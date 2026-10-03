"""Dimensões e versões reduzidas das imagens (item 6.9; layout do item 7.5b, I1)."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PilImage
from sqlalchemy.orm import Session

from imagineer import configuracao as modulo_de_configuracao
from imagineer.modelos import Imagem
from testes.teste_rotas_prompts import _montar_frame_completo

CABECALHO_DE_CACHE = "public, max-age=31536000, immutable"


@pytest.fixture(autouse=True)
def _diretorio_de_imagens(tmp_path, monkeypatch):
    """Pasta temporária como DIRETORIO_IMAGENS (o catálogo não grava no caminho real nos testes)."""
    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    monkeypatch.setenv("DIRETORIO_IMAGENS", str(tmp_path))
    try:
        yield tmp_path
    finally:
        obter.cache_clear()


def _png(largura: int, altura: int, modo: str = "RGB", cor=(200, 30, 30)) -> bytes:
    saida = io.BytesIO()
    PilImage.new(modo, (largura, altura), cor).save(saida, "PNG")
    return saida.getvalue()


def _cenario(cliente: TestClient, usar_provedor_falso) -> tuple[dict, dict, dict]:
    """Livro, frame e um prompt já montado, prontos para receber imagens."""
    livro, frame = _montar_frame_completo(cliente, usar_provedor_falso)
    prompt = cliente.post(f"/frames/{frame['id']}/prompts", json={}).json()
    return livro, frame, prompt


def _importar(cliente: TestClient, prompt_id: int, conteudo: bytes, nome: str = "imagem.png"):
    resposta = cliente.post(f"/prompts/{prompt_id}/imagens", files={"arquivo": (nome, conteudo, "image/png")})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _abrir(resposta) -> PilImage.Image:
    return PilImage.open(io.BytesIO(resposta.content))


# --------------------------------------------------------------------------- #
# Dimensões e orientação
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("largura", "altura", "orientacao"),
    [(400, 600, "RETRATO"), (600, 400, "PAISAGEM"), (500, 500, "PAISAGEM")],  # a quadrada é paisagem
)
def teste_importar_guarda_as_dimensoes_e_devolve_a_orientacao(
    cliente: TestClient, usar_provedor_falso, largura: int, altura: int, orientacao: str
) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)

    imagem = _importar(cliente, prompt["id"], _png(largura, altura))

    assert (imagem["largura"], imagem["altura"], imagem["orientacao"]) == (largura, altura, orientacao)
    detalhe = cliente.get(f"/prompts/{prompt['id']}").json()["imagens"][0]
    assert (detalhe["largura"], detalhe["altura"], detalhe["orientacao"]) == (largura, altura, orientacao)


def teste_arquivo_que_nao_e_imagem_continua_aceito_sem_dimensoes(
    cliente: TestClient, usar_provedor_falso
) -> None:
    """O catálogo nunca recusou isso; recusar agora quebraria quem já usa."""
    _, _, prompt = _cenario(cliente, usar_provedor_falso)

    imagem = _importar(cliente, prompt["id"], b"isto nao e um png de verdade")

    assert (imagem["largura"], imagem["altura"], imagem["orientacao"]) == (None, None, None)
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo").status_code == 200


# --------------------------------------------------------------------------- #
# ?tamanho=
# --------------------------------------------------------------------------- #


def teste_miniatura_reduz_o_lado_maior_mantendo_a_proporcao(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    imagem = _importar(cliente, prompt["id"], _png(800, 1200))

    resposta = cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=miniatura")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/jpeg"
    assert resposta.headers["cache-control"] == CABECALHO_DE_CACHE
    assert _abrir(resposta).size == (171, 256)  # 800x1200 -> lado maior 256, proporção 2:3


def teste_leitura_reduz_para_1280_e_o_original_continua_igual(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    original = _png(3000, 2000)
    imagem = _importar(cliente, prompt["id"], original)

    leitura = cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=leitura")
    padrao = cliente.get(f"/imagens/{imagem['id']}/arquivo")
    explicito = cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=original")

    assert _abrir(leitura).size == (1280, 853)
    assert padrao.content == original and explicito.content == original  # sem ?tamanho= é o arquivo como veio
    assert padrao.headers["content-type"] == "image/png"
    assert len(leitura.content) < len(original)


def teste_nunca_amplia_se_a_imagem_ja_cabe_devolve_o_original(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    original = _png(100, 100)
    imagem = _importar(cliente, prompt["id"], original)

    resposta = cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=leitura")

    assert resposta.content == original
    assert resposta.headers["content-type"] == "image/png"  # o arquivo original, não uma versão


def teste_a_versao_reduzida_e_gerada_uma_vez_e_reaproveitada(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens
) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    imagem = _importar(cliente, prompt["id"], _png(900, 600))
    arquivo = _diretorio_de_imagens / "derivadas" / "miniatura" / f"{imagem['id']}.jpg"
    assert not arquivo.exists()

    primeira = cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=miniatura")
    gerado_em = arquivo.stat().st_mtime_ns
    segunda = cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=miniatura")

    assert arquivo.is_file()
    assert arquivo.stat().st_mtime_ns == gerado_em  # não regerou
    assert primeira.content == segunda.content


def teste_transparencia_vira_fundo_branco(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    imagem = _importar(cliente, prompt["id"], _png(600, 600, modo="RGBA", cor=(0, 0, 0, 0)))  # toda transparente

    resposta = cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=miniatura")

    assert _abrir(resposta).convert("RGB").getpixel((10, 10)) == (255, 255, 255)


def teste_arquivo_ilegivel_volta_como_original_em_qualquer_tamanho(cliente: TestClient, usar_provedor_falso) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    imagem = _importar(cliente, prompt["id"], b"nao e imagem")

    resposta = cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=miniatura")

    assert resposta.status_code == 200
    assert resposta.content == b"nao e imagem"


def teste_tamanho_desconhecido_e_recusado(cliente: TestClient, usar_provedor_falso) -> None:
    """Tamanhos nomeados e em número fixo: uma largura livre deixaria qualquer cliente encher o disco."""
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    imagem = _importar(cliente, prompt["id"], _png(500, 500))

    assert cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=gigante").status_code == 422
    assert cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=640").status_code == 422


def teste_apagar_de_vez_a_imagem_apaga_as_versoes_reduzidas(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens
) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    imagem = _importar(cliente, prompt["id"], _png(2000, 1500))
    cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=miniatura")
    cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=leitura")
    derivadas = list((_diretorio_de_imagens / "derivadas").rglob("*.jpg"))
    assert len(derivadas) == 2

    # LX4: apagar só move para a lixeira; as reduzidas ficam até apagar de vez (LX5).
    assert cliente.delete(f"/imagens/{imagem['id']}").status_code == 204
    assert len(list((_diretorio_de_imagens / "derivadas").rglob("*.jpg"))) == 2

    assert cliente.delete(f"/lixeira/imagens/{imagem['id']}").status_code == 204

    assert list((_diretorio_de_imagens / "derivadas").rglob("*.jpg")) == []


def teste_apagar_o_prompt_apaga_as_versoes_reduzidas_das_suas_imagens(
    cliente: TestClient, usar_provedor_falso, _diretorio_de_imagens
) -> None:
    _, _, prompt = _cenario(cliente, usar_provedor_falso)
    imagem = _importar(cliente, prompt["id"], _png(2000, 1500))
    cliente.get(f"/imagens/{imagem['id']}/arquivo?tamanho=miniatura")

    assert cliente.delete(f"/prompts/{prompt['id']}").status_code == 204

    assert list((_diretorio_de_imagens / "derivadas").rglob("*.jpg")) == []


# --------------------------------------------------------------------------- #
# Imagens antigas: dimensões calculadas na primeira leitura
# --------------------------------------------------------------------------- #


def _apagar_dimensoes(sessao: Session) -> None:
    for imagem in sessao.query(Imagem).all():
        imagem.largura = imagem.altura = None
    sessao.commit()


def teste_o_manifesto_calcula_e_grava_as_dimensoes_das_imagens_antigas(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    livro, _, prompt = _cenario(cliente, usar_provedor_falso)
    _importar(cliente, prompt["id"], _png(400, 600))
    _apagar_dimensoes(sessao_com_tabelas)  # como uma imagem importada antes de a coluna existir

    midia = cliente.get(f"/livros/{livro['id']}/midias").json()["imagens"][0]

    assert (midia["largura"], midia["altura"], midia["orientacao"]) == (400, 600, "RETRATO")
    sessao_com_tabelas.expire_all()
    assert (sessao_com_tabelas.query(Imagem).one().largura) == 400  # ficou gravado


def teste_calcular_dimensoes_na_leitura_nao_sobe_a_revisao_do_livro(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """O app não precisa reler a lista do livro porque o servidor descobriu o tamanho de uma imagem."""
    livro, _, prompt = _cenario(cliente, usar_provedor_falso)
    _importar(cliente, prompt["id"], _png(400, 600))
    _apagar_dimensoes(sessao_com_tabelas)
    antes = cliente.get(f"/livros/{livro['id']}").json()["revisao"]

    cliente.get(f"/livros/{livro['id']}/midias")

    assert cliente.get(f"/livros/{livro['id']}").json()["revisao"] == antes


def teste_o_artefato_traz_as_dimensoes_e_a_orientacao_da_imagem(
    cliente: TestClient, usar_provedor_falso, sessao_com_tabelas: Session
) -> None:
    """O app decide o layout (duas colunas ou largura inteira) sem baixar a imagem."""
    _, frame, prompt = _cenario(cliente, usar_provedor_falso)
    _importar(cliente, prompt["id"], _png(400, 600))
    capitulo_id = frame["capitulo_id"]

    (artefato,) = [a for a in cliente.get(f"/capitulos/{capitulo_id}/artefatos").json()["artefatos"] if a["frame_id"] == frame["id"]]

    assert artefato["situacao"] == "ILUSTRADO"
    assert (artefato["imagem_largura"], artefato["imagem_altura"], artefato["imagem_orientacao"]) == (400, 600, "RETRATO")

    # E numa imagem antiga (sem dimensões gravadas), o artefato as calcula na hora:
    _apagar_dimensoes(sessao_com_tabelas)
    (de_novo,) = [a for a in cliente.get(f"/capitulos/{capitulo_id}/artefatos").json()["artefatos"] if a["frame_id"] == frame["id"]]
    assert de_novo["imagem_orientacao"] == "RETRATO"


def teste_artefato_sem_imagem_nao_tem_campos_de_imagem(
    cliente: TestClient, usar_provedor_falso
) -> None:
    _, frame, _ = _cenario(cliente, usar_provedor_falso)

    (artefato,) = [
        a for a in cliente.get(f"/capitulos/{frame['capitulo_id']}/artefatos").json()["artefatos"] if a["frame_id"] == frame["id"]
    ]

    assert (artefato["imagem_id"], artefato["imagem_largura"], artefato["imagem_orientacao"]) == (None, None, None)
