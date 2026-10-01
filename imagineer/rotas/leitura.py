"""Rotas do marcador e dos pins de um livro (Etapa 6.10, item 3.4h): onde o leitor parou."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.leitura import (
    MarcadorDoLivro,
    MarcadorGravacao,
    MarcadorGravado,
    MarcadorResposta,
    PinAjuste,
    PinNovo,
    PinResposta,
)
from imagineer.modelos import Capitulo, Livro, Marcador, Pin

rotas_de_livro = APIRouter(prefix="/livros", tags=["Leitura"])
rotas_de_pin = APIRouter(prefix="/pins", tags=["Leitura"])


# --------------------------------------------------------------------------- #
# Marcador (a posição automática)
# --------------------------------------------------------------------------- #


@rotas_de_livro.get(
    "/{livro_id}/marcador",
    response_model=MarcadorDoLivro,
    summary="Onde a pessoa parou de ler este livro",
)
def ler_marcador(livro_id: int, sessao: Session = Depends(obter_sessao)) -> MarcadorDoLivro:
    """O marcador do livro, ou ``{"marcador": null}`` se ainda não leu nada.

    "Nunca leu" é um estado normal, não um erro — o mesmo critério do ``gerado_em`` nulo do item 6.7.
    """
    _buscar_livro(sessao, livro_id)
    return MarcadorDoLivro(marcador=_marcador_do_livro(sessao, livro_id))


@rotas_de_livro.put(
    "/{livro_id}/marcador",
    response_model=MarcadorGravado,
    summary="Grava onde a pessoa parou (o mais recente vence)",
)
def gravar_marcador(
    livro_id: int,
    gravacao: MarcadorGravacao,
    sessao: Session = Depends(obter_sessao),
) -> MarcadorGravado:
    """Grava o marcador e **devolve o que ficou valendo**, com ``aceito`` dizendo se foi o enviado.

    A regra do item 3.4h: vence o marcador de ``lido_em`` **mais novo ou igual** (a hora do aparelho, e
    não a da chegada da gravação), então um aparelho que ficou offline e sincroniza tarde não passa por
    cima de uma leitura mais nova de outro. Um ``lido_em`` no futuro é limitado ao relógio do servidor.
    """
    _buscar_livro(sessao, livro_id)
    capitulo = _capitulo_do_livro(sessao, livro_id, gravacao.capitulo_id)
    _conferir_posicao(capitulo, gravacao.posicao_no_texto)

    lido_em = min(_com_fuso(gravacao.lido_em), datetime.now(timezone.utc))
    marcador = _marcador_do_livro(sessao, livro_id)

    if marcador is None:
        marcador = Marcador(livro_id=livro_id)
        sessao.add(marcador)
    elif lido_em < _com_fuso(marcador.lido_em):
        return MarcadorGravado(marcador=MarcadorResposta.model_validate(marcador), aceito=False)

    marcador.capitulo_id = gravacao.capitulo_id
    marcador.posicao_no_texto = gravacao.posicao_no_texto
    marcador.lido_em = lido_em
    try:
        sessao.commit()
    except IntegrityError:
        # Duas primeiras gravações ao mesmo tempo: a outra chegou antes e a restrição de "um por livro"
        # barrou esta. Relê o que ficou valendo e aplica a mesma regra do mais recente.
        sessao.rollback()
        vencedor = _marcador_do_livro(sessao, livro_id)
        if vencedor is None:
            raise
        if lido_em < _com_fuso(vencedor.lido_em):
            return MarcadorGravado(marcador=MarcadorResposta.model_validate(vencedor), aceito=False)
        vencedor.capitulo_id = gravacao.capitulo_id
        vencedor.posicao_no_texto = gravacao.posicao_no_texto
        vencedor.lido_em = lido_em
        sessao.commit()
        marcador = vencedor
    return MarcadorGravado(marcador=MarcadorResposta.model_validate(marcador), aceito=True)


# --------------------------------------------------------------------------- #
# Pins (as posições marcadas à mão)
# --------------------------------------------------------------------------- #


@rotas_de_livro.get(
    "/{livro_id}/pins",
    response_model=list[PinResposta],
    summary="Os pins do livro, na ordem do livro",
)
def listar_pins(livro_id: int, sessao: Session = Depends(obter_sessao)) -> list[Pin]:
    """Os pins por ordem do capítulo e, dentro dele, da posição no texto."""
    _buscar_livro(sessao, livro_id)
    return list(
        sessao.scalars(
            select(Pin)
            .join(Capitulo, Capitulo.id == Pin.capitulo_id)
            .where(Pin.livro_id == livro_id)
            .order_by(Capitulo.ordem, Pin.posicao_no_texto, Pin.id)
        )
    )


@rotas_de_livro.post(
    "/{livro_id}/pins",
    response_model=PinResposta,
    status_code=status.HTTP_201_CREATED,
    summary="Marca um ponto do livro à mão",
)
def criar_pin(livro_id: int, novo: PinNovo, sessao: Session = Depends(obter_sessao)) -> Pin:
    """Cria um pin. O capítulo precisa ser deste livro e a posição precisa caber no texto dele."""
    _buscar_livro(sessao, livro_id)
    capitulo = _capitulo_do_livro(sessao, livro_id, novo.capitulo_id)
    _conferir_posicao(capitulo, novo.posicao_no_texto)

    pin = Pin(
        livro_id=livro_id,
        capitulo_id=novo.capitulo_id,
        posicao_no_texto=novo.posicao_no_texto,
        nota=novo.nota,
    )
    sessao.add(pin)
    sessao.commit()
    sessao.refresh(pin)
    return pin


@rotas_de_pin.patch("/{pin_id}", response_model=PinResposta, summary="Ajusta a nota de um pin")
def ajustar_pin(pin_id: int, ajuste: PinAjuste, sessao: Session = Depends(obter_sessao)) -> Pin:
    """Troca a nota do pin; ``null`` (ou texto em branco) apaga a nota."""
    pin = _buscar_pin(sessao, pin_id)
    pin.nota = ajuste.nota
    sessao.commit()
    sessao.refresh(pin)
    return pin


@rotas_de_pin.delete(
    "/{pin_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove um pin"
)
def remover_pin(pin_id: int, sessao: Session = Depends(obter_sessao)) -> Response:
    pin = _buscar_pin(sessao, pin_id)
    sessao.delete(pin)
    sessao.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _com_fuso(momento: datetime) -> datetime:
    """Garante fuso na data/hora: o SQLite (testes) devolve datas sem fuso; o PostgreSQL, com.

    Sem fuso, assume UTC — é o que o servidor grava.
    """
    return momento if momento.tzinfo is not None else momento.replace(tzinfo=timezone.utc)


def _marcador_do_livro(sessao: Session, livro_id: int) -> Marcador | None:
    return sessao.scalar(select(Marcador).where(Marcador.livro_id == livro_id))


def _tamanho_em_utf16(texto: str) -> int:
    return len(texto.encode("utf-16-le")) // 2


def _conferir_posicao(capitulo: Capitulo, posicao: int) -> None:
    """422 se a posição passa do fim do texto do capítulo (a negativa o esquema já recusa)."""
    tamanho = _tamanho_em_utf16(capitulo.texto)
    if posicao > tamanho:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"A posição {posicao} passa do fim do capítulo {capitulo.id}, "
                f"que tem {tamanho} unidades UTF-16."
            ),
        )


def _capitulo_do_livro(sessao: Session, livro_id: int, capitulo_id: int) -> Capitulo:
    """O capítulo, que precisa ser deste livro (422 se não existe ou é de outro)."""
    capitulo = sessao.get(Capitulo, capitulo_id)
    if capitulo is None or capitulo.livro_id != livro_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"O capítulo {capitulo_id} não existe neste livro.",
        )
    return capitulo


def _buscar_livro(sessao: Session, livro_id: int) -> Livro:
    livro = sessao.get(Livro, livro_id)
    if livro is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe livro com id {livro_id}.",
        )
    return livro


def _buscar_pin(sessao: Session, pin_id: int) -> Pin:
    pin = sessao.get(Pin, pin_id)
    if pin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe pin com id {pin_id}.",
        )
    return pin
