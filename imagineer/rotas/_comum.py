"""O que várias rotas repetiam: buscar uma coisa pelo id ou responder 404.

Antes, cada módulo de rota tinha a sua cópia de ``_buscar_livro``, ``_buscar_capitulo``, ``_buscar_frame``...,
todas com o mesmo corpo (item "Helpers de busca duplicados" da Etapa 8). Aqui há uma só implementação
(``obter_ou_404``) e uma função fina por entidade, que existe para o **rótulo da mensagem** ficar no
mesmo lugar: ``Não existe livro com id 7.`` é texto que o app mostra e os testes conferem.
"""

from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    Frame,
    HistoricoIdentidadeElemento,
    Imagem,
    Livro,
    PerfilRenderizacao,
    Pin,
    Prompt,
    SugestaoDeElemento,
)

T = TypeVar("T")


def obter_ou_404(sessao: Session, modelo: type[T], id_: int, rotulo: str) -> T:
    """Devolve o registro ``modelo`` de id ``id_``, ou responde 404 ("Não existe ``rotulo`` com id ``id_``.")."""
    registro = sessao.get(modelo, id_)
    if registro is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe {rotulo} com id {id_}.",
        )
    return registro


def buscar_livro(sessao: Session, livro_id: int) -> Livro:
    return obter_ou_404(sessao, Livro, livro_id, "livro")


def buscar_capitulo(sessao: Session, capitulo_id: int) -> Capitulo:
    return obter_ou_404(sessao, Capitulo, capitulo_id, "capítulo")


def buscar_elemento(sessao: Session, elemento_id: int) -> Elemento:
    return obter_ou_404(sessao, Elemento, elemento_id, "elemento")


def buscar_estado(sessao: Session, estado_id: int) -> EstadoElemento:
    return obter_ou_404(sessao, EstadoElemento, estado_id, "estado")


def buscar_frame(sessao: Session, frame_id: int) -> Frame:
    return obter_ou_404(sessao, Frame, frame_id, "frame")


def buscar_prompt(sessao: Session, prompt_id: int) -> Prompt:
    return obter_ou_404(sessao, Prompt, prompt_id, "prompt")


def buscar_imagem(sessao: Session, imagem_id: int) -> Imagem:
    return obter_ou_404(sessao, Imagem, imagem_id, "imagem")


def buscar_perfil(sessao: Session, perfil_id: int) -> PerfilRenderizacao:
    return obter_ou_404(sessao, PerfilRenderizacao, perfil_id, "perfil de renderização")


def buscar_pin(sessao: Session, pin_id: int) -> Pin:
    return obter_ou_404(sessao, Pin, pin_id, "pin")


def buscar_sugestao_de_elemento(sessao: Session, sugestao_id: int) -> SugestaoDeElemento:
    return obter_ou_404(sessao, SugestaoDeElemento, sugestao_id, "sugestão de elemento")


def buscar_acrescimo(sessao: Session, acrescimo_id: int) -> HistoricoIdentidadeElemento:
    return obter_ou_404(sessao, HistoricoIdentidadeElemento, acrescimo_id, "acréscimo de identidade")
