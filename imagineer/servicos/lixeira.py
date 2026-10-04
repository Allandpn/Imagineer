"""A lógica da lixeira de imagens, sem HTTP (item 7.5b, LX3 a LX6)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.modelos import Capitulo, Elemento, EstadoElemento, Frame, Imagem, Livro, Prompt, SugestaoDeCena
from imagineer.servicos.catalogo_imagens import caminho_absoluto, remover_arquivo
from imagineer.servicos.imagens_reduzidas import remover_derivadas


def mover_para_a_lixeira(sessao: Session, imagem: Imagem) -> None:
    """Marca a imagem como apagada e **solta** as escolhas que apontavam para ela (LX4).

    Já estando na lixeira, não faz nada. Quem chama faz o ``commit``.
    """
    if imagem.apagada_em is not None:
        return
    imagem.apagada_em = datetime.now(timezone.utc)
    # A canônica do frame, a âncora do estado e a âncora padrão do elemento voltam a "sem escolha".
    for frame in sessao.scalars(select(Frame).where(Frame.imagem_canonica_id == imagem.id)):
        frame.imagem_canonica_id = None
    for estado in sessao.scalars(select(EstadoElemento).where(EstadoElemento.imagem_ancora_id == imagem.id)):
        estado.imagem_ancora_id = None
    for elemento in sessao.scalars(select(Elemento).where(Elemento.imagem_ancora_padrao_id == imagem.id)):
        elemento.imagem_ancora_padrao_id = None


def tamanho_da_imagem(imagem: Imagem) -> int:
    """O espaço da imagem: o gravado ou, se faltar, o do arquivo no disco."""
    if imagem.tamanho_em_bytes is not None:
        return imagem.tamanho_em_bytes
    arquivo = caminho_absoluto(imagem.caminho_arquivo)
    return arquivo.stat().st_size if arquivo.is_file() else 0


def apagar_de_vez(sessao: Session, imagem: Imagem) -> int:
    """Apaga a linha, o arquivo e as versões reduzidas. Devolve os bytes liberados. Quem chama faz o ``commit``."""
    liberados = tamanho_da_imagem(imagem)
    caminho, imagem_id = imagem.caminho_arquivo, imagem.id
    sessao.delete(imagem)
    sessao.flush()
    remover_derivadas(imagem_id)
    remover_arquivo(caminho)
    return liberados


# --------------------------------------------------------------------------- #
# Livros (LT2)
# --------------------------------------------------------------------------- #


def imagens_do_livro(sessao: Session, livro_id: int) -> list[Imagem]:
    """Todas as imagens do livro (ativas e as que já estavam na lixeira de imagens): o que ocupa disco por causa dele."""
    return list(
        sessao.scalars(
            select(Imagem)
            .join(Prompt, Prompt.id == Imagem.prompt_id)
            .join(Frame, Frame.id == Prompt.frame_id)
            .join(Capitulo, Capitulo.id == Frame.capitulo_id)
            .where(Capitulo.livro_id == livro_id)
        )
    )


def apagar_livro_de_vez(sessao: Session, livro: Livro) -> int:
    """Remove o livro e **antes** os arquivos das imagens dele (o disco não guarda arquivo sem dono). Devolve os bytes liberados.

    Capítulos, elementos, estados, frames e prompts saem em cascata com o livro. Quem chama faz o ``commit``.
    """
    liberados = sum(apagar_de_vez(sessao, imagem) for imagem in imagens_do_livro(sessao, livro.id))
    sessao.delete(livro)
    sessao.flush()
    return liberados


# --------------------------------------------------------------------------- #
# Frames: cenas e retratos (LT3)
# --------------------------------------------------------------------------- #


def mover_frame_para_a_lixeira(sessao: Session, frame: Frame) -> None:
    """Marca o frame como apagado. A cena sugerida que ele confirmara **volta a ser pendente** (``frame_id`` nulo), e o frame guarda
    de qual era, para restaurar religar. Já estando na lixeira, não faz nada. Quem chama faz o ``commit``."""
    if frame.apagado_em is not None:
        return
    frame.apagado_em = datetime.now(timezone.utc)
    sugestao = sessao.scalar(select(SugestaoDeCena).where(SugestaoDeCena.frame_id == frame.id))
    if sugestao is not None:
        frame.sugestao_de_cena_antes_id = sugestao.id
        sugestao.frame_id = None


def restaurar_frame(sessao: Session, frame: Frame) -> None:
    """Tira o frame da lixeira e, se a cena sugerida de antes ainda existe e **continua sem frame**, a religa a ele."""
    frame.apagado_em = None
    if frame.sugestao_de_cena_antes_id is not None:
        sugestao = sessao.get(SugestaoDeCena, frame.sugestao_de_cena_antes_id)
        if sugestao is not None and sugestao.frame_id is None and sugestao.capitulo_id == frame.capitulo_id:
            sugestao.frame_id = frame.id
        frame.sugestao_de_cena_antes_id = None


def imagens_do_frame(frame: Frame) -> list[Imagem]:
    """Todas as imagens do frame (ativas e as que já estavam na lixeira de imagens)."""
    return [imagem for prompt in frame.prompts for imagem in prompt.imagens]


def apagar_frame_de_vez(sessao: Session, frame: Frame) -> int:
    """Remove o frame, os prompts e as imagens dele, **com os arquivos**. Devolve os bytes liberados. Quem chama faz o ``commit``."""
    liberados = sum(apagar_de_vez(sessao, imagem) for imagem in imagens_do_frame(frame))
    sessao.delete(frame)
    sessao.flush()
    return liberados

