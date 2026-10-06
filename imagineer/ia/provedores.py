"""Os provedores de IA cuja chave a pessoa pode cadastrar no app (item CT24).

**Uma lista fixa**, e não um campo livre: o servidor só sabe falar com estes três, e cada um tem o seu header. A chave **nunca** é gravada no servidor
(CT19): o app a guarda e a manda a cada chamada, no header do provedor.
"""

import enum
from dataclasses import dataclass


class Provedor(str, enum.Enum):
    """Quem fornece IA ao servidor."""

    OPENROUTER = "OPENROUTER"
    FAL = "FAL"
    REPLICATE = "REPLICATE"


@dataclass(frozen=True)
class DadosDoProvedor:
    nome: str
    cabecalho: str
    """O header em que o app manda a chave deste provedor."""
    variavel_de_ambiente: str
    """Onde o **dono** põe a chave do servidor (``.env``); só vale para quem tem ``usa_chaves_do_servidor`` (CT9)."""
    usado_para: str


PROVEDORES: dict[Provedor, DadosDoProvedor] = {
    Provedor.OPENROUTER: DadosDoProvedor("OpenRouter", "X-Chave-API-OpenRouter", "CHAVE_API_OPENROUTER", "texto, voz e imagem"),
    Provedor.FAL: DadosDoProvedor("fal.ai", "X-Chave-API-Fal", "FAL_KEY", "imagem"),
    Provedor.REPLICATE: DadosDoProvedor("Replicate", "X-Chave-API-Replicate", "REPLICATE_API_TOKEN", "imagem"),
}
