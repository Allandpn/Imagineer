"""Converte o áudio **PCM cru** de alguns modelos de voz (o Gemini TTS, por exemplo) em MP3 (pendência PD14, 13/10/2026).

Esses modelos só sabem entregar PCM: amostras de 16 bits, com sinal, mono, a 24 kHz, sem cabeçalho nenhum. Um app não toca isso, e em WAV um
capítulo ocuparia umas dez vezes mais disco (no Raspberry Pi) do que em MP3. Por isso o servidor converte **cada trecho** para MP3 logo que
o recebe: o resto do sistema (juntar os trechos, guardar, servir com ``Range``) continua tratando só MP3, como sempre.
"""

import lameenc

TAXA_DO_PCM = 24_000
"""Amostras por segundo do PCM que o OpenRouter entrega (24 kHz, 16 bits, mono, little-endian)."""

KBPS_DA_FALA = 64
"""Taxa do MP3 de saída. Para voz falada em mono, 64 kbps soa limpo e dá cerca de 0,5 MB por minuto."""


def pcm_para_mp3(pcm: bytes, taxa: int = TAXA_DO_PCM) -> bytes:
    """Codifica [pcm] (16 bits, mono) como um MP3 completo. Cada chamada gera um MP3 **independente**, que se pode juntar a outros em ordem."""
    codificador = lameenc.Encoder()
    codificador.set_bit_rate(KBPS_DA_FALA)
    codificador.set_in_sample_rate(taxa)
    codificador.set_channels(1)
    codificador.set_quality(5)  # 2 = melhor e lento, 7 = rápido; 5 é o meio-termo para voz
    return bytes(codificador.encode(pcm)) + bytes(codificador.flush())
