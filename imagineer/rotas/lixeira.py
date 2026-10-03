"""A lixeira de imagens (item 7.5b, LX1 a LX10).

Apagar uma imagem só a **marca** (``apagada_em``); o arquivo fica no disco até o usuário **apagar de vez**. Nada some por tempo
(LX6). Prompts, frames, elementos e livros ainda são removidos de vez (LX2).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.lixeira import ImagemNaLixeira, Lixeira, LixeiraEsvaziada
from imagineer.modelos import Imagem, TipoDeFrame
from imagineer.servicos.imagens_reduzidas import orientacao_de
from imagineer.servicos.lixeira import apagar_de_vez, tamanho_da_imagem

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
