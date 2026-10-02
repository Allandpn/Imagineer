"""Testes dos fornecedores de imagem fal.ai e Replicate (item 6.6, F1 a F11).

Usam o transporte falso do ``httpx``: nenhuma chamada de verdade, nenhum custo. As formas das respostas seguem a
documentação dos dois fornecedores (consultada em 02/10/2026); **nada aqui foi rodado contra os serviços reais**.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from imagineer import configuracao as modulo_de_configuracao
from imagineer.ia.fornecedores_de_imagem import (
    GeradorFal,
    GeradorReplicate,
    montar_geradores,
    separar_fornecedor,
)
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter
from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ConteudoRecusado,
    ErroDoProvedorIA,
    ModeloNaoEscolhido,
    UsoDaChamada,
)

PNG = b"\x89PNG\r\n\x1a\nimagem-de-teste"
URL_DA_IMAGEM = "https://v3.fal.media/files/abc/imagem.png"


class Rede:
    """Um servidor falso: responde por (método, URL), na ordem, e guarda os pedidos feitos."""

    def __init__(self, respostas: dict[tuple[str, str], list[httpx.Response] | httpx.Response]):
        self._respostas = {chave: (valor if isinstance(valor, list) else [valor]) for chave, valor in respostas.items()}
        self.pedidos: list[httpx.Request] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        chave = (pedido.method, str(pedido.url))
        fila = self._respostas.get(chave)
        assert fila, f"pedido inesperado: {chave}"
        return fila.pop(0) if len(fila) > 1 else fila[0]

    def cliente(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _json(corpo: dict, codigo: int = 200) -> httpx.Response:
    return httpx.Response(codigo, json=corpo)


def _imagem(tipo: str = "image/png") -> httpx.Response:
    return httpx.Response(200, content=PNG, headers={"content-type": tipo})


class RelogioQueAvanca:
    """Cada leitura avança ``passo`` segundos: faz o limite de tempo estourar sem esperar de verdade."""

    def __init__(self, passo: float):
        self._agora = 0.0
        self._passo = passo

    def __call__(self) -> float:
        self._agora += self._passo
        return self._agora


# --------------------------------------------------------------------------- #
# F1: o prefixo do fornecedor
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "modelo, esperado",
    [
        ("meta/muse-image", ("openrouter", "meta/muse-image")),
        ("fal:fal-ai/flux/dev", ("fal", "fal-ai/flux/dev")),
        ("replicate:black-forest-labs/flux-1.1-pro", ("replicate", "black-forest-labs/flux-1.1-pro")),
        ("openrouter:meta/muse-image", ("openrouter", "meta/muse-image")),
        (" FAL : fal-ai/flux/dev ", ("fal", "fal-ai/flux/dev")),
        # Os sufixos do OpenRouter (depois da barra) não são fornecedor.
        ("openai/gpt-oss-120b:batch", ("openrouter", "openai/gpt-oss-120b:batch")),
        ("google/gemini-2.5-flash-lite:batch", ("openrouter", "google/gemini-2.5-flash-lite:batch")),
        # Prefixo que não é fornecedor conhecido: continua sendo do OpenRouter, sem cortar nada.
        ("outro:coisa", ("openrouter", "outro:coisa")),
        ("fal", ("openrouter", "fal")),
    ],
)
def teste_f1_o_prefixo_so_vale_para_fornecedor_conhecido(modelo: str, esperado: tuple[str, str]) -> None:
    assert separar_fornecedor(modelo) == esperado


# --------------------------------------------------------------------------- #
# fal.ai (F4, F5)
# --------------------------------------------------------------------------- #

SUBMISSAO = "https://queue.fal.run/fal-ai/flux/dev"
STATUS = "https://queue.fal.run/fal-ai/flux/requests/r1/status"
RESULTADO = "https://queue.fal.run/fal-ai/flux/requests/r1"
ENVIO = {"request_id": "r1", "status_url": STATUS, "response_url": RESULTADO}


def _fal(rede: Rede, **extra) -> GeradorFal:
    return GeradorFal("chave-fal", cliente=rede.cliente(), dormir=lambda _s: None, **extra)


def _rede_do_fal_com_sucesso(resultado: dict | None = None, status: list[httpx.Response] | None = None) -> Rede:
    if resultado is None:  # `{}` é um resultado válido para testar (resposta vazia), por isso não é `resultado or ...`
        resultado = {
            "images": [{"url": URL_DA_IMAGEM, "width": 1024, "height": 768, "content_type": "image/jpeg"}],
            "has_nsfw_concepts": [False],
        }
    return Rede(
        {
            ("POST", SUBMISSAO): _json(ENVIO),
            ("GET", STATUS): status or _json({"status": "COMPLETED"}),
            ("GET", RESULTADO): _json(resultado),
            ("GET", URL_DA_IMAGEM): _imagem("image/png"),
        }
    )


def teste_f5_fal_envia_so_o_prompt_com_a_chave_e_baixa_a_imagem() -> None:
    rede = _rede_do_fal_com_sucesso()

    imagem = _fal(rede).gerar("close-up, Auri", "fal-ai/flux/dev")

    assert imagem.conteudo == PNG
    assert imagem.tipo_de_midia == "image/jpeg"  # o que o fal.ai informou vale mais que o cabeçalho do arquivo
    envio = rede.pedidos[0]
    assert envio.method == "POST" and str(envio.url) == SUBMISSAO
    assert envio.headers["authorization"] == "Key chave-fal"
    assert json.loads(envio.content) == {"prompt": "close-up, Auri"}


def teste_f3_fal_nunca_manda_parametro_de_seguranca() -> None:
    """A moderação do fornecedor fica ligada: só o prompt vai no corpo."""
    rede = _rede_do_fal_com_sucesso()

    _fal(rede).gerar("qualquer prompt", "fal-ai/flux/dev")

    corpo = json.loads(rede.pedidos[0].content)
    assert list(corpo) == ["prompt"]
    texto = rede.pedidos[0].content.decode().lower()
    assert "safety" not in texto and "nsfw" not in texto


def teste_f5_fal_consulta_o_status_ate_completar() -> None:
    rede = _rede_do_fal_com_sucesso(
        status=[_json({"status": "IN_QUEUE"}), _json({"status": "IN_PROGRESS"}), _json({"status": "COMPLETED"})]
    )

    _fal(rede).gerar("x", "fal-ai/flux/dev")

    assert sum(1 for p in rede.pedidos if str(p.url) == STATUS) == 3


def teste_f10_fal_que_nao_termina_a_tempo_e_erro_do_provedor() -> None:
    rede = _rede_do_fal_com_sucesso(status=_json({"status": "IN_PROGRESS"}))

    with pytest.raises(ErroDoProvedorIA, match="não terminou"):
        _fal(rede, relogio=RelogioQueAvanca(passo=100.0)).gerar("x", "fal-ai/flux/dev")


def teste_f4_fal_devolve_imagem_preta_quando_o_filtro_dispara_e_ela_e_descartada() -> None:
    """O fal.ai não dá erro: marca `has_nsfw_concepts` e entrega uma imagem preta. Nunca pode ser gravada."""
    rede = _rede_do_fal_com_sucesso(
        {"images": [{"url": URL_DA_IMAGEM, "content_type": "image/png"}], "has_nsfw_concepts": [True]}
    )

    with pytest.raises(ConteudoRecusado, match="verificador de segurança"):
        _fal(rede).gerar("x", "fal-ai/flux/dev")

    assert not any(str(p.url) == URL_DA_IMAGEM for p in rede.pedidos)  # nem baixou a imagem preta


def teste_f4_fal_erro_422_de_politica_de_conteudo_vira_conteudo_recusado() -> None:
    erro = {"detail": [{"loc": ["body", "prompt"], "msg": "Content could not be processed due to material flagged by content checker", "type": "content_policy_violation"}]}
    rede = Rede({("POST", SUBMISSAO): _json(erro, 422)})

    with pytest.raises(ConteudoRecusado, match="flagged by content checker"):
        _fal(rede).gerar("x", "fal-ai/flux/dev")


def teste_f4_fal_a_recusa_tambem_vale_na_leitura_do_resultado() -> None:
    erro = {"detail": [{"msg": "flagged", "type": "content_policy_violation"}]}
    rede = Rede(
        {
            ("POST", SUBMISSAO): _json(ENVIO),
            ("GET", STATUS): _json({"status": "COMPLETED"}),
            ("GET", RESULTADO): _json(erro, 422),
        }
    )

    with pytest.raises(ConteudoRecusado):
        _fal(rede).gerar("x", "fal-ai/flux/dev")


def teste_f4_fal_erro_422_de_validacao_nao_e_recusa() -> None:
    """Só `content_policy_violation` é recusa (decide-se pelo `type`, nunca pela mensagem)."""
    erro = {"detail": [{"loc": ["body", "prompt"], "msg": "Field required", "type": "missing"}]}
    rede = Rede({("POST", SUBMISSAO): _json(erro, 422)})

    with pytest.raises(ErroDoProvedorIA) as erro_levantado:
        _fal(rede).gerar("x", "fal-ai/flux/dev")

    assert not isinstance(erro_levantado.value, ConteudoRecusado)


@pytest.mark.parametrize("codigo", [401, 403])
def teste_f10_fal_chave_recusada_diz_qual_variavel_conferir(codigo: int) -> None:
    rede = Rede({("POST", SUBMISSAO): httpx.Response(codigo, text="Unauthorized")})

    with pytest.raises(ChaveDeApiAusente, match="FAL_KEY"):
        _fal(rede).gerar("x", "fal-ai/flux/dev")


@pytest.mark.parametrize(
    "resultado",
    [
        {},
        {"images": []},
        {"images": [{"width": 10}]},  # sem URL
        {"images": "isto não é lista"},
    ],
)
def teste_f10_fal_sem_imagem_na_resposta_e_erro_do_provedor(resultado: dict) -> None:
    rede = _rede_do_fal_com_sucesso(resultado)

    with pytest.raises(ErroDoProvedorIA):
        _fal(rede).gerar("x", "fal-ai/flux/dev")


def teste_f10_fal_resposta_da_submissao_sem_as_urls_e_erro() -> None:
    rede = Rede({("POST", SUBMISSAO): _json({"request_id": "r1"})})

    with pytest.raises(ErroDoProvedorIA, match="formato inesperado"):
        _fal(rede).gerar("x", "fal-ai/flux/dev")


def teste_f10_fal_imagem_que_nao_baixa_e_erro() -> None:
    rede = _rede_do_fal_com_sucesso()
    rede._respostas[("GET", URL_DA_IMAGEM)] = [httpx.Response(404)]

    with pytest.raises(ErroDoProvedorIA, match="não entregou"):
        _fal(rede).gerar("x", "fal-ai/flux/dev")


def teste_f5_fal_aceita_resultado_com_uma_imagem_so() -> None:
    """Alguns modelos devolvem `image` (um objeto), e não `images` (uma lista)."""
    rede = _rede_do_fal_com_sucesso({"image": {"url": URL_DA_IMAGEM, "content_type": "image/webp"}})

    imagem = _fal(rede).gerar("x", "fal-ai/flux/dev")

    assert imagem.tipo_de_midia == "image/webp"


# --------------------------------------------------------------------------- #
# Replicate (F4, F6)
# --------------------------------------------------------------------------- #

PREDICAO = "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"
CONSULTA = "https://api.replicate.com/v1/predictions/p1"
SAIDA = "https://replicate.delivery/xezq/abc/out-0.webp"


def _replicate(rede: Rede, **extra) -> GeradorReplicate:
    return GeradorReplicate("chave-rep", cliente=rede.cliente(), dormir=lambda _s: None, **extra)


def _predicao(situacao: str, **campos) -> dict:
    return {"id": "p1", "status": situacao, "urls": {"get": CONSULTA}, **campos}


def teste_f6_replicate_espera_na_propria_chamada_e_baixa_a_imagem() -> None:
    rede = Rede({("POST", PREDICAO): _json(_predicao("succeeded", output=[SAIDA])), ("GET", SAIDA): _imagem("image/webp")})

    imagem = _replicate(rede).gerar("close-up, Auri", "black-forest-labs/flux-schnell")

    assert imagem.conteudo == PNG
    assert imagem.tipo_de_midia == "image/webp"
    envio = rede.pedidos[0]
    assert envio.headers["authorization"] == "Bearer chave-rep"
    assert envio.headers["prefer"] == "wait=60"
    assert json.loads(envio.content) == {"input": {"prompt": "close-up, Auri"}}


def teste_f3_replicate_nunca_manda_parametro_de_seguranca() -> None:
    rede = Rede({("POST", PREDICAO): _json(_predicao("succeeded", output=SAIDA)), ("GET", SAIDA): _imagem()})

    _replicate(rede).gerar("qualquer prompt", "black-forest-labs/flux-schnell")

    corpo = json.loads(rede.pedidos[0].content)
    assert list(corpo) == ["input"] and list(corpo["input"]) == ["prompt"]
    texto = rede.pedidos[0].content.decode().lower()
    assert "safety" not in texto and "nsfw" not in texto


def teste_f12_replicate_sem_filtro_manda_so_o_disable_safety_checker_alem_do_prompt() -> None:
    """O ÚNICO parâmetro de segurança que o sistema envia, e só por pedido explícito (F12)."""
    rede = Rede({("POST", PREDICAO): _json(_predicao("succeeded", output=SAIDA)), ("GET", SAIDA): _imagem()})

    _replicate(rede).gerar("um prompt", "black-forest-labs/flux-schnell", sem_filtro_de_seguranca=True)

    assert json.loads(rede.pedidos[0].content) == {"input": {"prompt": "um prompt", "disable_safety_checker": True}}


def teste_f14_fal_recusa_desligar_o_filtro_e_nao_chama_a_rede() -> None:
    rede = Rede({})

    with pytest.raises(ErroDoProvedorIA, match="só é permitido no Replicate"):
        GeradorFal("chave-fal", cliente=rede.cliente()).gerar("p", "fal-ai/flux/dev", sem_filtro_de_seguranca=True)

    assert rede.pedidos == []


def teste_f14_openrouter_recusa_desligar_o_filtro() -> None:
    provedor = ProvedorOpenRouter(chave_api="sk-teste")

    with pytest.raises(ErroDoProvedorIA, match="só é permitido no Replicate"):
        provedor.gerar_imagem("p", "meta/muse-image", sem_filtro_de_seguranca=True)


def teste_f6_replicate_a_saida_pode_ser_uma_url_so() -> None:
    rede = Rede({("POST", PREDICAO): _json(_predicao("succeeded", output=SAIDA)), ("GET", SAIDA): _imagem()})

    assert _replicate(rede).gerar("x", "black-forest-labs/flux-schnell").conteudo == PNG


def teste_f6_replicate_consulta_ate_terminar_quando_a_espera_nao_bastou() -> None:
    rede = Rede(
        {
            ("POST", PREDICAO): _json(_predicao("starting")),
            ("GET", CONSULTA): [_json(_predicao("processing")), _json(_predicao("succeeded", output=[SAIDA]))],
            ("GET", SAIDA): _imagem(),
        }
    )

    _replicate(rede).gerar("x", "black-forest-labs/flux-schnell")

    assert sum(1 for p in rede.pedidos if str(p.url) == CONSULTA) == 2


def teste_f10_replicate_que_nao_termina_a_tempo_e_erro_do_provedor() -> None:
    rede = Rede({("POST", PREDICAO): _json(_predicao("starting")), ("GET", CONSULTA): _json(_predicao("processing"))})

    with pytest.raises(ErroDoProvedorIA, match="não terminou"):
        _replicate(rede, relogio=RelogioQueAvanca(passo=100.0)).gerar("x", "black-forest-labs/flux-schnell")


def teste_f10_o_limite_do_servidor_e_menor_que_o_tempo_de_espera_do_app() -> None:
    """O app espera 180 s; o servidor tem de desistir antes, para o erro chegar com o nome do fornecedor."""
    from imagineer.ia.fornecedores_de_imagem import TEMPO_LIMITE_DA_GERACAO

    assert TEMPO_LIMITE_DA_GERACAO < 180


def teste_f10_o_tempo_conta_desde_o_pedido_nao_so_depois_da_espera_do_replicate() -> None:
    """A espera do `Prefer: wait` entra na conta: um pedido que já passou do limite não espera mais uma volta inteira."""
    rede = Rede({("POST", PREDICAO): _json(_predicao("starting")), ("GET", CONSULTA): _json(_predicao("processing"))})
    relogio = RelogioQueAvanca(passo=200.0)  # o primeiro `relogio()` (no pedido) e o segundo (na espera) já passam do limite

    with pytest.raises(ErroDoProvedorIA, match="não terminou"):
        _replicate(rede, relogio=relogio).gerar("x", "black-forest-labs/flux-schnell")

    assert sum(1 for p in rede.pedidos if str(p.url) == CONSULTA) == 0  # nem chegou a consultar de novo


@pytest.mark.parametrize(
    "mensagem",
    [
        "NSFW content detected. Try running it again, or try a different prompt.",
        "The input was flagged by the safety checker",
        "Prediction failed: sensitive content",
    ],
)
def teste_f4_replicate_predicao_que_falha_por_seguranca_vira_conteudo_recusado(mensagem: str) -> None:
    rede = Rede({("POST", PREDICAO): _json(_predicao("failed", error=mensagem))})

    with pytest.raises(ConteudoRecusado) as erro:
        _replicate(rede).gerar("x", "black-forest-labs/flux-schnell")

    assert erro.value.motivo == mensagem


def teste_f4_replicate_predicao_que_falha_por_outro_motivo_e_erro_comum() -> None:
    rede = Rede({("POST", PREDICAO): _json(_predicao("failed", error="CUDA out of memory"))})

    with pytest.raises(ErroDoProvedorIA, match="CUDA out of memory") as erro:
        _replicate(rede).gerar("x", "black-forest-labs/flux-schnell")

    assert not isinstance(erro.value, ConteudoRecusado)


def teste_f10_replicate_predicao_cancelada_e_erro() -> None:
    rede = Rede({("POST", PREDICAO): _json(_predicao("canceled"))})

    with pytest.raises(ErroDoProvedorIA, match="canceled"):
        _replicate(rede).gerar("x", "black-forest-labs/flux-schnell")


@pytest.mark.parametrize("codigo", [401, 403])
def teste_f10_replicate_chave_recusada_diz_qual_variavel_conferir(codigo: int) -> None:
    rede = Rede({("POST", PREDICAO): httpx.Response(codigo, json={"title": "Unauthenticated"})})

    with pytest.raises(ChaveDeApiAusente, match="REPLICATE_API_TOKEN"):
        _replicate(rede).gerar("x", "black-forest-labs/flux-schnell")


@pytest.mark.parametrize("saida", [None, [], "", [123]])
def teste_f10_replicate_sem_url_na_saida_e_erro(saida) -> None:
    rede = Rede({("POST", PREDICAO): _json(_predicao("succeeded", output=saida))})

    with pytest.raises(ErroDoProvedorIA):
        _replicate(rede).gerar("x", "black-forest-labs/flux-schnell")


# --------------------------------------------------------------------------- #
# A integração em ProvedorOpenRouter.gerar_imagem (F1, F2, F7)
# --------------------------------------------------------------------------- #


def _provedor_com_fornecedores(rede_fal: Rede | None = None, chave_openrouter: str | None = "chave-or", usos: list | None = None):
    chamadas_do_openrouter: list[httpx.Request] = []

    def openrouter(pedido: httpx.Request) -> httpx.Response:
        chamadas_do_openrouter.append(pedido)
        return httpx.Response(200, json={"data": [{"b64_json": "iVBORw0KGgo=", "media_type": "image/png"}]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(openrouter))
    geradores = {"fal": _fal(rede_fal)} if rede_fal is not None else {}
    provedor = ProvedorOpenRouter(
        chave_api=chave_openrouter,
        cliente=cliente,
        ao_usar=usos.append if usos is not None else None,
        geradores_de_imagem=geradores,
    )
    return provedor, chamadas_do_openrouter


def teste_f1_modelo_com_prefixo_vai_ao_fornecedor_e_nao_ao_openrouter() -> None:
    usos: list[UsoDaChamada] = []
    provedor, chamadas = _provedor_com_fornecedores(_rede_do_fal_com_sucesso(), usos=usos)

    imagem = provedor.gerar_imagem("close-up, Auri", "fal:fal-ai/flux/dev")

    assert imagem.conteudo == PNG
    assert imagem.modelo == "fal:fal-ai/flux/dev"  # o id completo, com o prefixo, é o que fica registrado
    assert chamadas == []
    # F7: o consumo é anotado, com custo nulo (nunca um zero inventado).
    assert usos == [UsoDaChamada(operacao="imagem", modelo="fal:fal-ai/flux/dev")]
    assert usos[0].custo is None


def teste_f1_a_recusa_do_fornecedor_chega_como_conteudo_recusado() -> None:
    """É o que mantém o fluxo S1 a S3 (suavizar e tentar de novo) funcionando com qualquer fornecedor."""
    rede = _rede_do_fal_com_sucesso(
        {"images": [{"url": URL_DA_IMAGEM}], "has_nsfw_concepts": [True]}
    )
    usos: list[UsoDaChamada] = []
    provedor, _ = _provedor_com_fornecedores(rede, usos=usos)

    with pytest.raises(ConteudoRecusado):
        provedor.gerar_imagem("x", "fal:fal-ai/flux/dev")

    assert usos == []  # a recusa não gera registro de consumo


def teste_f2_fornecedor_sem_chave_da_422_e_diz_qual_variavel_definir() -> None:
    provedor, chamadas = _provedor_com_fornecedores(None)

    with pytest.raises(ChaveDeApiAusente, match="Defina FAL_KEY no .env do servidor"):
        provedor.gerar_imagem("x", "fal:fal-ai/flux/dev")
    with pytest.raises(ChaveDeApiAusente, match="Defina REPLICATE_API_TOKEN no .env do servidor"):
        provedor.gerar_imagem("x", "replicate:black-forest-labs/flux-schnell")

    assert chamadas == []


def teste_f2_fornecedor_nao_depende_da_chave_do_openrouter() -> None:
    provedor, _ = _provedor_com_fornecedores(_rede_do_fal_com_sucesso(), chave_openrouter=None)

    assert provedor.gerar_imagem("x", "fal:fal-ai/flux/dev").conteudo == PNG


def teste_f1_prefixo_sem_modelo_depois_dele_e_modelo_nao_escolhido() -> None:
    provedor, _ = _provedor_com_fornecedores(_rede_do_fal_com_sucesso())

    with pytest.raises(ModeloNaoEscolhido):
        provedor.gerar_imagem("x", "fal:")


def teste_f1_modelo_sem_prefixo_continua_no_openrouter() -> None:
    provedor, chamadas = _provedor_com_fornecedores(_rede_do_fal_com_sucesso())

    provedor.gerar_imagem("x", "meta/muse-image")

    assert len(chamadas) == 1
    assert json.loads(chamadas[0].content)["model"] == "meta/muse-image"


def teste_f1_openrouter_com_prefixo_explicito_manda_o_id_sem_o_prefixo() -> None:
    provedor, chamadas = _provedor_com_fornecedores(None)

    provedor.gerar_imagem("x", "openrouter:meta/muse-image")

    assert json.loads(chamadas[0].content)["model"] == "meta/muse-image"


def teste_f1_sufixo_de_openrouter_com_dois_pontos_nao_e_cortado() -> None:
    provedor, chamadas = _provedor_com_fornecedores(None)

    provedor.gerar_imagem("x", "openai/gpt-oss-120b:batch")

    assert json.loads(chamadas[0].content)["model"] == "openai/gpt-oss-120b:batch"


def teste_f2_so_os_fornecedores_com_chave_tem_gerador() -> None:
    assert montar_geradores(None, None) == {}
    assert montar_geradores("   ", "") == {}
    assert set(montar_geradores("k1", None)) == {"fal"}
    assert set(montar_geradores("k1", "k2")) == {"fal", "replicate"}
    assert isinstance(montar_geradores("k1", "k2")["replicate"], GeradorReplicate)


# --------------------------------------------------------------------------- #
# GET /configuracao (F2)
# --------------------------------------------------------------------------- #


@pytest.fixture
def _sem_chaves_no_ambiente(monkeypatch):
    obter = modulo_de_configuracao.obter_configuracoes
    obter.cache_clear()
    for nome in ("FAL_KEY", "CHAVE_API_FAL", "REPLICATE_API_TOKEN", "CHAVE_API_REPLICATE"):
        monkeypatch.delenv(nome, raising=False)
    try:
        yield monkeypatch
    finally:
        obter.cache_clear()


def teste_f2_configuracao_diz_quais_fornecedores_tem_chave_sem_revelar_a_chave(
    cliente: TestClient, _sem_chaves_no_ambiente
) -> None:
    corpo = cliente.get("/configuracao").json()
    assert corpo["fornecedores_de_imagem"] == {"openrouter": False, "fal": False, "replicate": False}

    modulo_de_configuracao.obter_configuracoes.cache_clear()
    _sem_chaves_no_ambiente.setenv("FAL_KEY", "segredo-do-fal")
    _sem_chaves_no_ambiente.setenv("CHAVE_API_REPLICATE", "segredo-do-replicate")
    resposta = cliente.get("/configuracao")

    assert resposta.json()["fornecedores_de_imagem"]["fal"] is True
    assert resposta.json()["fornecedores_de_imagem"]["replicate"] is True
    assert "segredo-do-fal" not in resposta.text and "segredo-do-replicate" not in resposta.text


def teste_f2_as_duas_formas_do_nome_da_variavel_valem(cliente: TestClient, _sem_chaves_no_ambiente) -> None:
    """`FAL_KEY` e `REPLICATE_API_TOKEN` são os nomes dos próprios fornecedores; os `CHAVE_API_*` são os do projeto."""
    _sem_chaves_no_ambiente.setenv("CHAVE_API_FAL", "k")
    _sem_chaves_no_ambiente.setenv("REPLICATE_API_TOKEN", "k")
    modulo_de_configuracao.obter_configuracoes.cache_clear()

    corpo = cliente.get("/configuracao").json()

    assert corpo["fornecedores_de_imagem"]["fal"] is True
    assert corpo["fornecedores_de_imagem"]["replicate"] is True
