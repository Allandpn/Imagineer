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


# --------------------------------------------------------------------------- #
# Sugestões por item da configuração (item 4.10, SG1 a SG10)
# --------------------------------------------------------------------------- #


class TipoDeCampo(str, enum.Enum):
    """De que catálogo vêm as sugestões de um item."""

    TEXTO = "texto"
    IMAGEM = "imagem"
    VOZ = "voz"


@dataclass(frozen=True)
class CampoDeModelo:
    """Um item da tela de modelos: o campo que se grava, como se chama e de onde vêm as sugestões dele."""

    campo: str
    """O nome em ``PUT /configuracao`` e em ``PUT /livros/{id}/modelos`` (``modelo_leitura``...)."""
    rotulo: str
    descricao: str
    tipo: TipoDeCampo
    papel: Papel | None = None
    """Os sete papéis de texto da tabela ``RECOMENDACOES`` (os mesmos dos níveis): as sugestões saem dela."""
    sugestoes: dict[Nivel, Recomendacao] | None = None
    """Os itens de texto que **não** são papéis de nível (perfil, conferência): têm a própria tabela, e o nível **não** os grava (SG3)."""
    exige_imagem: bool = False
    """O modelo precisa **ler imagens** (a conferência da imagem): o catálogo diz se lê, e a sugestão avisa."""


_PERFIL = (
    "uma chamada por livro: vale pagar mais; os dois mais caros citaram referências de arte coerentes nos testes de 02/10/2026, o barato saiu genérico"
)
_CONFERENCIA = "olha uma imagem e a lista do que devia aparecer; precisa ler imagens"

CAMPOS_DE_MODELO: tuple[CampoDeModelo, ...] = (
    CampoDeModelo("modelo_extracao", "Identificar elementos e cenas", "Lê o capítulo e sugere os elementos e as cenas (a análise do capítulo).", TipoDeCampo.TEXTO, Papel.EXTRACAO),
    CampoDeModelo("modelo_leitura", "Ler cada elemento e cena", "Relê o capítulo para descrever a aparência de cada elemento e o dossiê de cada cena.", TipoDeCampo.TEXTO, Papel.LEITURA),
    CampoDeModelo("modelo_prompt", "Montar o prompt de imagem", "Escreve o prompt de imagem a partir da cena ou do retrato.", TipoDeCampo.TEXTO, Papel.PROMPT),
    CampoDeModelo("modelo_traducao", "Traduzir os prompts", "Traduz o prompt entre inglês e português.", TipoDeCampo.TEXTO, Papel.TRADUCAO),
    CampoDeModelo("modelo_suavizacao", "Suavizar um prompt recusado", "Reescreve só os trechos que o provedor de imagem recusou.", TipoDeCampo.TEXTO, Papel.SUAVIZACAO),
    CampoDeModelo("modelo_video", "Montar o prompt de vídeo", "Escreve o prompt de vídeo de uma cena.", TipoDeCampo.TEXTO, Papel.VIDEO),
    CampoDeModelo("modelo_reserva", "Modelo reserva", "Assume a chamada se o modelo principal falhar.", TipoDeCampo.TEXTO, Papel.RESERVA),
    CampoDeModelo(
        "modelo_perfil",
        "Sugerir o perfil de renderização",
        "Sugere o estilo visual do livro (usa a busca na web).",
        TipoDeCampo.TEXTO,
        sugestoes={
            Nivel.ECONOMICO: Recomendacao("openai/gpt-4o-mini", "o mais barato; a sugestão tende a sair genérica"),
            Nivel.EQUILIBRADO: Recomendacao("google/gemini-2.5-flash", _PERFIL),
            Nivel.QUALIDADE: Recomendacao("anthropic/claude-haiku-4.5", "testado em 02/10/2026: sugestões com referências de arte coerentes nas três categorias"),
        },
    ),
    CampoDeModelo(
        "modelo_conferencia",
        "Conferir a imagem gerada",
        "Compara a imagem com a lista do que devia aparecer na cena.",
        TipoDeCampo.TEXTO,
        sugestoes={
            Nivel.ECONOMICO: Recomendacao("google/gemini-2.5-flash-lite", _CONFERENCIA + "; o mais barato"),
            Nivel.EQUILIBRADO: Recomendacao("google/gemini-2.5-flash", _CONFERENCIA + "; mais atento aos detalhes"),
            Nivel.QUALIDADE: Recomendacao("anthropic/claude-haiku-4.5", _CONFERENCIA + "; o mais cuidadoso dos três"),
        },
        exige_imagem=True,
    ),
    CampoDeModelo("modelo_imagem", "Gerar a imagem", "O modelo que desenha a imagem a partir do prompt.", TipoDeCampo.IMAGEM),
    CampoDeModelo("modelo_narracao", "Narrar com voz de IA", "O modelo de voz que fala o capítulo.", TipoDeCampo.VOZ),
)
"""Os itens da tela de modelos, **na ordem da tela** (SG1). Cada um vira uma linha com o botão **Sugeridos**."""
