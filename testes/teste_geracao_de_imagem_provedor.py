"""Testes do provedor para gerar a imagem e suavizar o prompt (item 6.6, "Gerar a imagem", S4 e S6).

Usam o transporte falso do ``httpx``: nenhuma chamada de verdade, nenhum custo.
"""

import base64
import json
from decimal import Decimal

import httpx
import pytest

from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter, dividir_em_trechos
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
# suavizar_prompt (trecho a trecho, S7 revisada)
# --------------------------------------------------------------------------- #

PROMPT_RECUSADO = "close-up, Auri, nude with pale smooth skin, long golden hair, joyful smile, cinematic style, 2:3"


def _resposta_de_trechos(*trechos: str) -> dict:
    return {"choices": [{"message": {"content": json.dumps({"trechos": list(trechos)})}}]}


def _provedor_em_sequencia(respostas: list[dict], usos: list | None = None):
    """Um provedor que devolve uma resposta diferente a cada chamada, na ordem; guarda os pedidos feitos."""
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(200, json=respostas[len(pedidos) - 1])

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave-de-teste", cliente=cliente, ao_usar=usos.append if usos is not None else None), pedidos


def teste_suavizar_manda_os_trechos_numerados_e_junta_a_resposta_na_ordem() -> None:
    usos: list[UsoDaChamada] = []
    provedor, pedidos = _provedor_em_sequencia(
        [
            _resposta_de_trechos(
                "close-up", "Auri", "bare shoulders, pale smooth skin, covered by her hair", "long golden hair",
                "joyful smile", "cinematic style", "2:3",
            )
        ],
        usos,
    )

    suave = provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    assert suave.texto == (
        "close-up, Auri, bare shoulders, pale smooth skin, covered by her hair, long golden hair, "
        "joyful smile, cinematic style, 2:3"
    )
    assert suave.modelo == "openai/gpt-4o-mini"
    corpo = json.loads(pedidos[0].content)
    pedido = corpo["messages"][1]["content"]
    assert "1. close-up" in pedido and "3. nude with pale smooth skin" in pedido and "7. 2:3" in pedido
    assert "(7 no total)" in pedido
    assert usos[0].operacao == "suavizacao"


def teste_suavizar_usa_temperatura_baixa() -> None:
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trechos("a", "b")])

    provedor.suavizar_prompt("a, b", "openai/gpt-4o-mini")

    assert json.loads(pedidos[0].content)["temperature"] == 0.2


def teste_suavizar_com_numero_diferente_de_trechos_tenta_de_novo_uma_vez() -> None:
    """O modelo suprimiu um trecho (devolveu 2 de 3): pede de novo, e a segunda resposta certa vale."""
    provedor, pedidos = _provedor_em_sequencia(
        [_resposta_de_trechos("a", "c"), _resposta_de_trechos("a", "b", "c")]
    )

    suave = provedor.suavizar_prompt("a, x, c", "openai/gpt-4o-mini")

    assert suave.texto == "a, b, c"
    assert len(pedidos) == 2


def teste_suavizar_que_erra_duas_vezes_e_erro_e_nunca_um_prompt_com_trechos_faltando() -> None:
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trechos("a"), _resposta_de_trechos("a")])

    with pytest.raises(ErroDoProvedorIA, match="trechos"):
        provedor.suavizar_prompt("a, b, c", "openai/gpt-4o-mini")

    assert len(pedidos) == 2  # a primeira e mais uma, sem laço


@pytest.mark.parametrize(
    "conteudo",
    [
        "isto não é JSON",
        json.dumps({"trechos": "a, b"}),  # não é lista
        json.dumps({"trechos": ["a", ""]}),  # item vazio = trecho suprimido
        json.dumps({"trechos": ["a", 5]}),  # item que não é texto
        json.dumps({"outro": ["a", "b"]}),
    ],
)
def teste_suavizar_recusa_respostas_que_nao_servem(conteudo: str) -> None:
    resposta = {"choices": [{"message": {"content": conteudo}}]}
    provedor, _ = _provedor_em_sequencia([resposta, resposta])

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt("a, b", "openai/gpt-4o-mini")


def teste_suavizar_aceita_json_embrulhado_em_markdown() -> None:
    resposta = {"choices": [{"message": {"content": '```json\n{"trechos": ["a", "b novo"]}\n```'}}]}
    provedor, _ = _provedor_em_sequencia([resposta])

    assert provedor.suavizar_prompt("a, b", "openai/gpt-4o-mini").texto == "a, b novo"


def teste_suavizar_prompt_vazio_e_erro_sem_chamar_o_modelo() -> None:
    provedor, pedidos = _provedor_em_sequencia([])

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt(" , ,, ", "openai/gpt-4o-mini")

    assert pedidos == []


def teste_dividir_em_trechos_separa_por_virgula_e_descarta_vazios() -> None:
    assert dividir_em_trechos("close-up,  Auri , ,2:3") == ["close-up", "Auri", "2:3"]
    assert dividir_em_trechos("sem virgula") == ["sem virgula"]
    assert dividir_em_trechos("") == []


def teste_a_instrucao_de_suavizacao_exige_fidelidade_e_traz_as_regras_do_allan() -> None:
    """S7 revisada, S8 e S9."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trechos("a")])

    provedor.suavizar_prompt("a", "openai/gpt-4o-mini")

    instrucao = json.loads(pedidos[0].content)["messages"][0]["content"]
    assert "EXATAMENTE o mesmo número de itens" in instrucao
    assert "IDÊNTICO" in instrucao  # o que não é explícito não muda
    assert "o MÍNIMO" in instrucao
    assert "cobertura parcial" in instrucao
    assert "sempre sem sangue" in instrucao


def teste_a_instrucao_de_suavizacao_manda_sugerir_e_nao_vestir() -> None:
    """02/10: a suavização estava vestindo a personagem. Cobrir é composição (cabelo, braço, sombra, enquadramento)."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trechos("a")])

    provedor.suavizar_prompt("a", "openai/gpt-4o-mini")

    instrucao = json.loads(pedidos[0].content)["messages"][0]["content"]
    assert "SUGERIR, e não vestir" in instrucao
    assert "NÃO acrescente roupa" in instrucao
    assert "cabelo" in instrucao and "enquadramento" in instrucao  # as formas de cobrir
    assert "Exemplo CERTO" in instrucao and "Exemplo ERRADO" in instrucao
    assert "wearing a loose linen dress" in instrucao  # o erro, mostrado como erro
    # "tecido" saiu da lista de coberturas: o modelo o entendia como roupa.
    assert "cabelo, tecido" not in instrucao


def teste_a_regra_de_menores_so_vale_quando_o_trecho_diz_que_e_menor() -> None:
    """02/10: "Menores sempre vestidos" estava sendo lida como regra geral. Só vale com menor claro (S9)."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trechos("a")])

    provedor.suavizar_prompt("a", "openai/gpt-4o-mini")

    instrucao = json.loads(pedidos[0].content)["messages"][0]["content"]
    assert "SÓ quando o trecho disser ou deixar claro" in instrucao
    assert "sempre vestida e nunca em cena sensual" in instrucao
    assert "Young woman" in instrucao  # adulto: a regra não se aplica
    assert "nunca vista alguém só por precaução" in instrucao
