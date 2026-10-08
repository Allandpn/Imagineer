"""O catálogo de capacidades dos modelos de texto (item 4.10, LM17; etapa E1).

Nenhum teste vai ao OpenRouter: a leitura do catálogo (``_buscar_na_rede``) é trocada por uma função que devolve um catálogo de teste, e o
relógio do cache por um falso, para "passar" 10 minutos sem esperar. O ``conftest`` limpa o cache entre os testes.
"""

import json
from decimal import Decimal

import httpx
import pytest

from imagineer.ia import catalogo_de_texto
from imagineer.ia.catalogo_de_texto import capacidades_de, obter_capacidades
from imagineer.ia.openrouter import ENDERECO_BASE, ProvedorOpenRouter

MODELO_COMPLETO = {
    "id": "google/gemini-2.5-flash-lite",
    "context_length": 1048576,
    "pricing": {"prompt": "0.0000001", "completion": "0.0000004", "input_cache_read": "0.00000001", "input_cache_write": "0.0000000833"},
    "supported_parameters": ["max_tokens", "reasoning", "response_format", "structured_outputs", "temperature"],
    "reasoning": {"mandatory": False},
    "top_provider": {"max_completion_tokens": 65535, "is_moderated": False},
    "architecture": {"output_modalities": ["text"]},
}

MODELO_OBRIGATORIO = {
    "id": "google/gemini-3.8-flash",
    "context_length": 1048576,
    "pricing": {"prompt": "0.00000075", "completion": "0.00000375"},
    "supported_parameters": ["reasoning"],
    "reasoning": {"mandatory": True, "supported_efforts": ["high", "medium", "low"], "default_effort": "medium"},
    "top_provider": {"max_completion_tokens": 65536, "is_moderated": True},
}

MODELO_SEM_RACIOCINIO = {
    "id": "openai/gpt-4o-mini",
    "context_length": 128000,
    "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
    "supported_parameters": ["max_tokens", "response_format"],
    "reasoning": None,
    "top_provider": {"max_completion_tokens": 16384, "is_moderated": True},
}


class Relogio:
    """Um relógio que só anda quando o teste manda."""

    def __init__(self) -> None:
        self.agora = 1000.0

    def __call__(self) -> float:
        return self.agora


@pytest.fixture
def catalogo(monkeypatch):
    """Põe um catálogo de teste no lugar da rede e devolve a lista das idas a ele (uma entrada por ida)."""
    idas: list[int] = []
    entradas = [MODELO_COMPLETO, MODELO_OBRIGATORIO, MODELO_SEM_RACIOCINIO]

    def buscar() -> dict:
        idas.append(1)
        return {"data": entradas}

    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", buscar)
    return idas


@pytest.fixture
def relogio(monkeypatch) -> Relogio:
    falso = Relogio()
    monkeypatch.setattr(catalogo_de_texto, "_relogio", falso)
    return falso


def teste_lm17_le_as_capacidades_de_um_modelo_do_catalogo(catalogo) -> None:
    c = obter_capacidades("google/gemini-2.5-flash-lite")

    assert c is not None
    assert c.id == "google/gemini-2.5-flash-lite"
    assert c.contexto == 1048576
    assert c.saida_maxima == 65535
    assert c.estruturado is True
    assert c.raciocinio_suportado is True
    assert c.raciocinio_obrigatorio is False
    assert c.esforcos == ()
    assert c.preco_entrada == Decimal("0.0000001")
    assert c.preco_saida == Decimal("0.0000004")
    assert c.preco_cache_leitura == Decimal("0.00000001")
    assert c.preco_cache_escrita == Decimal("0.0000000833")
    assert c.gratuito is False
    assert c.moderado is False


def teste_lm17_os_precos_sao_decimal_e_nao_float(catalogo) -> None:
    c = obter_capacidades("google/gemini-2.5-flash-lite")

    assert isinstance(c.preco_entrada, Decimal)
    assert isinstance(c.preco_cache_leitura, Decimal)


def teste_lm17_raciocinio_obrigatorio_traz_os_esforcos_aceitos(catalogo) -> None:
    c = obter_capacidades("google/gemini-3.8-flash")

    assert c.raciocinio_obrigatorio is True
    assert c.esforcos == ("high", "medium", "low")
    assert c.moderado is True
    assert c.estruturado is False
    assert c.preco_cache_leitura is None  # o catálogo não traz: é "não sei", nunca zero


def teste_lm17_modelo_sem_raciocinio(catalogo) -> None:
    c = obter_capacidades("openai/gpt-4o-mini")

    assert c.raciocinio_suportado is False
    assert c.raciocinio_obrigatorio is False
    assert c.estruturado is False  # só ``response_format``, sem ``structured_outputs``: o esquema estrito não vale


def teste_lm17_modelo_gratuito_e_o_de_preco_zero() -> None:
    c = capacidades_de({"id": "a/gratis", "pricing": {"prompt": "0", "completion": "0"}})

    assert c.gratuito is True


def teste_lm17_campos_ausentes_ou_estranhos_viram_nao_sei() -> None:
    c = capacidades_de({"id": "x/y", "pricing": "lixo", "reasoning": "lixo", "top_provider": None, "supported_parameters": None, "context_length": "?"})

    assert c.contexto == 0
    assert c.saida_maxima is None
    assert c.preco_entrada is None
    assert c.gratuito is False
    assert c.esforcos == ()
    assert c.raciocinio_suportado is False


def teste_lm17_modelo_que_nao_esta_no_catalogo_devolve_none(catalogo) -> None:
    assert obter_capacidades("nao/existe") is None


def teste_lm17_o_catalogo_e_guardado_por_600_segundos(catalogo, relogio) -> None:
    obter_capacidades("google/gemini-2.5-flash-lite")
    relogio.agora += 599
    obter_capacidades("openai/gpt-4o-mini")

    assert len(catalogo) == 1

    relogio.agora += 2  # 601 s desde a leitura
    obter_capacidades("openai/gpt-4o-mini")

    assert len(catalogo) == 2


def teste_lm17_limpar_o_cache_forca_nova_leitura(catalogo) -> None:
    obter_capacidades("google/gemini-2.5-flash-lite")
    catalogo_de_texto.limpar_cache_do_catalogo()
    obter_capacidades("google/gemini-2.5-flash-lite")

    assert len(catalogo) == 2


def teste_lm17_falha_do_catalogo_devolve_none_e_nao_e_guardada(monkeypatch) -> None:
    chamadas: list[int] = []

    def buscar() -> dict:
        chamadas.append(1)
        if len(chamadas) == 1:
            raise httpx.ConnectError("fora do ar")
        return {"data": [MODELO_COMPLETO]}

    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", buscar)

    assert obter_capacidades("google/gemini-2.5-flash-lite") is None
    # A falha não ficou guardada: a próxima tentativa vai ao catálogo de novo e dá certo.
    assert obter_capacidades("google/gemini-2.5-flash-lite") is not None
    assert len(chamadas) == 2


def teste_lm17_catalogo_vazio_nao_e_guardado(monkeypatch) -> None:
    respostas = [{"data": []}, {"data": [MODELO_COMPLETO]}]
    monkeypatch.setattr(catalogo_de_texto, "_buscar_na_rede", lambda: respostas.pop(0))

    assert obter_capacidades("google/gemini-2.5-flash-lite") is None
    assert obter_capacidades("google/gemini-2.5-flash-lite") is not None


def teste_lm17_listar_modelos_e_obter_capacidades_dividem_a_mesma_leitura(catalogo) -> None:
    """A tela de modelos e a montagem da chamada fazem **uma** ida ao OpenRouter, não uma cada."""
    idas_do_cliente: list[str] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        idas_do_cliente.append(pedido.url.path)
        return httpx.Response(200, json={"data": [MODELO_COMPLETO, MODELO_SEM_RACIOCINIO]})

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(responder))
    provedor = ProvedorOpenRouter(cliente=cliente)

    assert {m.id for m in provedor.listar_modelos()} == {"google/gemini-2.5-flash-lite", "openai/gpt-4o-mini"}
    # O catálogo já está guardado: a consulta de capacidades não vai à rede.
    assert obter_capacidades("openai/gpt-4o-mini") is not None
    assert provedor.listar_modelos()  # nem a segunda listagem
    assert len(idas_do_cliente) == 1
    assert catalogo == []


def teste_lm17_listar_modelos_com_o_catalogo_fora_do_ar_continua_dando_erro_em_portugues() -> None:
    """Quem lista os modelos precisa saber que falhou (diferente da montagem da chamada, que segue sem o catálogo)."""
    from imagineer.ia.provedor import ErroDoProvedorIA

    cliente = httpx.Client(base_url=ENDERECO_BASE, transport=httpx.MockTransport(lambda p: httpx.Response(500, text="caiu")))

    with pytest.raises(ErroDoProvedorIA):
        ProvedorOpenRouter(cliente=cliente).listar_modelos()


def teste_lm17_o_catalogo_nao_leva_chave_de_api(monkeypatch) -> None:
    """O catálogo é público (CT19): a ida à rede não manda ``Authorization``."""
    visto: dict = {}

    def get_falso(url, **kwargs):
        visto["url"] = url
        visto["kwargs"] = kwargs
        return httpx.Response(200, json={"data": [MODELO_COMPLETO]}, request=httpx.Request("GET", url))

    # O ``conftest`` trocou ``_buscar_na_rede`` por uma função vazia; ``undo`` a devolve, para exercitar a de verdade (só o ``httpx.get`` é falso).
    monkeypatch.undo()
    monkeypatch.setattr(catalogo_de_texto.httpx, "get", get_falso)

    dados = catalogo_de_texto._buscar_na_rede()

    assert dados["data"][0]["id"] == "google/gemini-2.5-flash-lite"
    assert visto["url"] == f"{ENDERECO_BASE}/models"
    assert "headers" not in visto["kwargs"]
    assert "authorization" not in json.dumps(visto["kwargs"]).lower()
