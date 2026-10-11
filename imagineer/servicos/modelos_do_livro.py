"""Os modelos de IA por livro (item 7.5g, MV1 a MV3): a configuração global com as trocas do livro por cima.

Em vez de espalhar "o livro tem um modelo próprio?" por todo ponto que lê ``configuracao.modelo_...``, o livro devolve uma **visão** da
configuração: a mesma de sempre, só que os campos que o livro trocou valem o valor do livro. Quem já recebe uma ``Configuracao`` (os serviços de
leitura, de prompt, de imagem, de narração) funciona sem saber de nada: basta receber a visão em vez da configuração global.

A visão é **só de leitura** e nada é gravado na configuração global.
"""

from sqlalchemy.orm import Session

from imagineer.modelos import Configuracao, Livro
from imagineer.servicos.configuracao_ia import obter_ou_criar

CAMPOS_DE_MODELO_DO_LIVRO: tuple[str, ...] = (
    "modelo_extracao",
    "modelo_prompt",
    "modelo_leitura",
    "modelo_reserva",
    "modelo_conferencia",
    "modelo_perfil",
    "modelo_imagem",
    "modelo_suavizacao",
    "modelo_traducao",
    "modelo_video",
    "modelo_narracao",
    "narracao_voz",
)
"""Os campos da configuração que um livro pode trocar (MV1): os modelos de cada tarefa e a voz da narração."""


def trocas_do_livro(livro: Livro | None) -> dict[str, str]:
    """As trocas **válidas** do livro: só as chaves conhecidas, com valor não vazio (espaços nas pontas não contam)."""
    if livro is None or not livro.modelos:
        return {}
    trocas: dict[str, str] = {}
    for campo in CAMPOS_DE_MODELO_DO_LIVRO:
        valor = livro.modelos.get(campo)
        if isinstance(valor, str) and valor.strip():
            trocas[campo] = valor.strip()
    return trocas


class ConfiguracaoDoLivro:
    """A configuração global vista pelo livro: os campos trocados valem o valor do livro; os demais, o global. Somente leitura."""

    def __init__(self, base: Configuracao, trocas: dict[str, str]) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_trocas", dict(trocas))

    def __getattr__(self, nome: str):
        trocas = object.__getattribute__(self, "_trocas")
        if nome in trocas:
            return trocas[nome]
        return getattr(object.__getattribute__(self, "_base"), nome)

    def __setattr__(self, nome: str, valor) -> None:
        raise AttributeError("A configuração de um livro é só de leitura: mude a global em /configuracao ou as trocas em /livros/{id}/modelos.")


def configuracao_do_livro(sessao: Session, livro: Livro | None) -> Configuracao | ConfiguracaoDoLivro:
    """A configuração que vale para o ``livro``. Sem livro, ou sem trocas, é a própria configuração global (o mesmo objeto de sempre)."""
    base = obter_ou_criar(sessao)
    trocas = trocas_do_livro(livro)
    return ConfiguracaoDoLivro(base, trocas) if trocas else base


def origem_do_campo(livro: Livro | None, campo: str) -> str:
    """De onde vem o valor de ``campo`` para este livro: ``livro`` (trocado por ele) ou ``global``."""
    return "livro" if campo in trocas_do_livro(livro) else "global"
