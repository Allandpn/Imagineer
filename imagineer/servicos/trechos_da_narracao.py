"""Dividir o texto de um capítulo em trechos para a voz (itens NA2 e NA3).

Quem fala é o provedor de IA (``ProvedorIA.narrar``); aqui só se decide **como cortar** o texto e **quanto tempo** ele leva.
"""

import re

LIMITE_DO_TRECHO = 2500
"""Caracteres por pedido (NA2). O endpoint de fala do OpenRouter repassa o texto a modelos de fornecedores diferentes, e cada um tem o seu
limite de entrada (o menor que se conhece, na família OpenAI, é de 4.096 caracteres). 2.500 fica **bem abaixo** de todos, ao custo de mais
pedidos por capítulo. Não foi medido contra cada modelo: se algum recusar, é aqui que se ajusta."""

CARACTERES_POR_MINUTO = 900
"""Quantos caracteres uma voz de narração fala por minuto (NA3). Medida típica de leitura em português (~150 palavras por minuto);
serve só para **estimar** a duração antes de gerar."""


def dividir_em_trechos(texto: str, limite: int = LIMITE_DO_TRECHO) -> list[str]:
    """Divide o texto em trechos de **até** ``limite`` caracteres, cortando no ponto menos prejudicial para a voz (NA2).

    A ordem de preferência do corte: **fim de parágrafo**; se um parágrafo sozinho passa do limite, **fim de frase**; se uma frase
    passa, o **último espaço** antes do limite (e, sem nenhum espaço, no próprio limite). Parágrafos que cabem juntos ficam no mesmo
    trecho, separados por uma linha em branco (que a voz lê como pausa). Nenhum caractere do texto se perde, e a ordem é mantida.
    """
    paragrafos = [p.strip() for p in re.split(r"\n+", texto) if p.strip()]
    trechos: list[str] = []
    atual = ""

    def fechar() -> None:
        nonlocal atual
        if atual:
            trechos.append(atual)
            atual = ""

    for paragrafo in paragrafos:
        for pedaco in _cortar_o_paragrafo(paragrafo, limite):
            separador = "\n\n" if atual else ""
            if atual and len(atual) + len(separador) + len(pedaco) > limite:
                fechar()
                separador = ""
            atual += separador + pedaco
    fechar()
    return trechos


def _cortar_o_paragrafo(paragrafo: str, limite: int) -> list[str]:
    """Um parágrafo que cabe vai inteiro; um maior é cortado em frases e, se preciso, em palavras."""
    if len(paragrafo) <= limite:
        return [paragrafo]
    pedacos: list[str] = []
    atual = ""
    for frase in re.split(r"(?<=[.!?…])\s+", paragrafo):
        for parte in _cortar_a_frase(frase, limite):
            if atual and len(atual) + 1 + len(parte) > limite:
                pedacos.append(atual)
                atual = parte
            else:
                atual = f"{atual} {parte}" if atual else parte
    if atual:
        pedacos.append(atual)
    return pedacos


def _cortar_a_frase(frase: str, limite: int) -> list[str]:
    """Uma frase que cabe vai inteira; uma maior é cortada no último espaço antes do limite."""
    partes: list[str] = []
    while len(frase) > limite:
        corte = frase.rfind(" ", 0, limite)
        if corte <= 0:
            corte = limite
        partes.append(frase[:corte].strip())
        frase = frase[corte:].strip()
    if frase:
        partes.append(frase)
    return partes


def minutos_estimados(caracteres: int) -> float:
    """A duração estimada da fala, em minutos (NA3)."""
    return caracteres / CARACTERES_POR_MINUTO
