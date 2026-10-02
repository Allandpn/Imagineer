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
# suavizar_prompt (troca só os trechos explícitos, S7 revisada)
# --------------------------------------------------------------------------- #

# O prompt real que o Allan testou em 02/10/2026 (com a vírgula dentro de "pale, smooth skin" e o bloco final em outra linha).
PROMPT_RECUSADO = (
    "medium shot, Auri, nude with pale, smooth skin, long golden hair tied in a ponytail, slender arms raised, "
    "oil painting style,  --v 5 --q 2 --ar 3:4\n\nStyle: oil painting. Lighting: soft diffuse light. Format: portrait."
)


def _resposta_de_trocas(*trocas: tuple[str, str]) -> dict:
    corpo = {"trocas": [{"trecho": trecho, "novo": novo} for trecho, novo in trocas]}
    return {"choices": [{"message": {"content": json.dumps(corpo)}}]}


def _provedor_em_sequencia(respostas: list[dict], usos: list | None = None):
    """Um provedor que devolve uma resposta diferente a cada chamada, na ordem; guarda os pedidos feitos."""
    pedidos: list[httpx.Request] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido)
        return httpx.Response(200, json=respostas[len(pedidos) - 1])

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave-de-teste", cliente=cliente, ao_usar=usos.append if usos is not None else None), pedidos


TROCA_CERTA = ("nude with pale, smooth skin", "bare shoulders and arms, pale, smooth skin, her torso softly lost in shadow")


def teste_suavizar_troca_so_o_trecho_explicito_e_deixa_o_resto_identico() -> None:
    usos: list[UsoDaChamada] = []
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)], usos)

    suave = provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    # Tudo o que não é a troca é idêntico ao original, inclusive as vírgulas, os espaços duplos e as quebras de linha.
    assert suave.texto == PROMPT_RECUSADO.replace(TROCA_CERTA[0], TROCA_CERTA[1])
    assert suave.texto.startswith("medium shot, Auri, bare shoulders and arms, pale, smooth skin, her torso softly lost in shadow, long golden hair")
    assert "oil painting style,  --v 5 --q 2 --ar 3:4\n\nStyle: oil painting." in suave.texto
    assert suave.modelo == "openai/gpt-4o-mini"
    assert "PROMPT RECUSADO PELO PROVEDOR DE IMAGEM:\n" + PROMPT_RECUSADO == json.loads(pedidos[0].content)["messages"][1]["content"]
    assert usos[0].operacao == "suavizacao"


def teste_suavizar_usa_temperatura_baixa() -> None:
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)])

    provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    assert json.loads(pedidos[0].content)["temperature"] == 0.2


def teste_suavizar_aplica_mais_de_uma_troca() -> None:
    provedor, _ = _provedor_em_sequencia(
        [_resposta_de_trocas(("nude", "bare shoulders, covered by her hair"), ("slender arms raised", "slender arms reaching toward the light"))]
    )

    original = "close-up, Auri, nude, long golden hair, slender arms raised, soft diffuse light, oil painting style, 2:3"
    suave = provedor.suavizar_prompt(original, "openai/gpt-4o-mini")

    assert suave.texto == (
        "close-up, Auri, bare shoulders, covered by her hair, long golden hair, slender arms reaching toward the light, "
        "soft diffuse light, oil painting style, 2:3"
    )


@pytest.mark.parametrize(
    "troca",
    [
        ("trecho que não existe no prompt", "qualquer coisa"),  # o modelo inventou o trecho
        ("nude with pale, smooth skin", ""),  # novo vazio = apagar o que o autor descreveu
        ("nude with pale, smooth skin", "nude with pale, smooth skin"),  # não mudou nada
        ("", "texto"),
    ],
)
def teste_suavizar_recusa_troca_invalida_e_tenta_de_novo(troca: tuple[str, str]) -> None:
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(troca), _resposta_de_trocas(TROCA_CERTA)])

    suave = provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    assert "her torso softly lost in shadow" in suave.texto
    assert len(pedidos) == 2


def teste_suavizar_que_so_erra_e_erro_e_nunca_devolve_o_texto_sem_trocas() -> None:
    erro = _resposta_de_trocas(("trecho que não existe", "x"))
    provedor, pedidos = _provedor_em_sequencia([erro, erro])

    with pytest.raises(ErroDoProvedorIA, match="trocas válidas"):
        provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    assert len(pedidos) == 2  # a primeira e mais uma, sem laço


def teste_suavizar_sem_nenhuma_troca_nao_serve() -> None:
    """Se o provedor recusou, alguma coisa é explícita: devolver o texto igual só gastaria a segunda tentativa."""
    provedor, _ = _provedor_em_sequencia([_resposta_de_trocas(), _resposta_de_trocas()])

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")


def teste_suavizar_nao_deixa_o_modelo_reescrever_o_prompt_inteiro() -> None:
    """Uma troca que cobre o prompt todo (ou mais da metade) é reescrever, não suavizar: o autor perderia pontos."""
    tudo = _resposta_de_trocas((PROMPT_RECUSADO, "a woman in a long dress"))
    # 125 de 217 caracteres (58%): abaixo do limite de uma troca (200), mas acima da metade do texto.
    metade = _resposta_de_trocas(("medium shot, Auri, nude with pale, smooth skin, long golden hair tied in a ponytail, slender arms raised, oil painting style", "x"))
    provedor, _ = _provedor_em_sequencia([tudo, metade])

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")


def teste_suavizar_recusa_trocas_que_se_sobrepoem() -> None:
    sobrepostas = _resposta_de_trocas(("nude with pale", "bare shoulders with pale"), ("pale, smooth skin", "pale skin"))
    provedor, _ = _provedor_em_sequencia([sobrepostas, sobrepostas])

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")


@pytest.mark.parametrize(
    "conteudo",
    [
        "isto não é JSON",
        json.dumps({"trocas": "nude -> covered"}),  # não é lista
        json.dumps({"trocas": ["nude"]}),  # item que não é par
        json.dumps({"trocas": [{"trecho": "nude", "novo": 5}]}),
        json.dumps({"outro": []}),
    ],
)
def teste_suavizar_recusa_respostas_que_nao_servem(conteudo: str) -> None:
    resposta = {"choices": [{"message": {"content": conteudo}}]}
    provedor, _ = _provedor_em_sequencia([resposta, resposta])

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")


def teste_suavizar_aceita_json_embrulhado_em_markdown() -> None:
    corpo = json.dumps({"trocas": [{"trecho": "nude", "novo": "bare shoulders, covered by her hair"}]})
    resposta = {"choices": [{"message": {"content": f"```json\n{corpo}\n```"}}]}
    provedor, _ = _provedor_em_sequencia([resposta])

    assert provedor.suavizar_prompt("Auri, nude, oil painting", "openai/gpt-4o-mini").texto == "Auri, bare shoulders, covered by her hair, oil painting"


def teste_suavizar_prompt_vazio_e_erro_sem_chamar_o_modelo() -> None:
    provedor, pedidos = _provedor_em_sequencia([])

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt("   ", "openai/gpt-4o-mini")

    assert pedidos == []


def teste_a_instrucao_de_suavizacao_traz_as_regras_do_allan() -> None:
    """S7 revisada, S8 e S9: o modelo só aponta trocas, e a cobertura vem da composição."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)])

    provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    instrucao = json.loads(pedidos[0].content)["messages"][0]["content"]
    assert "reescrever SÓ esses" in instrucao
    assert "EXATAMENTE como está" in instrucao  # o resto o sistema mantém
    assert "LETRA POR LETRA" in instrucao
    assert "o MÍNIMO" in instrucao
    assert "sempre sem sangue" in instrucao


def teste_a_instrucao_de_suavizacao_manda_sugerir_e_nao_vestir_nem_so_apagar() -> None:
    """02/10: vestia a personagem; e, no teste manual, o modelo só apagava a palavra "nude" sem cobrir nada."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)])

    provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    instrucao = json.loads(pedidos[0].content)["messages"][0]["content"]
    assert "SUGERIR, e não vestir" in instrucao
    assert "NÃO acrescente roupa" in instrucao
    texto_corrido = " ".join(instrucao.split())
    assert "DUAS coisas" in texto_corrido and "APARECE" in texto_corrido and "COBRE o resto" in texto_corrido
    assert "Apagar só a palavra" in texto_corrido and "NÃO basta" in texto_corrido
    assert "Exemplo CERTO" in instrucao and "Exemplo ERRADO 1" in instrucao and "Exemplo ERRADO 2" in instrucao
    assert "her torso softly lost in shadow" in instrucao
    assert "cabelo, tecido" not in instrucao  # "tecido" saiu da lista: o modelo o entendia como roupa


def teste_a_regra_de_menores_so_vale_quando_o_prompt_diz_que_e_menor() -> None:
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)])

    provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    instrucao = json.loads(pedidos[0].content)["messages"][0]["content"]
    assert "SÓ quando o prompt disser ou deixar claro" in instrucao
    assert "sempre vestida e nunca em cena sensual" in instrucao
    assert "Young woman" in instrucao  # adulto: a regra não se aplica
    assert "nunca vista alguém só por precaução" in instrucao


def teste_a_instrucao_de_suavizacao_proibe_contradizer_o_prompt_e_prefere_sombra() -> None:
    """02/10: os modelos cobriam com o cabelo solto num prompt de cabelo preso, e cruzavam braços já levantados."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)])

    provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    texto = " ".join(json.loads(pedidos[0].content)["messages"][0]["content"].split())
    assert "NÃO pode contradizer o resto do prompt" in texto
    assert "se o cabelo está preso, não o faça cair sobre o corpo" in texto
    assert "cubra com SOMBRA ou ENQUADRAMENTO" in texto
    assert "her torso softly lost in shadow" in texto


def teste_a_instrucao_de_suavizacao_pede_o_trecho_completo_com_os_adjetivos() -> None:
    """O trecho a trocar vem inteiro ("nude with pale, smooth skin"), sem partir a expressão no meio."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)])

    provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    texto = " ".join(json.loads(pedidos[0].content)["messages"][0]["content"].split())
    assert "COMPLETO" in texto and "sem partir a expressão no meio" in texto


def teste_a_instrucao_de_suavizacao_manda_tirar_a_ferida_aberta_e_nao_so_a_palavra_sangue() -> None:
    """02/10: o gpt-4.1-mini tirava "blood" e mantinha "a deep gaping wound" (4 de 4 gerações)."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)])

    provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4o-mini")

    texto = " ".join(json.loads(pedidos[0].content)["messages"][0]["content"].split())
    assert "troque também a ferida aberta, o corte e o corpo mutilado, não só a palavra" in texto
    assert 'a dark shadow across his chest, his torn armor stained' in texto  # o exemplo certo
    assert "só tirou a palavra" in texto  # o exemplo errado


def teste_suavizar_recusa_cabelo_caindo_sobre_o_corpo_quando_o_prompt_diz_que_esta_preso() -> None:
    """02/10: os dois modelos cobriam a Auri (cabelo em rabo de cavalo) com "cabelo caindo sobre o corpo"."""
    ruim = _resposta_de_trocas(("nude with pale, smooth skin", "bare shoulders and arms, her long hair falling over her body"))
    provedor, pedidos = _provedor_em_sequencia([ruim, _resposta_de_trocas(TROCA_SOMBRA)])

    suave = provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4.1-mini")

    assert "her torso softly lost in shadow" in suave.texto
    assert "falling over her body" not in suave.texto
    assert len(pedidos) == 2
    # A segunda tentativa diz por que a primeira foi recusada.
    segundo = json.loads(pedidos[1].content)["messages"][1]["content"]
    assert "ATENÇÃO: a sua resposta anterior foi recusada porque o cabelo está preso no prompt" in segundo
    assert "ATENÇÃO" not in json.loads(pedidos[0].content)["messages"][1]["content"]


def teste_suavizar_aceita_cabelo_caindo_se_o_prompt_nao_diz_que_esta_preso() -> None:
    provedor, pedidos = _provedor_em_sequencia(
        [_resposta_de_trocas(("nude", "bare shoulders, her long hair falling over her body"))]
    )

    suave = provedor.suavizar_prompt("close-up, Auri, nude, long golden hair, oil painting", "openai/gpt-4.1-mini")

    assert "falling over her body" in suave.texto
    assert len(pedidos) == 1


def teste_suavizar_recusa_cruzar_bracos_que_o_prompt_diz_que_estao_levantados() -> None:
    cruzado = _resposta_de_trocas(("nude", "bare shoulders, one arm across her chest"))
    provedor, pedidos = _provedor_em_sequencia([cruzado, _resposta_de_trocas(("nude", "bare shoulders, half in shadow"))])

    suave = provedor.suavizar_prompt("close-up, Auri, nude, slender arms raised, oil painting", "openai/gpt-4.1-mini")

    assert "half in shadow" in suave.texto
    assert "os braços estão levantados no prompt" in json.loads(pedidos[1].content)["messages"][1]["content"]


def teste_suavizar_que_contradiz_duas_vezes_e_erro() -> None:
    ruim = _resposta_de_trocas(("nude with pale, smooth skin", "bare shoulders, her long hair falling over her body"))
    provedor, pedidos = _provedor_em_sequencia([ruim, ruim])

    with pytest.raises(ErroDoProvedorIA):
        provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4.1-mini")

    assert len(pedidos) == 2


TROCA_SOMBRA = ("nude with pale, smooth skin", "bare shoulders and arms, her torso softly lost in shadow, pale, smooth skin")


def teste_a_instrucao_de_suavizacao_manda_a_frase_continuar_correta_depois_da_troca() -> None:
    """02/10: "her torso softly lost in shadow gathered into a long ponytail": a troca engolia a palavra de ligação."""
    provedor, pedidos = _provedor_em_sequencia([_resposta_de_trocas(TROCA_CERTA)])

    provedor.suavizar_prompt(PROMPT_RECUSADO, "openai/gpt-4.1-mini")

    texto = " ".join(json.loads(pedidos[0].content)["messages"][0]["content"].split())
    assert "a frase tem de continuar correta" in texto
    assert "palavras de ligação" in texto
    assert "a young woman with bare shoulders and arms, her torso softly lost in shadow, and long golden hair" in texto


# --------------------------------------------------------------------------- #
# Imagens de referência (item 7.5b, W4)
# --------------------------------------------------------------------------- #


def teste_w4_openrouter_manda_as_referencias_como_input_references_em_data_url() -> None:
    from imagineer.ia.provedor import ImagemDeReferencia, ReferenciasParaGerar

    provedor, pedidos = _provedor(_resposta_de_imagem())
    referencias = ReferenciasParaGerar(
        [ImagemDeReferencia(b"abc", "image/jpeg"), ImagemDeReferencia(b"def", "image/png")], "input_references"
    )

    provedor.gerar_imagem("uma cena", "meta/muse-image", referencias=referencias)

    corpo = json.loads(pedidos[0].content)
    assert corpo["model"] == "meta/muse-image" and corpo["prompt"] == "uma cena"
    assert corpo["input_references"] == [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b"abc").decode()}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b"def").decode()}},
    ]


def teste_w4_sem_referencias_o_corpo_continua_so_com_modelo_e_prompt() -> None:
    provedor, pedidos = _provedor(_resposta_de_imagem())

    provedor.gerar_imagem("uma cena", "meta/muse-image")

    assert json.loads(pedidos[0].content) == {"model": "meta/muse-image", "prompt": "uma cena"}
