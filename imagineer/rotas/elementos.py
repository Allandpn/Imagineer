"""Rotas de elementos e estados (Etapa 6.3).

O coração da catalogação: manter a identidade de cada elemento recorrente e o
histórico de como ele estava em cada ponto da narrativa (item 3.4b). É o que o
passo 7 do fluxo alimenta e o passo 8 consome.
"""

import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.elemento import (
    CenaSugerida as CenaSugeridaResposta,
    ElementoAjuste,
    ElementoCasado,
    ElementoDetalhe,
    ElementoMesclagem,
    ElementoNovo,
    ElementoResumo,
    ElementoSugerido as ElementoSugeridoResposta,
    EstadoAjuste,
    EstadoComIdentidadeDoElemento,
    EstadoNovo,
    EstadoResumo,
    EstadosDeSugestoes,
    EstadoVigenteDaSugestao,
    HistoricoIdentidadeAjuste,
    HistoricoIdentidadeNovo,
    HistoricoIdentidadeResumo,
    Artefato,
    ArtefatosDoCapitulo,
    MarcadoresDoCapitulo,
    SituacaoDoArtefato,
    TipoDeArtefato,
    ParticipanteSugerido as ParticipanteSugeridoResposta,
    SugestaoDeCenaAjuste,
    SugestaoDeElementoAjuste,
    SugestaoDeElementoBuscada,
    PedidoDeAnalise,
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
    Frame,
    TipoDeFrame,
    HistoricoIdentidadeElemento,
    Imagem,
    SugestaoDeCena,
    SugestaoDeElemento,
    TipoElemento,
)
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento
from imagineer.servicos.identidade_de_elemento import identidade_vigente, resumir_texto
from imagineer.servicos.posicao_no_texto import posicao_da_citacao, posicao_da_primeira_mencao
from imagineer.servicos.trava_de_analise import AnaliseEmAndamento, analise_exclusiva
from imagineer.rotas._comum import (
    buscar_acrescimo as _buscar_acrescimo,
    buscar_capitulo as _buscar_capitulo,
    buscar_elemento as _buscar_elemento,
    buscar_estado as _buscar_estado,
    buscar_livro as _buscar_livro,
    buscar_sugestao_de_elemento as _buscar_sugestao_de_elemento,
)

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
            casamento_automatico=sugestao.casamento_automatico,
            estado_id=_estado_id_no_capitulo(sessao, sugestao),
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
    """Apaga o elemento e todos os seus estados."""
    sessao.delete(_buscar_elemento(sessao, elemento_id))
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


@rotas_de_sugestao_elemento.patch(
    "/{sugestao_elemento_id}",
    response_model=ElementoSugeridoResposta,
    summary="Corrige o casamento de uma sugestão de elemento, ou a descarta",
)
def ajustar_sugestao_de_elemento(
    sugestao_elemento_id: int,
    ajuste: SugestaoDeElementoAjuste,
    sessao: Session = Depends(obter_sessao),
) -> ElementoSugeridoResposta:
    """Ajusta **uma** coisa da sugestão: o casamento (`elemento_id`) ou `descartada`.

    **Casamento** — corrige só `elemento_id`, sem gravar Estado nenhum. Diferente de
    `POST /elementos/{id}/estados-de-sugestoes`, que sempre cria um Estado como efeito
    colateral (item 3.4e), o que serve ao caso comum mas não ao caso raro de o casamento
    automático ter errado e o usuário só querer desfazer. Se `elemento_id` vier
    preenchido, exige que o elemento exista e seja do mesmo livro do capítulo da sugestão.
    `elemento_id: null` **desfaz** o casamento **de verdade**: marca `casamento_desfeito`,
    para o casamento automático (que roda a cada leitura) não religar a sugestão ao mesmo
    elemento logo em seguida.

    **Descartar** (item 6.8) — `descartada: true` tira a sugestão das pendentes e ela
    sobrevive a uma reanálise; `false` a restaura. Só se descarta uma sugestão **ainda não
    ligada** a um elemento (409 senão: desfaça o casamento antes).
    """
    sugestao = _buscar_sugestao_de_elemento(sessao, sugestao_elemento_id)
    campos = ajuste.model_fields_set

    if "elemento_id" in campos and "descartada" in campos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Ajuste uma coisa por vez: o casamento (elemento_id) ou descartada.",
        )
    if "elemento_id" not in campos and ajuste.descartada is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Informe elemento_id (pode ser null) ou descartada.",
        )

    if "elemento_id" in campos:
        if ajuste.elemento_id is not None:
            elemento = _buscar_elemento(sessao, ajuste.elemento_id)
            if elemento.livro_id != sugestao.capitulo.livro_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"O elemento {ajuste.elemento_id} é do livro {elemento.livro_id}, "
                        f"não do livro {sugestao.capitulo.livro_id} desta sugestão."
                    ),
                )
        sugestao.elemento_id = ajuste.elemento_id
        # É uma correção explícita do usuário — deixa de ser "casamento nunca
        # revisado", mesmo que o novo valor seja null (desfazendo o casamento).
        sugestao.casamento_automatico = False
        sugestao.casamento_desfeito = ajuste.elemento_id is None
        if ajuste.elemento_id is not None:
            sugestao.descartada = False  # ligar é decidir o contrário de descartar
    elif ajuste.descartada:
        if sugestao.elemento_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Esta sugestão está ligada a um elemento. Desfaça o casamento "
                    "antes de descartá-la."
                ),
            )
        sugestao.descartada = True
    else:
        sugestao.descartada = False

    sessao.commit()
    sessao.refresh(sugestao)

    capitulo = sugestao.capitulo
    vigentes = estado_vigente_por_elemento(sessao, capitulo.livro_id, capitulo.ordem)
    return _resposta_de_elemento(sessao, sugestao, capitulo, vigentes)


@rotas_de_sugestao_cena.patch(
    "/{sugestao_cena_id}",
    response_model=CenaSugeridaResposta,
    summary="Descarta (ou restaura) uma sugestão de cena",
)
def ajustar_sugestao_de_cena(
    sugestao_cena_id: int,
    ajuste: SugestaoDeCenaAjuste,
    sessao: Session = Depends(obter_sessao),
) -> CenaSugeridaResposta:
    """`descartada: true` tira a cena das pendentes e ela sobrevive a uma reanálise;
    `false` a restaura. Uma cena que já virou Frame não se descarta (409): o Frame existe."""
    cena = sessao.get(SugestaoDeCena, sugestao_cena_id)
    if cena is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe sugestão de cena com id {sugestao_cena_id}.",
        )
    if ajuste.descartada and cena.frame_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Esta cena já virou o frame {cena.frame_id}; não dá para descartá-la.",
        )
    cena.descartada = ajuste.descartada
    sessao.commit()
    sessao.refresh(cena)

    capitulo = cena.capitulo
    vigentes = estado_vigente_por_elemento(sessao, capitulo.livro_id, capitulo.ordem)
    return _resposta_de_cena(sessao, cena, capitulo, vigentes)


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
    pedido: PedidoDeAnalise | None = None,
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

    **Orientação do usuário (M1, item 6.7):** o corpo opcional `{"orientacao": "..."}` diz o que a
    análise não pegou. Não vazia, ela **roda a IA** (mesmo sem `forcar=true`: mandá-la é o pedido de
    reanalisar) e fica guardada no capítulo para as reanálises seguintes; em branco, apaga a guardada
    e roda a IA sem ela; ausente, não mexe.
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)

    rodar_ia = forcar
    if pedido is not None and pedido.orientacao is not None:
        capitulo.orientacao_da_analise = pedido.orientacao.strip() or None
        rodar_ia = True

    if capitulo.sugestoes_geradas_em is None or rodar_ia:
        try:
            with analise_exclusiva(capitulo_id):
                _gerar_sugestoes(sessao, provedor, capitulo)
        except AnaliseEmAndamento as erro:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já há uma análise deste capítulo em andamento. Aguarde terminar.",
            ) from erro

    _casar_sugestoes_pendentes(sessao, capitulo_id, capitulo.livro_id)

    pendentes_anteriores = _sugestoes_pendentes_anteriores(sessao, capitulo)
    return _sugestoes_de_capitulo(sessao, capitulo, pendentes_anteriores)


@rotas_de_capitulo.get(
    "/{capitulo_id}/sugestoes",
    response_model=SugestoesDeCapitulo,
    summary="Lê as sugestões salvas do capítulo, sem chamar a IA",
)
def ler_sugestoes(
    capitulo_id: int,
    sessao: Session = Depends(obter_sessao),
) -> SugestoesDeCapitulo:
    """Devolve o que está **salvo** das sugestões do capítulo — e nunca chama a IA.

    Existe porque o `POST` da mesma rota **gera** (e cobra) quando o capítulo nunca
    foi analisado. Um leitor que carrega as sugestões ao abrir o capítulo, ou que
    reabre o painel depois de sair no meio de uma análise, não pode usá-lo: gastaria
    IA sem ninguém pedir, e duas chamadas simultâneas seriam duas cobranças. Ler não
    é gerar (item 6.8).

    **A garantia é estrutural**: esta função não declara a dependência do provedor de
    IA (`obter_provedor`), então não tem como chamá-lo — nem a chave de API nem o
    modelo de extração precisam estar configurados para ela responder.

    Nunca analisado: `gerado_em` nulo e listas vazias. Já analisado: a mesma resposta
    do `POST`, inclusive o casamento com `elemento_id` **recalculado** a cada leitura
    (idempotente; um elemento cadastrado depois já aparece casado). O recálculo só
    roda quando há sugestão salva, então um capítulo nunca analisado não gera escrita.
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)

    if capitulo.sugestoes_geradas_em is not None:
        _casar_sugestoes_pendentes(sessao, capitulo_id, capitulo.livro_id)

    pendentes_anteriores = _sugestoes_pendentes_anteriores(sessao, capitulo)
    return _sugestoes_de_capitulo(sessao, capitulo, pendentes_anteriores)


def _situacao_e_imagem(frame: Frame | None, *, confirmado: bool) -> tuple[SituacaoDoArtefato, Imagem | None]:
    """A situação de um artefato e a imagem a mostrar (a mais recente do frame, se houver).

    ``confirmado`` diz se a sugestão já virou elemento ou frame; sem isso, é só ``SUGERIDO``.
    """
    if not confirmado:
        return SituacaoDoArtefato.SUGERIDO, None
    imagens = [imagem for prompt in frame.prompts for imagem in prompt.imagens] if frame else []
    ultima = max(imagens, key=lambda i: (i.data_importacao, i.id), default=None)
    if ultima is not None:
        return SituacaoDoArtefato.ILUSTRADO, ultima
    if frame is not None and frame.prompts:
        return SituacaoDoArtefato.PROMPT_PRONTO, None
    return SituacaoDoArtefato.CONFIRMADO, None


def _sem_repetidas(sugestoes: list[SugestaoDeElemento]) -> list[SugestaoDeElemento]:
    """Uma sugestão por elemento: duas sugestões do mesmo elemento (ou do mesmo tipo e nome, se ainda
    não casadas) desenhariam o mesmo ícone duas vezes no mesmo parágrafo.

    Fica a **mais antiga** (id menor); o painel de IA continua mostrando todas. Existe porque o banco
    pode ter duplicatas de reanálises feitas antes de o servidor deixar de recriar as confirmadas.
    """
    vistas: set[object] = set()
    unicas: list[SugestaoDeElemento] = []
    for sugestao in sugestoes:  # já vêm por id
        chave: object = (
            ("elemento", sugestao.elemento_id)
            if sugestao.elemento_id is not None
            else ("nome", *_chave_normalizada(sugestao.tipo, sugestao.nome))
        )
        if chave in vistas:
            continue
        vistas.add(chave)
        unicas.append(sugestao)
    return unicas


@rotas_de_capitulo.get(
    "/{capitulo_id}/artefatos",
    response_model=ArtefatosDoCapitulo,
    summary="Os artefatos a desenhar sobre o texto do capítulo, sem chamar a IA",
)
def ler_artefatos(
    capitulo_id: int,
    sessao: Session = Depends(obter_sessao),
) -> ArtefatosDoCapitulo:
    """Os ícones do capítulo (item 6.8), numa chamada só — **só leitura, nunca chama a IA**."""
    return ArtefatosDoCapitulo(artefatos=_artefatos_do_capitulo(sessao, capitulo_id))


@rotas_de_capitulo.get(
    "/{capitulo_id}/marcadores",
    response_model=MarcadoresDoCapitulo,
    deprecated=True,
    summary="[Obsoleta] O mesmo que /artefatos, com o nome e o campo antigos",
)
def ler_marcadores_obsoleta(
    capitulo_id: int,
    sessao: Session = Depends(obter_sessao),
) -> MarcadoresDoCapitulo:
    """**Obsoleta** (item 6.8): o nome antigo de ``/artefatos``, mantido só para o app que ainda a usa.

    Devolve exatamente os mesmos dados, no campo ``marcadores`` em vez de ``artefatos``. "Marcador" agora
    é outra coisa (a posição de leitura, defeito D4); sai daqui quando o app migrar.
    """
    return MarcadoresDoCapitulo(marcadores=_artefatos_do_capitulo(sessao, capitulo_id))


def _artefatos_do_capitulo(sessao: Session, capitulo_id: int) -> list[Artefato]:
    """Monta os artefatos do capítulo.

    Cada sugestão **não descartada** vira um artefato. A posição dos **elementos** é achada **pelo
    nome**, no texto, na hora da leitura — funciona também nos capítulos já analisados. A das
    **cenas** vem da citação da IA, **gravada** quando a sugestão nasceu (item 3.4g): cena analisada
    antes disso fica sem posição até o capítulo ser reanalisado. Ordem: por posição; sem posição, depois.

    A situação mostra onde o usuário parou: ``SUGERIDO`` (não confirmado) → ``CONFIRMADO`` (virou
    elemento ou frame) → ``PROMPT_PRONTO`` (o frame tem prompt) → ``ILUSTRADO`` (o frame tem imagem).
    """
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    sugestoes = sessao.scalars(
        select(SugestaoDeElemento)
        .where(
            SugestaoDeElemento.capitulo_id == capitulo.id,
            SugestaoDeElemento.descartada.is_(False),
        )
        .order_by(SugestaoDeElemento.id)
    ).all()

    # Todos os frames do capítulo (item 3.4g, "Ilustrar aqui"): os que uma sugestão representa mandam a
    # posição para o artefato dela; os que nenhuma representa viram artefatos próprios, mais abaixo.
    frames = list(sessao.scalars(select(Frame).where(Frame.capitulo_id == capitulo.id).order_by(Frame.id)))

    # O retrato de cada elemento NESTE capítulo: o frame PERSONAGEM cujo único estado é dele.
    retratos: dict[int, Frame] = {}
    for frame in frames:
        if frame.tipo == TipoDeFrame.PERSONAGEM and frame.estados_elemento:
            retratos[frame.estados_elemento[0].elemento_id] = frame  # o mais novo (id maior) vence, pela ordem

    artefatos: list[Artefato] = []
    elementos_representados: set[int] = set()
    for sugestao in _sem_repetidas(sugestoes):
        elemento = sugestao.elemento
        frame = retratos.get(sugestao.elemento_id) if sugestao.elemento_id is not None else None
        if frame is not None:
            elementos_representados.add(sugestao.elemento_id)
        situacao, ultima = _situacao_e_imagem(frame, confirmado=sugestao.elemento_id is not None)

        artefatos.append(
            Artefato(
                tipo=TipoDeArtefato.ELEMENTO,
                tipo_do_elemento=elemento.tipo if elemento is not None else sugestao.tipo,
                sugestao_id=sugestao.id,
                frame_id=frame.id if frame is not None else None,
                rotulo=elemento.nome if elemento is not None else sugestao.nome,
                # O frame manda: se a pessoa pôs o retrato num lugar, é ali (item 3.4g).
                posicao_no_texto=(
                    frame.posicao_no_texto
                    if frame is not None and frame.posicao_no_texto is not None
                    else posicao_da_primeira_mencao(capitulo.texto, sugestao.nome)
                ),
                situacao=situacao,
                imagem_id=ultima.id if ultima is not None else None,
            )
        )

    cenas = sessao.scalars(
        select(SugestaoDeCena)
        .where(SugestaoDeCena.capitulo_id == capitulo.id, SugestaoDeCena.descartada.is_(False))
        .order_by(SugestaoDeCena.id)
    )
    frames_de_cena_representados: set[int] = set()
    for cena in cenas:
        situacao, ultima = _situacao_e_imagem(cena.frame, confirmado=cena.frame_id is not None)
        if cena.frame_id is not None:
            frames_de_cena_representados.add(cena.frame_id)
        artefatos.append(
            Artefato(
                tipo=TipoDeArtefato.CENA,
                sugestao_id=cena.id,
                frame_id=cena.frame_id,
                rotulo=cena.titulo,
                # O frame manda: se a pessoa pôs a cena num lugar, é ali (item 3.4g).
                posicao_no_texto=(
                    cena.frame.posicao_no_texto
                    if cena.frame is not None and cena.frame.posicao_no_texto is not None
                    else cena.posicao_no_texto
                ),
                situacao=situacao,
                imagem_id=ultima.id if ultima is not None else None,
            )
        )

    # Os frames que nenhuma sugestão representa (uma cena inventada à mão, o retrato de um elemento sem
    # sugestão neste capítulo) viram artefatos próprios — com posição, onde a pessoa os pôs; sem, na faixa
    # "sem posição" (item 3.4g, "Ilustrar aqui").
    for frame in frames:
        situacao, ultima = _situacao_e_imagem(frame, confirmado=True)
        if frame.tipo == TipoDeFrame.CENA and frame.id not in frames_de_cena_representados:
            artefatos.append(
                Artefato(
                    tipo=TipoDeArtefato.CENA,
                    frame_id=frame.id,
                    rotulo=frame.titulo,
                    posicao_no_texto=frame.posicao_no_texto,
                    situacao=situacao,
                    imagem_id=ultima.id if ultima is not None else None,
                )
            )
        elif frame.tipo == TipoDeFrame.PERSONAGEM and frame.estados_elemento:
            elemento = frame.estados_elemento[0].elemento
            # Só o retrato mais novo de cada elemento (como no mapa acima), e só se nenhuma sugestão já o mostra.
            if retratos.get(elemento.id) is frame and elemento.id not in elementos_representados:
                artefatos.append(
                    Artefato(
                        tipo=TipoDeArtefato.ELEMENTO,
                        tipo_do_elemento=elemento.tipo,
                        frame_id=frame.id,
                        rotulo=elemento.nome,
                        posicao_no_texto=frame.posicao_no_texto,
                        situacao=situacao,
                        imagem_id=ultima.id if ultima is not None else None,
                    )
                )

    # Por posição; sem posição vêm depois, na ordem em que as sugestões foram criadas (a ordem estável do sort).
    artefatos.sort(key=lambda m: (m.posicao_no_texto is None, m.posicao_no_texto or 0))
    return artefatos


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
        return (
            f"Já existe um elemento do tipo {tipo.name} chamado {nome!r} neste livro "
            f"(id {existente.id})."
        )

    return montar


def _estado_id_no_capitulo(sessao: Session, sugestao: SugestaoDeElemento) -> int | None:
    """O Estado já registrado para o elemento casado, neste capítulo específico.

    `elemento_id` preenchido só diz que a sugestão está ligada a um Elemento;
    não diz se aquele capítulo em particular já virou um `EstadoElemento`
    (item 3.4e) — achado com um caso real em que uma menção casada num
    capítulo posterior nunca tinha gerado Estado, e isso não aparecia em
    lugar nenhum da resposta. Campo calculado, não coluna no banco — mesmo
    princípio de `estado_vigente` (item 6.3).
    """
    if sugestao.elemento_id is None:
        return None
    return sessao.execute(
        select(EstadoElemento.id)
        .where(
            EstadoElemento.elemento_id == sugestao.elemento_id,
            EstadoElemento.capitulo_id == sugestao.capitulo_id,
        )
        .order_by(EstadoElemento.id.desc())
        .limit(1)
    ).scalar_one_or_none()


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
    (`elemento_id`/`frame_id` nulos) **e não descartadas** — uma sugestão já virada
    Elemento ou Frame de verdade, ou descartada pelo usuário, sobrevive a uma rodada
    nova, mesmo com `forcar=true`. Uma sugestão nova que repete uma descartada (mesmo
    tipo e nome, ou mesmo título de cena) **não é criada de novo**.
    """
    configuracao = obter_ou_criar(sessao)
    modelo_extracao = configuracao.modelo_extracao

    if not modelo_extracao:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nenhum modelo de extração foi escolhido. Configure um em /configuracao.",
        )

    elementos_conhecidos = _formatar_elementos_conhecidos(sessao, capitulo)

    try:
        contexto_do_modelo = next(
            (m.contexto for m in provedor.listar_modelos() if m.id == modelo_extracao), 0
        )
        conferir_se_cabe(capitulo.texto, contexto_do_modelo)
        extracao = provedor.extrair_elementos(
            capitulo.texto, elementos_conhecidos, modelo_extracao, capitulo.orientacao_da_analise
        )
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
            SugestaoDeElemento.descartada.is_(False),
        )
    )
    sessao.execute(
        delete(SugestaoDeCena).where(
            SugestaoDeCena.capitulo_id == capitulo.id,
            SugestaoDeCena.frame_id.is_(None),
            SugestaoDeCena.descartada.is_(False),
        )
    )

    # As descartadas e as já confirmadas ficam; o que a IA repetir delas não vira sugestão nova
    # (era isso que duplicava os cartões a cada reanálise: a confirmada sobrevivia e a IA a listava de
    # novo), mas os participantes das cenas novas ainda podem apontar para elas.
    elementos_desta_rodada: dict[tuple[TipoElemento, str], SugestaoDeElemento] = {
        _chave_normalizada(d.tipo, d.nome): d
        for d in sessao.scalars(
            select(SugestaoDeElemento).where(
                SugestaoDeElemento.capitulo_id == capitulo.id,
                or_(
                    SugestaoDeElemento.descartada.is_(True),
                    SugestaoDeElemento.elemento_id.is_not(None),
                ),
            )
        )
    }
    titulos_de_cenas_descartadas = {
        _texto_normalizado(c.titulo)
        for c in sessao.scalars(
            select(SugestaoDeCena).where(
                SugestaoDeCena.capitulo_id == capitulo.id,
                SugestaoDeCena.descartada.is_(True),
            )
        )
    }
    for item in extracao.elementos:
        if _chave_normalizada(item.tipo, item.nome) in elementos_desta_rodada:
            continue
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
        if _texto_normalizado(cena.titulo) in titulos_de_cenas_descartadas:
            continue
        linha_cena = SugestaoDeCena(
            capitulo_id=capitulo.id,
            titulo=cena.titulo,
            descricao=cena.descricao,
            horario=cena.horario,
            clima=cena.clima,
            humor=cena.humor,
            modelo=extracao.modelo,
            trecho_ancora=cena.trecho_ancora[:300] if cena.trecho_ancora else None,
            # A posição vem da citação, calculada aqui — a IA nunca devolve número (item 3.4g).
            posicao_no_texto=posicao_da_citacao(capitulo.texto, cena.trecho_ancora),
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
                # Descartada não se casa; casamento desfeito de propósito não religa sozinho.
                SugestaoDeElemento.descartada.is_(False),
                SugestaoDeElemento.casamento_desfeito.is_(False),
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
            sugestao.casamento_automatico = True
            mudou = True

    if mudou:
        sessao.commit()


def _sugestoes_de_capitulo(
    sessao: Session, capitulo: Capitulo, pendentes_anteriores: int = 0
) -> SugestoesDeCapitulo:
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

    vigentes = estado_vigente_por_elemento(sessao, capitulo.livro_id, capitulo.ordem)
    return SugestoesDeCapitulo(
        gerado_em=capitulo.sugestoes_geradas_em,
        sugestoes_pendentes_anteriores=pendentes_anteriores,
        orientacao=capitulo.orientacao_da_analise,
        elementos=[_resposta_de_elemento(sessao, e, capitulo, vigentes) for e in elementos],
        cenas=[_resposta_de_cena(sessao, c, capitulo, vigentes) for c in cenas],
    )


def _resposta_de_elemento(
    sessao: Session,
    sugestao: SugestaoDeElemento,
    capitulo: Capitulo,
    vigentes: dict[int, EstadoElemento],
) -> ElementoSugeridoResposta:
    """Uma sugestão de elemento como a API a devolve, com o elemento casado e o
    estado que vale para ele neste capítulo (item 7.5b, E1)."""
    casado = None
    estado_vigente = None
    if sugestao.elemento_id is not None:
        elemento = sugestao.elemento
        casado = ElementoCasado(
            id=elemento.id,
            tipo=elemento.tipo,
            nome=elemento.nome,
            identidade=resumir_texto(
                identidade_vigente(sessao, elemento, capitulo.ordem), LIMITE_DA_IDENTIDADE_NA_SUGESTAO
            ),
        )
        vigente = vigentes.get(elemento.id)
        if vigente is not None:
            estado_vigente = EstadoVigenteDaSugestao(
                id=vigente.id,
                capitulo_id=vigente.capitulo_id,
                ordem_do_capitulo=vigente.capitulo.ordem,
                titulo_do_capitulo=vigente.capitulo.titulo,
                descricao=vigente.descricao,
            )

    return ElementoSugeridoResposta(
        id=sugestao.id,
        tipo=sugestao.tipo,
        nome=sugestao.nome,
        descricao=sugestao.descricao,
        manter_estado_atual=sugestao.manter_estado_atual,
        elemento_id=sugestao.elemento_id,
        casamento_automatico=sugestao.casamento_automatico,
        estado_id=_estado_id_no_capitulo(sessao, sugestao),
        achado_no_texto=posicao_da_primeira_mencao(capitulo.texto, sugestao.nome) is not None,
        elemento_casado=casado,
        estado_vigente=estado_vigente,
        descartada=sugestao.descartada,
        modelo=sugestao.modelo,
    )


def _resposta_de_cena(
    sessao: Session,
    cena: SugestaoDeCena,
    capitulo: Capitulo,
    vigentes: dict[int, EstadoElemento],
) -> CenaSugeridaResposta:
    """Uma cena sugerida como a API a devolve."""
    return CenaSugeridaResposta(
        id=cena.id,
        titulo=cena.titulo,
        descricao=cena.descricao,
        horario=cena.horario,
        clima=cena.clima,
        humor=cena.humor,
        modelo=cena.modelo,
        descartada=cena.descartada,
        frame_id=cena.frame_id,
        participantes=[
            ParticipanteSugeridoResposta(
                sugestao_elemento_id=participante.id,
                tipo=participante.tipo,
                nome=participante.nome,
                elemento_id=participante.elemento_id,
                casamento_automatico=participante.casamento_automatico,
                estado_id=_estado_id_no_capitulo(sessao, participante),
            )
            for participante in cena.participantes
        ],
    )


def _sugestoes_pendentes_anteriores(sessao: Session, capitulo: Capitulo) -> int:
    """Quantas sugestões de capítulos anteriores deste livro ainda não foram
    confirmadas (item 4.6) — soma elementos e cenas, porque os dois tipos de
    confirmação pendente prejudicam igualmente o contexto que a IA recebe.
    """
    capitulos_anteriores = select(Capitulo.id).where(
        Capitulo.livro_id == capitulo.livro_id, Capitulo.ordem < capitulo.ordem
    )
    elementos_pendentes = sessao.scalar(
        select(func.count(SugestaoDeElemento.id)).where(
            SugestaoDeElemento.capitulo_id.in_(capitulos_anteriores),
            SugestaoDeElemento.elemento_id.is_(None),
            SugestaoDeElemento.descartada.is_(False),
        )
    )
    cenas_pendentes = sessao.scalar(
        select(func.count(SugestaoDeCena.id)).where(
            SugestaoDeCena.capitulo_id.in_(capitulos_anteriores),
            SugestaoDeCena.frame_id.is_(None),
            SugestaoDeCena.descartada.is_(False),
        )
    )
    return (elementos_pendentes or 0) + (cenas_pendentes or 0)


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


#: Quanto da identidade de cada elemento vai para a IA, e quanto o pedido inteiro pode ter
#: (item 7.5b, rodada 3): sem teto, a lista cresce com o livro e o pedido com ela.
LIMITE_DA_IDENTIDADE_NO_CONTEXTO = 200
TETO_DO_CONTEXTO_DA_IA = 8000
#: O quanto da identidade do elemento casado vai na resposta de cada sugestão.
LIMITE_DA_IDENTIDADE_NA_SUGESTAO = 300


def _formatar_elementos_conhecidos(sessao: Session, capitulo: Capitulo) -> list[str]:
    """Monta a lista "Nome (TIPO): identidade" que vai como contexto para a IA.

    Entram os elementos já cadastrados no livro, cada um com a sua **identidade vigente
    até o capítulo anterior** (item 3.4f) **resumida** — quem ou o que é —, e **nunca** o
    estado de aparência de um capítulo. Motivo (achado testando no tablet, 30/09/2026):
    quando recebia "Nome: aparência no capítulo 1", a IA copiava esse texto para a
    sugestão do capítulo 4, e a sugestão parecia descrever o capítulo errado. A lista serve
    a dois fins: a IA **usar o mesmo nome** de quem já existe e reconhecer apelidos pela
    identidade.

    **Tem teto** (``TETO_DO_CONTEXTO_DA_IA`` caracteres): vão primeiro os elementos que
    apareceram **mais recentemente** (o capítulo do estado vigente mais novo), e os sem estado
    por último. O que não cabe fica fora — o casamento automático é por nome, no servidor, e
    não depende desta lista.
    """
    elementos = list(
        sessao.scalars(select(Elemento).where(Elemento.livro_id == capitulo.livro_id))
    )
    vigentes = estado_vigente_por_elemento(sessao, capitulo.livro_id, capitulo.ordem - 1)

    def prioridade(elemento: Elemento) -> tuple[int, int, int]:
        vigente = vigentes.get(elemento.id)
        if vigente is None:
            return (1, 0, elemento.id)
        return (0, -vigente.capitulo.ordem, elemento.id)

    linhas: list[str] = []
    total = 0
    for elemento in sorted(elementos, key=prioridade):
        identidade = resumir_texto(
            identidade_vigente(sessao, elemento, capitulo.ordem - 1), LIMITE_DA_IDENTIDADE_NO_CONTEXTO
        )
        linha = f"{elemento.nome} ({elemento.tipo.name})"
        if identidade:
            linha = f"{linha}: {identidade}"
        if total + len(linha) + 1 > TETO_DO_CONTEXTO_DA_IA:
            break
        linhas.append(linha)
        total += len(linha) + 1
    return linhas


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
