"""O perfil de cada tarefa e o corpo do pedido ao OpenRouter (item 4.10, LM1 a LM3; etapa E1).

``_corpo_da_chamada`` é uma função pura: aqui ela é testada sem transporte, só com perfis e capacidades montados à mão. No fim, um teste
passa pelo ``_conversar`` de verdade (com um OpenRouter falso) para provar que o corpo chega à rede.
"""

import json
from decimal import Decimal

import httpx

from imagineer.ia import catalogo_de_texto
from imagineer.ia.catalogo_de_texto import Capacidades
from imagineer.ia.openrouter import (
    ENDERECO_BASE,
    FOLGA_DE_RACIOCINIO,
    TEMPERATURA_DA_CORRECAO,
    TEMPERATURA_DA_SUAVIZACAO,
    TEMPERATURA_DA_TRADUCAO,
    TEMPERATURA_DE_FIDELIDADE,
    TEMPERATURA_DO_PROMPT,
    ProvedorOpenRouter,
    _corpo_da_chamada,
)
from imagineer.ia.tarefas import PERFIL_NEUTRO, PERFIS, NivelDeRaciocinio, PerfilDaTarefa, perfil_da

ESQUEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}


def _perfil(raciocinio=NivelDeRaciocinio.NENHUM, esquema=None, limite=1000, temperatura=0.2) -> PerfilDaTarefa:
    return PerfilDaTarefa(temperatura=temperatura, limite_de_saida=limite, raciocinio=raciocinio, esquema=esquema, cache_do_capitulo=False)


def _capacidades(**mudancas) -> Capacidades:
    """Um modelo "comum": sem raciocínio, sem esquema, sem teto de saída."""
    base = dict(
        id="x/modelo",
        contexto=100000,
        saida_maxima=None,
        estruturado=False,
        raciocinio_suportado=False,
        raciocinio_obrigatorio=False,
        esforcos=(),
        preco_entrada=Decimal("0.000001"),
        preco_saida=Decimal("0.000002"),
        preco_cache_leitura=None,
        preco_cache_escrita=None,
        gratuito=False,
        moderado=False,
    )
    base.update(mudancas)
    return Capacidades(**base)


def _corpo(perfil=None, capacidades="comum", **argumentos) -> dict:
    return _corpo_da_chamada(
        "x/modelo",
        "instrução",
        "pedido",
        perfil or _perfil(),
        _capacidades() if capacidades == "comum" else capacidades,
        **argumentos,
    )


# --------------------------------------------------------------------------- #
# LM1: o perfil de cada tarefa
# --------------------------------------------------------------------------- #


def teste_lm1_a_tabela_de_perfis_tem_os_valores_da_especificacao() -> None:
    assert set(PERFIS) == {
        "extracao", "estado", "identidade", "fundamentacao", "prompt", "prompt_de_video", "traducao", "correcao", "suavizacao", "perfil",
    }
    assert {nome: perfil.limite_de_saida for nome, perfil in PERFIS.items()} == {
        "extracao": 8000, "estado": 3000, "identidade": 800, "fundamentacao": 3500,
        "prompt": 1500, "prompt_de_video": 1500, "traducao": 2000, "correcao": 2000, "suavizacao": 2000, "perfil": 3000,
    }
    assert {nome: perfil.esquema for nome, perfil in PERFIS.items()} == {
        "extracao": "extracao", "estado": "estado", "identidade": "identidade", "fundamentacao": "fundamentacao",
        "prompt": None, "prompt_de_video": None, "traducao": None, "correcao": None, "suavizacao": None, "perfil": None,
    }


def teste_lm1_so_a_leitura_do_capitulo_raciocina_pouco_e_usa_cache() -> None:
    for nome in ("extracao", "estado", "identidade", "fundamentacao"):
        assert PERFIS[nome].raciocinio is NivelDeRaciocinio.BAIXO
        assert PERFIS[nome].cache_do_capitulo is True
    for nome in ("prompt", "prompt_de_video", "traducao", "correcao", "suavizacao", "perfil"):
        assert PERFIS[nome].raciocinio is NivelDeRaciocinio.NENHUM
        assert PERFIS[nome].cache_do_capitulo is False


def teste_lm1_as_temperaturas_reaproveitam_as_constantes_que_ja_existiam() -> None:
    assert PERFIS["estado"].temperatura == TEMPERATURA_DE_FIDELIDADE
    assert PERFIS["prompt"].temperatura == TEMPERATURA_DO_PROMPT
    assert PERFIS["prompt_de_video"].temperatura == TEMPERATURA_DO_PROMPT
    assert PERFIS["traducao"].temperatura == TEMPERATURA_DA_TRADUCAO
    assert PERFIS["correcao"].temperatura == TEMPERATURA_DA_CORRECAO
    assert PERFIS["suavizacao"].temperatura == TEMPERATURA_DA_SUAVIZACAO
    assert PERFIS["perfil"].temperatura is None  # hoje essa chamada não manda temperatura: continua assim


def teste_lm1_operacao_fora_da_tabela_usa_o_perfil_neutro() -> None:
    assert perfil_da("operacao-que-ninguem-conhece") is PERFIL_NEUTRO
    assert PERFIL_NEUTRO == PerfilDaTarefa(temperatura=1.0, limite_de_saida=4000, raciocinio=NivelDeRaciocinio.NENHUM, esquema=None, cache_do_capitulo=False)
    assert perfil_da("estado") is PERFIS["estado"]


def teste_lm1_o_nivel_de_raciocinio_tem_o_texto_que_o_openrouter_espera() -> None:
    assert [n.value for n in NivelDeRaciocinio] == ["none", "minimal", "low", "medium"]


# --------------------------------------------------------------------------- #
# LM2: o corpo da chamada
# --------------------------------------------------------------------------- #


def teste_lm2_o_corpo_basico_tem_modelo_mensagens_uso_temperatura_e_limite() -> None:
    corpo = _corpo()

    assert corpo == {
        "model": "x/modelo",
        "messages": [{"role": "system", "content": "instrução"}, {"role": "user", "content": "pedido"}],
        "usage": {"include": True},
        "temperature": 0.2,
        "max_tokens": 1000,
    }


def teste_lm2_perfil_sem_temperatura_nao_manda_temperature() -> None:
    assert "temperature" not in _corpo(_perfil(temperatura=None))


def teste_lm2_modelo_sem_reasoning_nao_leva_nenhum_campo_de_raciocinio() -> None:
    for nivel in NivelDeRaciocinio:
        corpo = _corpo(_perfil(raciocinio=nivel), _capacidades(raciocinio_suportado=False))
        assert "reasoning" not in corpo
        assert corpo["max_tokens"] == 1000  # sem raciocínio, sem folga


def teste_lm2_nenhum_em_modelo_sem_raciocinio_obrigatorio_desliga_o_raciocinio() -> None:
    corpo = _corpo(_perfil(raciocinio=NivelDeRaciocinio.NENHUM), _capacidades(raciocinio_suportado=True))

    assert corpo["reasoning"] == {"effort": "none", "exclude": True}
    assert corpo["max_tokens"] == 1000  # ``none`` não raciocina: nenhuma folga


def teste_lm2_nenhum_em_modelo_com_raciocinio_obrigatorio_usa_o_menor_esforco_aceito() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, raciocinio_obrigatorio=True, esforcos=("high", "medium", "low"))

    corpo = _corpo(_perfil(raciocinio=NivelDeRaciocinio.NENHUM), capacidades)

    assert corpo["reasoning"] == {"effort": "low", "exclude": True}


def teste_lm2_raciocinio_obrigatorio_sem_lista_de_esforcos_usa_low() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, raciocinio_obrigatorio=True, esforcos=())

    assert _corpo(_perfil(), capacidades)["reasoning"]["effort"] == "low"


def teste_lm2_baixo_em_modelo_que_so_aceita_high_e_xhigh_sobe_para_high() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, esforcos=("high", "xhigh"))

    corpo = _corpo(_perfil(raciocinio=NivelDeRaciocinio.BAIXO), capacidades)

    assert corpo["reasoning"] == {"effort": "high", "exclude": True}


def teste_lm2_esforco_pedido_e_aceito_vai_como_esta() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, esforcos=("low", "medium", "high"))

    assert _corpo(_perfil(raciocinio=NivelDeRaciocinio.BAIXO), capacidades)["reasoning"]["effort"] == "low"
    assert _corpo(_perfil(raciocinio=NivelDeRaciocinio.MEDIO), capacidades)["reasoning"]["effort"] == "medium"


def teste_lm2_esforco_pedido_sem_lista_de_esforcos_vai_como_esta() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, esforcos=())

    assert _corpo(_perfil(raciocinio=NivelDeRaciocinio.MINIMO), capacidades)["reasoning"]["effort"] == "minimal"


def teste_lm2_se_nao_ha_esforco_acima_usa_o_mais_alto_que_o_modelo_tem() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, esforcos=("minimal",))

    assert _corpo(_perfil(raciocinio=NivelDeRaciocinio.MEDIO), capacidades)["reasoning"]["effort"] == "minimal"


def teste_lm2_o_texto_do_raciocinio_e_sempre_excluido() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, esforcos=("low",))

    for nivel in NivelDeRaciocinio:
        assert _corpo(_perfil(raciocinio=nivel), capacidades)["reasoning"]["exclude"] is True


def teste_lm2_response_format_so_com_esquema_e_com_suporte() -> None:
    esquemas = {"estado": ESQUEMA}
    perfil = _perfil(esquema="estado")

    corpo = _corpo(perfil, _capacidades(estruturado=True), esquemas=esquemas)

    assert corpo["response_format"] == {"type": "json_schema", "json_schema": {"name": "estado", "strict": True, "schema": ESQUEMA}}
    assert corpo["provider"] == {"require_parameters": True}


def teste_lm2_sem_suporte_a_esquema_nao_leva_response_format_nem_provider() -> None:
    corpo = _corpo(_perfil(esquema="estado"), _capacidades(estruturado=False), esquemas={"estado": ESQUEMA})

    assert "response_format" not in corpo
    assert "provider" not in corpo


def teste_lm2_perfil_sem_esquema_nao_leva_response_format_mesmo_com_suporte() -> None:
    corpo = _corpo(_perfil(esquema=None), _capacidades(estruturado=True), esquemas={"estado": ESQUEMA})

    assert "response_format" not in corpo
    assert "provider" not in corpo


def teste_lm2_esquema_que_ainda_nao_existe_nao_leva_response_format() -> None:
    """O perfil cita um nome que não está em ``ESQUEMAS``: nada é mandado (e a chamada não quebra)."""
    corpo = _corpo(_perfil(esquema="esquema-que-nao-existe"), _capacidades(estruturado=True))

    assert "response_format" not in corpo


def teste_lm2_session_id_vai_cortado_em_256_caracteres() -> None:
    corpo = _corpo(sessao_de_cache="s" * 300)

    assert corpo["session_id"] == "s" * 256


def teste_lm2_sem_sessao_nao_leva_session_id() -> None:
    assert "session_id" not in _corpo()
    assert "session_id" not in _corpo(sessao_de_cache="")


def teste_lm2_models_leva_o_principal_e_as_alternativas_sem_repetir() -> None:
    corpo = _corpo(alternativos=["x/modelo", "a/reserva", "a/reserva", "b/reserva2"])

    assert corpo["models"] == ["x/modelo", "a/reserva", "b/reserva2"]


def teste_lm2_models_leva_no_maximo_duas_alternativas() -> None:
    corpo = _corpo(alternativos=["a/1", "a/2", "a/3", "a/4"])

    assert corpo["models"] == ["x/modelo", "a/1", "a/2"]


def teste_lm2_alternativa_igual_ao_principal_nao_gera_models() -> None:
    assert "models" not in _corpo(alternativos=["x/modelo"])
    assert "models" not in _corpo(alternativos=())


def teste_lm2_a_busca_na_web_liga_o_plugin() -> None:
    assert _corpo(usar_busca_web=True)["plugins"] == [{"id": "web"}]
    assert "plugins" not in _corpo()


def teste_lm2_a_ordem_do_corpo_e_a_da_especificacao() -> None:
    capacidades = _capacidades(estruturado=True, raciocinio_suportado=True)
    corpo = _corpo(
        _perfil(raciocinio=NivelDeRaciocinio.BAIXO, esquema="estado"),
        capacidades,
        sessao_de_cache="cap-1",
        alternativos=["a/reserva"],
        usar_busca_web=True,
        esquemas={"estado": ESQUEMA},
    )

    assert list(corpo) == [
        "model", "messages", "usage", "temperature", "max_tokens", "reasoning", "response_format", "provider", "session_id", "models", "plugins",
    ]


# --------------------------------------------------------------------------- #
# LM3: a folga do raciocínio e o teto do modelo
# --------------------------------------------------------------------------- #


def teste_lm3_quem_raciocina_ganha_a_folga_no_max_tokens() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, esforcos=("low", "medium"))

    corpo = _corpo(_perfil(raciocinio=NivelDeRaciocinio.BAIXO, limite=3000), capacidades)

    assert FOLGA_DE_RACIOCINIO == 4000
    assert corpo["max_tokens"] == 3000 + 4000


def teste_lm3_quem_nao_raciocina_nao_ganha_folga() -> None:
    capacidades = _capacidades(raciocinio_suportado=True)

    assert _corpo(_perfil(raciocinio=NivelDeRaciocinio.NENHUM, limite=3000), capacidades)["max_tokens"] == 3000


def teste_lm3_o_max_tokens_nunca_passa_do_teto_de_saida_do_modelo() -> None:
    capacidades = _capacidades(raciocinio_suportado=True, esforcos=("low",), saida_maxima=5000)

    assert _corpo(_perfil(raciocinio=NivelDeRaciocinio.BAIXO, limite=3000), capacidades)["max_tokens"] == 5000  # 7000 limitado a 5000


def teste_lm3_teto_de_saida_maior_que_o_pedido_nao_muda_nada() -> None:
    assert _corpo(_perfil(limite=3000), _capacidades(saida_maxima=16384))["max_tokens"] == 3000


# --------------------------------------------------------------------------- #
# Sem catálogo: o corpo mínimo
# --------------------------------------------------------------------------- #


def teste_lm2_sem_capacidades_o_corpo_e_o_minimo() -> None:
    corpo = _corpo(
        _perfil(raciocinio=NivelDeRaciocinio.BAIXO, esquema="estado", limite=3000),
        capacidades=None,
        sessao_de_cache="cap-1",
        alternativos=["a/reserva"],
        esquemas={"estado": ESQUEMA},
    )

    assert corpo == {
        "model": "x/modelo",
        "messages": [{"role": "system", "content": "instrução"}, {"role": "user", "content": "pedido"}],
        "usage": {"include": True},
        "temperature": 0.2,
        "max_tokens": 3000,  # sem folga: não se sabe se o modelo raciocina
    }


def teste_lm2_sem_capacidades_a_busca_na_web_continua_ligada() -> None:
    """A busca é o que a tarefa pediu (o perfil de renderização), não depende do catálogo."""
    assert _corpo(capacidades=None, usar_busca_web=True)["plugins"] == [{"id": "web"}]


# --------------------------------------------------------------------------- #
# Pelo _conversar de verdade
# --------------------------------------------------------------------------- #


def _provedor(pedidos: list[dict]) -> ProvedorOpenRouter:
    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(pedido.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "texto"}}]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    return ProvedorOpenRouter(chave_api="chave", cliente=cliente)


def teste_lm2_o_conversar_manda_o_perfil_da_operacao_sem_catalogo() -> None:
    pedidos: list[dict] = []

    _provedor(pedidos).traduzir_prompt("a red door", "pt", "x/modelo")

    (corpo,) = pedidos
    assert corpo["model"] == "x/modelo"
    assert corpo["temperature"] == TEMPERATURA_DA_TRADUCAO
    assert corpo["max_tokens"] == PERFIS["traducao"].limite_de_saida
    assert "reasoning" not in corpo  # o catálogo de teste está vazio: corpo mínimo


def teste_lm2_o_conversar_usa_o_catalogo_para_ajustar_o_raciocinio(monkeypatch) -> None:
    catalogo = {
        "data": [
            {
                "id": "x/modelo",
                "context_length": 100000,
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "supported_parameters": ["reasoning", "max_tokens"],
                "reasoning": {"mandatory": False},
                "top_provider": {"max_completion_tokens": 64000},
            }
        ]
    }
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: catalogo)
    pedidos: list[dict] = []

    _provedor(pedidos).traduzir_prompt("a red door", "pt", "x/modelo")

    (corpo,) = pedidos
    assert corpo["reasoning"] == {"effort": "none", "exclude": True}
    assert corpo["max_tokens"] == 2000


def teste_lm2_a_temperatura_explicita_vence_a_do_perfil() -> None:
    pedidos: list[dict] = []
    provedor = _provedor(pedidos)

    provedor._conversar("x/modelo", "i", "p", operacao="traducao", temperatura=0.9)
    provedor._conversar("x/modelo", "i", "p", operacao="traducao")

    assert [p["temperature"] for p in pedidos] == [0.9, TEMPERATURA_DA_TRADUCAO]


def teste_lm2_operacao_desconhecida_usa_o_perfil_neutro_e_nao_quebra() -> None:
    pedidos: list[dict] = []

    _provedor(pedidos)._conversar("x/modelo", "i", "p", operacao="operacao-nova")

    (corpo,) = pedidos
    assert corpo["temperature"] == 1.0
    assert corpo["max_tokens"] == 4000


def teste_lm2_a_geracao_do_perfil_nao_manda_temperatura_e_liga_a_busca() -> None:
    pedidos: list[dict] = []

    _provedor(pedidos)._conversar("x/modelo", "i", "p", operacao="perfil", usar_busca_web=True)

    (corpo,) = pedidos
    assert "temperature" not in corpo
    assert corpo["plugins"] == [{"id": "web"}]
    assert corpo["max_tokens"] == 3000


def teste_lm2_sessao_e_alternativos_do_conversar_so_vao_com_catalogo(monkeypatch) -> None:
    """``sessao_de_cache`` e ``alternativos`` passam pelo ``_conversar`` até o corpo (a E3 e a E5 os usarão)."""
    catalogo = {"data": [{"id": "x/modelo", "context_length": 1000, "pricing": {"prompt": "1"}, "supported_parameters": []}]}
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: catalogo)
    pedidos: list[dict] = []

    _provedor(pedidos)._conversar("x/modelo", "i", "p", operacao="prompt", sessao_de_cache="cap-9", alternativos=["a/reserva"])

    (corpo,) = pedidos
    assert corpo["session_id"] == "cap-9"
    assert corpo["models"] == ["x/modelo", "a/reserva"]
