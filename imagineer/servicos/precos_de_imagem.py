"""Quanto custa uma imagem de cada modelo, **sem tabela fixa** (item 7.5b, PD1 a PD6).

O OpenRouter devolve o custo real de cada chamada (``usage.cost``). O **fal.ai** e o **Replicate** não devolvem. De onde vem o preço,
em ordem de confiança:

1. **medido** — a média do que as imagens do modelo já custaram de verdade (só OpenRouter, que informa o custo);
2. **informado** — o preço que a **pessoa** digitou no app (vale para qualquer modelo; é o único caminho no Replicate, que não publica
   preço pela API);
3. **fornecedor** — o preço que o **fal.ai** publica hoje em sua API (``GET /v1/models/pricing``), lido na hora e guardado por 6 horas.
   Costuma ser **por megapixel**; sem saber a resolução, conta-se **1 megapixel**, então é uma **estimativa**.

Nada é inventado: sem nenhuma das três origens, o preço fica **nulo** (e a chamada conta em "sem preço").
"""

import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from imagineer.configuracao import obter_configuracoes

URL_DO_FAL = "https://api.fal.ai/v1"
URL_DO_REPLICATE = "https://api.replicate.com/v1"

VALIDADE_DO_CACHE = 6 * 3600.0
"""Segundos que um preço ou uma lista lida do fornecedor vale antes de ser lida de novo."""

_cache: dict[str, tuple[float, object]] = {}


def limpar_cache() -> None:
    """Esquece tudo o que foi lido dos fornecedores (os testes usam; o servidor também, se quiser forçar uma releitura)."""
    _cache.clear()


def _get(url: str, params: list[tuple[str, str]] | None = None, cabecalhos: dict[str, str] | None = None) -> dict:
    """Uma leitura ``GET`` que devolve o JSON, ou levanta ``httpx.HTTPError``. Isolada para os testes não irem à rede."""
    resposta = httpx.get(url, params=params, headers=cabecalhos, timeout=20.0)
    resposta.raise_for_status()
    return resposta.json()


def _guardado(chave: str, ler):
    """O valor lido por ``ler()``, guardado por [VALIDADE_DO_CACHE]. Falha de leitura **não** é guardada (tenta de novo na vez seguinte)."""
    agora = time.monotonic()
    if chave in _cache and agora - _cache[chave][0] < VALIDADE_DO_CACHE:
        return _cache[chave][1]
    valor = ler()
    _cache[chave] = (agora, valor)
    return valor


def _chave_do_fal() -> str:
    return obter_configuracoes().chave_api_fal.strip()


def _chave_do_replicate() -> str:
    return obter_configuracoes().chave_api_replicate.strip()


@dataclass(frozen=True)
class PrecoDoFal:
    """O preço de lista de um modelo do fal.ai: [valor] dólares por [unidade] (``megapixels``, ``images``...)."""

    valor: Decimal
    unidade: str

    def por_imagem(self, megapixels: float = 1.0) -> Decimal | None:
        """O preço estimado de **uma imagem**: por megapixel × os megapixels da imagem; por imagem, o próprio valor; outra unidade, nulo."""
        if self.unidade in ("image", "images"):
            return self.valor
        if self.unidade in ("megapixel", "megapixels"):
            return (self.valor * Decimal(str(max(megapixels, 0.0)))).quantize(Decimal("0.0001"))
        return None


def precos_do_fal(ids_dos_endpoints: list[str]) -> dict[str, PrecoDoFal]:
    """Os preços que o fal.ai publica para os endpoints dados (sem o prefixo ``fal:``). Sem chave ou com falha, devolve vazio."""
    chave = _chave_do_fal()
    if not chave or not ids_dos_endpoints:
        return {}
    encontrados: dict[str, PrecoDoFal] = {}
    pedir = []
    for endpoint in dict.fromkeys(ids_dos_endpoints):
        guardado = _cache.get(f"fal-preco:{endpoint}")
        if guardado is not None and time.monotonic() - guardado[0] < VALIDADE_DO_CACHE:
            if guardado[1] is not None:
                encontrados[endpoint] = guardado[1]  # type: ignore[assignment]
        else:
            pedir.append(endpoint)
    for inicio in range(0, len(pedir), 50):
        lote = pedir[inicio : inicio + 50]
        try:
            dados = _get(f"{URL_DO_FAL}/models/pricing", [("endpoint_id", e) for e in lote], {"Authorization": f"Key {chave}"})
        except (httpx.HTTPError, ValueError):
            logging.getLogger(__name__).warning("Não foi possível ler os preços do fal.ai agora.")
            continue
        lidos = {}
        for item in dados.get("prices", []):
            try:
                lidos[item["endpoint_id"]] = PrecoDoFal(Decimal(str(item["unit_price"])), str(item.get("unit", "")).lower())
            except (KeyError, InvalidOperation):
                continue
        for endpoint in lote:
            _cache[f"fal-preco:{endpoint}"] = (time.monotonic(), lidos.get(endpoint))
            if endpoint in lidos:
                encontrados[endpoint] = lidos[endpoint]
    return encontrados


def modelos_de_imagem_do_fal() -> list[tuple[str, str]]:
    """Os modelos de **texto para imagem** do fal.ai: ``(id com o prefixo, nome)``. Sem chave ou com falha, vazio."""
    chave = _chave_do_fal()
    if not chave:
        return []

    def ler() -> list[tuple[str, str]]:
        modelos: list[tuple[str, str]] = []
        cursor: str | None = None
        for _ in range(10):  # no máximo 10 páginas
            parametros = [("category", "text-to-image"), ("limit", "100")] + ([("cursor", cursor)] if cursor else [])
            dados = _get(f"{URL_DO_FAL}/models", parametros, {"Authorization": f"Key {chave}"})
            for item in dados.get("models", []):
                endpoint = item.get("endpoint_id")
                if endpoint and (item.get("metadata") or {}).get("status", "active") == "active":
                    modelos.append((f"fal:{endpoint}", (item.get("metadata") or {}).get("display_name") or endpoint))
            cursor = dados.get("next_cursor")
            if not dados.get("has_more") or not cursor:
                break
        return modelos

    try:
        return _guardado("fal-lista", ler)  # type: ignore[return-value]
    except (httpx.HTTPError, ValueError):
        logging.getLogger(__name__).warning("Não foi possível ler a lista de modelos do fal.ai agora.")
        return []


def modelos_de_imagem_do_replicate() -> list[tuple[str, str]]:
    """Os modelos da coleção **text-to-image** do Replicate: ``(id com o prefixo, nome)``. Sem chave ou com falha, vazio."""
    chave = _chave_do_replicate()
    if not chave:
        return []

    def ler() -> list[tuple[str, str]]:
        dados = _get(f"{URL_DO_REPLICATE}/collections/text-to-image", None, {"Authorization": f"Bearer {chave}"})
        return [
            (f"replicate:{m['owner']}/{m['name']}", f"{m['owner']}/{m['name']}")
            for m in dados.get("models", [])
            if m.get("owner") and m.get("name")
        ]

    try:
        return _guardado("replicate-lista", ler)  # type: ignore[return-value]
    except (httpx.HTTPError, ValueError, KeyError):
        logging.getLogger(__name__).warning("Não foi possível ler a lista de modelos do Replicate agora.")
        return []


def preco_informado(modelo: str, informados: dict[str, str] | None) -> Decimal | None:
    """O preço que a pessoa digitou para o ``modelo`` (chave igual à do ``usos_ia``), ou ``None``."""
    bruto = (informados or {}).get(modelo.strip())
    try:
        valor = Decimal(str(bruto)) if bruto is not None else None
    except InvalidOperation:
        return None
    return valor if valor is not None and valor > 0 else None


def preco_estimado_da_imagem(modelo: str, informados: dict[str, str] | None = None, megapixels: float = 1.0) -> Decimal | None:
    """O preço estimado de uma imagem do ``modelo`` (com prefixo): o **informado** pela pessoa; senão o que o **fal.ai** publica; senão ``None``.

    Nunca um valor inventado: sem informação, ``None``.
    """
    modelo = modelo.strip()
    informado = preco_informado(modelo, informados)
    if informado is not None:
        return informado
    prefixo, _, endpoint = modelo.partition(":")
    if prefixo == "fal" and endpoint:
        preco = precos_do_fal([endpoint]).get(endpoint)
        return preco.por_imagem(megapixels) if preco is not None else None
    return None
