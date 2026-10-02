"""Procura sinal de que um prompt fala de um menor de idade (F15).

Serve de trava da geração **sem o filtro de segurança**: com o filtro desligado, o sistema recusa o pedido se o prompt
traz sinal de menor. É uma lista de palavras, em inglês e em português, mais uma idade abaixo de 18 anos. **Não pega
tudo** (um livro pode chamar uma criança só pelo nome), e por isso o app avisa o usuário na tela; mas pega o que o próprio
prompt diz. Uma idade de adulto ("young woman", 21 anos) não dispara.
"""

import re

_PALAVRAS = (
    # inglês
    "child", "children", "kid", "kids", "girl", "girls", "boy", "boys", "teen", "teens", "teenager",
    "teenagers", "teenage", "preteen", "minor", "minors", "underage", "infant", "baby", "toddler",
    "schoolgirl", "schoolboy", "youth", "juvenile", "lolita",
    # português
    "crian[çc]as?", "menin[oa]s?", "garotinh[oa]s?", "adolescentes?", "beb[êe]s?", "pr[ée]-adolescentes?",
    r"menor(?:es)?\s+de\s+idade", "infantil", "juvenil",
)
_RE_PALAVRAS = re.compile(r"\b(?:" + "|".join(_PALAVRAS) + r")\b", re.IGNORECASE)
_RE_IDADE = re.compile(r"\b(\d{1,2})[\s-]*(?:years?[\s-]*old|yo|anos)\b", re.IGNORECASE)


def sinal_de_menor(texto: str) -> str | None:
    """Devolve o trecho que indica menor de idade, ou ``None`` se não há sinal."""
    achado = _RE_PALAVRAS.search(texto)
    if achado:
        return achado.group(0)
    for idade in _RE_IDADE.finditer(texto):
        if int(idade.group(1)) < 18:
            return idade.group(0)
    return None
