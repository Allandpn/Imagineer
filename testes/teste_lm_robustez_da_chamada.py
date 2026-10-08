"""A chamada que se defende: retentativa, parâmetro recusado, resposta cortada e uso registrado (item 4.10, LM4 a LM7; etapa E2).

O OpenRouter é um transporte falso do ``httpx`` que **responde o que o teste mandar, na ordem**: uma resposta, ou uma exceção de rede. A espera entre
tentativas também é falsa (``dormir``): o teste confere **quanto** o servidor esperaria, sem esperar.
"""

import json
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from imagineer.ia import catalogo_de_texto, openrouter
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter, _interpretar_uso
from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA, UsoDaChamada
from imagineer.modelos import UsoDeIA
from imagineer.servicos.uso_de_ia import gravar_uso

JSON_VALIDO = json.dumps({"descricao": "ele é alto"})


def _ok(conteudo: str = "texto", finish_reason: str | None = "stop", **extras) -> httpx.Response:
    escolha: dict = {"message": {"content": conteudo}}
    if finish_reason is not None:
        escolha["finish_reason"] = finish_reason
    return httpx.Response(200, json={"choices": [escolha], "id": "gen-1", **extras})


class Roteiro:
    """Um OpenRouter falso: devolve as respostas na ordem e guarda o corpo de cada pedido recebido."""

    def __init__(self, *respostas) -> None:
        self.respostas = list(respostas)
        self.corpos: list[dict] = []
        self.esperas: list[float] = []
        self.avisos: list[UsoDaChamada] = []

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.corpos.append(json.loads(pedido.content) if pedido.content else {})  # um GET não tem corpo
        proxima = self.respostas.pop(0)
        if isinstance(proxima, Exception):
            raise proxima
        return proxima

    def provedor(self) -> ProvedorOpenRouter:
        cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(self))
        return ProvedorOpenRouter(chave_api="chave", cliente=cliente, ao_usar=self.avisos.append, dormir=self.esperas.append)


def _conversar(provedor: ProvedorOpenRouter, modelo: str = "x/modelo", operacao: str = "prompt", **argumentos) -> str:
    return provedor._conversar(modelo, "instrução", "pedido", operacao=operacao, **argumentos)


def _catalogo(monkeypatch, **campos) -> None:
    """Põe ``x/modelo`` no catálogo de teste: com raciocínio, esquema e teto de saída, a menos que ``campos`` mude."""
    modelo = {
        "id": "x/modelo",
        "context_length": 100000,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "supported_parameters": ["reasoning", "structured_outputs", "max_tokens"],
        "reasoning": {"mandatory": False},
        "top_provider": {"max_completion_tokens": 64000},
        **campos,
    }
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: {"data": [modelo]})


# --------------------------------------------------------------------------- #
# LM5: tentar de novo no erro de rede
# --------------------------------------------------------------------------- #


def teste_lm5_falha_de_conexao_uma_vez_e_depois_sucesso_espera_2_segundos() -> None:
    roteiro = Roteiro(httpx.RemoteProtocolError("Server disconnected"), _ok())

    assert _conversar(roteiro.provedor()) == "texto"

    assert len(roteiro.corpos) == 2
    assert roteiro.esperas == [2.0]
    assert len(roteiro.avisos) == 1  # a primeira não deu resposta: nada foi cobrado, o consumo é anotado uma vez só


@pytest.mark.parametrize(
    "erro",
    [httpx.RemoteProtocolError("caiu"), httpx.ReadError("leitura"), httpx.ConnectError("sem rota"), httpx.ConnectTimeout("demorou a abrir")],
)
def teste_lm5_cada_erro_de_rede_passageiro_e_repetido(erro: Exception) -> None:
    roteiro = Roteiro(erro, _ok())

    assert _conversar(roteiro.provedor()) == "texto"
    assert roteiro.esperas == [2.0]


def teste_lm5_duas_falhas_seguidas_dao_o_erro_em_portugues() -> None:
    roteiro = Roteiro(httpx.RemoteProtocolError("caiu 1"), httpx.RemoteProtocolError("caiu 2"))

    with pytest.raises(ErroDoProvedorIA, match="Não foi possível falar com o OpenRouter"):
        _conversar(roteiro.provedor())

    assert len(roteiro.corpos) == 2  # a original e uma repetição, nunca mais
    assert roteiro.esperas == [2.0]
    assert roteiro.avisos == []


def teste_lm5_read_timeout_nao_e_repetido() -> None:
    """Já esperou o tempo todo (até 180 s): repetir seria esperar 6 minutos."""
    roteiro = Roteiro(httpx.ReadTimeout("devagar"), _ok())

    with pytest.raises(ErroDoProvedorIA, match="não respondeu no tempo esperado"):
        _conversar(roteiro.provedor())

    assert len(roteiro.corpos) == 1
    assert roteiro.esperas == []


def teste_lm5_connect_timeout_duas_vezes_diz_que_nao_respondeu() -> None:
    roteiro = Roteiro(httpx.ConnectTimeout("a"), httpx.ConnectTimeout("b"))

    with pytest.raises(ErroDoProvedorIA, match="não respondeu no tempo esperado"):
        _conversar(roteiro.provedor())


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def teste_lm5_status_passageiro_e_repetido(status: int) -> None:
    roteiro = Roteiro(httpx.Response(status, text="tente depois"), _ok())

    assert _conversar(roteiro.provedor()) == "texto"
    assert roteiro.esperas == [2.0]


def teste_lm5_status_passageiro_duas_vezes_da_o_erro_de_sempre() -> None:
    roteiro = Roteiro(httpx.Response(503, text="a"), httpx.Response(503, text="b"))

    with pytest.raises(ErroDoProvedorIA, match="respondeu 503"):
        _conversar(roteiro.provedor())

    assert len(roteiro.corpos) == 2


def teste_lm5_401_nunca_e_repetido() -> None:
    roteiro = Roteiro(httpx.Response(401, text="chave ruim"), _ok())

    with pytest.raises(ChaveDeApiAusente):
        _conversar(roteiro.provedor())

    assert len(roteiro.corpos) == 1
    assert roteiro.esperas == []


def teste_lm5_402_e_outros_4xx_nunca_sao_repetidos() -> None:
    for status in (402, 403, 404, 409):
        roteiro = Roteiro(httpx.Response(status, text="não"), _ok())

        with pytest.raises(ErroDoProvedorIA):
            _conversar(roteiro.provedor())

        assert len(roteiro.corpos) == 1, status
        assert roteiro.esperas == []


def teste_lm5_429_respeita_o_retry_after() -> None:
    roteiro = Roteiro(httpx.Response(429, headers={"Retry-After": "3"}, text="devagar"), _ok())

    _conversar(roteiro.provedor())

    assert roteiro.esperas == [3.0]


def teste_lm5_429_com_retry_after_enorme_espera_no_maximo_10_segundos() -> None:
    roteiro = Roteiro(httpx.Response(429, headers={"Retry-After": "99"}, text="devagar"), _ok())

    _conversar(roteiro.provedor())

    assert roteiro.esperas == [10.0]


def teste_lm5_429_com_retry_after_estranho_espera_o_padrao() -> None:
    roteiro = Roteiro(httpx.Response(429, headers={"Retry-After": "logo"}, text="devagar"), _ok())

    _conversar(roteiro.provedor())

    assert roteiro.esperas == [2.0]


def teste_lm5_so_a_conversa_tenta_de_novo() -> None:
    """``_pedir`` sem ``tentar_de_novo`` (a lista de modelos, a geração de imagem) falha na primeira, como sempre."""
    roteiro = Roteiro(httpx.RemoteProtocolError("caiu"), _ok())

    with pytest.raises(ErroDoProvedorIA):
        roteiro.provedor()._pedir("GET", "/models")

    assert len(roteiro.corpos) == 1
    assert roteiro.esperas == []


# --------------------------------------------------------------------------- #
# LM4: o parâmetro opcional que o modelo recusa
# --------------------------------------------------------------------------- #


def teste_lm4_400_citando_reasoning_repete_sem_os_opcionais(monkeypatch) -> None:
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(400, text="Unsupported parameter: reasoning"), _ok())

    assert _conversar(roteiro.provedor(), sessao_de_cache="cap-1") == "texto"

    primeiro, segundo = roteiro.corpos
    assert "reasoning" in primeiro and "session_id" in primeiro
    assert set(segundo) == {"model", "messages", "usage", "temperature", "max_tokens"}


def teste_lm4_a_segunda_chamada_ao_mesmo_modelo_ja_omite_o_que_foi_recusado(monkeypatch) -> None:
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(400, text="reasoning is not supported"), _ok(), _ok())
    provedor = roteiro.provedor()

    _conversar(provedor)
    _conversar(provedor)

    assert len(roteiro.corpos) == 3  # a que falhou, a repetida e a seguinte, que já foi limpa
    assert "reasoning" in roteiro.corpos[0]
    assert "reasoning" not in roteiro.corpos[2]


def teste_lm4_so_se_omite_o_que_o_erro_citou(monkeypatch) -> None:
    """Recusou ``reasoning``: o ``session_id`` continua indo nas chamadas seguintes."""
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(400, text="reasoning is not supported"), _ok(), _ok())
    provedor = roteiro.provedor()

    _conversar(provedor, sessao_de_cache="cap-1")
    _conversar(provedor, sessao_de_cache="cap-1")

    assert "reasoning" not in roteiro.corpos[2]
    assert roteiro.corpos[2]["session_id"] == "cap-1"


def teste_lm4_a_memoria_e_por_modelo(monkeypatch) -> None:
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(400, text="reasoning is not supported"), _ok(), _ok())
    provedor = roteiro.provedor()

    _conversar(provedor, modelo="x/modelo")
    _conversar(provedor, modelo="outro/modelo")

    assert openrouter._parametros_recusados_por("x/modelo") == {"reasoning"}
    assert openrouter._parametros_recusados_por("outro/modelo") == frozenset()


@pytest.mark.parametrize("codigo", [400, 404, 422])
def teste_lm4_vale_para_400_404_e_422(monkeypatch, codigo: int) -> None:
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(codigo, text="invalid response_format"), _ok())

    _conversar(roteiro.provedor(), operacao="prompt", sessao_de_cache="cap-1")

    assert len(roteiro.corpos) == 2
    assert "session_id" not in roteiro.corpos[1]


@pytest.mark.parametrize("palavra", ["json_schema", "structured outputs", "require_parameters", "session_id", "cache_control"])
def teste_lm4_cada_palavra_da_especificacao_dispara_a_repeticao(monkeypatch, palavra: str) -> None:
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(400, text=f"bad request: {palavra}"), _ok())

    _conversar(roteiro.provedor(), sessao_de_cache="cap-1")

    assert len(roteiro.corpos) == 2


def teste_lm4_no_endpoints_found_tira_todos_os_opcionais_e_lembra_de_todos(monkeypatch) -> None:
    """Sem nomear o parâmetro (o ``require_parameters`` sem nenhum provedor que aceite tudo): vale tudo o que o corpo levava."""
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(404, text="No endpoints found that can handle the requested parameters"), _ok(), _ok())
    provedor = roteiro.provedor()

    _conversar(provedor, sessao_de_cache="cap-1", alternativos=["a/reserva"])
    _conversar(provedor, sessao_de_cache="cap-1", alternativos=["a/reserva"])

    assert {"reasoning", "session_id", "models"} <= set(roteiro.corpos[0])
    assert {"reasoning", "session_id", "models"}.isdisjoint(roteiro.corpos[1])
    assert {"reasoning", "session_id", "models"}.isdisjoint(roteiro.corpos[2])


def teste_lm4_400_sem_as_palavras_nao_repete(monkeypatch) -> None:
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(400, text="Your prompt is too long"), _ok())

    with pytest.raises(ErroDoProvedorIA, match="respondeu 400"):
        _conversar(roteiro.provedor())

    assert len(roteiro.corpos) == 1
    assert openrouter._parametros_recusados_por("x/modelo") == frozenset()


@pytest.mark.parametrize("status", [401, 402, 403, 500])
def teste_lm4_outros_codigos_nao_disparam_a_degradacao(monkeypatch, status: int) -> None:
    _catalogo(monkeypatch)
    # Mesmo citando "reasoning": o código decide. (500 é repetido pelo LM5, não pelo LM4; por isso a segunda resposta é igual.)
    roteiro = Roteiro(httpx.Response(status, text="reasoning"), httpx.Response(status, text="reasoning"), _ok())

    with pytest.raises(ErroDoProvedorIA):
        _conversar(roteiro.provedor())

    assert openrouter._parametros_recusados_por("x/modelo") == frozenset()
    assert all("reasoning" in corpo for corpo in roteiro.corpos)  # nenhum corpo foi limpo


def teste_lm4_sem_opcionais_no_corpo_o_erro_sobe_sem_repetir() -> None:
    """Sem catálogo o corpo é o mínimo: um 400 que cita ``reasoning`` não pode ser culpa de um opcional que não foi."""
    roteiro = Roteiro(httpx.Response(400, text="reasoning"), _ok())

    with pytest.raises(ErroDoProvedorIA):
        _conversar(roteiro.provedor())

    assert len(roteiro.corpos) == 1


def teste_lm4_se_a_repeticao_tambem_falha_o_erro_sobe(monkeypatch) -> None:
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(400, text="reasoning"), httpx.Response(400, text="outro problema"))

    with pytest.raises(ErroDoProvedorIA, match="outro problema"):
        _conversar(roteiro.provedor())


def teste_lm4_avisa_no_log_uma_vez_por_modelo_e_parametro(monkeypatch, caplog) -> None:
    _catalogo(monkeypatch)
    roteiro = Roteiro(httpx.Response(400, text="reasoning"), _ok(), _ok())
    provedor = roteiro.provedor()

    with caplog.at_level("WARNING", logger="imagineer.ia.openrouter"):
        _conversar(provedor)
        _conversar(provedor)

    avisos = [r for r in caplog.records if "recusou o parâmetro" in r.getMessage()]
    assert len(avisos) == 1
    assert "x/modelo" in avisos[0].getMessage() and "reasoning" in avisos[0].getMessage()


def teste_lm4_tira_o_cache_control_dos_blocos_e_mantem_o_texto() -> None:
    corpo = {
        "model": "anthropic/x",
        "messages": [
            {"role": "system", "content": "i"},
            {"role": "user", "content": [{"type": "text", "text": "capítulo", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "variável"}]},
        ],
        "usage": {"include": True},
        "max_tokens": 10,
        "session_id": "s",
    }

    assert openrouter._opcionais_presentes(corpo) == {"session_id", "cache_control"}
    simples = openrouter._sem_parametros_opcionais(corpo)

    assert simples["messages"][1]["content"] == [{"type": "text", "text": "capítulo"}, {"type": "text", "text": "variável"}]
    assert simples["messages"][0] == {"role": "system", "content": "i"}
    assert "session_id" not in simples
    assert "cache_control" in json.dumps(corpo)  # o corpo original não foi mexido


# --------------------------------------------------------------------------- #
# LM6: resposta cortada e resposta que não é JSON
# --------------------------------------------------------------------------- #


def teste_lm6_resposta_cortada_repete_com_o_limite_vezes_1_5(monkeypatch) -> None:
    _catalogo(monkeypatch, supported_parameters=["max_tokens"])  # sem raciocínio: sem folga, limite do perfil = 1500
    roteiro = Roteiro(_ok('{"corta', finish_reason="length"), _ok("completo"))

    assert _conversar(roteiro.provedor(), operacao="prompt") == "completo"

    assert [c["max_tokens"] for c in roteiro.corpos] == [1500, 2250]
    assert len(roteiro.avisos) == 2  # a cortada também foi cobrada


def teste_lm6_o_novo_limite_respeita_o_teto_de_saida_do_modelo(monkeypatch) -> None:
    _catalogo(monkeypatch, supported_parameters=["max_tokens"], top_provider={"max_completion_tokens": 2000})
    roteiro = Roteiro(_ok("corta", finish_reason="length"), _ok("completo"))

    _conversar(roteiro.provedor(), operacao="prompt")

    assert [c["max_tokens"] for c in roteiro.corpos] == [1500, 2000]


def teste_lm6_cortando_de_novo_da_o_erro_e_nunca_devolve_o_texto_cortado(monkeypatch) -> None:
    _catalogo(monkeypatch, supported_parameters=["max_tokens"])
    roteiro = Roteiro(_ok('{"corta', finish_reason="length"), _ok('{"corta de novo', finish_reason="length"))

    with pytest.raises(ErroDoProvedorIA) as erro:
        _conversar(roteiro.provedor(), modelo="x/modelo", operacao="prompt")

    assert str(erro.value) == (
        "A resposta do modelo x/modelo foi cortada por passar do limite de 2250 tokens. Escolha outro modelo ou um capítulo menor."
    )
    assert len(roteiro.corpos) == 2


def teste_lm6_ja_no_teto_do_modelo_nao_gasta_uma_repeticao_igual(monkeypatch) -> None:
    _catalogo(monkeypatch, supported_parameters=["max_tokens"], top_provider={"max_completion_tokens": 1500})
    roteiro = Roteiro(_ok("corta", finish_reason="length"), _ok("completo"))

    with pytest.raises(ErroDoProvedorIA, match="limite de 1500 tokens"):
        _conversar(roteiro.provedor(), operacao="prompt")

    assert len(roteiro.corpos) == 1


def teste_lm6_sem_catalogo_o_limite_tambem_sobe_1_5() -> None:
    roteiro = Roteiro(_ok("corta", finish_reason="length"), _ok("completo"))

    assert _conversar(roteiro.provedor(), operacao="prompt") == "completo"
    assert [c["max_tokens"] for c in roteiro.corpos] == [1500, 2250]


def teste_lm6_o_corte_vale_mesmo_quando_o_texto_parece_json_valido() -> None:
    """Um JSON cortado no meio pode até fechar por sorte; o ``finish_reason`` é quem manda."""
    roteiro = Roteiro(_ok(JSON_VALIDO, finish_reason="length"), _ok(JSON_VALIDO))

    _conversar(roteiro.provedor(), operacao="estado")

    assert len(roteiro.corpos) == 2


def teste_lm6_resposta_que_nao_e_json_repete_uma_vez() -> None:
    roteiro = Roteiro(_ok("Claro! Aqui vai a descrição."), _ok(JSON_VALIDO))

    assert _conversar(roteiro.provedor(), operacao="estado") == JSON_VALIDO

    assert len(roteiro.corpos) == 2
    assert roteiro.corpos[0]["max_tokens"] == roteiro.corpos[1]["max_tokens"]  # repetição igual, sem mais espaço
    assert len(roteiro.avisos) == 2


def teste_lm6_a_mensagem_de_sem_json_so_sai_na_segunda_falha() -> None:
    roteiro = Roteiro(_ok("prosa 1"), _ok("prosa 2"))

    with pytest.raises(ErroDoProvedorIA, match="O modelo não devolveu JSON"):
        roteiro.provedor().sugerir_estado("capítulo", _tipo(), "Jon", None, None, "x/modelo")

    assert len(roteiro.corpos) == 2  # nunca uma terceira


def teste_lm6_json_valido_de_primeira_nao_repete() -> None:
    roteiro = Roteiro(_ok(JSON_VALIDO))

    _conversar(roteiro.provedor(), operacao="estado")

    assert len(roteiro.corpos) == 1


def teste_lm6_tarefa_de_texto_livre_nao_repete_por_nao_ser_json() -> None:
    """Prompt, tradução e correção devolvem prosa: não é defeito."""
    roteiro = Roteiro(_ok("a red door"))

    _conversar(roteiro.provedor(), operacao="prompt")

    assert len(roteiro.corpos) == 1


def teste_lm6_a_geracao_do_perfil_espera_json_mesmo_sem_esquema() -> None:
    roteiro = Roteiro(_ok("prosa"), _ok(json.dumps({"estilo": "aquarela"})))

    perfil = roteiro.provedor().sugerir_perfil_renderizacao("Livro", "Autor", "pt", None, "x/modelo")

    assert perfil.estilo == "aquarela"
    assert len(roteiro.corpos) == 2


def teste_lm6_o_chamador_pode_dizer_que_nao_espera_json() -> None:
    roteiro = Roteiro(_ok("prosa"))

    _conversar(roteiro.provedor(), operacao="estado", esperar_json=False)

    assert len(roteiro.corpos) == 1


def _tipo():
    from imagineer.modelos import TipoElemento

    return TipoElemento.PERSONAGEM


# --------------------------------------------------------------------------- #
# LM7: o uso registrado
# --------------------------------------------------------------------------- #


def teste_lm7_le_os_tokens_de_cache_e_de_raciocinio_e_o_modelo_real() -> None:
    dados = {
        "id": "gen-9",
        "model": "google/gemini-2.5-flash-lite",
        "usage": {
            "prompt_tokens": 12000,
            "completion_tokens": 900,
            "cost": 0.0021,
            "prompt_tokens_details": {"cached_tokens": 11000},
            "completion_tokens_details": {"reasoning_tokens": 300},
        },
    }

    uso = _interpretar_uso("estado", "anthropic/pedido", dados)

    assert uso == UsoDaChamada(
        operacao="estado",
        modelo="google/gemini-2.5-flash-lite",  # o que respondeu, não o que foi pedido
        tokens_entrada=12000,
        tokens_saida=900,
        custo=Decimal("0.0021"),
        id_da_geracao="gen-9",
        tokens_em_cache=11000,
        tokens_de_raciocinio=300,
    )


def teste_lm7_campo_ausente_ou_estranho_vira_none_e_nunca_zero() -> None:
    sem_detalhes = _interpretar_uso("estado", "m", {"usage": {"prompt_tokens": 10}})
    estranho = _interpretar_uso(
        "estado", "m", {"usage": {"prompt_tokens_details": {"cached_tokens": "muitos"}, "completion_tokens_details": "lixo"}, "model": 7}
    )

    assert (sem_detalhes.tokens_em_cache, sem_detalhes.tokens_de_raciocinio) == (None, None)
    assert (estranho.tokens_em_cache, estranho.tokens_de_raciocinio) == (None, None)
    assert estranho.modelo == "m"  # ``model`` que não é texto: vale o pedido


def teste_lm7_cache_zero_informado_continua_zero() -> None:
    uso = _interpretar_uso("estado", "m", {"usage": {"prompt_tokens_details": {"cached_tokens": 0}}})

    assert uso.tokens_em_cache == 0


def teste_lm7_a_alternativa_que_respondeu_e_o_modelo_anotado(monkeypatch) -> None:
    roteiro = Roteiro(_ok(model="reserva/modelo", usage={"prompt_tokens": 5, "cost": 0.0001}))

    _conversar(roteiro.provedor(), modelo="principal/modelo")

    (uso,) = roteiro.avisos
    assert uso.modelo == "reserva/modelo"


def teste_lm7_o_provedor_avisa_com_os_novos_campos_pelo_conversar() -> None:
    roteiro = Roteiro(
        _ok(usage={"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 80}})
    )

    _conversar(roteiro.provedor())

    (uso,) = roteiro.avisos
    assert (uso.tokens_entrada, uso.tokens_em_cache, uso.tokens_de_raciocinio) == (100, 80, None)


def teste_lm7_gravar_uso_guarda_cache_e_raciocinio(sessao_com_tabelas: Session) -> None:
    criador = sessionmaker(bind=sessao_com_tabelas.get_bind())

    gravar_uso(
        UsoDaChamada(operacao="estado", modelo="m", tokens_entrada=100, tokens_saida=20, tokens_em_cache=80, tokens_de_raciocinio=5), criador
    )
    gravar_uso(UsoDaChamada(operacao="estado", modelo="m"), criador)

    linhas = sessao_com_tabelas.query(UsoDeIA).order_by(UsoDeIA.id).all()
    assert [(l.tokens_em_cache, l.tokens_de_raciocinio) for l in linhas] == [(80, 5), (None, None)]


def teste_lm7_a_linha_de_log_diz_quantos_tokens_vieram_do_cache(sessao_com_tabelas: Session, caplog) -> None:
    criador = sessionmaker(bind=sessao_com_tabelas.get_bind())

    with caplog.at_level("INFO", logger="imagineer.servicos.uso_de_ia"):
        gravar_uso(UsoDaChamada(operacao="estado", modelo="m", tokens_entrada=100, tokens_em_cache=80), criador)

    assert "100 tokens de entrada (80 em cache)" in caplog.text


def teste_lm7_o_modelo_tem_as_colunas_novas_nulas_por_padrao() -> None:
    colunas = UsoDeIA.__table__.columns

    for nome in ("tokens_em_cache", "tokens_de_raciocinio"):
        assert colunas[nome].nullable is True
