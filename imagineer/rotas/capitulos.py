"""Rotas de capítulos (Etapa 6.2): abrir um capítulo e ajustá-lo.

O passo 5 do fluxo — o usuário escolhe um capítulo — e a confirmação da sugestão
de "ignorado" que a importação deixou (item 2.2).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.livro import CapituloAjuste, CapituloDetalhe
from imagineer.modelos import Capitulo
from imagineer.rotas._comum import (
    buscar_capitulo as _buscar_capitulo,
)

rotas = APIRouter(prefix="/capitulos", tags=["Capítulos"])


@rotas.get(
    "/{capitulo_id}",
    response_model=CapituloDetalhe,
    summary="Abre um capítulo com o texto",
)
def abrir_capitulo(
    capitulo_id: int, sessao: Session = Depends(obter_sessao)
) -> CapituloDetalhe:
    """Devolve o capítulo com o texto completo.

    É a única rota que traz o texto. As listagens devolvem só o tamanho, porque
    um livro inteiro em JSON chegaria a megabytes (Etapa 6.2).
    """
    return _detalhe(_buscar_capitulo(sessao, capitulo_id))


@rotas.patch(
    "/{capitulo_id}",
    response_model=CapituloDetalhe,
    summary="Ajusta um capítulo",
)
def ajustar_capitulo(
    capitulo_id: int,
    ajuste: CapituloAjuste,
    sessao: Session = Depends(obter_sessao),
) -> CapituloDetalhe:
    """Muda o título ou marca o capítulo como ignorado.

    É aqui que o usuário confirma ou desfaz a sugestão da importação. Só os campos
    presentes no corpo são aplicados — ``exclude_unset`` é o que distingue "não
    mandei o título" de "mandei o título vazio".
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)

    for campo, valor in ajuste.model_dump(exclude_unset=True).items():
        setattr(capitulo, campo, valor)

    sessao.commit()
    sessao.refresh(capitulo)
    return _detalhe(capitulo)


def _detalhe(capitulo: Capitulo) -> CapituloDetalhe:
    """Monta a resposta a partir do modelo."""
    return CapituloDetalhe(
        id=capitulo.id,
        livro_id=capitulo.livro_id,
        ordem=capitulo.ordem,
        titulo=capitulo.titulo,
        ignorado=capitulo.ignorado,
        texto=capitulo.texto,
        tamanho_do_texto=len(capitulo.texto),
    )
