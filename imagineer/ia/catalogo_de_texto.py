"""O que cada modelo de texto do OpenRouter sabe fazer, lido do catálogo público (item 4.10, LM17).

O ``GET /models`` do OpenRouter diz, de cada modelo, o tamanho do contexto, os preços (inclusive do cache), os parâmetros que aceita e como
funciona o raciocínio dele. Antes, o servidor usava quase nada disso. Aqui o catálogo é lido **uma vez a cada 10 minutos** e guardado no
módulo: a tela de modelos (``listar_modelos``) e a montagem de cada chamada (``obter_capacidades``) **dividem** a mesma leitura.

O catálogo é **público**: nenhuma chave de API vai nesta chamada (CT19).
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

TEMPO_DE_VIDA_DO_CATALOGO = 600.0
"""Segundos que a leitura do catálogo vale. Os preços mudam por semana, não por minuto."""

TEMPO_LIMITE_DA_LEITURA = 30.0
"""Segundos de espera pelo catálogo. Curto de propósito: sem ele a chamada segue com o corpo mínimo (LM2), então não vale esperar."""


@dataclass(frozen=True)
class Capacidades:
    """O que o catálogo diz de um modelo. Os preços são ``Decimal`` (dinheiro não se faz com ``float``) e vêm em US$ **por token**."""

    id: str
    contexto: int
    saida_maxima: int | None
    estruturado: bool
    """Aceita ``response_format`` com ``json_schema`` (``structured_outputs`` em ``supported_parameters``)."""
    raciocinio_suportado: bool
    raciocinio_obrigatorio: bool
    esforcos: tuple[str, ...]
    """Os esforços de raciocínio que o modelo aceita. Vazio = o catálogo não diz (qualquer um serve)."""
    preco_entrada: Decimal | None
    preco_saida: Decimal | None
    preco_cache_leitura: Decimal | None
    preco_cache_escrita: Decimal | None
    gratuito: bool
    moderado: bool


def decimal_ou_nulo(valor: object) -> Decimal | None:
    """O número em ``valor`` como ``Decimal`` (o OpenRouter manda os preços como texto), ou ``None`` se não é número."""
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def _inteiro_positivo_ou_nulo(valor: object) -> int | None:
    """``valor`` como inteiro maior que zero, ou ``None``."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    return int(valor) if valor > 0 else None


def capacidades_de(bruto: dict) -> Capacidades:
    """Lê uma entrada do ``/models`` do OpenRouter. Campo ausente ou estranho vira "não sei" (``None``, vazio ou falso), nunca erro."""
    preco = bruto.get("pricing") if isinstance(bruto.get("pricing"), dict) else {}
    raciocinio = bruto.get("reasoning") if isinstance(bruto.get("reasoning"), dict) else {}
    provedor = bruto.get("top_provider") if isinstance(bruto.get("top_provider"), dict) else {}
    parametros = {p for p in (bruto.get("supported_parameters") or []) if isinstance(p, str)}

    preco_entrada = decimal_ou_nulo(preco.get("prompt"))
    return Capacidades(
        id=bruto.get("id") or "",
        contexto=_inteiro_positivo_ou_nulo(bruto.get("context_length")) or 0,
        saida_maxima=_inteiro_positivo_ou_nulo(provedor.get("max_completion_tokens")),
        estruturado="structured_outputs" in parametros,
        raciocinio_suportado="reasoning" in parametros,
        raciocinio_obrigatorio=bool(raciocinio.get("mandatory")),
        esforcos=tuple(e for e in (raciocinio.get("supported_efforts") or []) if isinstance(e, str)),
        preco_entrada=preco_entrada,
        preco_saida=decimal_ou_nulo(preco.get("completion")),
        preco_cache_leitura=decimal_ou_nulo(preco.get("input_cache_read")),
        preco_cache_escrita=decimal_ou_nulo(preco.get("input_cache_write")),
        gratuito=preco_entrada == 0,
        moderado=bool(provedor.get("is_moderated")),
    )


_relogio: Callable[[], float] = time.monotonic
"""O relógio do cache. É uma variável do módulo para os testes trocarem por um falso e "passarem" 10 minutos sem esperar."""

_trava = threading.Lock()
_guardado: tuple[float, list[dict]] | None = None
"""Quando foi lido (pelo ``_relogio``) e as entradas brutas do catálogo."""


def _buscar_na_rede() -> dict:
    """``GET /models`` do OpenRouter, sem chave. Levanta ``httpx.HTTPError`` se falhar."""
    # Importado aqui (e não no alto) porque o ``openrouter`` importa este módulo: no alto seria um ciclo.
    from imagineer.ia.openrouter import ENDERECO_BASE

    resposta = httpx.get(f"{ENDERECO_BASE}/models", timeout=TEMPO_LIMITE_DA_LEITURA)
    resposta.raise_for_status()
    return resposta.json()


def ler_catalogo(buscar: Callable[[], dict] | None = None) -> list[dict]:
    """As entradas brutas do catálogo, do cache se a leitura tem menos de 10 minutos.

    ``buscar`` é como ir buscar o catálogo **se for preciso** (o cache vencido ou vazio). Quem já tem um cliente HTTP à mão
    (``listar_modelos``) passa o dele; sem nada, vale a ida à rede. **Uma falha não é guardada** (a exceção sobe), e um catálogo
    **vazio** também não: vazio é sinal de resposta ruim, e guardá-lo por 10 minutos esconderia o catálogo de verdade.
    """
    global _guardado
    with _trava:
        agora = _relogio()
        if _guardado is not None and agora - _guardado[0] < TEMPO_DE_VIDA_DO_CATALOGO:
            return _guardado[1]

        dados = (buscar or _buscar_na_rede)()
        entradas = [e for e in (dados.get("data") or []) if isinstance(e, dict)] if isinstance(dados, dict) else []
        if entradas:
            _guardado = (agora, entradas)
        return entradas


def obter_capacidades(modelo_id: str) -> Capacidades | None:
    """O que o catálogo diz do modelo, ou ``None`` se ele não está lá **ou** o catálogo não pôde ser lido.

    ``None`` não é erro: quem monta a chamada segue com o corpo mínimo (LM2), e o provedor responde por si se o modelo não existe.
    """
    try:
        entradas = ler_catalogo()
    except Exception:  # noqa: BLE001 - de propósito: o catálogo é um enfeite da chamada, nunca a derruba
        logging.getLogger(__name__).warning("Não foi possível ler o catálogo de modelos do OpenRouter.", exc_info=True)
        return None

    for entrada in entradas:
        if entrada.get("id") == modelo_id:
            return capacidades_de(entrada)
    return None


def limpar_cache_do_catalogo() -> None:
    """Esquece a leitura guardada. Os testes chamam isto para um teste não herdar o catálogo do outro."""
    global _guardado
    with _trava:
        _guardado = None
