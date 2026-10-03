"""A lógica da lixeira de imagens, sem HTTP (item 7.5b, LX3 a LX6)."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.modelos import Elemento, EstadoElemento, Frame, Imagem
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
