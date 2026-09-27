"""Rotas de elementos e estados (Etapa 6.3).

O coração da catalogação: manter a identidade de cada elemento recorrente e o
histórico de como ele estava em cada ponto da narrativa (item 3.4b). É o que o
passo 7 do fluxo alimenta e o passo 8 consome.
"""

import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.elemento import (
    ElementoAjuste,
    ElementoDetalhe,
    ElementoNovo,
    ElementoResumo,
    ElementoSugerido as ElementoSugeridoResposta,
    EstadoAjuste,
    EstadoNovo,
    EstadoResumo,
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
from imagineer.modelos import Capitulo, Elemento, EstadoElemento, Imagem, Livro, TipoElemento
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
    """Cria o elemento e, se vier, o primeiro estado dele — num pedido só.

    O passo 7 do fluxo confirma as duas coisas ao mesmo tempo: que o personagem
    existe e como ele está naquele capítulo. Em dois pedidos, uma falha no meio
    deixaria um elemento sem estado nenhum.
    """
    _buscar_livro(sessao, livro_id)

    elemento = Elemento(
        livro_id=livro_id, tipo=novo.tipo, nome=novo.nome, descricao=novo.descricao
    )

    if novo.estado_inicial is not None:
        capitulo = _buscar_capitulo_do_livro(sessao, novo.estado_inicial.capitulo_id, livro_id)
        elemento.estados = [
            EstadoElemento(
                capitulo_id=capitulo.id, descricao=novo.estado_inicial.descricao
            )
        ]

    sessao.add(elemento)
    _gravar(sessao, _conflito_de_elemento(sessao, livro_id, novo.tipo, novo.nome))
    sessao.refresh(elemento)
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
    """Apaga um estado. O elemento e as cenas que o citavam permanecem."""
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
    summary="Pede à IA os elementos e estados sugeridos do capítulo",
)
def sugerir_elementos(
    capitulo_id: int,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> SugestoesDeCapitulo:
    """Sugere elementos e estados a partir do texto do capítulo (passo 6).

    **Não grava nada no banco.** É a IA sugerindo; o usuário confirma pelas rotas
    de cadastro da Etapa 6.3 (item 4.4) — esta rota só devolve a sugestão.
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    configuracao = obter_ou_criar(sessao)
    modelo = configuracao.modelo_extracao

    if not modelo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nenhum modelo de extração foi escolhido. Configure um em /configuracao.",
        )

    estados_conhecidos = _formatar_estados_conhecidos(sessao, capitulo)

    try:
        contexto_do_modelo = next(
            (m.contexto for m in provedor.listar_modelos() if m.id == modelo), 0
        )
        conferir_se_cabe(capitulo.texto, contexto_do_modelo)
        extracao = provedor.extrair_elementos(capitulo.texto, estados_conhecidos, modelo)
    except (ChaveDeApiAusente, ModeloNaoEscolhido, TextoLongoDemais) as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro
    except ErroDoProvedorIA as erro:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(erro)
        ) from erro

    elementos_existentes = _elementos_por_chave_normalizada(sessao, capitulo.livro_id)

    return SugestoesDeCapitulo(
        modelo=extracao.modelo,
        elementos=[
            ElementoSugeridoResposta(
                tipo=sugestao.tipo,
                nome=sugestao.nome,
                descricao=sugestao.descricao,
                estado_sugerido=sugestao.estado_sugerido,
                manter_estado_atual=sugestao.manter_estado_atual,
                elemento_id=elementos_existentes.get(
                    _chave_normalizada(sugestao.tipo, sugestao.nome)
                ),
            )
            for sugestao in extracao.elementos
        ],
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


def _chave_normalizada(tipo: TipoElemento, nome: str) -> tuple[TipoElemento, str]:
    """Normaliza tipo e nome para casar a sugestão da IA com um elemento existente.

    Ignora maiúsculas/minúsculas e acentuação: a IA foi instruída a repetir o nome
    exato de um elemento conhecido, mas variações de caixa e acento são comuns o
    suficiente para valer a pena tolerar, sem risco de casar elementos diferentes
    por engano — a comparação continua exigindo o mesmo tipo e (quase) o mesmo nome.
    """
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return (tipo, sem_acento.strip().lower())


def _elementos_por_chave_normalizada(
    sessao: Session, livro_id: int
) -> dict[tuple[TipoElemento, str], int]:
    """Mapeia (tipo, nome normalizado) -> id, para casar sugestões da IA."""
    elementos = sessao.scalars(select(Elemento).where(Elemento.livro_id == livro_id))
    return {
        _chave_normalizada(elemento.tipo, elemento.nome): elemento.id
        for elemento in elementos
    }
