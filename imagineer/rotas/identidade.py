"""Rotas do histórico de identidade de um elemento (Etapa 6.3): os acréscimos que a narrativa faz a quem ele é."""

from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy import update
from sqlalchemy.orm import Session
from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.elemento import (
    HistoricoIdentidadeAjuste,
    HistoricoIdentidadeNovo,
    HistoricoIdentidadeResumo,
)
from imagineer.modelos import HistoricoIdentidadeElemento
from imagineer.rotas._comum import (
    buscar_acrescimo as _buscar_acrescimo,
    buscar_elemento as _buscar_elemento,
)
from imagineer.rotas._elementos_comum import (
    buscar_capitulo_do_livro,
)

rotas = APIRouter(prefix="/elementos", tags=["Elementos"])
rotas_de_identidade = APIRouter(prefix="/historico-identidade", tags=["Elementos"])


def _resumo_do_acrescimo(registro: HistoricoIdentidadeElemento) -> HistoricoIdentidadeResumo:
    """O acréscimo como a API o devolve, já com a posição e o título do capítulo."""
    return HistoricoIdentidadeResumo.model_validate(registro).model_copy(
        update={
            "ordem_do_capitulo": registro.capitulo.ordem,
            "titulo_do_capitulo": registro.capitulo.titulo,
        }
    )


@rotas.post(
    "/{elemento_id}/historico-identidade",
    response_model=HistoricoIdentidadeResumo,
    status_code=status.HTTP_201_CREATED,
    summary="Acrescenta à mão o que um capítulo revela sobre quem o elemento é",
)
def criar_acrescimo_de_identidade(
    elemento_id: int,
    corpo: HistoricoIdentidadeNovo,
    sessao: Session = Depends(obter_sessao),
) -> HistoricoIdentidadeResumo:
    """Grava um acréscimo de identidade (item 3.4f) escrito pelo usuário.

    Vale como o gravado pelo servidor na leitura profunda de identidade: como esta só tenta
    um acréscimo para um par (elemento, capítulo) que ainda não tem nenhum (item 4.4, fase 2b),
    escrever um à mão **impede** o automático naquele capítulo. O capítulo tem de ser do
    mesmo livro do elemento.
    """
    elemento = _buscar_elemento(sessao, elemento_id)
    capitulo = buscar_capitulo_do_livro(sessao, corpo.capitulo_id, elemento.livro_id)
    registro = HistoricoIdentidadeElemento(
        elemento_id=elemento.id, capitulo_id=capitulo.id, descricao=corpo.descricao
    )
    sessao.add(registro)
    sessao.commit()
    sessao.refresh(registro)
    return _resumo_do_acrescimo(registro)


@rotas_de_identidade.patch(
    "/{acrescimo_id}",
    response_model=HistoricoIdentidadeResumo,
    summary="Corrige o texto de um acréscimo de identidade",
)
def ajustar_acrescimo_de_identidade(
    acrescimo_id: int,
    ajuste: HistoricoIdentidadeAjuste,
    sessao: Session = Depends(obter_sessao),
) -> HistoricoIdentidadeResumo:
    registro = _buscar_acrescimo(sessao, acrescimo_id)
    registro.descricao = ajuste.descricao
    sessao.commit()
    sessao.refresh(registro)
    return _resumo_do_acrescimo(registro)


@rotas_de_identidade.delete(
    "/{acrescimo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Apaga um acréscimo de identidade",
)
def remover_acrescimo_de_identidade(acrescimo_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    sessao.delete(_buscar_acrescimo(sessao, acrescimo_id))
    sessao.commit()
