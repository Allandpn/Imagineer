"""O bloco técnico fixo de cada categoria de estilo (BT3, BT4 — item 4.5 da especificação).

**Por que existe.** O estilo de um perfil é um texto livre, escrito por IA ou à mão, e vai para o prompt **traduzido
literalmente**. Um texto genérico ("pintura a óleo", "ethereal brushwork") dá imagem genérica nos modelos que não reescrevem o
prompt do usuário (testado em 04/10/2026 no Gemini: pintura digital chapada). O bloco abaixo é **a técnica concreta**, escrita
por nós e **colada ao fim do prompt por código**, depois da resposta da IA: ela nunca o vê nem o reescreve, então não há o que
parafrasear ou perder.

**Os textos são em inglês** (é o que vai ao modelo de imagem) e são **conteúdo**, não nomes de código. Todos seguem o mesmo
molde, validado nos testes: frases de técnica, textura e luz (nunca adjetivo vazio), o que o estilo **nunca** é e, no fim,
``no signature, no text`` (sem isso, o Gemini assinou um quadro). **Nenhum cita estúdio ou artista**: o nome pode viciar o
resultado ou ser recusado; a técnica basta.
"""

from imagineer.modelos import CategoriaEstilo

POSICAO_DO_BLOCO = "fim"
"""Onde o bloco entra no prompt. ``"fim"`` por decisão de 04/10/2026: no começo o Gemini pintou melhor, mas inventou um bastão,
trocou a roupa e assinou a tela — o Imagineer quer fidelidade à cena do livro. Mudar para ``"inicio"`` é só trocar esta constante."""

BLOCO_TECNICO_POR_CATEGORIA: dict[CategoriaEstilo, str] = {
    CategoriaEstilo.FOTORREALISTA_CINEMATOGRAFICO: (
        "Cinematic film still, shot on a professional cinema camera. Photographic lens characteristics, shallow depth of "
        "field with natural bokeh, visible fine film grain, naturalistic skin pores and fabric weave, motivated "
        "directional light with realistic falloff and soft contrast, subtle atmospheric haze, anamorphic framing, "
        "restrained filmic color grading typical of a feature film — never painterly brushwork, never a digital "
        "illustration look, never plastic skin, no signature, no text."
    ),
    CategoriaEstilo.PINTURA_A_OLEO: (
        "Classical oil painting on linen canvas. Impasto technique with thick, visibly textured brushstrokes and raised "
        "paint relief that catches the light, visible canvas weave in the thinner areas, rich layered glazes, soft "
        "chiaroscuro modeling of form, warm earthy pigments, subtly craquelured aged varnish, traditional academic "
        "painting technique — never a smooth digital-painting look, never airbrushed gradients, never photographic, "
        "no signature, no text."
    ),
    CategoriaEstilo.AQUARELA: (
        "Watercolor painting on cold-pressed paper. Loose flowing brushstrokes, visible paper grain, soft bleeding "
        "edges where pigment diffuses into wet paper, granulating pigment, light transparent washes layered wet-on-wet, "
        "areas of untouched white paper left as highlights, delicate pencil underdrawing barely visible, no hard "
        "outlines — never crisp vector-like edges, never opaque coverage, never digital gradients, no signature, "
        "no text."
    ),
    CategoriaEstilo.ARTE_DIGITAL_CONCEITUAL: (
        "Digital concept art for games and film. Polished digital painting technique with confident visible brushwork, "
        "dramatic directional lighting with a strong focal point, atmospheric perspective and depth layers, cinematic "
        "composition with a clear silhouette read, rich color harmony, selective crisp detail against softer "
        "backgrounds — no canvas texture, no film grain, no traditional media texture, no signature, no text."
    ),
    CategoriaEstilo.QUADRINHOS: (
        "Comic book / graphic novel illustration. Bold consistent black ink outlines with varied line weight, dynamic "
        "panel-like composition, flat or halftone-screened color fills, hatching for shadow, strong spotted blacks, "
        "limited but punchy color palette, graphic novel line-art aesthetic — never photorealistic, never painterly "
        "blending, never soft airbrushed gradients, no signature, no text."
    ),
    CategoriaEstilo.CARTOON_ANIMACAO: (
        "Cartoon animation style, 2D animated production. Simplified geometric shapes, bold clean outlines, bold vivid "
        "saturated colors, clean flat shading with minimal highlight shapes, exaggerated expressive poses and "
        "proportions, simple painted backgrounds with clear color separation from the characters — never "
        "photorealistic, never traditional painting texture, never complex rendering, no signature, no text."
    ),
    CategoriaEstilo.ANIME: (
        "Japanese anime illustration, high-quality animated film look. Thin precise ink outlines, cel-shading with "
        "hard-edged flat shadow shapes (no soft gradients), large expressive stylized eyes with detailed highlights, "
        "simplified stylized facial features, vibrant saturated color palette, stylized hair rendered in defined "
        "flowing strands with sharp highlight shapes, detailed painted background with luminous skies and soft "
        "light bloom — never realistic skin texture, never photographic, never film grain, no signature, no text."
    ),
    CategoriaEstilo.PIXEL_ART: (
        "Pixel art, retro 16-bit video game aesthetic. Deliberately visible pixel grid, no anti-aliasing or "
        "smoothing, a restricted limited color palette (16 to 32 colors), dithering patterns used to simulate gradients "
        "and shading instead of smooth blending, one-pixel dark outlines, hand-placed pixel clusters, low native "
        "resolution rendered at a crisp integer scale — never smooth gradients, never high-resolution detail, never "
        "soft edges, never blur, no signature, no text."
    ),
    CategoriaEstilo.GRAVURA_CLASSICA: (
        "Classical engraving / woodcut illustration, in the style of 19th-century book frontispieces. Ink linework "
        "built from cross-hatching and fine parallel lines to render shadow and volume, line weight that swells and "
        "thins, monochrome or sepia tone on aged cream paper with subtle foxing, framed composition with a thin border, "
        "dense detailed texture, no flat color fills, no painterly brushwork — never color, never soft shading, never "
        "photographic, no signature, no text."
    ),
    CategoriaEstilo.ANIMACAO_3D: (
        "3D animated feature film still, stylized CGI. Smooth sculpted shapes with slightly exaggerated proportions, "
        "large expressive eyes, soft subsurface-scattered skin, detailed fabric and hair simulation, global "
        "illumination with soft shadows and rim light, rich saturated color, shallow depth of field, polished "
        "family-film production design — never photographic, never flat 2D, never painterly brushwork, "
        "no signature, no text."
    ),
}


def com_bloco_tecnico(texto: str, categoria: CategoriaEstilo | None) -> str:
    """O ``texto`` do prompt com o bloco técnico da ``categoria`` colado (ao fim, ou no começo se ``POSICAO_DO_BLOCO`` mudar).

    Sem categoria, devolve o texto como veio: um perfil sem categoria funciona exatamente como antes.
    """
    if categoria is None:
        return texto
    bloco = BLOCO_TECNICO_POR_CATEGORIA[categoria]
    if bloco in texto:  # já está (a pessoa refez a partir de um prompt que o tinha): não repete
        return texto
    return f"{bloco} {texto}" if POSICAO_DO_BLOCO == "inicio" else f"{texto} {bloco}"
