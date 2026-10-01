"""Dimensões e versões reduzidas das imagens do catálogo (item 6.9, "Tamanhos de imagem e dimensões").

Duas coisas, ambas com a biblioteca Pillow:

- **Dimensões** (``largura`` x ``altura``): o app decide o layout da imagem no texto por elas, porque a
  ferramenta de imagem externa nem sempre respeita o formato pedido no prompt (item 7.5b, I1).
- **Versões reduzidas** (``miniatura`` e ``leitura``): a imagem aparece em vários lugares e pesa até
  ~2 MB; carregar o original para um ícone desperdiça a rede do tablet.

**Nada aqui levanta erro por causa de um arquivo estranho.** Um arquivo que o Pillow não lê (corrompido,
ou um "PNG" que não é) continua sendo aceito na importação, sem dimensões e sem versão reduzida: o
catálogo nunca recusou isso, e recusar agora quebraria quem já usa.
"""

import enum
import io
from pathlib import Path

from PIL import Image as PilImage
from PIL import UnidentifiedImageError

from imagineer.configuracao import obter_configuracoes
from imagineer.modelos import Imagem


class TamanhoDeImagem(str, enum.Enum):
    """Os tamanhos que ``GET /imagens/{id}/arquivo?tamanho=`` aceita. **Nomeados e em número fixo**: uma
    largura livre deixaria qualquer cliente gerar versões sem limite e encher o disco."""

    MINIATURA = "miniatura"
    LEITURA = "leitura"
    ORIGINAL = "original"


LADO_MAIOR_EM_PIXELS = {TamanhoDeImagem.MINIATURA: 256, TamanhoDeImagem.LEITURA: 1280}
"""O lado maior de cada versão reduzida. O ``original`` não aparece: é o arquivo como veio."""

QUALIDADE_DO_JPEG = 85


class Orientacao(str, enum.Enum):
    RETRATO = "RETRATO"
    PAISAGEM = "PAISAGEM"


def orientacao_de(largura: int | None, altura: int | None) -> Orientacao | None:
    """``RETRATO`` se a altura é maior que a largura; ``PAISAGEM`` no resto (a quadrada inclusive); nulo sem dimensões."""
    if not largura or not altura:
        return None
    return Orientacao.RETRATO if altura > largura else Orientacao.PAISAGEM


def ler_dimensoes(origem: bytes | Path) -> tuple[int, int] | None:
    """``(largura, altura)`` em pixels, ou ``None`` se o Pillow não consegue ler o arquivo."""
    try:
        with PilImage.open(io.BytesIO(origem) if isinstance(origem, bytes) else origem) as imagem:
            return imagem.size
    except (UnidentifiedImageError, OSError, ValueError, PilImage.DecompressionBombError):
        return None


def garantir_dimensoes(imagem: Imagem, caminho: Path) -> bool:
    """Preenche ``largura``/``altura`` de uma imagem antiga a partir do arquivo. ``True`` se mudou algo.

    Não faz commit: quem chama decide (as leituras que usam isto já gravam o que calcularam). Não sobe a
    ``revisao`` do livro (``banco/revisao.py``). Sem arquivo ou ilegível, deixa nulo.
    """
    if imagem.largura is not None and imagem.altura is not None:
        return False
    if not caminho.is_file():
        return False
    dimensoes = ler_dimensoes(caminho)
    if dimensoes is None:
        return False
    imagem.largura, imagem.altura = dimensoes
    return True


def _caminho_da_derivada(imagem_id: int, tamanho: TamanhoDeImagem) -> Path:
    return Path(obter_configuracoes().diretorio_imagens) / "derivadas" / tamanho.value / f"{imagem_id}.jpg"


def arquivo_no_tamanho(imagem_id: int, original: Path, tamanho: TamanhoDeImagem) -> tuple[Path, str | None]:
    """O arquivo a servir para o tamanho pedido: ``(caminho, tipo_de_midia)``.

    ``tipo_de_midia`` é ``None`` quando é o **original** (quem chama descobre o tipo pelo nome do arquivo).
    Devolve o original quando o tamanho é ``original``, quando a imagem **já cabe** no tamanho pedido
    (ampliar só engordaria o arquivo e pioraria a imagem) ou quando o Pillow não consegue lê-la. A versão
    reduzida é gerada **na primeira vez** e guardada em ``derivadas/<tamanho>/<id>.jpg``.
    """
    if tamanho is TamanhoDeImagem.ORIGINAL:
        return original, None

    alvo = _caminho_da_derivada(imagem_id, tamanho)
    if alvo.is_file():
        return alvo, "image/jpeg"

    limite = LADO_MAIOR_EM_PIXELS[tamanho]
    try:
        with PilImage.open(original) as imagem:
            if max(imagem.size) <= limite:
                return original, None
            imagem.thumbnail((limite, limite), PilImage.Resampling.LANCZOS)  # mantém a proporção
            if imagem.mode in ("RGBA", "LA", "P"):
                imagem = imagem.convert("RGBA")
                fundo = PilImage.new("RGB", imagem.size, (255, 255, 255))  # transparência vira branco
                fundo.paste(imagem, mask=imagem.getchannel("A"))
                imagem = fundo
            elif imagem.mode != "RGB":
                imagem = imagem.convert("RGB")
            alvo.parent.mkdir(parents=True, exist_ok=True)
            imagem.save(alvo, "JPEG", quality=QUALIDADE_DO_JPEG, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, PilImage.DecompressionBombError):
        return original, None
    return alvo, "image/jpeg"


def remover_derivadas(imagem_id: int) -> None:
    """Apaga as versões reduzidas de uma imagem (sem reclamar se não existem)."""
    for tamanho in LADO_MAIOR_EM_PIXELS:
        _caminho_da_derivada(imagem_id, tamanho).unlink(missing_ok=True)
