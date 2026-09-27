"""Rotas de elementos e estados (Etapa 6.3).

O coração da catalogação: manter a identidade de cada elemento recorrente e o
histórico de como ele estava em cada ponto da narrativa (item 3.4b). É o que o
passo 7 do fluxo alimenta e o passo 8 consome.
"""

import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.elemento import (
    CenaSugerida as CenaSugeridaResposta,
    ElementoAjuste,
    ElementoDetalhe,
    ElementoNovo,
    ElementoResumo,
    ElementoSugerido as ElementoSugeridoResposta,
    EstadoAjuste,
    EstadoNovo,
    EstadoResumo,
    EstadosDeSugestoes,
    ParticipanteSugerido as ParticipanteSugeridoResposta,
    SugestaoDeElementoBuscada,
    SugestoesDeCapitulo,
)
from imagineer.ia.openrouter import conferir_se_cabe
from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ErroDoProvedorIA,
    ModeloNaoEscolhido,
    ProvedorIA,
    TextoLongoDemais,
)
from imagineer.modelos import (
    Capitulo,
    Elemento,
    EstadoElemento,
    Imagem,
    Livro,
    SugestaoDeCena,
    SugestaoDeElemento,
    TipoElemento,
)
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento

rotas_de_livro = APIRouter(prefix="/livros", tags=["Elementos"])
rotas = APIRouter(prefix="/elementos", tags=["Elementos"])
rotas_de_estado = APIRouter(prefix="/estados", tags=["Elementos"])
rotas_de_capitulo = APIRouter(prefix="/capitulos", tags=["Elementos"])


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


@rotas_de_livro.get(
    "/{livro_id}/sugestoes-elemento",
    response_model=list[SugestaoDeElementoBuscada],
    summary="Busca sugestões de elemento por nome, em todo o livro",
)
def buscar_sugestoes_de_elemento(
    livro_id: int,
    nome: str = Query(min_length=1, description="Busca parcial, sem diferenciar caixa/acento."),
    sessao: Session = Depends(obter_sessao),
) -> list[SugestaoDeElementoBuscada]:
    """Acha todas as menções de um nome no livro inteiro, cruzando capítulos (item 3.4e).

    Resolve o caso em que a IA sugere o mesmo personagem com nomes diferentes
    demais para o casamento automático reconhecer — "Sextus Hospius" num
    capítulo, "Hospius" sozinho capítulos depois — sem o usuário vasculhar
    capítulo por capítulo à procura da menção anterior.
    """
    _buscar_livro(sessao, livro_id)

    linhas = sessao.execute(
        select(SugestaoDeElemento, Capitulo.ordem, Capitulo.titulo)
        .join(Capitulo, Capitulo.id == SugestaoDeElemento.capitulo_id)
        .where(Capitulo.livro_id == livro_id)
        .order_by(Capitulo.ordem, SugestaoDeElemento.id)
    ).all()

    alvo = _texto_normalizado(nome)
    return [
        SugestaoDeElementoBuscada(
            id=sugestao.id,
            capitulo_id=sugestao.capitulo_id,
            capitulo_ordem=ordem,
            capitulo_titulo=titulo,
            tipo=sugestao.tipo,
            nome=sugestao.nome,
            descricao=sugestao.descricao,
            manter_estado_atual=sugestao.manter_estado_atual,
            elemento_id=sugestao.elemento_id,
        )
        for sugestao, ordem, titulo in linhas
        if alvo in _texto_normalizado(sugestao.nome)
    ]


# --------------------------------------------------------------------------- #
# Um elemento
# --------------------------------------------------------------------------- #


@rotas.get("/{elemento_id}", response_model=ElementoDetalhe, summary="Abre um elemento")
def abrir_elemento(
    elemento_id: int, sessao: Session = Depends(obter_sessao)
) -> ElementoDetalhe:
    """O elemento com todos os seus estados, em ordem narrativa."""
    return _detalhe(sessao, _buscar_elemento(sessao, elemento_id))


@rotas.patch("/{elemento_id}", response_model=ElementoDetalhe, summary="Ajusta um elemento")
def ajustar_elemento(
    elemento_id: int,
    ajuste: ElementoAjuste,
    sessao: Session = Depends(obter_sessao),
) -> ElementoDetalhe:
    """Muda a identidade do elemento: nome, tipo ou descrição.

    Não mexe nos estados: a aparência é assunto deles (item 3.4b).
    """
    elemento = _buscar_elemento(sessao, elemento_id)
    campos = ajuste.model_dump(exclude_unset=True)
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
    """Apaga o elemento e todos os seus estados."""
    sessao.delete(_buscar_elemento(sessao, elemento_id))
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


@rotas_de_capitulo.post(
    "/{capitulo_id}/sugestoes",
    response_model=SugestoesDeCapitulo,
    summary="Os elementos e frames sugeridos do capítulo",
)
def sugerir_elementos(
    capitulo_id: int,
    forcar: bool = Query(
        default=False,
        description=(
            "Ignora a sugestão salva deste capítulo e pede uma nova à IA. Só "
            "substitui sugestões ainda não confirmadas — as já viradas "
            "Elemento ou Frame sobrevivem. Sem isso, o que já está salvo é "
            "devolvido sem chamar a IA de novo."
        ),
    ),
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> SugestoesDeCapitulo:
    """Sugere elementos e cenas a partir do texto do capítulo (passo 6).

    **Não grava Elemento nem Frame** — quem confirma é o usuário, pelas rotas
    de cadastro da Etapa 6.3 e de frame da Etapa 6.4. Mas a sugestão em si é
    persistida, em linhas próprias (`SugestaoDeElemento`/`SugestaoDeCena`,
    item 3.4e): sem isso, cada chamada arriscava devolver algo diferente da
    anterior, porque a IA não é determinística. `forcar=true` força uma
    sugestão nova, por iniciativa do usuário.

    O casamento com `elemento_id` é recalculado a cada leitura, mesmo servindo
    do que já está salvo — só o texto da sugestão vem do cache. Assim,
    cadastrar um elemento novo entre uma chamada e outra já aparece casado na
    próxima leitura, sem precisar de `forcar=true`.
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)

    if capitulo.sugestoes_geradas_em is None or forcar:
        _gerar_sugestoes(sessao, provedor, capitulo)

    _casar_sugestoes_pendentes(sessao, capitulo_id, capitulo.livro_id)

    return _sugestoes_de_capitulo(sessao, capitulo)


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
    filtros = [Elemento.livro_id == livro_id]
    if tipo is not None:
        filtros.append(Elemento.tipo == tipo)

    elementos = list(
        sessao.scalars(
            select(Elemento).where(*filtros).order_by(Elemento.tipo, Elemento.nome)
        )
    )

    vigentes = estado_vigente_por_elemento(sessao, livro_id, ordem_limite)

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
            estado_vigente=(
                EstadoResumo.model_validate(vigentes[elemento.id])
                if elemento.id in vigentes
                else None
            ),
        )
        for elemento in elementos
    ]


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

    return ElementoDetalhe(
        id=elemento.id,
        livro_id=elemento.livro_id,
        tipo=elemento.tipo,
        nome=elemento.nome,
        descricao=elemento.descricao,
        estados=[EstadoResumo.model_validate(estado) for estado in estados],
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
        return (
            f"Já existe um elemento do tipo {tipo.name} chamado {nome!r} neste livro "
            f"(id {existente.id})."
        )

    return montar


def _buscar_livro(sessao: Session, livro_id: int) -> Livro:
    livro = sessao.get(Livro, livro_id)
    if livro is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe livro com id {livro_id}.",
        )
    return livro


def _buscar_elemento(sessao: Session, elemento_id: int) -> Elemento:
    elemento = sessao.get(Elemento, elemento_id)
    if elemento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe elemento com id {elemento_id}.",
        )
    return elemento


def _buscar_estado(sessao: Session, estado_id: int) -> EstadoElemento:
    estado = sessao.get(EstadoElemento, estado_id)
    if estado is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe estado com id {estado_id}.",
        )
    return estado


def _buscar_capitulo(sessao: Session, capitulo_id: int) -> Capitulo:
    capitulo = sessao.get(Capitulo, capitulo_id)
    if capitulo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe capítulo com id {capitulo_id}.",
        )
    return capitulo


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
    if sessao.get(Imagem, imagem_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Não existe imagem com id {imagem_id}.",
        )


def _gerar_sugestoes(sessao: Session, provedor: ProvedorIA, capitulo: Capitulo) -> None:
    """Chama a IA e grava o resultado como linhas (item 3.4e).

    Só substitui as sugestões deste capítulo que ainda não foram confirmadas
    (`elemento_id`/`frame_id` nulos) — uma sugestão já virada Elemento ou
    Frame de verdade sobrevive a uma rodada nova, mesmo com `forcar=true`.
    """
    configuracao = obter_ou_criar(sessao)
    modelo_extracao = configuracao.modelo_extracao

    if not modelo_extracao:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nenhum modelo de extração foi escolhido. Configure um em /configuracao.",
        )

    estados_conhecidos = _formatar_estados_conhecidos(sessao, capitulo)

    try:
        contexto_do_modelo = next(
            (m.contexto for m in provedor.listar_modelos() if m.id == modelo_extracao), 0
        )
        conferir_se_cabe(capitulo.texto, contexto_do_modelo)
        extracao = provedor.extrair_elementos(capitulo.texto, estados_conhecidos, modelo_extracao)
    except (ChaveDeApiAusente, ModeloNaoEscolhido, TextoLongoDemais) as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro
    except ErroDoProvedorIA as erro:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(erro)
        ) from erro

    sessao.execute(
        delete(SugestaoDeElemento).where(
            SugestaoDeElemento.capitulo_id == capitulo.id,
            SugestaoDeElemento.elemento_id.is_(None),
        )
    )
    sessao.execute(
        delete(SugestaoDeCena).where(
            SugestaoDeCena.capitulo_id == capitulo.id,
            SugestaoDeCena.frame_id.is_(None),
        )
    )

    elementos_desta_rodada: dict[tuple[TipoElemento, str], SugestaoDeElemento] = {}
    for item in extracao.elementos:
        linha = SugestaoDeElemento(
            capitulo_id=capitulo.id,
            tipo=item.tipo,
            nome=item.nome,
            descricao=item.descricao,
            manter_estado_atual=item.manter_estado_atual,
            modelo=extracao.modelo,
        )
        sessao.add(linha)
        elementos_desta_rodada[_chave_normalizada(item.tipo, item.nome)] = linha

    for cena in extracao.cenas:
        linha_cena = SugestaoDeCena(
            capitulo_id=capitulo.id,
            titulo=cena.titulo,
            descricao=cena.descricao,
            horario=cena.horario,
            clima=cena.clima,
            humor=cena.humor,
            modelo=extracao.modelo,
        )
        for participante in cena.participantes:
            correspondente = elementos_desta_rodada.get(
                _chave_normalizada(participante.tipo, participante.nome)
            )
            if correspondente is not None:
                linha_cena.participantes.append(correspondente)
        sessao.add(linha_cena)

    capitulo.sugestoes_geradas_em = datetime.now(timezone.utc)
    sessao.add(capitulo)
    sessao.commit()


def _casar_sugestoes_pendentes(sessao: Session, capitulo_id: int, livro_id: int) -> None:
    """Tenta casar por nome as sugestões deste capítulo ainda sem `elemento_id`.

    Roda a cada leitura, não só na geração: se o usuário cadastrar um elemento
    entre uma chamada e outra, a próxima leitura já mostra o casamento novo,
    sem precisar de `forcar=true` (item 3.4e).
    """
    pendentes = list(
        sessao.scalars(
            select(SugestaoDeElemento).where(
                SugestaoDeElemento.capitulo_id == capitulo_id,
                SugestaoDeElemento.elemento_id.is_(None),
            )
        )
    )
    if not pendentes:
        return

    elementos_existentes = _elementos_por_chave_normalizada(sessao, livro_id)
    mudou = False
    for sugestao in pendentes:
        correspondente = elementos_existentes.get(
            _chave_normalizada(sugestao.tipo, sugestao.nome)
        )
        if correspondente is not None:
            sugestao.elemento_id = correspondente
            mudou = True

    if mudou:
        sessao.commit()


def _sugestoes_de_capitulo(sessao: Session, capitulo: Capitulo) -> SugestoesDeCapitulo:
    """Monta a resposta a partir do que está salvo para este capítulo."""
    elementos = list(
        sessao.scalars(
            select(SugestaoDeElemento)
            .where(SugestaoDeElemento.capitulo_id == capitulo.id)
            .order_by(SugestaoDeElemento.id)
        )
    )
    cenas = list(
        sessao.scalars(
            select(SugestaoDeCena)
            .where(SugestaoDeCena.capitulo_id == capitulo.id)
            .order_by(SugestaoDeCena.id)
        )
    )

    return SugestoesDeCapitulo(
        gerado_em=capitulo.sugestoes_geradas_em,
        elementos=[
            ElementoSugeridoResposta(
                id=elemento.id,
                tipo=elemento.tipo,
                nome=elemento.nome,
                descricao=elemento.descricao,
                manter_estado_atual=elemento.manter_estado_atual,
                elemento_id=elemento.elemento_id,
                modelo=elemento.modelo,
            )
            for elemento in elementos
        ],
        cenas=[
            CenaSugeridaResposta(
                id=cena.id,
                titulo=cena.titulo,
                descricao=cena.descricao,
                horario=cena.horario,
                clima=cena.clima,
                humor=cena.humor,
                modelo=cena.modelo,
                participantes=[
                    ParticipanteSugeridoResposta(
                        sugestao_elemento_id=participante.id,
                        tipo=participante.tipo,
                        nome=participante.nome,
                        elemento_id=participante.elemento_id,
                    )
                    for participante in cena.participantes
                ],
            )
            for cena in cenas
        ],
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


def _formatar_estados_conhecidos(sessao: Session, capitulo: Capitulo) -> list[str]:
    """Monta a lista "Nome (TIPO): descrição" que vai como contexto para a IA.

    Só entram elementos que já têm um estado até este ponto da narrativa — um
    elemento sem estado ainda não apareceu, e listá-lo sem descrição não ajudaria
    a IA a decidir "manter estado atual" (item 4.4).
    """
    elementos = {
        elemento.id: elemento
        for elemento in sessao.scalars(
            select(Elemento).where(Elemento.livro_id == capitulo.livro_id)
        )
    }
    vigentes = estado_vigente_por_elemento(sessao, capitulo.livro_id, capitulo.ordem)

    return [
        f"{elementos[elemento_id].nome} ({elementos[elemento_id].tipo.name}): "
        f"{estado.descricao}"
        for elemento_id, estado in vigentes.items()
    ]


def _texto_normalizado(texto: str) -> str:
    """Sem caixa nem acentuação — a base de toda comparação de nome do módulo.

    Usada tanto para casar sugestão com elemento (`_chave_normalizada`) quanto
    para a busca por nome (`GET /livros/{id}/sugestoes-elemento`, item 3.4e).
    """
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.strip().lower()


def _chave_normalizada(tipo: TipoElemento, nome: str) -> tuple[TipoElemento, str]:
    """Normaliza tipo e nome para casar a sugestão da IA com um elemento existente.

    Ignora maiúsculas/minúsculas e acentuação: a IA foi instruída a repetir o nome
    exato de um elemento conhecido, mas variações de caixa e acento são comuns o
    suficiente para valer a pena tolerar, sem risco de casar elementos diferentes
    por engano — a comparação continua exigindo o mesmo tipo e (quase) o mesmo nome.
    """
    return (tipo, _texto_normalizado(nome))


def _elementos_por_chave_normalizada(
    sessao: Session, livro_id: int
) -> dict[tuple[TipoElemento, str], int]:
    """Mapeia (tipo, nome normalizado) -> id, para casar sugestões da IA."""
    elementos = sessao.scalars(select(Elemento).where(Elemento.livro_id == livro_id))
    return {
        _chave_normalizada(elemento.tipo, elemento.nome): elemento.id
        for elemento in elementos
    }
