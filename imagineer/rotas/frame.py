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
    ImagemCanonicaDoFrame,
    ImagemCanonicaNova,
    ImagemOcultaNova,
    ReferenciasDoFrame,
    VinculosDoFrame,
)
from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    Frame,
    Imagem,
    SugestaoDeCena,
    TipoDeFrame,
    TipoElemento,
    frames_estados_elemento,
)
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento
from imagineer.servicos.lixeira import mover_frame_para_a_lixeira
from imagineer.servicos.posicao_no_texto import tamanho_em_utf16
from imagineer.rotas._comum import (
    buscar_capitulo as _buscar_capitulo,
    buscar_frame as _buscar_frame,
)

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
            select(Frame).where(Frame.capitulo_id == capitulo_id, Frame.apagado_em.is_(None)).order_by(Frame.id)
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

    Com ``sugestao_cena_id`` (item 3.4e), título/descrição/atributos e
    ``estados_ids`` ausentes do pedido são pré-preenchidos a partir da
    ``SugestaoDeCena`` referenciada — um valor explícito no pedido sempre
    vence sobre o da sugestão.
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)

    sugestao = None
    if novo.sugestao_cena_id is not None:
        sugestao = _buscar_sugestao_de_cena(sessao, novo.sugestao_cena_id, capitulo_id)
        _exigir_cena_ainda_nao_confirmada(sugestao)

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

    _exigir_posicao_valida(capitulo, novo.posicao_no_texto)
    _exigir_contagem_valida(novo.tipo, estados_ids)
    estados = _estados_do_livro(sessao, estados_ids, capitulo.livro_id)
    vinculados = _estados_do_livro(sessao, novo.estados_vinculados_ids, capitulo.livro_id)
    _exigir_vinculos_validos(novo.tipo, estados, vinculados)

    frame = Frame(
        capitulo_id=capitulo.id,
        tipo=novo.tipo,
        titulo=_resolver_titulo(novo.tipo, titulo, estados),
        descricao=descricao,
        horario=horario,
        clima=clima,
        humor=humor,
        posicao_no_texto=novo.posicao_no_texto,
    )
    frame.estados_elemento = estados
    frame.estados_vinculados = vinculados

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
    """Muda título, descrição, os atributos situacionais ou a posição no texto.

    ``posicao_no_texto: null`` tira o frame da posição (ele cai para a da sugestão, ou para a faixa
    "sem posição").
    """
    frame = _buscar_frame(sessao, frame_id)
    _exigir_posicao_valida(frame.capitulo, ajuste.posicao_no_texto)

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

    novos = _estados_do_livro(sessao, corpo.estados_ids, capitulo.livro_id)
    # V4: trocar o sujeito revalida os vínculos que ele já tinha (o novo sujeito pode ser um personagem, que é individual).
    _exigir_vinculos_validos(frame.tipo, novos, list(frame.estados_vinculados))
    frame.estados_elemento = novos
    sessao.commit()
    sessao.refresh(frame)
    return _detalhe(sessao, frame)


@rotas.put(
    "/{frame_id}/vinculos",
    response_model=FrameDetalhe,
    summary="Define os elementos vinculados ao sujeito do retrato",
)
def definir_vinculos(
    frame_id: int, corpo: VinculosDoFrame, sessao: Session = Depends(obter_sessao)
) -> FrameDetalhe:
    """Substitui os vinculados do retrato pelos que vieram (V4); lista vazia tira todos.

    Só vale em frame ``PERSONAGEM`` cujo sujeito **não** é um personagem; os vinculados podem ser de qualquer tipo (V2, V3 revisto).
    **Não** refaz os prompts que já existem (V7): o próximo **Novo prompt** usa estes vínculos.
    """
    frame = _buscar_frame(sessao, frame_id)
    capitulo = _buscar_capitulo(sessao, frame.capitulo_id)
    vinculados = _estados_do_livro(sessao, corpo.estados_ids, capitulo.livro_id)
    _exigir_vinculos_validos(frame.tipo, list(frame.estados_elemento), vinculados)

    frame.estados_vinculados = vinculados
    sessao.commit()
    sessao.refresh(frame)
    return _detalhe(sessao, frame)


@rotas.put(
    "/{frame_id}/referencias",
    response_model=FrameDetalhe,
    summary="Guarda as imagens de referência escolhidas para a próxima geração",
)
def definir_referencias(
    frame_id: int, corpo: ReferenciasDoFrame, sessao: Session = Depends(obter_sessao)
) -> FrameDetalhe:
    """Substitui as imagens de referência **escolhidas** do frame (RS1, RS3); lista vazia limpa a escolha.

    Só **guarda**: quem manda a geração continua sendo o app, que lê isto ao abrir o frame. Cada id tem de ser de uma imagem
    do catálogo que **não** esteja na lixeira, sem repetir, e são no máximo 4 (o limite do envio, W3).
    """
    frame = _buscar_frame(sessao, frame_id)
    ids = list(dict.fromkeys(corpo.imagens_ids))
    if len(ids) != len(corpo.imagens_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Há imagens repetidas entre as referências.")
    for imagem_id in ids:
        imagem = sessao.get(Imagem, imagem_id)
        if imagem is None or imagem.apagada_em is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Não existe imagem com id {imagem_id} para usar como referência."
            )
    frame.imagens_de_referencia = ids
    sessao.commit()
    sessao.refresh(frame)
    return _detalhe(sessao, frame)


def _imagem_pode_ser_canonica(frame: Frame, imagem: Imagem) -> bool:
    """A imagem é de um prompt **deste** frame ou, num **retrato**, de outro retrato **do mesmo elemento** (VM3: usar uma imagem que
    já existe, de outro capítulo, sem gerar nada)."""
    outro = imagem.prompt.frame
    if outro is None:
        return False
    if outro.id == frame.id:
        return True
    if frame.tipo != TipoDeFrame.PERSONAGEM or outro.tipo != TipoDeFrame.PERSONAGEM:
        return False
    if len(frame.estados_elemento) != 1 or len(outro.estados_elemento) != 1:
        return False
    return frame.estados_elemento[0].elemento_id == outro.estados_elemento[0].elemento_id


@rotas.put(
    "/{frame_id}/imagem-canonica",
    response_model=ImagemCanonicaDoFrame,
    summary="Escolhe a imagem canônica do frame (a que o capítulo mostra)",
)
def definir_imagem_canonica(
    frame_id: int, corpo: ImagemCanonicaNova, sessao: Session = Depends(obter_sessao)
) -> ImagemCanonicaDoFrame:
    """Marca uma das variações como a **canônica** do frame (CAN1 a CAN3); `null` tira a escolha.

    No **retrato** de um elemento ela é também a **âncora** do estado dele (a referência do item 4.5) e, se o elemento ainda
    não tem âncora padrão, passa a ser a padrão; uma padrão já escolhida **não** é trocada (CAN2). As outras variações ficam
    como alternativas: nada é apagado.
    """
    frame = _buscar_frame(sessao, frame_id)
    anterior = frame.imagem_canonica_id
    if corpo.imagem_id is not None:
        imagem = sessao.get(Imagem, corpo.imagem_id)
        if imagem is None or imagem.apagada_em is not None or not _imagem_pode_ser_canonica(frame, imagem):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Essa imagem não é de um prompt deste frame.",
            )
    frame.imagem_canonica_id = corpo.imagem_id
    if corpo.imagem_id is not None:
        frame.imagem_oculta = False  # OC3: escolher uma canônica é querer vê-la no capítulo

    if frame.tipo == TipoDeFrame.PERSONAGEM and len(frame.estados_elemento) == 1:
        estado = frame.estados_elemento[0]
        if corpo.imagem_id is not None:
            estado.imagem_ancora_id = corpo.imagem_id
            if estado.elemento.imagem_ancora_padrao_id is None:
                estado.elemento.imagem_ancora_padrao_id = corpo.imagem_id
        elif anterior is not None and estado.imagem_ancora_id == anterior:
            estado.imagem_ancora_id = None  # só solta a âncora se era a mesma imagem (CAN3)

    sessao.commit()
    return ImagemCanonicaDoFrame(frame_id=frame.id, imagem_canonica_id=frame.imagem_canonica_id, imagem_oculta=frame.imagem_oculta)


@rotas.put(
    "/{frame_id}/imagem-oculta",
    response_model=ImagemCanonicaDoFrame,
    summary="Oculta (ou volta a mostrar) a imagem do frame no capítulo, sem apagar nada",
)
def definir_imagem_oculta(frame_id: int, corpo: ImagemOcultaNova, sessao: Session = Depends(obter_sessao)) -> ImagemCanonicaDoFrame:
    """OC1 a OC3: o capítulo deixa de mostrar a imagem do frame (o artefato volta a ser só o ícone). Nenhuma imagem é apagada
    nem sai da galeria ou do perfil do elemento; vale só no capítulo."""
    frame = _buscar_frame(sessao, frame_id)
    frame.imagem_oculta = corpo.oculta
    sessao.commit()
    return ImagemCanonicaDoFrame(frame_id=frame.id, imagem_canonica_id=frame.imagem_canonica_id, imagem_oculta=frame.imagem_oculta)


@rotas.delete(
    "/{frame_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove um frame"
)
def remover_frame(frame_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Move o frame **para a lixeira** (LT3): ele some do capítulo, dos ícones e da galeria, com os prompts e as imagens dele, mas
    **nada é apagado**. Só "apagar de vez", na lixeira, remove o frame, os prompts e as imagens (com os arquivos). Os estados que ele
    citava nunca vão junto: um estado pertence ao elemento e à narrativa, não ao frame (item 3.4c).

    A cena sugerida que ele confirmara **volta a ser pendente**. Mover de novo um frame que já está na lixeira não dá erro.
    """
    frame = sessao.get(Frame, frame_id)
    if frame is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Não existe frame com id {frame_id}.")
    mover_frame_para_a_lixeira(sessao, frame)
    sessao.commit()


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _exigir_posicao_valida(capitulo: Capitulo, posicao: int | None) -> None:
    """422 se a posição escolhida passa do fim do texto do capítulo, contado em UTF-16 (item 3.4g).

    ``None`` é válido (sem posição); a negativa o esquema já recusa.
    """
    if posicao is None:
        return
    tamanho = tamanho_em_utf16(capitulo.texto)
    if posicao > tamanho:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A posição {posicao} passa do fim do capítulo, que tem {tamanho} unidades UTF-16.",
        )


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


MAXIMO_DE_VINCULADOS = 4
"""Quantos elementos podem se vincular ao sujeito de um retrato (V3)."""


def _exigir_vinculos_validos(
    tipo: TipoDeFrame, sujeitos: list[EstadoElemento], vinculados: list[EstadoElemento]
) -> None:
    """As regras V2 e V3 do retrato com elementos vinculados. Sem vinculados não há o que conferir.

    **O retrato de um personagem é individual** (V2, decisão do Allan, 02/10/2026): o **sujeito** não pode ser ``PERSONAGEM``.
    Um personagem **pode ser vinculado** ao retrato de outro elemento (V3 revisto em 03/10/2026: *"a Auri não apareceu no
    elemento do Porto"*). O sujeito é o único estado do frame de retrato (``_exigir_contagem_valida`` garante isso).
    """
    if not vinculados:
        return

    def _422(detalhe: str) -> HTTPException:
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detalhe)

    if tipo != TipoDeFrame.PERSONAGEM:
        raise _422("Vínculos só valem num retrato (tipo PERSONAGEM): a cena já tem os seus participantes.")
    if len(vinculados) > MAXIMO_DE_VINCULADOS:
        raise _422(f"No máximo {MAXIMO_DE_VINCULADOS} elementos vinculados por retrato.")
    sujeito = sujeitos[0].elemento if sujeitos else None
    if sujeito is not None and sujeito.tipo == TipoElemento.PERSONAGEM:
        raise _422(
            f"{sujeito.nome} é um personagem: o retrato de um personagem é sempre só dele. "
            "Para um personagem junto de outro elemento, use uma cena."
        )
    vistos: set[int] = set()
    for estado in vinculados:
        elemento = estado.elemento
        if sujeito is not None and elemento.id == sujeito.id:
            raise _422(f"{elemento.nome} é o próprio sujeito do retrato: não pode ser vinculado a si mesmo.")
        if elemento.id in vistos:
            raise _422(f"{elemento.nome} aparece duas vezes entre os vinculados.")
        vistos.add(elemento.id)


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


def _buscar_sugestao_de_cena(
    sessao: Session, sugestao_cena_id: int, capitulo_id: int
) -> SugestaoDeCena:
    sugestao = sessao.get(SugestaoDeCena, sugestao_cena_id)
    if sugestao is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe sugestão de cena com id {sugestao_cena_id}.",
        )
    if sugestao.capitulo_id != capitulo_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"A sugestão {sugestao_cena_id} é do capítulo {sugestao.capitulo_id}, "
                f"não do capítulo {capitulo_id}."
            ),
        )
    return sugestao


def _exigir_cena_ainda_nao_confirmada(sugestao: SugestaoDeCena) -> None:
    """Impede confirmar a mesma cena sugerida duas vezes (item 4.6/6.4).

    Sem isto, cada chamada criava um Frame novo, sobrescrevendo
    `SugestaoDeCena.frame_id` sem aviso — o Frame anterior ficava órfão no
    banco (achado testando: três confirmações seguidas, três Frames, só o
    último referenciado). Mesmo padrão já usado para elemento duplicado
    (item 6.3): 409 com o id do registro existente, para o app oferecer
    abrir o Frame já criado em vez de duplicar. Vale só para
    `sugestao_cena_id` — um frame manual com `estados_ids` continua livre,
    porque duas cenas com os mesmos participantes podem ser legítimas.
    """
    if sugestao.frame_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Esta sugestão de cena já virou o frame {sugestao.frame_id}. "
                "Abra o frame existente em vez de confirmar de novo."
            ),
        )


def _resolver_estados_da_sugestao(
    sessao: Session, sugestao: SugestaoDeCena, capitulo: Capitulo
) -> list[int]:
    """Resolve ``estados_ids`` a partir dos participantes de uma cena sugerida.

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
        posicao_no_texto=frame.posicao_no_texto,
        total_de_elementos=total,
        imagem_canonica_id=frame.imagem_canonica_id,
        imagem_oculta=frame.imagem_oculta,
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

    vinculados = [
        EstadoComElemento(
            estado_id=estado.id,
            elemento_id=estado.elemento.id,
            tipo=estado.elemento.tipo,
            nome=estado.elemento.nome,
            descricao=estado.descricao,
            capitulo_id=estado.capitulo_id,
        )
        for estado in sorted(frame.estados_vinculados, key=lambda e: (e.elemento.tipo.name, e.elemento.nome))
    ]

    # RS1: só as referências que continuam ativas (uma imagem que foi para a lixeira ou foi apagada de vez sai da escolha).
    guardadas = list(frame.imagens_de_referencia or [])
    ativas = set(
        sessao.scalars(select(Imagem.id).where(Imagem.id.in_(guardadas), Imagem.apagada_em.is_(None)))
    ) if guardadas else set()

    return FrameDetalhe(
        **_resumo(frame, len(elementos)).model_dump(),
        elementos=elementos,
        vinculados=vinculados,
        imagens_de_referencia=[i for i in guardadas if i in ativas],
        contexto_do_livro=frame.contexto_do_livro,
    )


