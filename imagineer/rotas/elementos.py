"""Rotas de elementos e estados (Etapa 6.3).

O coração da catalogação: manter a identidade de cada elemento recorrente e o
histórico de como ele estava em cada ponto da narrativa (item 3.4b). É o que o
passo 7 do fluxo alimenta e o passo 8 consome.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.elemento import (
    CenaDoElemento,
    ElementoAjuste,
    ElementoDetalhe,
    ElementoMesclagem,
    ElementoNovo,
    ElementoResumo,
    EstadoAjuste,
    EstadoComIdentidadeDoElemento,
    EstadoNovo,
    EstadoResumo,
    EstadosDeSugestoes,
    GaleriaDoElemento,
    HistoricoIdentidadeAjuste,
    HistoricoIdentidadeNovo,
    HistoricoIdentidadeResumo,
    ImagemDoElemento,
)
from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    Frame,
    HistoricoIdentidadeElemento,
    Imagem,
    Prompt,
    SugestaoDeElemento,
    TipoDeFrame,
    TipoElemento,
    frames_estados_elemento,
)
from imagineer.rotas._comum import (
    buscar_acrescimo as _buscar_acrescimo,
    buscar_capitulo as _buscar_capitulo,
    buscar_elemento as _buscar_elemento,
    buscar_estado as _buscar_estado,
    buscar_livro as _buscar_livro,
)
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento
from imagineer.servicos.imagens_reduzidas import orientacao_de
from imagineer.servicos.lixeira import mover_elemento_para_a_lixeira

rotas_de_livro = APIRouter(prefix="/livros", tags=["Elementos"])
rotas = APIRouter(prefix="/elementos", tags=["Elementos"])
rotas_de_estado = APIRouter(prefix="/estados", tags=["Elementos"])
rotas_de_capitulo = APIRouter(prefix="/capitulos", tags=["Elementos"])
rotas_de_sugestao_elemento = APIRouter(prefix="/sugestoes-elemento", tags=["Elementos"])
rotas_de_sugestao_cena = APIRouter(prefix="/sugestoes-cena", tags=["Elementos"])
rotas_de_identidade = APIRouter(prefix="/historico-identidade", tags=["Elementos"])


# --------------------------------------------------------------------------- #
# Elementos de um livro
# --------------------------------------------------------------------------- #


@rotas_de_livro.get(
    "/{livro_id}/elementos",
    response_model=list[ElementoResumo],
    summary="Lista os elementos de um livro",
)
def listar_elementos(
    livro_id: int,
    tipo: TipoElemento | None = Query(
        default=None, description="Filtra por tipo, para a tela separar em abas."
    ),
    sessao: Session = Depends(obter_sessao),
) -> list[ElementoResumo]:
    """Os elementos do livro, cada um com o seu estado mais recente.

    "Mais recente" é pela ordem **narrativa** e não pela data de cadastro — ver
    ``servicos.estados_de_elemento``.
    """
    _buscar_livro(sessao, livro_id)
    return _montar_resumos(sessao, livro_id, tipo=tipo, ordem_limite=None)


@rotas_de_livro.post(
    "/{livro_id}/elementos",
    response_model=ElementoDetalhe,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastra um elemento",
)
def criar_elemento(
    livro_id: int,
    novo: ElementoNovo,
    sessao: Session = Depends(obter_sessao),
) -> ElementoDetalhe:
    """Cria o elemento e, se vier, o(s) primeiro(s) estado(s) dele — num pedido só.

    O passo 7 do fluxo confirma as duas coisas ao mesmo tempo: que o personagem
    existe e como ele está naquele capítulo. Em dois pedidos, uma falha no meio
    deixaria um elemento sem estado nenhum.

    ``sugestoes_elemento_ids`` (item 3.4e) acrescenta um Estado por sugestão
    escolhida, cada uma do seu próprio capítulo — resolve o caso em que a IA
    sugeriu o mesmo personagem em capítulos diferentes sem casar pelo nome.
    Pode vir junto com ``estado_inicial``.

    ``tipo``/``nome`` são opcionais quando vêm sugestões: sem ambiguidade,
    confirmar não deveria exigir redigitar o que a IA já identificou — usa o
    da primeira sugestão da lista. Sem nenhuma sugestão, os dois continuam
    obrigatórios (422 sem eles).
    """
    _buscar_livro(sessao, livro_id)
    sugestoes = _sugestoes_de_elemento_do_livro(sessao, novo.sugestoes_elemento_ids, livro_id)
    tipo, nome = _resolver_tipo_e_nome(novo.tipo, novo.nome, sugestoes)

    elemento = Elemento(livro_id=livro_id, tipo=tipo, nome=nome, descricao=novo.descricao)

    estados = []
    if novo.estado_inicial is not None:
        capitulo = _buscar_capitulo_do_livro(sessao, novo.estado_inicial.capitulo_id, livro_id)
        estados.append(
            EstadoElemento(capitulo_id=capitulo.id, descricao=novo.estado_inicial.descricao)
        )
    for sugestao in sugestoes:
        estados.append(
            EstadoElemento(capitulo_id=sugestao.capitulo_id, descricao=sugestao.descricao or "")
        )
    elemento.estados = estados

    sessao.add(elemento)
    _gravar(sessao, _conflito_de_elemento(sessao, livro_id, tipo, nome))
    sessao.refresh(elemento)

    if sugestoes:
        for sugestao in sugestoes:
            sugestao.elemento_id = elemento.id
        sessao.commit()

    return _detalhe(sessao, elemento)


# --------------------------------------------------------------------------- #
# Um elemento
# --------------------------------------------------------------------------- #


@rotas.get("/{elemento_id}", response_model=ElementoDetalhe, summary="Abre um elemento")
def abrir_elemento(
    elemento_id: int, sessao: Session = Depends(obter_sessao)
) -> ElementoDetalhe:
    """O elemento com todos os seus estados, em ordem narrativa."""
    return _detalhe(sessao, _buscar_elemento(sessao, elemento_id))


@rotas.get(
    "/{elemento_id}/galeria",
    response_model=GaleriaDoElemento,
    summary="As imagens e as cenas do elemento, para a ficha dele",
)
def galeria_do_elemento(elemento_id: int, sessao: Session = Depends(obter_sessao)) -> GaleriaDoElemento:
    """As imagens dos **retratos** do elemento e as **cenas** em que ele participa (FI1 a FI3). Nunca chama a IA.

    ``imagens``: de todos os frames de retrato dele (``PERSONAGEM``, só ele), mais recentes primeiro. ``cenas``: os frames
    ``CENA`` em que um estado dele participa, por ordem narrativa; cena sem imagem também aparece.
    """
    elemento = _buscar_elemento(sessao, elemento_id)
    ancoras = {elemento.imagem_ancora_padrao_id} | {e.imagem_ancora_id for e in elemento.estados}
    ancoras.discard(None)

    imagens: dict[int, ImagemDoElemento] = {}
    cenas: dict[int, CenaDoElemento] = {}
    for estado in elemento.estados:
        for frame in estado.frames:
            if frame.apagado_em is not None:  # na lixeira (LT3)
                continue
            capitulo = frame.capitulo
            if frame.tipo == TipoDeFrame.PERSONAGEM and len(frame.estados_elemento) == 1:
                for prompt in frame.prompts:
                    for imagem in prompt.imagens_ativas:
                        orientacao = orientacao_de(imagem.largura, imagem.altura)
                        imagens[imagem.id] = ImagemDoElemento(
                            id=imagem.id,
                            prompt_id=prompt.id,
                            frame_id=frame.id,
                            capitulo_id=capitulo.id,
                            titulo_do_capitulo=capitulo.titulo,
                            ordem_do_capitulo=capitulo.ordem,
                            largura=imagem.largura,
                            altura=imagem.altura,
                            orientacao=orientacao.value if orientacao else None,
                            modelo=imagem.modelo,
                            origem=imagem.origem.value,
                            sem_filtro_de_seguranca=imagem.sem_filtro_de_seguranca,
                            data_importacao=imagem.data_importacao,
                            ancora=imagem.id in ancoras,
                            canonica=frame.imagem_canonica_id == imagem.id,
                        )
            elif frame.tipo == TipoDeFrame.CENA and frame.id not in cenas:
                todas = [i for prompt in frame.prompts for i in prompt.imagens_ativas]
                canonica = next((i for i in todas if i.id == frame.imagem_canonica_id), None)
                ultima = canonica or (max(todas, key=lambda i: i.id) if todas else None)
                orientacao = orientacao_de(ultima.largura, ultima.altura) if ultima else None
                cenas[frame.id] = CenaDoElemento(
                    frame_id=frame.id,
                    titulo=frame.titulo,
                    descricao=frame.descricao,
                    capitulo_id=capitulo.id,
                    titulo_do_capitulo=capitulo.titulo,
                    ordem_do_capitulo=capitulo.ordem,
                    participantes=sorted(e.elemento.nome for e in frame.estados_elemento if e.elemento_id != elemento.id),
                    total_de_imagens=len(todas),
                    imagem_id=ultima.id if ultima else None,
                    imagem_orientacao=orientacao.value if orientacao else None,
                )
    return GaleriaDoElemento(
        imagens=sorted(imagens.values(), key=lambda i: i.id, reverse=True),
        cenas=sorted(cenas.values(), key=lambda c: (c.ordem_do_capitulo, c.frame_id)),
    )


@rotas.patch("/{elemento_id}", response_model=ElementoDetalhe, summary="Ajusta um elemento")
def ajustar_elemento(
    elemento_id: int,
    ajuste: ElementoAjuste,
    sessao: Session = Depends(obter_sessao),
) -> ElementoDetalhe:
    """Muda a identidade do elemento: nome, tipo, descrição ou a referência
    visual principal (`imagem_ancora_padrao_id`, item 4.5).

    Não mexe nos estados: a aparência é assunto deles (item 3.4b).
    """
    elemento = _buscar_elemento(sessao, elemento_id)
    campos = ajuste.model_dump(exclude_unset=True)

    if campos.get("imagem_ancora_padrao_id") is not None:
        _exigir_imagem(sessao, campos["imagem_ancora_padrao_id"])

    for campo, valor in campos.items():
        setattr(elemento, campo, valor)

    _gravar(
        sessao,
        _conflito_de_elemento(
            sessao,
            elemento.livro_id,
            campos.get("tipo", elemento.tipo),
            campos.get("nome", elemento.nome),
            ignorando=elemento_id,
        ),
    )
    sessao.refresh(elemento)
    return _detalhe(sessao, elemento)


@rotas.delete(
    "/{elemento_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove um elemento",
)
def remover_elemento(elemento_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Move o elemento **para a lixeira** (LT4), com os estados, a identidade e os retratos dele; nada é apagado. De novo, sem erro.

    As sugestões que o citavam voltam a ser pendentes. Só "apagar de vez", na lixeira, remove tudo (com os arquivos das imagens).
    """
    elemento = sessao.get(Elemento, elemento_id)
    if elemento is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Não existe elemento com id {elemento_id}.")
    mover_elemento_para_a_lixeira(sessao, elemento)
    sessao.commit()


@rotas.post(
    "/{elemento_id}/mesclar",
    response_model=ElementoDetalhe,
    summary="Junta este elemento a outro do mesmo livro",
)
def mesclar_elemento(
    elemento_id: int,
    corpo: ElementoMesclagem,
    sessao: Session = Depends(obter_sessao),
) -> ElementoDetalhe:
    """Junta o elemento (a **origem**) ao `destino_id`, que fica; a origem deixa de existir.

    Existe porque o mesmo personagem (ou lugar, ou veículo) pode ter sido cadastrado duas
    vezes — por exemplo, com tipos diferentes (achado testando no tablet, 30/09/2026) — e o
    servidor não aceita dois elementos com o mesmo tipo e nome no livro, então corrigir o
    tipo de um dava conflito e não havia como juntar os dois.

    **Passam para o destino:** todos os estados de aparência (os frames que os usam
    continuam ligados a eles), todo o histórico de identidade e as sugestões de elemento
    casadas com a origem. **Fica o do destino:** nome, tipo e identidade inicial — que a
    origem só empresta se o destino não tiver uma. A referência visual padrão segue a mesma
    regra. Tudo numa transação: se algo falha, nada muda.
    """
    if corpo.destino_id == elemento_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não dá para juntar um elemento a ele mesmo.",
        )
    origem = _buscar_elemento(sessao, elemento_id)
    destino = _buscar_elemento(sessao, corpo.destino_id)
    if origem.livro_id != destino.livro_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"O elemento {destino.id} é do livro {destino.livro_id}, "
                f"não do livro {origem.livro_id} do elemento {origem.id}."
            ),
        )

    if not destino.descricao and origem.descricao:
        destino.descricao = origem.descricao
    if destino.imagem_ancora_padrao_id is None and origem.imagem_ancora_padrao_id is not None:
        destino.imagem_ancora_padrao_id = origem.imagem_ancora_padrao_id

    # Em massa, e não pela lista `origem.estados`: essa relação apaga o que sobrar nela ao
    # apagar a origem, e os estados já são do destino.
    sessao.execute(
        update(EstadoElemento).where(EstadoElemento.elemento_id == origem.id).values(elemento_id=destino.id)
    )
    sessao.execute(
        update(HistoricoIdentidadeElemento)
        .where(HistoricoIdentidadeElemento.elemento_id == origem.id)
        .values(elemento_id=destino.id)
    )
    sessao.execute(
        update(SugestaoDeElemento)
        .where(SugestaoDeElemento.elemento_id == origem.id)
        .values(elemento_id=destino.id)
    )
    sessao.flush()
    sessao.expire(origem)  # a origem ainda "lembra" os estados que acabaram de sair dela

    sessao.delete(origem)
    sessao.commit()
    sessao.refresh(destino)
    return _detalhe(sessao, destino)


# --------------------------------------------------------------------------- #
# Acréscimos de identidade, à mão (item 7.5b, rodada 5)
# --------------------------------------------------------------------------- #


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
    capitulo = _buscar_capitulo_do_livro(sessao, corpo.capitulo_id, elemento.livro_id)
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


# --------------------------------------------------------------------------- #
# Estados de um elemento
# --------------------------------------------------------------------------- #


@rotas.post(
    "/{elemento_id}/estados",
    response_model=EstadoResumo,
    status_code=status.HTTP_201_CREATED,
    summary="Registra um novo estado",
)
def criar_estado(
    elemento_id: int,
    novo: EstadoNovo,
    sessao: Session = Depends(obter_sessao),
) -> EstadoResumo:
    """Registra como o elemento passa a estar, a partir de um capítulo.

    Vários estados no mesmo capítulo são permitidos de propósito: um personagem
    pode entrar ferido e sair curado (item 3.4b).
    """
    elemento = _buscar_elemento(sessao, elemento_id)
    capitulo = _buscar_capitulo_do_livro(sessao, novo.capitulo_id, elemento.livro_id)

    estado = EstadoElemento(
        elemento_id=elemento.id, capitulo_id=capitulo.id, descricao=novo.descricao
    )
    sessao.add(estado)
    sessao.commit()
    sessao.refresh(estado)
    return EstadoResumo.model_validate(estado)


@rotas.post(
    "/{elemento_id}/estados-de-sugestoes",
    response_model=list[EstadoResumo],
    status_code=status.HTTP_201_CREATED,
    summary="Registra estados a partir de sugestões de elemento (item 3.4e)",
)
def criar_estados_de_sugestoes(
    elemento_id: int,
    corpo: EstadosDeSugestoes,
    sessao: Session = Depends(obter_sessao),
) -> list[EstadoResumo]:
    """Cria um Estado por sugestão escolhida, num elemento **já existente**.

    Rota separada de `POST /elementos/{id}/estados` porque aquela cria um
    estado e devolve um `EstadoResumo`; esta cria vários de uma vez —
    resolve o caso em que a IA sugeriu o mesmo personagem em capítulos
    diferentes sem casar pelo nome, sem o usuário copiar a descrição de cada
    sugestão à mão, uma chamada por capítulo.

    **A descrição de cada Estado criado aqui é um rascunho, não a aparência
    do capítulo.** Vem da sugestão de identidade (fase 1, item 4.4 — "quem é",
    documentada como algo que não muda entre capítulos), não de uma leitura
    do texto daquele capítulo especificamente. Por isso vários estados criados
    por aqui podem sair com o mesmo texto, mesmo sendo capítulos diferentes —
    isso não significa que não há nada novo no capítulo, só que a leitura
    profunda ainda não rodou pra esse estado. Ela roda sozinha, e sobrescreve
    esse rascunho, na primeira vez que um prompt é montado a partir dele
    (`POST /frames/{id}/prompts`) — mesmo princípio de `estado_inicial` em
    `POST /livros/{id}/elementos`.
    """
    elemento = _buscar_elemento(sessao, elemento_id)
    sugestoes = _sugestoes_de_elemento_do_livro(
        sessao, corpo.sugestoes_elemento_ids, elemento.livro_id
    )

    estados = [
        EstadoElemento(
            elemento_id=elemento.id, capitulo_id=sugestao.capitulo_id, descricao=sugestao.descricao or ""
        )
        for sugestao in sugestoes
    ]
    sessao.add_all(estados)
    sessao.commit()
    for estado in estados:
        sessao.refresh(estado)

    for sugestao in sugestoes:
        sugestao.elemento_id = elemento.id
    sessao.commit()

    return [EstadoResumo.model_validate(estado) for estado in estados]


@rotas_de_estado.get(
    "/{estado_id}",
    response_model=EstadoComIdentidadeDoElemento,
    summary="Abre um estado isolado",
)
def abrir_estado(
    estado_id: int, sessao: Session = Depends(obter_sessao)
) -> EstadoComIdentidadeDoElemento:
    """Um estado isolado, com o elemento a que pertence.

    Faltava: só existiam ``PATCH`` e ``DELETE`` para um estado — não havia
    como abrir (ou testar) um estado só pelo id, a não ser abrindo o
    elemento inteiro (``GET /elementos/{id}``) ou pelo estado vigente
    (``GET /capitulos/{id}/estados-vigentes``). Mesmo padrão de ``GET
    /frames/{id}`` (item 6.4): a resposta traz nome/tipo do elemento
    embutidos, para a tela não ter que cruzar duas chamadas.
    """
    estado = _buscar_estado(sessao, estado_id)
    return EstadoComIdentidadeDoElemento(
        **EstadoResumo.model_validate(estado).model_dump(),
        elemento_tipo=estado.elemento.tipo,
        elemento_nome=estado.elemento.nome,
    )


@rotas_de_estado.patch(
    "/{estado_id}", response_model=EstadoResumo, summary="Ajusta um estado"
)
def ajustar_estado(
    estado_id: int,
    ajuste: EstadoAjuste,
    sessao: Session = Depends(obter_sessao),
) -> EstadoResumo:
    """Muda a descrição da aparência ou define a imagem-âncora.

    A imagem-âncora é a referência visual do item 3.1: uma imagem já aprovada
    daquele estado, usada nas gerações seguintes para manter a aparência
    consistente entre capítulos distantes.
    """
    estado = _buscar_estado(sessao, estado_id)
    campos = ajuste.model_dump(exclude_unset=True)

    if campos.get("imagem_ancora_id") is not None:
        _exigir_imagem(sessao, campos["imagem_ancora_id"])

    for campo, valor in campos.items():
        setattr(estado, campo, valor)

    sessao.commit()
    sessao.refresh(estado)
    return EstadoResumo.model_validate(estado)


@rotas_de_estado.delete(
    "/{estado_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove um estado"
)
def remover_estado(estado_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga um estado. O elemento e os frames que o citavam permanecem."""
    sessao.delete(_buscar_estado(sessao, estado_id))
    sessao.commit()


# --------------------------------------------------------------------------- #
# Corrigir o casamento de uma sugestão (item 4.6)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Estados vigentes num capítulo
# --------------------------------------------------------------------------- #


@rotas_de_capitulo.get(
    "/{capitulo_id}/estados-vigentes",
    response_model=list[ElementoResumo],
    summary="O estado de cada elemento neste ponto da narrativa",
)
def listar_estados_vigentes(
    capitulo_id: int, sessao: Session = Depends(obter_sessao)
) -> list[ElementoResumo]:
    """Como estava cada elemento do livro ao chegar neste capítulo.

    É o que dá contexto à IA no passo 6 e ao usuário na tela de revisão. Devolve
    **todos** os elementos do livro, inclusive os que ainda não apareceram — para
    esses, ``estado_vigente`` vem nulo, e esse nulo é informação: significa
    primeira aparição, o caso em que não há estado anterior para mandar à IA.
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    return _montar_resumos(
        sessao, capitulo.livro_id, tipo=None, ordem_limite=capitulo.ordem
    )


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _montar_resumos(
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
    capas = _capas_dos_elementos(sessao, [elemento.id for elemento in elementos])

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


def _capas_dos_elementos(sessao: Session, elementos_ids: list[int]) -> dict[int, int]:
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


def _detalhe(sessao: Session, elemento: Elemento) -> ElementoDetalhe:
    """O elemento com os estados em ordem narrativa.

    A ordenação junta ``Capitulo.ordem`` para seguir a história, e não a ordem de
    cadastro — o usuário pode ter registrado o estado do capítulo 30 antes do
    estado do capítulo 3.
    """
    estados = list(
        sessao.scalars(
            select(EstadoElemento)
            .join(Capitulo, Capitulo.id == EstadoElemento.capitulo_id)
            .where(EstadoElemento.elemento_id == elemento.id)
            .order_by(Capitulo.ordem, EstadoElemento.id)
        )
    )

    historico_identidade = list(
        sessao.scalars(
            select(HistoricoIdentidadeElemento)
            .join(Capitulo, Capitulo.id == HistoricoIdentidadeElemento.capitulo_id)
            .where(HistoricoIdentidadeElemento.elemento_id == elemento.id)
            .order_by(Capitulo.ordem, HistoricoIdentidadeElemento.id)
        )
    )

    return ElementoDetalhe(
        id=elemento.id,
        livro_id=elemento.livro_id,
        tipo=elemento.tipo,
        nome=elemento.nome,
        descricao=elemento.descricao,
        imagem_ancora_padrao_id=elemento.imagem_ancora_padrao_id,
        estados=[
            EstadoResumo.model_validate(estado).model_copy(
                update={
                    "ordem_do_capitulo": estado.capitulo.ordem,
                    "titulo_do_capitulo": estado.capitulo.titulo,
                }
            )
            for estado in estados
        ],
        historico_identidade=[
            HistoricoIdentidadeResumo.model_validate(registro).model_copy(
                update={
                    "ordem_do_capitulo": registro.capitulo.ordem,
                    "titulo_do_capitulo": registro.capitulo.titulo,
                }
            )
            for registro in historico_identidade
        ],
    )


def _gravar(sessao: Session, mensagem_de_conflito) -> None:
    """Grava, traduzindo violação de unicidade em 409.

    A restrição (``livro_id``, ``tipo``, ``nome``) existe porque a extração
    automática reencontra o mesmo personagem em outro capítulo (item 3.4b). Sem
    esta tradução, o app receberia um 500 sem explicação.
    """
    try:
        sessao.commit()
    except IntegrityError as erro:
        sessao.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=mensagem_de_conflito()
        ) from erro


def _resolver_tipo_e_nome(
    tipo: TipoElemento | None, nome: str | None, sugestoes: list[SugestaoDeElemento]
) -> tuple[TipoElemento, str]:
    """Decide tipo/nome quando o pedido não trouxe os dois (item 3.4e).

    Explícito no pedido sempre vence. Faltando, usa a primeira sugestão da
    lista — só faz sentido como padrão porque não há como a rota escolher
    entre nomes diferentes de sugestões diferentes (ex.: "Sextus Hospius" vs.
    "Hospius") sozinha; se vier mais de uma sugestão com nomes divergentes, é
    responsabilidade do usuário digitar o nome canônico que quer.
    """
    if tipo is not None and nome is not None:
        return tipo, nome
    if sugestoes:
        primeira = sugestoes[0]
        return tipo or primeira.tipo, nome or primeira.nome
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=(
            "'tipo' e 'nome' são obrigatórios quando não vem nenhuma sugestão "
            "em sugestoes_elemento_ids."
        ),
    )


def _conflito_de_elemento(
    sessao: Session,
    livro_id: int,
    tipo: TipoElemento,
    nome: str,
    ignorando: int | None = None,
):
    """Devolve uma função que monta a mensagem de conflito, com o id existente.

    É preguiçosa de propósito: só vale a pena procurar o elemento repetido se a
    gravação de fato falhar. E o id vai na mensagem para o app poder oferecer
    "usar o que já existe" em vez de só reclamar.
    """

    def montar() -> str:
        filtros = [
            Elemento.livro_id == livro_id,
            Elemento.tipo == tipo,
            Elemento.nome == nome,
        ]
        if ignorando is not None:
            filtros.append(Elemento.id != ignorando)
        existente = sessao.scalars(select(Elemento).where(*filtros)).first()

        if existente is None:
            return f"Não foi possível gravar o elemento {nome!r}."
        if existente.apagado_em is not None:  # LT4: o nome continua ocupado enquanto ele está na lixeira
            return (
                f"Já existe um elemento do tipo {tipo.name} chamado {nome!r} neste livro, mas ele está na lixeira "
                f"(id {existente.id}). Restaure-o ou apague-o de vez."
            )
        return (
            f"Já existe um elemento do tipo {tipo.name} chamado {nome!r} neste livro "
            f"(id {existente.id})."
        )

    return montar


def _buscar_capitulo_do_livro(sessao: Session, capitulo_id: int, livro_id: int) -> Capitulo:
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


def _exigir_imagem(sessao: Session, imagem_id: int) -> None:
    """Confere que a imagem-âncora existe, para o erro sair claro.

    Sem isto, a chave estrangeira falharia no commit e o app receberia um 500.
    """
    imagem = sessao.get(Imagem, imagem_id)
    if imagem is None or imagem.apagada_em is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Não existe imagem com id {imagem_id}.",
        )


def _sugestoes_de_elemento_do_livro(
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
