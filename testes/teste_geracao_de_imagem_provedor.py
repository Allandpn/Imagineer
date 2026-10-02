"""Testes do provedor para gerar a imagem e suavizar o prompt (item 6.6, "Gerar a imagem", S4 e S6).

Usam o transporte falso do ``httpx``: nenhuma chamada de verdade, nenhum custo.
"""

import base64
import json
from decimal import Decimal

import httpx
import pytest

from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ConteudoRecusado,
    ErroDoProvedorIA,
    ModeloNaoEscolhido,
    UsoDaChamada,
)

PNG = b"\x89PNG\r\n\x1a\nbytes-de-imagem"
MENSAGEM_DA_META = "The response was filtered due to the prompt triggering our content management policy."


def _provedor(resposta: httpx.Response | dict, chave: str | None = "chave-de-teste", usos: list | None = None):
    """Um ``ProvedorOpenRouter`` que responde o que o teste combinar e guarda os pedidos feitos."""
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return resposta if isinstance(resposta, httpx.Response) else httpx.Response(200, json=resposta)

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    ao_usar = usos.append if usos is not None else None
    return ProvedorOpenRouter(chave_api=chave, cliente=cliente, ao_usar=ao_usar), pedidos


def _resposta_de_imagem(media_type: str = "image/webp", custo: float | None = 0.01) -> dict:
    corpo = {"created": 1, "data": [{"b64_json": base64.b64encode(PNG).decode(), "media_type": media_type}]}
    if custo is not None:
        corpo["usage"] = {"prompt_tokens": 40, "completion_tokens": 2445, "cost": custo}
    return corpo


def _erro_400(mensagem: str) -> httpx.Response:
    return httpx.Response(400, json={"error": {"message": mensagem, "code": 400}})


# --------------------------------------------------------------------------- #
# gerar_imagem
# --------------------------------------------------------------------------- #


def teste_gerar_imagem_chama_images_com_modelo_e_prompt_e_decodifica_o_base64() -> None:
    provedor, pedidos = _provedor(_resposta_de_imagem("image/webp"))

    imagem = provedor.gerar_imagem("close-up, Auri", "meta/muse-image")

    assert imagem.conteudo == PNG
    assert imagem.tipo_de_midia == "image/webp"
    assert imagem.modelo == "meta/muse-image"
    assert pedidos[0].url.path == "/api/v1/images"  # não o /chat/completions: o OpenRouter o recusa
    assert json.loads(pedidos[0].content) == {"model": "meta/muse-image", "prompt": "close-up, Auri"}
    assert pedidos[0].headers["authorization"] == "Bearer chave-de-teste"


def teste_gerar_imagem_avisa_o_consumo_com_a_operacao_imagem() -> None:
    usos: list[UsoDaChamada] = []
    provedor, _ = _provedor(_resposta_de_imagem(custo=0.01), usos=usos)

    provedor.gerar_imagem("x", "meta/muse-image")

    assert len(usos) == 1
    assert usos[0].operacao == "imagem"
    assert usos[0].modelo == "meta/muse-image"
    assert usos[0].custo == Decimal("0.01")
    assert usos[0].tokens_saida == 2445


def teste_recusa_de_conteudo_da_meta_vira_conteudo_recusado_sem_gravar_consumo() -> None:
    usos: list[UsoDaChamada] = []
    provedor, _ = _provedor(_erro_400(MENSAGEM_DA_META), usos=usos)

    with pytest.raises(ConteudoRecusado) as erro:
        provedor.gerar_imagem("close-up, Auri, nude", "meta/muse-image")

    assert erro.value.motivo == MENSAGEM_DA_META
    assert usos == []  # a recusa não cobra


def teste_recusa_de_conteudo_da_black_forest_labs_tambem_e_reconhecida() -> None:
    provedor, _ = _provedor(_erro_400("Black Forest Labs blocked this request: it was flagged for sexual or adult content."))

    with pytest.raises(ConteudoRecusado):
        provedor.gerar_imagem("x", "black-forest-labs/flux.2-klein-4b")


def teste_recusa_com_corpo_que_nao_e_json_ainda_e_reconhecida_pelo_texto() -> None:
    provedor, _ = _provedor(httpx.Response(400, text=MENSAGEM_DA_META))

    with pytest.raises(ConteudoRecusado):
        provedor.gerar_imagem("x", "meta/muse-image")


def teste_erro_400_que_nao_e_de_conteudo_e_erro_comum() -> None:
    """S4: só a recusa de conteúdo dispara a suavização; um pedido inválido não."""
    provedor, _ = _provedor(_erro_400("Invalid request: model does not support this size."))

    with pytest.raises(ErroDoProvedorIA) as erro:
        provedor.gerar_imagem("x", "meta/muse-image")

    assert not isinstance(erro.value, ConteudoRecusado)


def teste_503_nao_e_recusa() -> None:
    """O 503 "temporariamente indisponível" que a Meta devolveu num teste real é falha, não moderação."""
    provedor, _ = _provedor(httpx.Response(503, json={"error": {"message": "The image generation service is temporarily unavailable."}}))

    with pytest.raises(ErroDoProvedorIA) as erro:
        provedor.gerar_imagem("x", "meta/muse-image")

    assert not isinstance(erro.value, ConteudoRecusado)


def teste_mesmo_texto_de_recusa_com_outro_codigo_nao_e_recusa() -> None:
    provedor, _ = _provedor(httpx.Response(500, text=MENSAGEM_DA_META))

    with pytest.raises(ErroDoProvedorIA) as erro:
        provedor.gerar_imagem("x", "meta/muse-image")

    assert not isinstance(erro.value, ConteudoRecusado)


def teste_gerar_imagem_sem_chave_ou_sem_modelo_falha_antes_de_chamar() -> None:
    sem_chave, pedidos = _provedor(_resposta_de_imagem(), chave=None)
    with pytest.raises(ChaveDeApiAusente):
        sem_chave.gerar_imagem("x", "meta/muse-image")

    sem_modelo, pedidos_sem_modelo = _provedor(_resposta_de_imagem())
    with pytest.raises(ModeloNaoEscolhido):
        sem_modelo.gerar_imagem("x", "")

    assert pedidos == [] and pedidos_sem_modelo == []


@pytest.mark.parametrize(
    "resposta",
    [
        {"data": []},
        {"created": 1},
        {"data": [{"url": "https://exemplo/imagem.png"}]},  # só URL: não tratado por enquanto
        {"data": [{"b64_json": "isto não é base64!!"}]},
        {"data": [{"b64_json": ""}]},
    ],
)
def teste_resposta_fora_do_formato_vira_erro_do_provedor(resposta: dict) -> None:
    provedor, _ = _provedor(resposta)

    with pytest.raises(ErroDoProvedorIA):
        provedor.gerar_imagem("x", "meta/muse-image")


# --------------------------------------------------------------------------- #
# suavizar_prompt
# --------------------------------------------------------------------------- #


def teste_suavizar_prompt_manda_o_texto_recusado_e_devolve_o_novo() -> None:
    usos: list[UsoDaChamada] = []
    resposta = {"choices": [{"message": {"content": "  close-up, Auri, bare shoulders, covered by her hair  "}}]}
    provedor, pedidos = _provedor(resposta, usos=usos)

    suave = provedor.suavizar_prompt("close-up, Auri, nude", "openai/gpt-4o-mini")

    assert suave.texto == "close-up, Auri, bare shoulders, covered by her hair"
    assert suave.modelo == "openai/gpt-4o-mini"
    corpo = json.loads(pedidos[0].content)
    assert pedidos[0].url.path == "/api/v1/chat/completions"
    assert "close-up, Auri, nude" in corpo["messages"][1]["content"]
    assert usos[0].operacao == "suavizacao"


def teste_a_instrucao_de_suavizacao_traz_as_regras_do_allan() -> None:
    """S7 a S9: cobertura parcial, sem sangue, menores vestidos e nunca sensuais."""
    provedor, pedidos = _provedor({"choices": [{"message": {"content": "texto"}}]})

    provedor.suavizar_prompt("x", "openai/gpt-4o-mini")

    instrucao = json.loads(pedidos[0].content)["messages"][0]["content"]
    assert "cobertura parcial" in instrucao
    assert "sem sangue" in instrucao
    assert "Menores de idade: sempre vestidos e nunca em cena sensual" in instrucao
    assert "nude" in instrucao  # citado como palavra a evitar


def teste_suavizar_prompt_com_resposta_vazia_e_erro() -> None:
    provedor, _ = _provedor({"choices": [{"message": {"content": "   "}}]})

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt("x", "openai/gpt-4o-mini")
