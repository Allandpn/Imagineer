"""O que as rotas de elementos, estados e identidade usam em comum (Etapa 6.3)."""

from fastapi import (
    HTTPException,
    status,
)
from sqlalchemy import (
    func,
    select,
)
from sqlalchemy.orm import Session
from imagineer.esquemas.elemento import (
    ElementoResumo,
    EstadoResumo,
)
from imagineer.servicos.acesso import buscar_visivel
from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    Frame,
    Imagem,
    Prompt,
    SugestaoDeElemento,
    TipoDeFrame,
    TipoElemento,
    frames_estados_elemento,
)
from imagineer.rotas._comum import buscar_capitulo as _buscar_capitulo
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento


def montar_resumos(
    sessao: Session,
    livro_id: int,
    *,
    tipo: TipoElemento | None,
    ordem_limite: int | None,
) -> list[ElementoResumo]:
    """Monta a listagem de elementos com o estado vigente e a contagem de estados.

    As três informações vêm de três consultas de tamanho fixo — a lista de
    elementos, os estados vigentes e as contagens — em vez de uma consulta por
    elemento.
    """
    filtros = [Elemento.livro_id == livro_id, Elemento.apagado_em.is_(None)]
    if tipo is not None:
        filtros.append(Elemento.tipo == tipo)

    elementos = list(
        sessao.scalars(
            select(Elemento).where(*filtros).order_by(Elemento.tipo, Elemento.nome)
        )
    )

    vigentes = estado_vigente_por_elemento(sessao, livro_id, ordem_limite)
    capas = capas_dos_elementos(sessao, [elemento.id for elemento in elementos])

    contagens = dict(
        sessao.execute(
            select(EstadoElemento.elemento_id, func.count(EstadoElemento.id))
            .join(Elemento, Elemento.id == EstadoElemento.elemento_id)
            .where(Elemento.livro_id == livro_id)
            .group_by(EstadoElemento.elemento_id)
        ).all()
    )

    return [
        ElementoResumo(
            id=elemento.id,
            livro_id=elemento.livro_id,
            tipo=elemento.tipo,
            nome=elemento.nome,
            descricao=elemento.descricao,
            total_de_estados=contagens.get(elemento.id, 0),
            imagem_de_capa_id=elemento.imagem_ancora_padrao_id or capas.get(elemento.id),
            estado_vigente=(
                EstadoResumo.model_validate(vigentes[elemento.id])
                if elemento.id in vigentes
                else None
            ),
        )
        for elemento in elementos
    ]


def capas_dos_elementos(sessao: Session, elementos_ids: list[int]) -> dict[int, int]:
    """A imagem mais recente do **retrato** de cada elemento, numa consulta só (FI4).

    Retrato = frame ``PERSONAGEM`` com o elemento como **único** estado (item 3.4c). A âncora padrão, quando existe,
    tem prioridade sobre esta (quem chama a prefere).
    """
    if not elementos_ids:
        return {}
    de_um_estado_so = (
        select(frames_estados_elemento.c.frame_id)
        .group_by(frames_estados_elemento.c.frame_id)
        .having(func.count(frames_estados_elemento.c.estado_elemento_id) == 1)
    )
    return dict(
        sessao.execute(
            select(EstadoElemento.elemento_id, func.max(Imagem.id))
            .join(frames_estados_elemento, frames_estados_elemento.c.estado_elemento_id == EstadoElemento.id)
            .join(Frame, Frame.id == frames_estados_elemento.c.frame_id)
            .join(Prompt, Prompt.frame_id == Frame.id)
            .join(Imagem, Imagem.prompt_id == Prompt.id)
            .where(
                Imagem.apagada_em.is_(None),
                Frame.apagado_em.is_(None),
                Frame.tipo == TipoDeFrame.PERSONAGEM,
                Frame.id.in_(de_um_estado_so),
                EstadoElemento.elemento_id.in_(elementos_ids),
            )
            .group_by(EstadoElemento.elemento_id)
        ).all()
    )


def buscar_capitulo_do_livro(sessao: Session, capitulo_id: int, livro_id: int) -> Capitulo:
    """Exige que o capítulo pertença ao mesmo livro do elemento.

    Nada no banco impede o contrário: as chaves estrangeiras de ``elemento_id`` e
    ``capitulo_id`` são independentes. Sem esta checagem, um estado poderia ficar
    ligado a um capítulo de outro livro, e apareceria na narrativa errada sem
    nenhum erro visível.
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    if capitulo.livro_id != livro_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"O capítulo {capitulo_id} é do livro {capitulo.livro_id}, não do "
                f"livro {livro_id}."
            ),
        )
    return capitulo


def exigir_imagem(sessao: Session, imagem_id: int) -> None:
    """Confere que a imagem-âncora existe, para o erro sair claro.

    Sem isto, a chave estrangeira falharia no commit e o app receberia um 500.
    """
    imagem = buscar_visivel(sessao, Imagem, imagem_id)
    if imagem is None or imagem.apagada_em is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Não existe imagem com id {imagem_id}.",
        )


def sugestoes_de_elemento_do_livro(
    sessao: Session, ids: list[int], livro_id: int
) -> list[SugestaoDeElemento]:
    """Carrega as sugestões pedidas, exigindo que sejam todas do mesmo livro.

    Mesmo padrão de `_estados_do_livro` (item 6.4): a sugestão aponta para um
    capítulo, e nada impede pedir a sugestão de um capítulo de outro livro.
    """
    pedidos = list(dict.fromkeys(ids))
    if not pedidos:
        return []

    encontradas = list(
        sessao.scalars(select(SugestaoDeElemento).where(SugestaoDeElemento.id.in_(pedidos)))
    )
    ausentes = sorted(set(pedidos) - {sugestao.id for sugestao in encontradas})
    if ausentes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existem sugestões de elemento com os ids {ausentes}.",
        )

    livros_por_sugestao = dict(
        sessao.execute(
            select(SugestaoDeElemento.id, Capitulo.livro_id)
            .join(Capitulo, Capitulo.id == SugestaoDeElemento.capitulo_id)
            .where(SugestaoDeElemento.id.in_(pedidos))
        ).all()
    )
    de_outro_livro = sorted(
        identificador for identificador, dono in livros_por_sugestao.items() if dono != livro_id
    )
    if de_outro_livro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"As sugestões {de_outro_livro} são de outro livro, não do livro {livro_id}."
            ),
        )

    por_id = {sugestao.id: sugestao for sugestao in encontradas}
    return [por_id[identificador] for identificador in pedidos]
