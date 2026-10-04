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
        "Cinematic film still. Photographic lens characteristics, shallow depth of field, visible film grain, "
        "naturalistic skin and fabric texture, color grading typical of a feature film — never painterly brushwork, "
        "never a digital illustration look, no signature, no text."
    ),
    CategoriaEstilo.PINTURA_A_OLEO: (
        "Classical oil painting. Impasto technique, thick and visibly textured brushstrokes with raised paint relief, "
        "painted on linen canvas, traditional academic painting technique — never a smooth digital-painting look, "
        "never photographic, no signature, no text."
    ),
    CategoriaEstilo.AQUARELA: (
        "Watercolor painting. Loose flowing brushstrokes, visible paper texture, soft bleeding edges where pigment "
        "diffuses into wet paper, areas of transparent color letting the white paper show through, no hard outlines — "
        "never crisp vector-like edges, never opaque coverage, no signature, no text."
    ),
    CategoriaEstilo.ARTE_DIGITAL_CONCEITUAL: (
        "Digital concept art for games and film. Clean digital painting technique, dramatic directional lighting, "
        "confident visible digital brushwork — no canvas texture, no film grain, no traditional media texture, "
        "no signature, no text."
    ),
    CategoriaEstilo.QUADRINHOS: (
        "Comic book / graphic novel illustration. Bold consistent black ink outlines, flat or halftone-screened color "
        "fills, graphic novel line-art aesthetic — never photorealistic, never painterly blending, no signature, no text."
    ),
    CategoriaEstilo.CARTOON_ANIMACAO: (
        "Cartoon animation style. Simplified geometric shapes, bold vivid saturated colors, clean flat shading typical "
        "of animated productions — never photorealistic, never traditional painting texture, no signature, no text."
    ),
    CategoriaEstilo.ANIME: (
        "Japanese anime illustration. Thin precise ink outlines, cel-shading with hard-edged flat shadow shapes (no soft "
        "gradients), large expressive stylized eyes, simplified stylized facial features, vibrant saturated color "
        "palette, stylized hair rendered in defined flowing strands with sharp highlight shapes — never realistic skin "
        "texture, never photographic, never film grain, no signature, no text."
    ),
    CategoriaEstilo.PIXEL_ART: (
        "Pixel art, retro video game aesthetic. Deliberately visible pixel grid, no anti-aliasing or smoothing, a "
        "restricted limited color palette (16 to 32 colors), dithering patterns used to simulate gradients and shading "
        "instead of smooth blending, low native resolution rendered at a crisp scale — never smooth gradients, never "
        "high-resolution detail, never soft edges, no signature, no text."
    ),
    CategoriaEstilo.GRAVURA_CLASSICA: (
        "Classical engraving / woodcut illustration, in the style of 19th-century book frontispieces. Ink linework "
        "built from cross-hatching and fine parallel lines to render shadow and volume, monochrome or sepia tone on aged "
        "paper, no flat color fills, no painterly brushwork — never color, never soft shading, never photographic, "
        "no signature, no text."
    ),
    CategoriaEstilo.ANIMACAO_3D: (
        "3D animated feature film still, stylized CGI. Smooth sculpted shapes with slightly exaggerated proportions, "
        "large expressive eyes, soft subsurface-scattered skin, detailed fabric and hair simulation, global "
        "illumination with rich saturated color and shallow depth of field — never photographic, never flat 2D, never "
        "painterly brushwork, no signature, no text."
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
