"""Rotas dos destaques de um livro (RL9 a RL13): trechos marcados, com cor, nota e, se quiser, um elemento ligado."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.leitura import LIMITE_DO_DESTAQUE, DestaqueAjuste, DestaqueNovo, DestaqueResposta
from imagineer.modelos import Capitulo, Destaque
from imagineer.rotas._comum import buscar_elemento, buscar_livro, obter_ou_404
from imagineer.rotas.leitura import _capitulo_do_livro, _conferir_posicao

rotas_de_livro = APIRouter(prefix="/livros", tags=["Destaques"])
rotas_de_destaque = APIRouter(prefix="/destaques", tags=["Destaques"])
rotas_de_elemento = APIRouter(prefix="/elementos", tags=["Destaques"])


def _trecho_em_utf16(texto: str, inicio: int, fim: int) -> str:
    """O pedaço do texto entre duas posições **UTF-16** (a unidade do contrato), ou 422 se uma delas corta um emoji ao meio."""
    bytes_do_texto = texto.encode("utf-16-le")
    try:
        return bytes_do_texto[inicio * 2 : fim * 2].decode("utf-16-le")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="O trecho começa ou termina no meio de um caractere (um emoji, por exemplo).",
        ) from None


def _elemento_do_livro(sessao: Session, livro_id: int, elemento_id: int) -> None:
    """422 se o elemento não é deste livro (404 se não existe ou está na lixeira)."""
    elemento = buscar_elemento(sessao, elemento_id)
    if elemento.livro_id != livro_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"O elemento {elemento_id} não é deste livro."
        )


def _buscar_destaque(sessao: Session, destaque_id: int) -> Destaque:
    return obter_ou_404(sessao, Destaque, destaque_id, "destaque")


def _na_ordem_do_livro(consulta):
    return consulta.join(Capitulo, Capitulo.id == Destaque.capitulo_id).order_by(
        Capitulo.ordem, Destaque.inicio, Destaque.id
    )


@rotas_de_livro.get("/{livro_id}/destaques", response_model=list[DestaqueResposta], summary="Os destaques do livro, na ordem do livro")
def listar_destaques(livro_id: int, capitulo_id: int | None = None, sessao: Session = Depends(obter_sessao)) -> list[Destaque]:
    """Todos os destaques do livro; com ``?capitulo_id=``, só os daquele capítulo."""
    buscar_livro(sessao, livro_id)
    consulta = select(Destaque).where(Destaque.livro_id == livro_id)
    if capitulo_id is not None:
        consulta = consulta.where(Destaque.capitulo_id == capitulo_id)
    return list(sessao.scalars(_na_ordem_do_livro(consulta)))


@rotas_de_livro.post(
    "/{livro_id}/destaques",
    response_model=DestaqueResposta,
    status_code=status.HTTP_201_CREATED,
    summary="Destaca um trecho do texto",
)
def criar_destaque(livro_id: int, novo: DestaqueNovo, sessao: Session = Depends(obter_sessao)) -> Destaque:
    """Cria o destaque. O servidor copia o ``trecho`` do capítulo; o app só diz onde ele começa e termina."""
    buscar_livro(sessao, livro_id)
    capitulo = _capitulo_do_livro(sessao, livro_id, novo.capitulo_id)
    if novo.fim <= novo.inicio:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="O fim do destaque precisa vir depois do início.")
    if novo.fim - novo.inicio > LIMITE_DO_DESTAQUE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Um destaque tem no máximo {LIMITE_DO_DESTAQUE} caracteres.",
        )
    _conferir_posicao(capitulo, novo.fim)
    if novo.elemento_id is not None:
        _elemento_do_livro(sessao, livro_id, novo.elemento_id)

    destaque = Destaque(
        livro_id=livro_id,
        capitulo_id=novo.capitulo_id,
        inicio=novo.inicio,
        fim=novo.fim,
        trecho=_trecho_em_utf16(capitulo.texto, novo.inicio, novo.fim),
        cor=novo.cor,
        nota=novo.nota,
        elemento_id=novo.elemento_id,
    )
    sessao.add(destaque)
    sessao.commit()
    sessao.refresh(destaque)
    return destaque


@rotas_de_destaque.patch("/{destaque_id}", response_model=DestaqueResposta, summary="Ajusta a cor, a nota ou o elemento de um destaque")
def ajustar_destaque(destaque_id: int, ajuste: DestaqueAjuste, sessao: Session = Depends(obter_sessao)) -> Destaque:
    """Muda **só o que foi enviado**; ``nota`` ou ``elemento_id`` nulos apagam a nota ou desfazem o vínculo."""
    destaque = _buscar_destaque(sessao, destaque_id)
    enviados = ajuste.model_fields_set
    if "cor" in enviados and ajuste.cor is not None:
        destaque.cor = ajuste.cor
    if "nota" in enviados:
        destaque.nota = ajuste.nota
    if "elemento_id" in enviados:
        if ajuste.elemento_id is not None:
            _elemento_do_livro(sessao, destaque.livro_id, ajuste.elemento_id)
        destaque.elemento_id = ajuste.elemento_id
    sessao.commit()
    sessao.refresh(destaque)
    return destaque


@rotas_de_destaque.delete("/{destaque_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove um destaque")
def remover_destaque(destaque_id: int, sessao: Session = Depends(obter_sessao)) -> Response:
    sessao.delete(_buscar_destaque(sessao, destaque_id))
    sessao.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@rotas_de_elemento.get(
    "/{elemento_id}/destaques", response_model=list[DestaqueResposta], summary="As passagens destacadas ligadas a um elemento"
)
def listar_destaques_do_elemento(elemento_id: int, sessao: Session = Depends(obter_sessao)) -> list[Destaque]:
    """Os destaques que apontam para o elemento, na ordem do livro (a seção "Passagens destacadas" da ficha)."""
    buscar_elemento(sessao, elemento_id)
    return list(sessao.scalars(_na_ordem_do_livro(select(Destaque).where(Destaque.elemento_id == elemento_id))))
