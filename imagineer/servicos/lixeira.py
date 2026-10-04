"""A lógica da lixeira de imagens, sem HTTP (item 7.5b, LX3 a LX6)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    Frame,
    Imagem,
    Livro,
    Prompt,
    SugestaoDeCena,
    SugestaoDeElemento,
    TipoDeFrame,
)
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


# --------------------------------------------------------------------------- #
# Elementos (LT4)
# --------------------------------------------------------------------------- #


def retratos_do_elemento(sessao: Session, elemento: Elemento) -> list[Frame]:
    """Os retratos do elemento (frames ``PERSONAGEM`` com ele como **único** estado), ativos e na lixeira."""
    ids_dos_estados = {estado.id for estado in elemento.estados}
    if not ids_dos_estados:
        return []
    frames = sessao.scalars(
        select(Frame).where(Frame.tipo == TipoDeFrame.PERSONAGEM).join(Frame.estados_elemento).where(EstadoElemento.id.in_(ids_dos_estados))
    ).unique()
    return [frame for frame in frames if len(frame.estados_elemento) == 1]


def mover_elemento_para_a_lixeira(sessao: Session, elemento: Elemento) -> None:
    """Marca o elemento como apagado (LT4). **As sugestões que o citavam voltam a ser pendentes**, lembrando de qual elemento eram, e
    **os retratos vão junto** (marcados com este elemento, para voltarem juntos). Já estando na lixeira, não faz nada. Quem chama faz
    o ``commit``."""
    if elemento.apagado_em is not None:
        return
    elemento.apagado_em = datetime.now(timezone.utc)
    for sugestao in sessao.scalars(select(SugestaoDeElemento).where(SugestaoDeElemento.elemento_id == elemento.id)):
        sugestao.elemento_antes_id = elemento.id
        sugestao.elemento_id = None
    for frame in retratos_do_elemento(sessao, elemento):
        if frame.apagado_em is None:
            mover_frame_para_a_lixeira(sessao, frame)
            frame.apagado_com_elemento_id = elemento.id


def restaurar_elemento(sessao: Session, elemento: Elemento) -> None:
    """Tira o elemento da lixeira, **religa** as sugestões que continuam sem elemento (e não foram descartadas) e traz de volta os
    retratos que foram com ele."""
    elemento.apagado_em = None
    for sugestao in sessao.scalars(select(SugestaoDeElemento).where(SugestaoDeElemento.elemento_antes_id == elemento.id)):
        if sugestao.elemento_id is None and not sugestao.descartada:
            sugestao.elemento_id = elemento.id
        sugestao.elemento_antes_id = None
    for frame in sessao.scalars(select(Frame).where(Frame.apagado_com_elemento_id == elemento.id)):
        restaurar_frame(sessao, frame)
        frame.apagado_com_elemento_id = None


def retratos_que_foram_com_o_elemento(sessao: Session, elemento: Elemento) -> list[Frame]:
    """Os retratos que foram para a lixeira junto com o elemento."""
    return list(sessao.scalars(select(Frame).where(Frame.apagado_com_elemento_id == elemento.id)))


def imagens_do_elemento(sessao: Session, elemento: Elemento) -> list[Imagem]:
    """As imagens dos retratos que foram com o elemento (o que sai do disco ao apagar de vez)."""
    return [imagem for frame in retratos_que_foram_com_o_elemento(sessao, elemento) for imagem in imagens_do_frame(frame)]


def apagar_elemento_de_vez(sessao: Session, elemento: Elemento) -> int:
    """Remove o elemento, os estados, a identidade e os retratos que foram com ele, **com os arquivos das imagens**. Devolve os bytes
    liberados. Quem chama faz o ``commit``."""
    liberados = sum(apagar_frame_de_vez(sessao, frame) for frame in retratos_que_foram_com_o_elemento(sessao, elemento))
    for sugestao in sessao.scalars(select(SugestaoDeElemento).where(SugestaoDeElemento.elemento_antes_id == elemento.id)):
        sugestao.elemento_antes_id = None
    sessao.delete(elemento)
    sessao.flush()
    return liberados
