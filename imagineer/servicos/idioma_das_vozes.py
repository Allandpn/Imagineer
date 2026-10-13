"""Quais modelos de voz falam português (pendência PD12, 13/10/2026).

O catálogo de vozes do OpenRouter **não informa o idioma** de cada modelo. Sem isso, a pessoa escolhe um modelo, gera um capítulo inteiro (e
paga) e só ouve, no fim, que ele lê português com sotaque de inglês. Este módulo responde com o que **se sabe**:

1. **As vozes dizem.** Se alguma voz do modelo é de português (``pt-BR-Luana:...``), o modelo fala português: é um dado do próprio catálogo.
2. **Uma tabela curada à mão** para os modelos conhecidos, por prefixo do id.
3. **Senão, ``None``** ("idioma não informado"): nunca um palpite. A resposta é um **aviso** para a tela, não bloqueia nenhuma escolha.
"""

PREFIXOS_QUE_FALAM_PORTUGUES = (
    "google/gemini",  # Gemini TTS: multilíngue, inclui português
    "openai/gpt-4o-mini-tts",  # multilíngue
    "microsoft/mai-voice",  # tem vozes pt-BR (também aparecem nas vozes do catálogo)
)
"""Modelos que a documentação do fornecedor diz que falam português."""

PREFIXOS_SO_EM_INGLES = (
    "canopylabs/orpheus",  # Orpheus 3B: o modelo do catálogo é o de inglês
)
"""Modelos que só falam inglês: lerem português com eles dá um sotaque que a pessoa não quer descobrir só depois de pagar."""


def _voz_de_portugues(voz: str) -> bool:
    """``pt-BR-Luana:MAI-Voice-2.1-Flash``, ``pt_br_...``, ``Portuguese``: o id da voz carrega o idioma."""
    texto = voz.lower().replace("_", "-")
    return texto.startswith("pt-") or "portugu" in texto


def fala_portugues(modelo_id: str, vozes: list[str]) -> bool | None:
    """``True`` fala português, ``False`` só fala inglês, ``None`` não se sabe (nunca um palpite)."""
    if any(_voz_de_portugues(voz) for voz in vozes):
        return True
    identificador = modelo_id.lower()
    if identificador.startswith(PREFIXOS_QUE_FALAM_PORTUGUES):
        return True
    if identificador.startswith(PREFIXOS_SO_EM_INGLES):
        return False
    return None
