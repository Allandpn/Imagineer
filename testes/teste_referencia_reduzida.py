"""A imagem enviada como referência vai pequena e compactada (item 7.5b, W4)."""

import io

from PIL import Image as PilImage

from imagineer.servicos.imagens_reduzidas import LADO_DA_REFERENCIA, preparar_referencia


def _salvar(tmp_path, nome: str, imagem: PilImage.Image, formato: str):
    caminho = tmp_path / nome
    imagem.save(caminho, formato)
    return caminho


def teste_w4_reduz_para_o_lado_maior_da_referencia_e_vira_jpeg(tmp_path) -> None:
    grande = PilImage.effect_noise((2000, 3000), 80).convert("RGB")  # ruído: não comprime fácil, como uma foto
    caminho = _salvar(tmp_path, "grande.png", grande, "PNG")

    conteudo, tipo = preparar_referencia(caminho)

    assert tipo == "image/jpeg"
    with PilImage.open(io.BytesIO(conteudo)) as saida:
        assert max(saida.size) == LADO_DA_REFERENCIA
        assert saida.size == (341, 512)  # a proporção 2:3 se mantém
    assert len(conteudo) < caminho.stat().st_size / 10  # e fica muito menor que o original


def teste_w4_nunca_amplia_uma_imagem_pequena(tmp_path) -> None:
    caminho = _salvar(tmp_path, "pequena.png", PilImage.new("RGB", (100, 80), (10, 20, 30)), "PNG")

    conteudo, _ = preparar_referencia(caminho)

    with PilImage.open(io.BytesIO(conteudo)) as saida:
        assert saida.size == (100, 80)


def teste_w4_transparencia_vira_fundo_branco(tmp_path) -> None:
    caminho = _salvar(tmp_path, "transparente.png", PilImage.new("RGBA", (40, 40), (255, 0, 0, 0)), "PNG")

    conteudo, tipo = preparar_referencia(caminho)

    assert tipo == "image/jpeg"
    with PilImage.open(io.BytesIO(conteudo)) as saida:
        assert saida.mode == "RGB"
        r, g, b = saida.getpixel((5, 5))
        assert min(r, g, b) > 240  # branco, não preto


def teste_w4_arquivo_que_o_pillow_nao_le_vai_como_esta(tmp_path) -> None:
    caminho = tmp_path / "estranho.png"
    caminho.write_bytes(b"\x89PNG\r\n\x1a\nnao-e-imagem")

    conteudo, tipo = preparar_referencia(caminho)

    assert conteudo == b"\x89PNG\r\n\x1a\nnao-e-imagem"
    assert tipo == "image/png"


def teste_w4_a_referencia_nao_grava_nada_no_catalogo(tmp_path) -> None:
    caminho = _salvar(tmp_path, "a.png", PilImage.new("RGB", (900, 900), (1, 2, 3)), "PNG")

    preparar_referencia(caminho)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.png"]  # só o original: nada de derivadas
