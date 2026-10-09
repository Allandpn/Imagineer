"""O perfil de cada tarefa de IA de texto (item 4.10, LM1).

Cada passo do fluxo (ler o estado de um elemento, montar um prompt, traduzir...) pede uma coisa diferente ao modelo: uns precisam de
fidelidade e resposta em JSON, outros de redação rápida e barata. Em vez de espalhar esses números pelo código, o perfil de cada tarefa
fica **num lugar só**, e a chamada ao OpenRouter (``ProvedorOpenRouter._conversar``) o consulta pela ``operacao``.

Os valores abaixo são o **ponto de partida** (proposta, LM1): a medição com o script de avaliação (LM18, LM20) os confirma ou muda.
"""

from dataclasses import dataclass
from enum import Enum

TEMPERATURA_DA_SUAVIZACAO = 0.2
"""Baixa de propósito: suavizar é reescrever com o mínimo de mudança, não criar."""

TEMPERATURA_DA_TRADUCAO = 0.2

TEMPERATURA_DA_CORRECAO = 0.2
"""Corrigir é mudar o mínimo que a pessoa pediu: sem variar (como a tradução e a suavização)."""

TEMPERATURA_DE_FIDELIDADE = 0.2
"""Extração, leitura profunda (fases 2 e 2b) e fundamentação (FD5): tarefas em que o modelo deve **ler e descrever o que o texto diz**, sem
variar. O padrão dos provedores (~1,0) deixava o mesmo capítulo render descrições diferentes a cada leitura."""

TEMPERATURA_DO_PROMPT = 0.4
"""Montagem do prompt (FD5): é um texto corrido que ainda precisa de alguma liberdade de redação, mas dentro dos fatos recebidos."""


class NivelDeRaciocinio(str, Enum):
    """Quanto o modelo pode "pensar" antes de responder. O valor é o texto que o OpenRouter espera em ``reasoning.effort``.

    É o que se **pede**; a chamada se ajusta ao que o modelo aceita (LM2): há modelos em que o raciocínio é obrigatório e outros que só
    aceitam esforço alto. Raciocinar demora e custa tokens de saída, então as tarefas de leitura pedem pouco e as de redação, nenhum.
    """

    NENHUM = "none"
    MINIMO = "minimal"
    BAIXO = "low"
    MEDIO = "medium"


ORDEM_DOS_ESFORCOS = ("minimal", "low", "medium", "high", "xhigh", "max")
"""Os esforços de raciocínio que o OpenRouter conhece, do menor ao maior. Serve para achar "o mais próximo acima" (LM2.3)."""


@dataclass(frozen=True)
class PerfilDaTarefa:
    """O que uma tarefa pede à chamada de conversa."""

    temperatura: float | None
    """``None`` = não manda ``temperature`` (o padrão do provedor), como a geração do perfil de renderização sempre fez."""

    limite_de_saida: int
    """Tokens do **texto visível** da resposta. A folga do raciocínio é somada à parte (LM3)."""

    raciocinio: NivelDeRaciocinio

    esquema: str | None
    """Nome de um esquema de ``esquemas_json.ESQUEMAS`` (LM8). ``None`` = texto livre."""

    cache_do_capitulo: bool
    """Se o pedido leva o capítulo inteiro, que vale a pena pôr em cache entre as leituras do mesmo capítulo (LM9 a LM11)."""


PERFIL_NEUTRO = PerfilDaTarefa(
    temperatura=1.0, limite_de_saida=4000, raciocinio=NivelDeRaciocinio.NENHUM, esquema=None, cache_do_capitulo=False
)
"""O perfil de uma ``operacao`` que não está em ``PERFIS``: nenhuma chamada que já existia quebra."""


def _leitura(limite_de_saida: int, esquema: str) -> PerfilDaTarefa:
    """As quatro tarefas que **leem o capítulo** são parecidas: fiéis, com pouco raciocínio, em JSON e com o capítulo em cache."""
    return PerfilDaTarefa(
        temperatura=TEMPERATURA_DE_FIDELIDADE,
        limite_de_saida=limite_de_saida,
        raciocinio=NivelDeRaciocinio.BAIXO,
        esquema=esquema,
        cache_do_capitulo=True,
    )


def _redacao(temperatura: float | None, limite_de_saida: int) -> PerfilDaTarefa:
    """As tarefas de redação (prompt, tradução, correção...) não leem o capítulo e não precisam raciocinar."""
    return PerfilDaTarefa(
        temperatura=temperatura,
        limite_de_saida=limite_de_saida,
        raciocinio=NivelDeRaciocinio.NENHUM,
        esquema=None,
        cache_do_capitulo=False,
    )


PERFIS: dict[str, PerfilDaTarefa] = {
    "extracao": _leitura(8000, "extracao"),
    "estado": _leitura(3000, "estado_com_momentos"),  # item 4.9, FL3: o formato com a linha do tempo do elemento (o `estado` de antes continua em ESQUEMAS)
    "identidade": _leitura(800, "identidade"),
    "fundamentacao": _leitura(3500, "dossie"),  # item 4.9, FL5: a fundamentação de três frases virou o dossiê da cena
    "conferencia": PerfilDaTarefa(
        temperatura=0.0, limite_de_saida=1500, raciocinio=NivelDeRaciocinio.NENHUM, esquema="conferencia", cache_do_capitulo=False
    ),  # item 4.9, FL13.1: comparar a imagem com a lista; sem variar
    "prompt": _redacao(TEMPERATURA_DO_PROMPT, 1500),
    "prompt_de_video": _redacao(TEMPERATURA_DO_PROMPT, 1500),
    "traducao": _redacao(TEMPERATURA_DA_TRADUCAO, 2000),
    "correcao": _redacao(TEMPERATURA_DA_CORRECAO, 2000),
    "suavizacao": _redacao(TEMPERATURA_DA_SUAVIZACAO, 2000),
    "perfil": _redacao(None, 3000),
}
"""O perfil de cada ``operacao`` que ``_conversar`` recebe (a tabela do LM1)."""


def perfil_da(operacao: str) -> PerfilDaTarefa:
    """O perfil da ``operacao``, ou o neutro se ela não está na tabela."""
    return PERFIS.get(operacao, PERFIL_NEUTRO)
