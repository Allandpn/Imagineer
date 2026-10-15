"""O custo de um capítulo e o preço por milhão de tokens na lista de modelos (15/10/2026): o preço por token (0,000002) ninguém lê, e o preço por milhão
sozinho não diz quanto um capítulo custa. A lista passa a trazer os dois números que dão para comparar modelos lado a lado."""

import pytest
from fastapi.testclient import TestClient

from imagineer.ia.catalogo_de_texto import capacidades_de
from imagineer.ia.provedor import mensagem_de_variante_em_lote
from imagineer.servicos.estimativa_de_leitura import custo_do_capitulo_tipico
from testes.teste_lm_presets_e_lista_de_modelos import _entrada, _provedor_com_lista

ARGON = _entrada(
    "google/gemini-4-argon", "0.000002", "0.00001",
    pricing={"prompt": "0.000002", "completion": "0.00001", "input_cache_read": "0.0000001", "input_cache_write": "0.0000002"},
)


@pytest.fixture(autouse=True)
def _catalogo_limpo():
    from imagineer.ia import catalogo_de_texto

    catalogo_de_texto.limpar_cache_do_catalogo()
    yield
    catalogo_de_texto.limpar_cache_do_catalogo()


def teste_o_provedor_calcula_o_custo_do_capitulo_pela_mesma_conta_da_estimativa() -> None:
    modelo = _provedor_com_lista(ARGON).listar_modelos()[0]

    sem_cache, com_cache = custo_do_capitulo_tipico(capacidades_de(ARGON))

    assert modelo.custo_do_capitulo_tipico == pytest.approx(float(com_cache), abs=1e-6)
    assert modelo.custo_do_capitulo_tipico_sem_cache == pytest.approx(float(sem_cache), abs=1e-6)
    assert modelo.custo_do_capitulo_tipico < modelo.custo_do_capitulo_tipico_sem_cache  # o cache barateia
    assert modelo.custo_do_capitulo_tipico_sem_cache == pytest.approx(0.324, abs=0.001)  # 9 leituras x (12 mil x US$ 2/M + 1,2 mil x US$ 10/M)


def teste_a_rota_traz_o_preco_por_milhao_e_o_custo_do_capitulo(cliente: TestClient, usar_provedor_falso) -> None:
    usar_provedor_falso(_provedor_com_lista(ARGON))

    [argon] = cliente.get("/configuracao/modelos").json()

    assert argon["preco_entrada_por_milhao"] == 2.0 and argon["preco_saida_por_milhao"] == 10.0
    assert argon["custo_do_capitulo_tipico_sem_cache"] == pytest.approx(0.324, abs=0.001)
    assert 0 < argon["custo_do_capitulo_tipico"] < argon["custo_do_capitulo_tipico_sem_cache"]
    assert argon["preco_entrada"] == pytest.approx(0.000002)  # o campo de antes continua


def teste_modelo_gratuito_custa_zero_e_o_provedor_falso_nao_quebra(cliente: TestClient, usar_provedor_falso) -> None:
    from imagineer.ia.falso import ProvedorFalso

    usar_provedor_falso(_provedor_com_lista(_entrada("x/gratis", "0", "0")))
    assert cliente.get("/configuracao/modelos").json()[0]["custo_do_capitulo_tipico"] == 0

    usar_provedor_falso(ProvedorFalso())  # sem custo informado: os campos novos têm padrão seguro
    modelos = cliente.get("/configuracao/modelos").json()
    assert modelos and all(m["custo_do_capitulo_tipico"] is None and m["preco_entrada_por_milhao"] == 0.0 for m in modelos)


def teste_a_mensagem_do_lote_explica_por_que_e_o_que_escolher() -> None:
    mensagem = mensagem_de_variante_em_lote("google/gemini-4-argon:batch")

    assert "metade do preço" in mensagem and "horas depois" in mensagem
    assert "Escolha google/gemini-4-argon, a versão normal" in mensagem and "dobro por token" in mensagem
