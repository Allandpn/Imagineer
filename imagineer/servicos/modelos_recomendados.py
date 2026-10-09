"""Os modelos recomendados por nível: Econômico, Equilibrado e Qualidade (item 4.10, LM14).

Quem não entende de modelos escolhe um **nível** e recebe um modelo para cada papel. A tabela é **curada à mão** e validada contra o catálogo ao
vivo: um modelo que sumiu do OpenRouter aparece como indisponível, em vez de quebrar. Os valores são a **proposta inicial** do item 4.10; a
medição com o script de avaliação (LM18, LM20) os confirma ou troca. **Modelos gratuitos nunca entram aqui**: ficam em fila e devolvem JSON
irregular.
"""

import enum
from dataclasses import dataclass


class Nivel(str, enum.Enum):
    """Quanto se quer gastar para ler o livro."""

    ECONOMICO = "ECONOMICO"
    EQUILIBRADO = "EQUILIBRADO"
    QUALIDADE = "QUALIDADE"


class Papel(str, enum.Enum):
    """O trabalho que um modelo de texto faz."""

    EXTRACAO = "EXTRACAO"
    LEITURA = "LEITURA"
    PROMPT = "PROMPT"
    TRADUCAO = "TRADUCAO"
    SUAVIZACAO = "SUAVIZACAO"
    VIDEO = "VIDEO"
    RESERVA = "RESERVA"


CAMPO_DA_CONFIGURACAO: dict[Papel, str] = {
    Papel.EXTRACAO: "modelo_extracao",
    Papel.LEITURA: "modelo_leitura",
    Papel.PROMPT: "modelo_prompt",
    Papel.TRADUCAO: "modelo_traducao",
    Papel.SUAVIZACAO: "modelo_suavizacao",
    Papel.VIDEO: "modelo_video",
    Papel.RESERVA: "modelo_reserva",
}
"""Em que campo de ``Configuracao`` cada papel é gravado. A **correção** do prompt não tem campo (usa o ``modelo_prompt``), e a tabela do item 4.10
a agrupava com a tradução e a suavização: por isso não é um papel aqui. Imagem, narração e perfil de renderização também ficam de fora."""


@dataclass(frozen=True)
class Recomendacao:
    modelo: str
    motivo: str


_TRADUZIR_E_SUAVIZAR = "traduzir e suavizar pedem pouco do modelo: o mais barato basta"
_VIDEO_BOM_E_BARATO = "bom no prompt de vídeo por menos da metade do preço do melhor"

RECOMENDACOES: dict[Nivel, dict[Papel, Recomendacao]] = {
    Nivel.ECONOMICO: {
        Papel.EXTRACAO: Recomendacao("google/gemini-2.5-flash-lite", "o mais barato com contexto longo; foi o melhor em fidelidade por preço na leitura (0 invenções, 1,8 s)"),
        Papel.LEITURA: Recomendacao("google/gemini-2.5-flash-lite", "lê o capítulo em rajada por centavos, com cache; sem raciocínio obrigatório"),
        Papel.PROMPT: Recomendacao("openai/gpt-4o-mini", "redige o prompt de imagem barato e rápido, sem raciocínio"),
        Papel.TRADUCAO: Recomendacao("google/gemini-2.5-flash-lite", _TRADUZIR_E_SUAVIZAR),
        Papel.SUAVIZACAO: Recomendacao("google/gemini-2.5-flash-lite", _TRADUZIR_E_SUAVIZAR),
        Papel.VIDEO: Recomendacao("google/gemini-3.8-flash", _VIDEO_BOM_E_BARATO),
        Papel.RESERVA: Recomendacao("openai/gpt-4o-mini", "de outro fornecedor: cobre a queda do principal"),
    },
    Nivel.EQUILIBRADO: {
        Papel.EXTRACAO: Recomendacao("openai/gpt-4.1-mini", "mais cuidadoso que o econômico ao identificar elementos e cenas, sem raciocínio (rápido)"),
        Papel.LEITURA: Recomendacao("google/gemini-2.5-flash", "mais fiel que o econômico nos detalhes de cada elemento, ainda com cache barato"),
        Papel.PROMPT: Recomendacao("google/gemini-2.5-flash", "prompts mais ricos sem pagar raciocínio obrigatório"),
        Papel.TRADUCAO: Recomendacao("google/gemini-2.5-flash-lite", _TRADUZIR_E_SUAVIZAR),
        Papel.SUAVIZACAO: Recomendacao("google/gemini-2.5-flash-lite", _TRADUZIR_E_SUAVIZAR),
        Papel.VIDEO: Recomendacao("google/gemini-3.8-flash", _VIDEO_BOM_E_BARATO),
        Papel.RESERVA: Recomendacao("google/gemini-2.5-flash-lite", "barato e de contexto longo: aguenta qualquer capítulo se o principal falhar"),
    },
    Nivel.QUALIDADE: {
        Papel.EXTRACAO: Recomendacao("anthropic/claude-haiku-4.5", "o mais cuidadoso nas citações do texto; custa mais, mas é uma chamada por capítulo"),
        Papel.LEITURA: Recomendacao("anthropic/claude-haiku-4.5", "leitura mais atenta; o cache do Anthropic corta cerca de metade do custo"),
        Papel.PROMPT: Recomendacao("google/gemini-3.8-flash", "os melhores prompts de imagem entre os testados"),
        Papel.TRADUCAO: Recomendacao("google/gemini-2.5-flash", "tradução e suavização mais naturais"),
        Papel.SUAVIZACAO: Recomendacao("google/gemini-2.5-flash", "tradução e suavização mais naturais"),
        Papel.VIDEO: Recomendacao("anthropic/claude-sonnet-5.5", "o melhor no prompt de vídeo nos testes"),
        Papel.RESERVA: Recomendacao("google/gemini-3.8-flash", "forte o bastante para assumir qualquer papel se o principal cair"),
    },
}
"""A tabela curada (proposta inicial do item 4.10, LM14)."""
