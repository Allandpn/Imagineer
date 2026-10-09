"""Rotas dos estados de um elemento (Etapa 6.3): criar, abrir, ajustar, apagar e o estado vigente de cada elemento num capítulo."""

from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy.orm import Session
from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.elemento import (
    ElementoResumo,
    EstadoAjuste,
    EstadoComIdentidadeDoElemento,
    EstadoNovo,
    EstadoResumo,
    EstadosDeSugestoes,
)
from imagineer.modelos import EstadoElemento
from imagineer.rotas._comum import (
    buscar_capitulo as _buscar_capitulo,
    buscar_elemento as _buscar_elemento,
    buscar_estado as _buscar_estado,
)
from imagineer.rotas._elementos_comum import (
    buscar_capitulo_do_livro,
    exigir_imagem,
    montar_resumos,
    sugestoes_de_elemento_do_livro,
)

rotas = APIRouter(prefix="/elementos", tags=["Elementos"])
rotas_de_estado = APIRouter(prefix="/estados", tags=["Elementos"])
rotas_de_capitulo = APIRouter(prefix="/capitulos", tags=["Elementos"])


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
    capitulo = buscar_capitulo_do_livro(sessao, novo.capitulo_id, elemento.livro_id)

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
    sugestoes = sugestoes_de_elemento_do_livro(
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
        exigir_imagem(sessao, campos["imagem_ancora_id"])

    if "descricao" in campos and campos["descricao"] != estado.descricao:
        # FL4: a descrição escrita à mão passa a valer sozinha; a linha do tempo que a IA leu já não descreve este texto.
        estado.momentos = None

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
    return montar_resumos(
        sessao, capitulo.livro_id, tipo=None, ordem_limite=capitulo.ordem
    )
