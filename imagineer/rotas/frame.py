"""Rotas de frames (Etapa 6.4).

Um frame é o recorte de um capítulo que vai virar uma imagem — um retrato solo
de um elemento (`tipo=PERSONAGEM`) ou uma cena com vários elementos interagindo
(`tipo=CENA`, item 4.4). O que ele guarda de próprio são o tipo e os atributos
situacionais — horário, clima, humor —, e o que ele referencia são os
**estados** dos elementos, não os elementos: é isso que registra *como* cada um
estava naquele ponto (item 3.4c).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.frame import (
    EstadoComElemento,
    EstadosDoFrame,
    FrameAjuste,
    FrameDetalhe,
    FrameNovo,
    FrameResumo,
)
from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    Frame,
    SugestaoDeFrame,
    TipoDeFrame,
    frames_estados_elemento,
)
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento

rotas_de_capitulo = APIRouter(prefix="/capitulos", tags=["Frames"])
rotas = APIRouter(prefix="/frames", tags=["Frames"])


@rotas_de_capitulo.get(
    "/{capitulo_id}/frames",
    response_model=list[FrameResumo],
    summary="Lista os frames de um capítulo",
)
def listar_frames(
    capitulo_id: int, sessao: Session = Depends(obter_sessao)
) -> list[FrameResumo]:
    """Os frames do capítulo, na ordem em que foram criados.

    O Frame não tem campo ``ordem``, diferente do Capítulo (item 3.4c): os
    frames são criados enquanto o usuário lê o capítulo, então a ordem de
    criação já é a narrativa.
    """
    _buscar_capitulo(sessao, capitulo_id)

    frames = list(
        sessao.scalars(
            select(Frame).where(Frame.capitulo_id == capitulo_id).order_by(Frame.id)
        )
    )
    contagens = _contar_elementos(sessao, [frame.id for frame in frames])

    return [_resumo(frame, contagens.get(frame.id, 0)) for frame in frames]


@rotas_de_capitulo.post(
    "/{capitulo_id}/frames",
    response_model=FrameDetalhe,
    status_code=status.HTTP_201_CREATED,
    summary="Cria um frame",
)
def criar_frame(
    capitulo_id: int, novo: FrameNovo, sessao: Session = Depends(obter_sessao)
) -> FrameDetalhe:
    """Cria o frame e, se vier, já liga os estados dos elementos que aparecem nele.

    Com ``sugestao_frame_id`` (item 3.4e), título/descrição/atributos e
    ``estados_ids`` ausentes do pedido são pré-preenchidos a partir da
    ``SugestaoDeFrame`` referenciada — um valor explícito no pedido sempre
    vence sobre o da sugestão.
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)

    sugestao = None
    if novo.sugestao_frame_id is not None:
        sugestao = _buscar_sugestao_de_frame(sessao, novo.sugestao_frame_id, capitulo_id)

    titulo = novo.titulo if novo.titulo is not None else (sugestao.titulo if sugestao else None)
    descricao = (
        novo.descricao if novo.descricao is not None else (sugestao.descricao if sugestao else None)
    )
    horario = novo.horario if novo.horario is not None else (sugestao.horario if sugestao else None)
    clima = novo.clima if novo.clima is not None else (sugestao.clima if sugestao else None)
    humor = novo.humor if novo.humor is not None else (sugestao.humor if sugestao else None)

    estados_ids = novo.estados_ids
    if not estados_ids and sugestao is not None:
        estados_ids = _resolver_estados_da_sugestao(sessao, sugestao, capitulo)

    _exigir_contagem_valida(novo.tipo, estados_ids)
    estados = _estados_do_livro(sessao, estados_ids, capitulo.livro_id)

    frame = Frame(
        capitulo_id=capitulo.id,
        tipo=novo.tipo,
        titulo=_resolver_titulo(novo.tipo, titulo, estados),
        descricao=descricao,
        horario=horario,
        clima=clima,
        humor=humor,
    )
    frame.estados_elemento = estados

    sessao.add(frame)
    sessao.commit()
    sessao.refresh(frame)

    if sugestao is not None:
        sugestao.frame_id = frame.id
        sessao.commit()

    return _detalhe(sessao, frame)


@rotas.get("/{frame_id}", response_model=FrameDetalhe, summary="Abre um frame")
def abrir_frame(frame_id: int, sessao: Session = Depends(obter_sessao)) -> FrameDetalhe:
    """O frame com os elementos que aparecem nele, cada um no seu estado."""
    return _detalhe(sessao, _buscar_frame(sessao, frame_id))


@rotas.patch("/{frame_id}", response_model=FrameDetalhe, summary="Ajusta um frame")
def ajustar_frame(
    frame_id: int, ajuste: FrameAjuste, sessao: Session = Depends(obter_sessao)
) -> FrameDetalhe:
    """Muda título, descrição ou os atributos situacionais."""
    frame = _buscar_frame(sessao, frame_id)

    for campo, valor in ajuste.model_dump(exclude_unset=True).items():
        setattr(frame, campo, valor)

    sessao.commit()
    sessao.refresh(frame)
    return _detalhe(sessao, frame)


@rotas.put(
    "/{frame_id}/estados",
    response_model=FrameDetalhe,
    summary="Define quem aparece no frame",
)
def definir_estados(
    frame_id: int, corpo: EstadosDoFrame, sessao: Session = Depends(obter_sessao)
) -> FrameDetalhe:
    """Substitui a lista completa de estados do frame pela que veio no pedido.

    É ``PUT`` porque o app manda o conjunto inteiro: na tela, o usuário marca e
    desmarca elementos e salva. Trocar a lista **não** apaga estado nenhum — só
    desfaz as ligações.
    """
    frame = _buscar_frame(sessao, frame_id)
    _exigir_contagem_valida(frame.tipo, corpo.estados_ids)
    capitulo = _buscar_capitulo(sessao, frame.capitulo_id)

    frame.estados_elemento = _estados_do_livro(sessao, corpo.estados_ids, capitulo.livro_id)
    sessao.commit()
    sessao.refresh(frame)
    return _detalhe(sessao, frame)


@rotas.delete(
    "/{frame_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove um frame"
)
def remover_frame(frame_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga o frame e os prompts dele — mas **não** os estados que ele citava.

    Um estado pertence ao elemento e à narrativa, não ao frame que o referenciou
    (item 3.4c).
    """
    sessao.delete(_buscar_frame(sessao, frame_id))
    sessao.commit()


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _exigir_contagem_valida(tipo: TipoDeFrame, estados_ids: list[int]) -> None:
    """Um frame de personagem é um retrato solo — nada de citar outro elemento.

    A regra é de contagem, não de conteúdo: exatamente um estado, para o prompt
    usar só a descrição daquele elemento (item 4.4). Um frame de cena aceita
    qualquer quantidade, inclusive zero (o usuário ainda pode estar montando).
    """
    if tipo == TipoDeFrame.PERSONAGEM and len(dict.fromkeys(estados_ids)) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Um frame do tipo PERSONAGEM aceita exatamente um estado — é "
                "um retrato solo, não uma cena. Use tipo CENA para vários "
                "elementos interagindo."
            ),
        )


def _resolver_titulo(
    tipo: TipoDeFrame, titulo: str | None, estados: list[EstadoElemento]
) -> str:
    """Decide o título quando o pedido não trouxe um.

    Para CENA não há como adivinhar — título e descrição são a própria conta do
    usuário sobre quem, onde e o quê, e o livro não pode inventar isso por ele
    (item 4.4). Para PERSONAGEM o nome do elemento já veio em `estados_ids`, e
    esse é exatamente o único elemento do retrato — gerar "Retrato de X" evita
    pedir de novo uma informação que o pedido já contém.
    """
    if titulo:
        return titulo
    if tipo == TipoDeFrame.PERSONAGEM and estados:
        return f"Retrato de {estados[0].elemento.nome}"
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="O campo 'titulo' é obrigatório para frames do tipo CENA.",
    )


def _buscar_sugestao_de_frame(
    sessao: Session, sugestao_frame_id: int, capitulo_id: int
) -> SugestaoDeFrame:
    sugestao = sessao.get(SugestaoDeFrame, sugestao_frame_id)
    if sugestao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe sugestão de frame com id {sugestao_frame_id}.",
        )
    if sugestao.capitulo_id != capitulo_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"A sugestão {sugestao_frame_id} é do capítulo {sugestao.capitulo_id}, "
                f"não do capítulo {capitulo_id}."
            ),
        )
    return sugestao


def _resolver_estados_da_sugestao(
    sessao: Session, sugestao: SugestaoDeFrame, capitulo: Capitulo
) -> list[int]:
    """Resolve ``estados_ids`` a partir dos participantes de uma sugestão de frame.

    Cada participante precisa já ter ``elemento_id`` resolvido — sem isso não há
    como saber qual estado usar, e confirmar elemento sempre vem antes de
    confirmar frame (item 3.4e). Usa o **estado vigente** de cada elemento até
    este capítulo (mesma função do item 6.3), não exige um estado criado *neste*
    capítulo especificamente.
    """
    pendentes = [p.nome for p in sugestao.participantes if p.elemento_id is None]
    if pendentes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Confirme primeiro os elementos desta cena, antes de criar o "
                f"frame a partir dela: ainda faltam {', '.join(pendentes)}."
            ),
        )

    elementos_ids = [p.elemento_id for p in sugestao.participantes]
    vigentes = estado_vigente_por_elemento(sessao, capitulo.livro_id, capitulo.ordem)

    sem_estado = [
        eid for eid in elementos_ids if eid not in vigentes
    ]
    if sem_estado:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Os elementos {sem_estado} ainda não têm nenhum estado registrado "
                "até este capítulo."
            ),
        )

    return [vigentes[eid].id for eid in elementos_ids]


def _estados_do_livro(
    sessao: Session, estados_ids: list[int], livro_id: int
) -> list[EstadoElemento]:
    """Carrega os estados pedidos, exigindo que sejam todos do mesmo livro.

    Nada no banco impede associar a um frame o estado de um personagem de outro
    livro: o frame aponta para um capítulo e o estado aponta para um elemento, e
    as duas cadeias são independentes. Sem esta checagem o prompt sairia com um
    personagem que não pertence à história.

    Ids repetidos são contados uma vez. A chave primária da tabela de associação já
    impediria o repetido, e devolver erro por isso só criaria trabalho para o app.
    """
    pedidos = list(dict.fromkeys(estados_ids))
    if not pedidos:
        return []

    encontrados = list(
        sessao.scalars(select(EstadoElemento).where(EstadoElemento.id.in_(pedidos)))
    )

    ausentes = sorted(set(pedidos) - {estado.id for estado in encontrados})
    if ausentes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existem estados com os ids {ausentes}.",
        )

    livros_por_estado = dict(
        sessao.execute(
            select(EstadoElemento.id, Elemento.livro_id)
            .join(Elemento, Elemento.id == EstadoElemento.elemento_id)
            .where(EstadoElemento.id.in_(pedidos))
        ).all()
    )
    de_outro_livro = sorted(
        identificador
        for identificador, dono in livros_por_estado.items()
        if dono != livro_id
    )
    if de_outro_livro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Os estados {de_outro_livro} pertencem a elementos de outro livro, "
                f"não do livro {livro_id}."
            ),
        )

    # Devolve na ordem em que o app pediu, que é a ordem que a tela mostra.
    por_id = {estado.id: estado for estado in encontrados}
    return [por_id[identificador] for identificador in pedidos]


def _contar_elementos(sessao: Session, frames_ids: list[int]) -> dict[int, int]:
    """Quantos estados cada frame referencia, numa consulta só."""
    if not frames_ids:
        return {}

    return dict(
        sessao.execute(
            select(
                frames_estados_elemento.c.frame_id,
                func.count(frames_estados_elemento.c.estado_elemento_id),
            )
            .where(frames_estados_elemento.c.frame_id.in_(frames_ids))
            .group_by(frames_estados_elemento.c.frame_id)
        ).all()
    )


def _resumo(frame: Frame, total: int) -> FrameResumo:
    return FrameResumo(
        id=frame.id,
        capitulo_id=frame.capitulo_id,
        tipo=frame.tipo,
        titulo=frame.titulo,
        descricao=frame.descricao,
        horario=frame.horario,
        clima=frame.clima,
        humor=frame.humor,
        total_de_elementos=total,
    )


def _detalhe(sessao: Session, frame: Frame) -> FrameDetalhe:
    """O frame com cada estado acompanhado da identidade do elemento."""
    linhas = sessao.execute(
        select(
            EstadoElemento.id,
            Elemento.id,
            Elemento.tipo,
            Elemento.nome,
            EstadoElemento.descricao,
            EstadoElemento.capitulo_id,
        )
        .join(Elemento, Elemento.id == EstadoElemento.elemento_id)
        .join(
            frames_estados_elemento,
            frames_estados_elemento.c.estado_elemento_id == EstadoElemento.id,
        )
        .where(frames_estados_elemento.c.frame_id == frame.id)
        .order_by(Elemento.tipo, Elemento.nome)
    ).all()

    elementos = [
        EstadoComElemento(
            estado_id=estado_id,
            elemento_id=elemento_id,
            tipo=tipo,
            nome=nome,
            descricao=descricao,
            capitulo_id=capitulo_id,
        )
        for estado_id, elemento_id, tipo, nome, descricao, capitulo_id in linhas
    ]

    return FrameDetalhe(
        **_resumo(frame, len(elementos)).model_dump(),
        elementos=elementos,
        contexto_do_livro=frame.contexto_do_livro,
    )


def _buscar_frame(sessao: Session, frame_id: int) -> Frame:
    frame = sessao.get(Frame, frame_id)
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe frame com id {frame_id}.",
        )
    return frame


def _buscar_capitulo(sessao: Session, capitulo_id: int) -> Capitulo:
    capitulo = sessao.get(Capitulo, capitulo_id)
    if capitulo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe capítulo com id {capitulo_id}.",
        )
    return capitulo
