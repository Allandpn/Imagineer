"""Rotas das sugestões de IA e dos artefatos de um capítulo (Etapas 6.7 e 6.8).

Analisar o capítulo, corrigir o casamento de uma sugestão, descartar, buscar sugestões por nome no livro e ler os artefatos a desenhar sobre o texto. A regra de negócio mora em `servicos/sugestoes.py` e `servicos/artefatos.py`; aqui ficam só o HTTP e a montagem da resposta."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.frame import PosicaoManualDoArtefato, PosicaoManualNova
from imagineer.esquemas.elemento import (
    ArtefatosDeUmCapitulo,
    ArtefatosDoLivro,
    SituacaoDoArtefato,
    TipoDeArtefato,
    ArtefatosDoCapitulo,
    CenaSugerida as CenaSugeridaResposta,
    ElementoCasado,
    ElementoSugerido as ElementoSugeridoResposta,
    EstadoVigenteDaSugestao,
    MarcadoresDoCapitulo,
    ParticipanteSugerido as ParticipanteSugeridoResposta,
    PedidoDeAnalise,
    SugestaoDeCenaAjuste,
    SugestaoDeElementoAjuste,
    SugestaoDeElementoBuscada,
    SugestoesDeCapitulo,
)
from imagineer.ia.catalogo_de_texto import obter_capacidades
from imagineer.ia.provedor import ModeloNaoEscolhido, ProvedorIA
from imagineer.servicos.acesso import buscar_visivel
from imagineer.servicos.configuracao_ia import modelo_de_leitura, obter_ou_criar
from imagineer.servicos.estimativa_de_leitura import estimar_leitura
from imagineer.modelos import Capitulo, EstadoElemento, Frame, SugestaoDeCena, SugestaoDeElemento, TipoDeFrame
from imagineer.rotas._comum import (
    buscar_capitulo as _buscar_capitulo,
    buscar_elemento as _buscar_elemento,
    buscar_livro as _buscar_livro,
    buscar_sugestao_de_elemento as _buscar_sugestao_de_elemento,
)
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.artefatos import artefatos_do_capitulo
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento
from imagineer.servicos.identidade_de_elemento import identidade_vigente, resumir_texto
from imagineer.servicos.posicao_no_texto import posicao_da_primeira_mencao, tamanho_em_utf16
from imagineer.servicos.sugestoes import (
    casar_sugestoes_pendentes,
    estado_id_no_capitulo,
    gerar_sugestoes,
    sugestoes_pendentes_anteriores,
    texto_normalizado,
)
from imagineer.servicos.trava_de_analise import analise_exclusiva

rotas_de_livro = APIRouter(prefix="/livros", tags=["Sugestões"])
rotas_de_capitulo = APIRouter(prefix="/capitulos", tags=["Sugestões"])
rotas_de_sugestao_elemento = APIRouter(prefix="/sugestoes-elemento", tags=["Sugestões"])
rotas_de_sugestao_cena = APIRouter(prefix="/sugestoes-cena", tags=["Sugestões"])

#: O quanto da identidade do elemento casado vai na resposta de cada sugestão.
LIMITE_DA_IDENTIDADE_NA_SUGESTAO = 300


def _artefatos_do_livro(sessao: Session, livro_id: int, aceita) -> ArtefatosDoLivro:
    """Os artefatos de cada capítulo **ativo** do livro que passam em ``aceita(artefato)``, na ordem do livro (LY7, LY8)."""
    capitulos = sessao.scalars(
        select(Capitulo).where(Capitulo.livro_id == livro_id, Capitulo.ignorado.is_(False)).order_by(Capitulo.ordem)
    ).all()
    grupos = []
    for capitulo in capitulos:
        escolhidos = [a for a in artefatos_do_capitulo(sessao, capitulo) if aceita(a)]
        if escolhidos:
            grupos.append(ArtefatosDeUmCapitulo(capitulo_id=capitulo.id, ordem=capitulo.ordem, titulo=capitulo.titulo, artefatos=escolhidos))
    sessao.commit()  # grava as dimensões de imagens antigas, calculadas agora
    return ArtefatosDoLivro(total=sum(len(g.artefatos) for g in grupos), capitulos=grupos)


@rotas_de_livro.get(
    "/{livro_id}/pendencias",
    response_model=ArtefatosDoLivro,
    summary="Todas as sugestões ainda não confirmadas do livro, por capítulo",
)
def ler_pendencias_do_livro(livro_id: int, sessao: Session = Depends(obter_sessao)) -> ArtefatosDoLivro:
    """A tela de Pendências (LY7): os artefatos com situação ``SUGERIDO`` (elementos e cenas) de cada capítulo ativo. **Só lê.**"""
    _buscar_livro(sessao, livro_id)
    return _artefatos_do_livro(sessao, livro_id, lambda a: a.situacao == SituacaoDoArtefato.SUGERIDO)


@rotas_de_livro.get(
    "/{livro_id}/cenas",
    response_model=ArtefatosDoLivro,
    summary="Todas as cenas do livro, por capítulo, em qualquer situação",
)
def ler_cenas_do_livro(livro_id: int, sessao: Session = Depends(obter_sessao)) -> ArtefatosDoLivro:
    """A tela de Cenas (LY8): os artefatos de tipo ``CENA`` (sugeridas, confirmadas, com prompt, ilustradas) de cada capítulo ativo. **Só lê.**"""
    _buscar_livro(sessao, livro_id)
    return _artefatos_do_livro(sessao, livro_id, lambda a: a.tipo == TipoDeArtefato.CENA)


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

    alvo = texto_normalizado(nome)
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
            estado_id=estado_id_no_capitulo(sessao, sugestao),
        )
        for sugestao, ordem, titulo in linhas
        if alvo in texto_normalizado(sugestao.nome)
    ]


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


def _exigir_posicao_manual_valida(capitulo, posicao: int | None) -> None:
    """422 se a posição passa do fim do texto do capítulo, contado em UTF-16 (PM4)."""
    if posicao is None:
        return
    tamanho = tamanho_em_utf16(capitulo.texto)
    if posicao > tamanho:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A posição {posicao} passa do fim do capítulo, que tem {tamanho} unidades UTF-16.",
        )


@rotas_de_sugestao_elemento.put(
    "/{sugestao_elemento_id}/posicao",
    response_model=PosicaoManualDoArtefato,
    summary="Põe o artefato do elemento num parágrafo, à mão (ou tira a posição manual)",
)
def posicionar_elemento(
    sugestao_elemento_id: int, corpo: PosicaoManualNova, sessao: Session = Depends(obter_sessao)
) -> PosicaoManualDoArtefato:
    """PM1 a PM4: o usuário escolheu o parágrafo do artefato. Vale mais que a posição achada pelo nome e **sobrevive a uma
    reanálise**. `null` tira a escolha. Nunca chama a IA."""
    sugestao = _buscar_sugestao_de_elemento(sessao, sugestao_elemento_id)
    _exigir_posicao_manual_valida(sugestao.capitulo, corpo.posicao_no_texto)
    sugestao.posicao_manual = corpo.posicao_no_texto
    # O frame (o retrato) com posição própria manda sobre a manual: para reposicionar de verdade, ele a segue.
    if sugestao.elemento_id is not None:
        retrato = None
        for frame in sessao.scalars(select(Frame).where(Frame.capitulo_id == sugestao.capitulo_id, Frame.apagado_em.is_(None)).order_by(Frame.id)):
            if frame.tipo == TipoDeFrame.PERSONAGEM and len(frame.estados_elemento) == 1 and frame.estados_elemento[0].elemento_id == sugestao.elemento_id:
                retrato = frame  # o mais novo vence, como nos artefatos
        if retrato is not None and retrato.posicao_no_texto is not None:
            retrato.posicao_no_texto = corpo.posicao_no_texto
    sessao.commit()
    return PosicaoManualDoArtefato(sugestao_id=sugestao.id, posicao_manual=sugestao.posicao_manual)


@rotas_de_sugestao_cena.put(
    "/{sugestao_cena_id}/posicao",
    response_model=PosicaoManualDoArtefato,
    summary="Põe o artefato da cena num parágrafo, à mão (ou tira a posição manual)",
)
def posicionar_cena(
    sugestao_cena_id: int, corpo: PosicaoManualNova, sessao: Session = Depends(obter_sessao)
) -> PosicaoManualDoArtefato:
    """PM1 a PM4, para cenas. Mesmas regras de `PUT /sugestoes-elemento/{id}/posicao`."""
    cena = buscar_visivel(sessao, SugestaoDeCena, sugestao_cena_id)
    if cena is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe sugestão de cena com id {sugestao_cena_id}.",
        )
    _exigir_posicao_manual_valida(cena.capitulo, corpo.posicao_no_texto)
    cena.posicao_manual = corpo.posicao_no_texto
    if cena.frame is not None and cena.frame.posicao_no_texto is not None:
        cena.frame.posicao_no_texto = corpo.posicao_no_texto  # o frame manda sobre a manual: ele a segue
    sessao.commit()
    return PosicaoManualDoArtefato(sugestao_id=cena.id, posicao_manual=cena.posicao_manual)


@rotas_de_sugestao_cena.patch(
    "/{sugestao_cena_id}",
    response_model=CenaSugeridaResposta,
    summary="Descarta, restaura ou edita (título e descrição) uma sugestão de cena",
)
def ajustar_sugestao_de_cena(
    sugestao_cena_id: int,
    ajuste: SugestaoDeCenaAjuste,
    sessao: Session = Depends(obter_sessao),
) -> CenaSugeridaResposta:
    """`descartada: true` tira a cena das pendentes e ela sobrevive a uma reanálise;
    `false` a restaura. Uma cena que já virou Frame não se descarta (409): o Frame existe."""
    cena = buscar_visivel(sessao, SugestaoDeCena, sugestao_cena_id)
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
    if ajuste.descartada is not None:
        cena.descartada = ajuste.descartada
    # LV6: editar o título e a descrição; o frame da cena (se já existe) acompanha, para o modal e o prompt dizerem o mesmo.
    if ajuste.titulo is not None:
        cena.titulo = ajuste.titulo
        if cena.frame is not None:
            cena.frame.titulo = ajuste.titulo
    if ajuste.descricao is not None:
        cena.descricao = ajuste.descricao.strip() or None
        if cena.frame is not None:
            cena.frame.descricao = cena.descricao
    sessao.commit()
    sessao.refresh(cena)

    capitulo = cena.capitulo
    vigentes = estado_vigente_por_elemento(sessao, capitulo.livro_id, capitulo.ordem)
    return _resposta_de_cena(sessao, cena, capitulo, vigentes)


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
        with analise_exclusiva(capitulo_id):  # 409 se já há uma análise rodando (imagineer/erros.py)
            gerar_sugestoes(sessao, provedor, capitulo)

    casar_sugestoes_pendentes(sessao, capitulo_id, capitulo.livro_id)

    pendentes_anteriores = sugestoes_pendentes_anteriores(sessao, capitulo)
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
        casar_sugestoes_pendentes(sessao, capitulo_id, capitulo.livro_id)

    pendentes_anteriores = sugestoes_pendentes_anteriores(sessao, capitulo)
    return _sugestoes_de_capitulo(sessao, capitulo, pendentes_anteriores)


class EstimativaDeLeituraDoCapitulo(BaseModel):
    """Quanto custaria ler um capítulo, antes de gastar (item 4.10, LM15)."""

    modelo: str = Field(description="O modelo de leitura (ou, na falta dele, o de extração ou de prompt) cujos preços entraram na conta.")
    tokens_do_capitulo: int = Field(description="Tamanho estimado do capítulo, em tokens.")
    elementos: int = Field(description="Quantos elementos entraram na conta (o que veio em `elementos`, ou as sugestões não descartadas).")
    cenas: int = Field(description="Quantas cenas entraram na conta (o que veio em `cenas`, ou as sugestões não descartadas).")
    leituras: int = Field(description="Quantas chamadas à IA a leitura faz: estado e identidade por elemento, dossiê por cena e, se ainda não analisado, a extração.")
    inclui_extracao: bool = Field(description="O capítulo ainda não foi analisado: a conta inclui a chamada de extração dos elementos.")
    custo_sem_cache: float | None = Field(description="US$, se cada leitura pagasse o capítulo inteiro. Nulo = o catálogo não tem o preço do modelo.")
    custo_com_cache: float | None = Field(description="US$, com o capítulo em cache entre as leituras. Nulo = o catálogo não tem o preço do modelo.")
    aviso: str


@rotas_de_capitulo.get(
    "/{capitulo_id}/estimativa-de-leitura",
    response_model=EstimativaDeLeituraDoCapitulo,
    summary="Estima quanto custa ler o capítulo, sem chamar a IA",
)
def estimar_custo_da_leitura(
    capitulo_id: int,
    elementos: int | None = Query(
        default=None, ge=0, le=500, description="Quantos elementos contar. Padrão: as sugestões de elemento do capítulo não descartadas."
    ),
    cenas: int | None = Query(
        default=None, ge=0, le=500, description="Quantas cenas contar. Padrão: as sugestões de cena do capítulo não descartadas."
    ),
    sessao: Session = Depends(obter_sessao),
) -> EstimativaDeLeituraDoCapitulo:
    """A conta de ler o capítulo, para a tela mostrar **antes** de "Analisar" (item 4.10, LM15). **Nunca chama a IA** (não declara o provedor).

    Usa os preços do **catálogo ao vivo** do OpenRouter para o modelo de leitura em uso (`modelo_leitura`, senão `modelo_extracao`, senão
    `modelo_prompt`). `elementos` e `cenas` deixam a tela perguntar "e se fossem 10?". Capítulo ainda não analisado inclui a extração.
    Modelo sem preço no catálogo: os custos vêm nulos e o `aviso` diz isso."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)  # 404 para capítulo de outra pessoa
    configuracao = obter_ou_criar(sessao)
    modelo = modelo_de_leitura(configuracao)
    if not modelo:
        raise ModeloNaoEscolhido("Nenhum modelo de leitura foi escolhido. Configure um em /configuracao.")

    if elementos is None:
        elementos = sessao.scalar(
            select(func.count()).select_from(SugestaoDeElemento).where(
                SugestaoDeElemento.capitulo_id == capitulo.id, SugestaoDeElemento.descartada.is_(False)
            )
        )
    if cenas is None:
        cenas = sessao.scalar(
            select(func.count()).select_from(SugestaoDeCena).where(
                SugestaoDeCena.capitulo_id == capitulo.id, SugestaoDeCena.descartada.is_(False)
            )
        )

    ainda_nao_analisado = capitulo.sugestoes_geradas_em is None
    estimativa = estimar_leitura(
        capitulo.texto,
        obter_capacidades(modelo),
        elementos,
        cenas,
        com_extracao=ainda_nao_analisado,
        capacidades_da_extracao=obter_capacidades(configuracao.modelo_extracao) if configuracao.modelo_extracao else None,
    )
    return EstimativaDeLeituraDoCapitulo(
        modelo=modelo,
        tokens_do_capitulo=estimativa.tokens_do_capitulo,
        elementos=elementos,
        cenas=cenas,
        leituras=estimativa.leituras,
        inclui_extracao=ainda_nao_analisado,
        custo_sem_cache=None if estimativa.custo_sem_cache is None else float(round(estimativa.custo_sem_cache, 6)),
        custo_com_cache=None if estimativa.custo_com_cache is None else float(round(estimativa.custo_com_cache, 6)),
        aviso=estimativa.aviso,
    )


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
    artefatos = artefatos_do_capitulo(sessao, _buscar_capitulo(sessao, capitulo_id))
    sessao.commit()  # grava as dimensões de imagens antigas, calculadas agora (não sobe a revisão)
    return ArtefatosDoCapitulo(artefatos=artefatos)


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
    artefatos = artefatos_do_capitulo(sessao, _buscar_capitulo(sessao, capitulo_id))
    sessao.commit()
    return MarcadoresDoCapitulo(marcadores=artefatos)


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
        estado_id=estado_id_no_capitulo(sessao, sugestao),
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
        trecho=cena.trecho,
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
                estado_id=estado_id_no_capitulo(sessao, participante),
            )
            for participante in cena.participantes
        ],
    )
