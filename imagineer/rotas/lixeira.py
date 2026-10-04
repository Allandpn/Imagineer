"""A lixeira de imagens (item 7.5b, LX1 a LX10).

Apagar uma imagem só a **marca** (``apagada_em``); o arquivo fica no disco até o usuário **apagar de vez**. Nada some por tempo
(LX6). Prompts, frames, elementos e livros ainda são removidos de vez (LX2).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.lixeira import ElementoNaLixeira, ElementosDaLixeira, FrameNaLixeira, FramesDaLixeira, ImagemNaLixeira, LivroNaLixeira, LivrosDaLixeira, Lixeira, LixeiraEsvaziada
from imagineer.modelos import Capitulo, Elemento, Frame, Imagem, Livro, TipoDeFrame
from imagineer.servicos.imagens_reduzidas import orientacao_de
from imagineer.servicos.lixeira import (
    apagar_de_vez,
    apagar_elemento_de_vez,
    apagar_frame_de_vez,
    apagar_livro_de_vez,
    imagens_do_elemento,
    imagens_do_frame,
    imagens_do_livro,
    restaurar_elemento,
    restaurar_frame,
    retratos_que_foram_com_o_elemento,
    tamanho_da_imagem,
)

rotas = APIRouter(prefix="/lixeira", tags=["Lixeira"])


def _na_lixeira(sessao: Session, imagem_id: int) -> Imagem:
    """A imagem, desde que esteja na lixeira; senão 404 (LX5)."""
    imagem = sessao.get(Imagem, imagem_id)
    if imagem is None or imagem.apagada_em is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Não há imagem com id {imagem_id} na lixeira.")
    return imagem


def _descrever(imagem: Imagem) -> ImagemNaLixeira:
    frame = imagem.prompt.frame
    capitulo = frame.capitulo
    elemento = frame.estados_elemento[0].elemento if frame.tipo == TipoDeFrame.PERSONAGEM and frame.estados_elemento else None
    orientacao = orientacao_de(imagem.largura, imagem.altura)
    return ImagemNaLixeira(
        id=imagem.id,
        prompt_id=imagem.prompt_id,
        frame_id=frame.id,
        frame_titulo=frame.titulo,
        frame_tipo=frame.tipo.name,
        nome_do_elemento=elemento.nome if elemento is not None else None,
        capitulo_id=capitulo.id,
        titulo_do_capitulo=capitulo.titulo,
        ordem_do_capitulo=capitulo.ordem,
        livro_id=capitulo.livro_id,
        titulo_do_livro=capitulo.livro.titulo,
        largura=imagem.largura,
        altura=imagem.altura,
        orientacao=orientacao.value if orientacao else None,
        modelo=imagem.modelo,
        origem=imagem.origem.value,
        sem_filtro_de_seguranca=imagem.sem_filtro_de_seguranca,
        tamanho_em_bytes=imagem.tamanho_em_bytes,
        apagada_em=imagem.apagada_em,
    )


@rotas.get("/imagens", response_model=Lixeira, summary="As imagens da lixeira")
def listar_a_lixeira(sessao: Session = Depends(obter_sessao)) -> Lixeira:
    """Da apagada mais recentemente para a mais antiga, com o livro, o capítulo e o frame de cada uma (LX5)."""
    imagens = list(sessao.scalars(select(Imagem).where(Imagem.apagada_em.is_not(None)).order_by(Imagem.apagada_em.desc(), Imagem.id.desc())))
    return Lixeira(imagens=[_descrever(i) for i in imagens], total_em_bytes=sum(tamanho_da_imagem(i) for i in imagens))


@rotas.post("/imagens/{imagem_id}/restaurar", response_model=ImagemNaLixeira, summary="Tira a imagem da lixeira")
def restaurar(imagem_id: int, sessao: Session = Depends(obter_sessao)) -> ImagemNaLixeira:
    """A imagem volta ao prompt, ao capítulo e à galeria. A canônica e as âncoras que ela tinha **não** voltam (LX4)."""
    imagem = _na_lixeira(sessao, imagem_id)
    descricao = _descrever(imagem).model_copy(update={"apagada_em": imagem.apagada_em})
    imagem.apagada_em = None
    sessao.commit()
    return descricao


@rotas.delete("/imagens/{imagem_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga de vez uma imagem da lixeira")
def apagar_a_imagem_de_vez(imagem_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga a linha e o arquivo do disco. **Não tem volta.**"""
    apagar_de_vez(sessao, _na_lixeira(sessao, imagem_id))
    sessao.commit()


@rotas.delete("/imagens", response_model=LixeiraEsvaziada, summary="Esvazia a lixeira")
def esvaziar(sessao: Session = Depends(obter_sessao)) -> LixeiraEsvaziada:
    """Apaga de vez **tudo** o que está na lixeira (LX5). Nada disso roda sozinho (LX6)."""
    imagens = list(sessao.scalars(select(Imagem).where(Imagem.apagada_em.is_not(None))))
    liberados = sum(apagar_de_vez(sessao, imagem) for imagem in imagens)
    sessao.commit()
    return LixeiraEsvaziada(removidas=len(imagens), liberados_em_bytes=liberados)


# --------------------------------------------------------------------------- #
# Livros (LT2)
# --------------------------------------------------------------------------- #


def _livro_na_lixeira(sessao: Session, livro_id: int) -> Livro:
    """O livro, desde que esteja na lixeira; senão 404 (LT1)."""
    livro = sessao.get(Livro, livro_id)
    if livro is None or livro.apagado_em is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Não há livro com id {livro_id} na lixeira.")
    return livro


def _descrever_livro(sessao: Session, livro: Livro) -> LivroNaLixeira:
    imagens = imagens_do_livro(sessao, livro.id)
    return LivroNaLixeira(
        id=livro.id,
        titulo=livro.titulo,
        autor=livro.autor,
        apagado_em=livro.apagado_em,
        total_de_capitulos=sessao.query(Capitulo).filter(Capitulo.livro_id == livro.id).count(),
        total_de_imagens=len(imagens),
        tamanho_das_imagens_em_bytes=sum(tamanho_da_imagem(i) for i in imagens),
        tem_capa=livro.capa_tipo is not None,
    )


@rotas.get("/livros", response_model=LivrosDaLixeira, summary="Os livros da lixeira")
def listar_livros_da_lixeira(sessao: Session = Depends(obter_sessao)) -> LivrosDaLixeira:
    """Do apagado mais recentemente para o mais antigo, com o que cada um leva junto (LT2)."""
    livros = list(sessao.scalars(select(Livro).where(Livro.apagado_em.is_not(None)).order_by(Livro.apagado_em.desc(), Livro.id.desc())))
    descritos = [_descrever_livro(sessao, livro) for livro in livros]
    return LivrosDaLixeira(livros=descritos, total_em_bytes=sum(d.tamanho_das_imagens_em_bytes for d in descritos))


@rotas.post("/livros/{livro_id}/restaurar", response_model=LivroNaLixeira, summary="Tira o livro da lixeira")
def restaurar_livro(livro_id: int, sessao: Session = Depends(obter_sessao)) -> LivroNaLixeira:
    """O livro volta à biblioteca **inteiro**, com capítulos, elementos, cenas e imagens (nada foi apagado)."""
    livro = _livro_na_lixeira(sessao, livro_id)
    descricao = _descrever_livro(sessao, livro)
    livro.apagado_em = None
    sessao.commit()
    return descricao


@rotas.delete("/livros/{livro_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga de vez um livro da lixeira")
def apagar_o_livro_de_vez(livro_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Remove o livro, tudo o que depende dele e os arquivos das imagens. **Não tem volta.**"""
    apagar_livro_de_vez(sessao, _livro_na_lixeira(sessao, livro_id))
    sessao.commit()


@rotas.delete("/livros", response_model=LixeiraEsvaziada, summary="Esvazia a lixeira de livros")
def esvaziar_livros(sessao: Session = Depends(obter_sessao)) -> LixeiraEsvaziada:
    """Apaga de vez **todos** os livros da lixeira. Nada disso roda sozinho (LX6)."""
    livros = list(sessao.scalars(select(Livro).where(Livro.apagado_em.is_not(None))))
    liberados = sum(apagar_livro_de_vez(sessao, livro) for livro in livros)
    sessao.commit()
    return LixeiraEsvaziada(removidas=len(livros), liberados_em_bytes=liberados)


# --------------------------------------------------------------------------- #
# Frames: cenas e retratos (LT3)
# --------------------------------------------------------------------------- #


def _frame_na_lixeira(sessao: Session, frame_id: int) -> Frame:
    """O frame, desde que esteja na lixeira; senão 404 (LT1)."""
    frame = sessao.get(Frame, frame_id)
    # Um retrato que foi junto com o elemento volta com ele (LT4): não se restaura nem se apaga sozinho.
    if frame is None or frame.apagado_em is None or frame.apagado_com_elemento_id is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Não há frame com id {frame_id} na lixeira.")
    return frame


def _descrever_frame(frame: Frame) -> FrameNaLixeira:
    capitulo = frame.capitulo
    imagens = imagens_do_frame(frame)
    ativas = [i for i in imagens if i.apagada_em is None]
    elemento = frame.estados_elemento[0].elemento if frame.tipo == TipoDeFrame.PERSONAGEM and frame.estados_elemento else None
    return FrameNaLixeira(
        id=frame.id,
        titulo=frame.titulo,
        tipo=frame.tipo.name,
        nome_do_elemento=elemento.nome if elemento is not None else None,
        capitulo_id=capitulo.id,
        titulo_do_capitulo=capitulo.titulo,
        ordem_do_capitulo=capitulo.ordem,
        livro_id=capitulo.livro_id,
        titulo_do_livro=capitulo.livro.titulo,
        apagado_em=frame.apagado_em,
        total_de_prompts=len(frame.prompts),
        total_de_imagens=len(imagens),
        tamanho_em_bytes=sum(tamanho_da_imagem(i) for i in imagens),
        imagem_id=max((i.id for i in ativas), default=None),
    )


def _frames_da_lixeira(sessao: Session) -> list[Frame]:
    """Os frames na lixeira, do mais recentemente apagado ao mais antigo, **sem os de um livro que também está na lixeira**."""
    return list(
        sessao.scalars(
            select(Frame)
            .join(Capitulo, Capitulo.id == Frame.capitulo_id)
            .join(Livro, Livro.id == Capitulo.livro_id)
            .where(Frame.apagado_em.is_not(None), Frame.apagado_com_elemento_id.is_(None), Livro.apagado_em.is_(None))
            .order_by(Frame.apagado_em.desc(), Frame.id.desc())
        )
    )


@rotas.get("/frames", response_model=FramesDaLixeira, summary="As cenas e os retratos da lixeira")
def listar_frames_da_lixeira(sessao: Session = Depends(obter_sessao)) -> FramesDaLixeira:
    """Do apagado mais recentemente para o mais antigo, com o capítulo, o livro e o que cada um leva junto (LT3)."""
    descritos = [_descrever_frame(frame) for frame in _frames_da_lixeira(sessao)]
    return FramesDaLixeira(frames=descritos, total_em_bytes=sum(d.tamanho_em_bytes for d in descritos))


@rotas.post("/frames/{frame_id}/restaurar", response_model=FrameNaLixeira, summary="Tira a cena ou o retrato da lixeira")
def restaurar_o_frame(frame_id: int, sessao: Session = Depends(obter_sessao)) -> FrameNaLixeira:
    """O frame volta ao capítulo com os prompts e as imagens; a cena sugerida de antes é religada, se ainda existe e está sem frame."""
    frame = _frame_na_lixeira(sessao, frame_id)
    descricao = _descrever_frame(frame)
    restaurar_frame(sessao, frame)
    sessao.commit()
    return descricao


@rotas.delete("/frames/{frame_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga de vez uma cena ou um retrato da lixeira")
def apagar_o_frame_de_vez(frame_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Remove o frame, os prompts e as imagens, com os arquivos. **Não tem volta.**"""
    apagar_frame_de_vez(sessao, _frame_na_lixeira(sessao, frame_id))
    sessao.commit()


@rotas.delete("/frames", response_model=LixeiraEsvaziada, summary="Esvazia a lixeira de cenas e retratos")
def esvaziar_frames(sessao: Session = Depends(obter_sessao)) -> LixeiraEsvaziada:
    """Apaga de vez **todos** os frames da lixeira (os de livros na lixeira ficam, saem com o livro). Nada disso roda sozinho (LX6)."""
    frames = _frames_da_lixeira(sessao)
    liberados = sum(apagar_frame_de_vez(sessao, frame) for frame in frames)
    sessao.commit()
    return LixeiraEsvaziada(removidas=len(frames), liberados_em_bytes=liberados)


# --------------------------------------------------------------------------- #
# Elementos (LT4)
# --------------------------------------------------------------------------- #


def _elemento_na_lixeira(sessao: Session, elemento_id: int) -> Elemento:
    """O elemento, desde que esteja na lixeira; senão 404 (LT1)."""
    elemento = sessao.get(Elemento, elemento_id)
    if elemento is None or elemento.apagado_em is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Não há elemento com id {elemento_id} na lixeira.")
    return elemento


def _descrever_elemento(sessao: Session, elemento: Elemento) -> ElementoNaLixeira:
    retratos = retratos_que_foram_com_o_elemento(sessao, elemento)
    imagens = imagens_do_elemento(sessao, elemento)
    ativas = [i for i in imagens if i.apagada_em is None]
    return ElementoNaLixeira(
        id=elemento.id,
        nome=elemento.nome,
        tipo=elemento.tipo.name,
        livro_id=elemento.livro_id,
        titulo_do_livro=elemento.livro.titulo,
        apagado_em=elemento.apagado_em,
        total_de_estados=len(elemento.estados),
        total_de_retratos=len(retratos),
        total_de_imagens=len(imagens),
        tamanho_em_bytes=sum(tamanho_da_imagem(i) for i in imagens),
        imagem_id=max((i.id for i in ativas), default=None),
    )


def _elementos_da_lixeira(sessao: Session) -> list[Elemento]:
    """Os elementos na lixeira, do mais recentemente apagado ao mais antigo, **sem os de um livro que também está na lixeira**."""
    return list(
        sessao.scalars(
            select(Elemento)
            .join(Livro, Livro.id == Elemento.livro_id)
            .where(Elemento.apagado_em.is_not(None), Livro.apagado_em.is_(None))
            .order_by(Elemento.apagado_em.desc(), Elemento.id.desc())
        )
    )


@rotas.get("/elementos", response_model=ElementosDaLixeira, summary="Os elementos da lixeira")
def listar_elementos_da_lixeira(sessao: Session = Depends(obter_sessao)) -> ElementosDaLixeira:
    """Do apagado mais recentemente para o mais antigo, com o livro e o que cada um leva junto (LT4)."""
    descritos = [_descrever_elemento(sessao, elemento) for elemento in _elementos_da_lixeira(sessao)]
    return ElementosDaLixeira(elementos=descritos, total_em_bytes=sum(d.tamanho_em_bytes for d in descritos))


@rotas.post("/elementos/{elemento_id}/restaurar", response_model=ElementoNaLixeira, summary="Tira o elemento da lixeira")
def restaurar_o_elemento(elemento_id: int, sessao: Session = Depends(obter_sessao)) -> ElementoNaLixeira:
    """O elemento volta ao livro com estados, identidade e retratos; as sugestões que o citavam são religadas, se ainda estão sem elemento."""
    elemento = _elemento_na_lixeira(sessao, elemento_id)
    descricao = _descrever_elemento(sessao, elemento)
    restaurar_elemento(sessao, elemento)
    sessao.commit()
    return descricao


@rotas.delete("/elementos/{elemento_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga de vez um elemento da lixeira")
def apagar_o_elemento_de_vez(elemento_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Remove o elemento, os estados, a identidade, os retratos que foram com ele e as imagens (com os arquivos). **Não tem volta.**"""
    apagar_elemento_de_vez(sessao, _elemento_na_lixeira(sessao, elemento_id))
    sessao.commit()


@rotas.delete("/elementos", response_model=LixeiraEsvaziada, summary="Esvazia a lixeira de elementos")
def esvaziar_elementos(sessao: Session = Depends(obter_sessao)) -> LixeiraEsvaziada:
    """Apaga de vez **todos** os elementos da lixeira (os de livros na lixeira ficam, saem com o livro). Nada disso roda sozinho (LX6)."""
    elementos = _elementos_da_lixeira(sessao)
    liberados = sum(apagar_elemento_de_vez(sessao, elemento) for elemento in elementos)
    sessao.commit()
    return LixeiraEsvaziada(removidas=len(elementos), liberados_em_bytes=liberados)
