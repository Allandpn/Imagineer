"""Rotas de perfis de renderização (Etapa 6.5).

O perfil é o estilo visual a aplicar, separado dos dados narrativos. Ele **não**
pertence a um livro: é o Livro que aponta para o seu perfil padrão, e é isso que
permite reaproveitar a mesma combinação de estilo entre obras (item 3.4c).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.frame import (
    PerfilRenderizacao as EsquemaPerfil,
)
from imagineer.esquemas.frame import (
    PerfilRenderizacaoAjuste,
    PerfilRenderizacaoNovo,
)
from imagineer.modelos import PerfilRenderizacao
from imagineer.rotas._comum import (
    buscar_perfil as _buscar_perfil,
)

rotas = APIRouter(prefix="/perfis-renderizacao", tags=["Perfis de renderização"])


@rotas.get("", response_model=list[EsquemaPerfil], summary="Lista os perfis")
def listar_perfis(sessao: Session = Depends(obter_sessao)) -> list[EsquemaPerfil]:
    """Todos os perfis, em ordem alfabética. Eles são compartilhados entre livros."""
    perfis = sessao.scalars(
        select(PerfilRenderizacao).order_by(PerfilRenderizacao.nome)
    )
    return [EsquemaPerfil.model_validate(perfil) for perfil in perfis]


@rotas.post(
    "",
    response_model=EsquemaPerfil,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um perfil",
)
def criar_perfil(
    novo: PerfilRenderizacaoNovo, sessao: Session = Depends(obter_sessao)
) -> EsquemaPerfil:
    """Cria um perfil de estilo."""
    perfil = PerfilRenderizacao(**novo.model_dump())
    sessao.add(perfil)
    _gravar(sessao, novo.nome)
    sessao.refresh(perfil)
    return EsquemaPerfil.model_validate(perfil)


@rotas.get("/{perfil_id}", response_model=EsquemaPerfil, summary="Abre um perfil")
def abrir_perfil(
    perfil_id: int, sessao: Session = Depends(obter_sessao)
) -> EsquemaPerfil:
    return EsquemaPerfil.model_validate(_buscar_perfil(sessao, perfil_id))


@rotas.patch("/{perfil_id}", response_model=EsquemaPerfil, summary="Ajusta um perfil")
def ajustar_perfil(
    perfil_id: int,
    ajuste: PerfilRenderizacaoAjuste,
    sessao: Session = Depends(obter_sessao),
) -> EsquemaPerfil:
    """Muda o nome ou qualquer campo de estilo. Só o que vem é aplicado."""
    perfil = _buscar_perfil(sessao, perfil_id)
    campos = ajuste.model_dump(exclude_unset=True)
    for campo, valor in campos.items():
        setattr(perfil, campo, valor)

    _gravar(sessao, campos.get("nome", perfil.nome))
    sessao.refresh(perfil)
    return EsquemaPerfil.model_validate(perfil)


@rotas.delete(
    "/{perfil_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um perfil",
)
def remover_perfil(perfil_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga o perfil sem levar nada com ele.

    Os livros que o usavam como padrão ficam com o campo nulo, e os prompts
    gerados com ele continuam no histórico — é o ``ON DELETE SET NULL`` do item
    3.4c. Apagar um estilo não pode apagar trabalho de catalogação.
    """
    sessao.delete(_buscar_perfil(sessao, perfil_id))
    sessao.commit()


def _gravar(sessao: Session, nome: str) -> None:
    """Grava, traduzindo nome repetido em 409.

    Dois perfis com o mesmo nome seriam indistinguíveis na tela de escolha — é o
    motivo da unicidade no item 3.4c.
    """
    try:
        sessao.commit()
    except IntegrityError as erro:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Já existe um perfil de renderização chamado {nome!r}.",
        ) from erro
