"""A trava de menores da geração sem filtro (item 7.5b, F15)."""

import pytest

from imagineer.servicos.sinais_de_menor import sinal_de_menor


@pytest.mark.parametrize(
    "texto",
    [
        "a young girl in a meadow",
        "two children playing",
        "a teenage boy",
        "uma menina de vestido",
        "a criança dormindo",
        "um adolescente",
        "a 12-year-old with long hair",
        "she is 15 years old",
        "ela tem 10 anos",
        "A KID on a bike",
        "a baby sleeping",
    ],
)
def teste_aponta_o_sinal_de_menor(texto: str) -> None:
    assert sinal_de_menor(texto) is not None


@pytest.mark.parametrize(
    "texto",
    [
        "close-up, a young woman with pale golden hair, oil painting",
        "a 23-year-old woman, tall",
        "ela tem 25 anos",
        "an elderly man with a grey beard",
        "Style: Oil painting. Format: Portrait. Reference: Caspar David Friedrich.",
        "a girlfriend's portrait",  # "girlfriend" não é "girl": palavra inteira
        "",
    ],
)
def teste_nao_aponta_sinal_em_adulto(texto: str) -> None:
    assert sinal_de_menor(texto) is None
