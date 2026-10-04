"""Quanto custa, por imagem, cada modelo de imagem que **não informa** o custo (item 7.5b, CU2).

O OpenRouter devolve o custo da chamada (``usage.cost``) quando tem; o **fal.ai** e o **Replicate** não devolvem. Para o Allan ver
o total dos três lugares, o custo deles é **estimado** por esta tabela: o preço de lista **por imagem de cerca de 1 megapixel**, em
dólares. **São valores de referência a conferir**: os fornecedores mudam os preços, e alguns cobram por megapixel ou por segundo de
GPU. Por isso o custo estimado fica **marcado** (``estimado``) e o app o mostra com "~".

Modelo que **não está** aqui não tem preço: o custo fica **nulo** e a chamada conta em "sem preço" (nunca um zero inventado).
"""

from decimal import Decimal

PRECOS_POR_IMAGEM: dict[str, Decimal] = {
    # fal.ai (preço de lista por imagem de ~1 MP)
    "fal:fal-ai/flux/dev": Decimal("0.025"),
    "fal:fal-ai/flux/schnell": Decimal("0.003"),
    "fal:fal-ai/flux-pro/v1.1": Decimal("0.04"),
    # Replicate
    "replicate:black-forest-labs/flux-schnell": Decimal("0.003"),
    "replicate:black-forest-labs/flux-dev": Decimal("0.025"),
    "replicate:black-forest-labs/flux-1.1-pro": Decimal("0.04"),
    "replicate:bytedance/seedream-4.5": Decimal("0.04"),
    "replicate:bytedance/seedream-3": Decimal("0.03"),
}
"""O preço estimado por imagem, pelo id do modelo **com o prefixo do fornecedor** (como o app e a configuração o guardam)."""


def preco_estimado_da_imagem(modelo: str) -> Decimal | None:
    """O preço estimado de uma imagem do ``modelo`` (com prefixo), ou ``None`` se a tabela não o conhece."""
    return PRECOS_POR_IMAGEM.get(modelo.strip())
