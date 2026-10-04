"""A lixeira de imagens (item 7.5b, LX1 a LX10).

Apagar uma imagem só a **marca** (``apagada_em``); o arquivo fica no disco até o usuário **apagar de vez**. Nada some por tempo
(LX6). Prompts, frames, elementos e livros ainda são removidos de vez (LX2).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.lixeira import ImagemNaLixeira, LivroNaLixeira, LivrosDaLixeira, Lixeira, LixeiraEsvaziada
from imagineer.modelos import Capitulo, Imagem, Livro, TipoDeFrame
from imagineer.servicos.imagens_reduzidas import orientacao_de
from imagineer.servicos.lixeira import apagar_de_vez, apagar_livro_de_vez, imagens_do_livro, tamanho_da_imagem

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
