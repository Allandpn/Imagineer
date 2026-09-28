"""Rotas de prompts e catálogo de imagens (Etapa 6.6).

Cobrem os passos 8 a 11 do fluxo da Etapa 2: montar o prompt a partir do frame,
levá-lo a uma ferramenta de geração de imagem fora do sistema, e trazer o
resultado de volta para o catálogo.
"""

import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.prompt import (
    ImagemResumo,
    PromptAjuste,
    PromptDetalhe,
    PromptNovo,
    PromptResumo,
)
from imagineer.ia.provedor import (
    ChaveDeApiAusente,
    ErroDoProvedorIA,
    ModeloNaoEscolhido,
    ProvedorIA,
)
from imagineer.modelos import (
    Capitulo,
    Configuracao,
    EstadoElemento,
    Frame,
    HistoricoIdentidadeElemento,
    Imagem,
    Livro,
    PerfilRenderizacao,
    PrioridadeIA,
    Prompt,
    TipoDeFrame,
)
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.catalogo_imagens import (
    TAMANHO_MAXIMO_DA_IMAGEM,
    ExtensaoDeImagemInvalida,
    caminho_absoluto,
    remover_arquivo,
    salvar_imagem,
)
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.identidade_de_elemento import identidade_vigente
from imagineer.servicos.upload import ler_com_limite

rotas_de_frame = APIRouter(prefix="/frames", tags=["Prompts"])
rotas = APIRouter(prefix="/prompts", tags=["Prompts"])
rotas_de_imagem = APIRouter(prefix="/imagens", tags=["Prompts"])


# --------------------------------------------------------------------------- #
# Prompts de um frame
# --------------------------------------------------------------------------- #


@rotas_de_frame.get(
    "/{frame_id}/prompts",
    response_model=list[PromptResumo],
    summary="O histórico de prompts do frame",
)
def listar_prompts(frame_id: int, sessao: Session = Depends(obter_sessao)) -> list[PromptResumo]:
    """Os prompts já montados para o frame, do mais antigo ao mais recente."""
    _buscar_frame(sessao, frame_id)

    prompts = list(
        sessao.scalars(select(Prompt).where(Prompt.frame_id == frame_id).order_by(Prompt.id))
    )
    contagens = _contar_imagens(sessao, [prompt.id for prompt in prompts])
    return [_resumo(prompt, contagens.get(prompt.id, 0)) for prompt in prompts]


@rotas_de_frame.post(
    "/{frame_id}/prompts",
    response_model=PromptDetalhe,
    status_code=status.HTTP_201_CREATED,
    summary="Monta o prompt com a IA",
)
def criar_prompt(
    frame_id: int,
    corpo: PromptNovo,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> PromptDetalhe:
    """Monta o prompt de imagem a partir do frame (passo 8).

    Antes de montar o prompt: (1) faz a leitura profunda (item 4.4) de cada
    estado do frame que ainda precisa dela — sempre, em modo `QUALIDADE`; só se
    nunca lido, em modo `ECONOMIA`; e (2), só para frames do tipo CENA, confere
    o que o usuário escreveu contra o capítulo (`fundamentar_frame`) — sem
    sobrescrever: o resultado é contexto de apoio, a descrição do usuário
    continua tendo prioridade na montagem final. Um frame do tipo PERSONAGEM
    não passa por isso — o prompt usa só a descrição do próprio elemento, sem
    citar mais ninguém. O perfil vem do pedido ou do padrão do livro, e os
    modelos vêm do pedido ou da configuração — sempre nessa ordem de preferência.
    """
    frame = _buscar_frame(sessao, frame_id)
    livro = frame.capitulo.livro
    configuracao = obter_ou_criar(sessao)

    perfil = _resolver_perfil(sessao, corpo.perfil_renderizacao_id, livro)
    modelo_prompt = corpo.modelo or configuracao.modelo_prompt
    if not modelo_prompt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nenhum modelo de prompt foi escolhido. Configure um em /configuracao.",
        )

    try:
        _fazer_leitura_profunda(sessao, provedor, frame, configuracao)
        contexto_do_livro = _fundamentar_se_necessario(sessao, provedor, frame, configuracao)
        resultado = provedor.montar_prompt(
            descricao_do_frame=_descricao_do_frame(frame),
            elementos=_elementos_do_frame(frame),
            perfil_renderizacao=_descricao_do_perfil(perfil),
            modelo=modelo_prompt,
            contexto_do_livro=contexto_do_livro,
            comentario_do_usuario=corpo.comentario,
        )
    except (ChaveDeApiAusente, ModeloNaoEscolhido) as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro
    except ErroDoProvedorIA as erro:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(erro)
        ) from erro

    prompt = Prompt(
        frame_id=frame.id,
        perfil_renderizacao_id=perfil.id if perfil else None,
        modelo_ia=resultado.modelo,
        texto=resultado.texto,
    )
    sessao.add(prompt)
    sessao.commit()
    sessao.refresh(prompt)
    return _detalhe(prompt, [], _referencias_visuais(frame))


# --------------------------------------------------------------------------- #
# Um prompt
# --------------------------------------------------------------------------- #


@rotas.get("/{prompt_id}", response_model=PromptDetalhe, summary="Abre um prompt")
def abrir_prompt(prompt_id: int, sessao: Session = Depends(obter_sessao)) -> PromptDetalhe:
    """O prompt com as imagens que saíram dele."""
    prompt = _buscar_prompt(sessao, prompt_id)
    imagens = list(
        sessao.scalars(
            select(Imagem).where(Imagem.prompt_id == prompt_id).order_by(Imagem.id)
        )
    )
    return _detalhe(prompt, imagens, _referencias_visuais(prompt.frame))


@rotas.patch("/{prompt_id}", response_model=PromptDetalhe, summary="Anota a avaliação do resultado")
def ajustar_prompt(
    prompt_id: int, ajuste: PromptAjuste, sessao: Session = Depends(obter_sessao)
) -> PromptDetalhe:
    """Registra o que você achou do resultado, para comparar modelos depois."""
    prompt = _buscar_prompt(sessao, prompt_id)
    prompt.avaliacao = ajuste.avaliacao
    sessao.commit()
    sessao.refresh(prompt)
    return abrir_prompt(prompt_id, sessao)


@rotas.delete(
    "/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove o prompt e suas imagens"
)
def remover_prompt(prompt_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga o prompt, as linhas de imagem e os arquivos delas no disco.

    A cascata do banco (item 3.4c) já apaga as linhas de ``imagens`` sozinha; o
    que ela não faz é tocar no disco, então os arquivos são removidos aqui, antes
    do commit.
    """
    prompt = _buscar_prompt(sessao, prompt_id)
    caminhos = list(
        sessao.scalars(select(Imagem.caminho_arquivo).where(Imagem.prompt_id == prompt_id))
    )

    sessao.delete(prompt)
    sessao.commit()

    for caminho in caminhos:
        remover_arquivo(caminho)


# --------------------------------------------------------------------------- #
# Imagens de um prompt
# --------------------------------------------------------------------------- #


@rotas.post(
    "/{prompt_id}/imagens",
    response_model=ImagemResumo,
    status_code=status.HTTP_201_CREATED,
    summary="Importa o arquivo de imagem gerado",
)
async def importar_imagem(
    prompt_id: int,
    arquivo: UploadFile = File(description="O arquivo de imagem gerado"),
    sessao: Session = Depends(obter_sessao),
) -> ImagemResumo:
    """Recebe de volta a imagem gerada fora do sistema (passos 10 e 11)."""
    prompt = _buscar_prompt(sessao, prompt_id)
    conteudo = await ler_com_limite(arquivo, TAMANHO_MAXIMO_DA_IMAGEM)

    try:
        caminho = salvar_imagem(prompt.id, arquivo.filename or "", conteudo)
    except ExtensaoDeImagemInvalida as erro:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)
        ) from erro

    imagem = Imagem(prompt_id=prompt.id, caminho_arquivo=caminho)
    sessao.add(imagem)
    sessao.commit()
    sessao.refresh(imagem)
    return ImagemResumo.model_validate(imagem)


# --------------------------------------------------------------------------- #
# Uma imagem
# --------------------------------------------------------------------------- #


@rotas_de_imagem.get("/{imagem_id}/arquivo", summary="Devolve o arquivo da imagem")
def baixar_imagem(imagem_id: int, sessao: Session = Depends(obter_sessao)) -> FileResponse:
    """O arquivo de imagem em si, para exibir ou baixar no app."""
    imagem = _buscar_imagem(sessao, imagem_id)
    caminho = caminho_absoluto(imagem.caminho_arquivo)
    if not caminho.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="O arquivo desta imagem não está mais no disco.",
        )

    tipo, _ = mimetypes.guess_type(caminho.name)
    return FileResponse(caminho, media_type=tipo or "application/octet-stream")


@rotas_de_imagem.delete(
    "/{imagem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a imagem do catálogo, e o arquivo do disco",
)
def remover_imagem(imagem_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga a linha do catálogo e o arquivo em disco."""
    imagem = _buscar_imagem(sessao, imagem_id)
    caminho_relativo = imagem.caminho_arquivo

    sessao.delete(imagem)
    sessao.commit()

    remover_arquivo(caminho_relativo)


# --------------------------------------------------------------------------- #
# Funções internas
# --------------------------------------------------------------------------- #


def _fazer_leitura_profunda(
    sessao: Session,
    provedor: ProvedorIA,
    frame: Frame,
    configuracao: Configuracao,
) -> None:
    """Relê o capítulo de origem de cada estado que precisa (item 4.4).

    Em modo ``QUALIDADE``, relê todos os estados do frame. Em modo ``ECONOMIA``
    (padrão), só os que ainda não passaram pela leitura profunda — o campo
    ``confirmado_pela_leitura_profunda`` é quem marca isso. Sobrescreve
    ``EstadoElemento.descricao`` no lugar: o livro é a fonte de verdade para a
    aparência de um elemento, mesmo que substitua o que foi digitado à mão no
    passo 7 — diferente da descrição do frame em si (ver ``_fundamentar_se_necessario``),
    onde quem tem prioridade é o usuário.

    Usa o modelo de **extração** (``modelo_extracao``), não o de prompt: ler e
    entender o capítulo é a mesma tarefa da fase 1, não a de escrever texto
    criativo que ``montar_prompt`` faz.
    """
    estados = list(frame.estados_elemento)
    a_reler = [
        estado
        for estado in estados
        if configuracao.prioridade_ia == PrioridadeIA.QUALIDADE
        or not estado.confirmado_pela_leitura_profunda
    ]
    if not a_reler:
        return

    modelo = configuracao.modelo_extracao
    if not modelo:
        raise ModeloNaoEscolhido(
            "Nenhum modelo de extração foi escolhido — ele também é usado na "
            "leitura profunda dos estados do frame. Configure um em /configuracao."
        )

    for estado in a_reler:
        capitulo_de_origem = sessao.get(Capitulo, estado.capitulo_id)
        sugestao = provedor.sugerir_estado(
            texto_capitulo=capitulo_de_origem.texto,
            tipo=estado.elemento.tipo,
            nome=estado.elemento.nome,
            descricao_do_elemento=estado.elemento.descricao,
            estado_atual=estado.descricao,
            modelo=modelo,
        )
        estado.descricao = sugestao.descricao
        estado.confirmado_pela_leitura_profunda = True
        sessao.add(estado)

        _sugerir_identidade_se_necessario(sessao, provedor, estado, capitulo_de_origem, modelo)


def _sugerir_identidade_se_necessario(
    sessao: Session,
    provedor: ProvedorIA,
    estado: EstadoElemento,
    capitulo_de_origem: Capitulo,
    modelo: str,
) -> None:
    """A leitura profunda de *identidade* — fase 2b do item 4.4, especificada
    no item 4.6 como resolução da pendência de prioridade alta da Etapa 8.

    Roda no mesmo ponto da fase 2 (aparência), reaproveitando a decisão de
    "este estado precisa ser relido" que ``_fazer_leitura_profunda`` já
    tomou — sem chamada de IA extra além da que a fase 2 já faz.

    **Gatilho é a existência do registro, não `prioridade_ia`.** Diferente da
    fase 2 (que sobrescreve o mesmo campo a cada releitura), aqui um
    incremento só é tentado uma vez por (elemento, capítulo): se já existe um
    `HistoricoIdentidadeElemento` para este par, não há por que perguntar de
    novo — mesmo em `QUALIDADE`, perguntar toda vez arriscaria um incremento
    quase idêntico repetido a cada prompt gerado.
    """
    ja_existe = sessao.execute(
        select(HistoricoIdentidadeElemento.id).where(
            HistoricoIdentidadeElemento.elemento_id == estado.elemento_id,
            HistoricoIdentidadeElemento.capitulo_id == capitulo_de_origem.id,
        )
    ).first()
    if ja_existe is not None:
        return

    identidade_ate_aqui = identidade_vigente(sessao, estado.elemento, capitulo_de_origem.ordem)
    sugestao = provedor.sugerir_identidade(
        texto_capitulo=capitulo_de_origem.texto,
        tipo=estado.elemento.tipo,
        nome=estado.elemento.nome,
        identidade_vigente=identidade_ate_aqui,
        modelo=modelo,
    )
    if sugestao.descricao is None:
        return

    sessao.add(
        HistoricoIdentidadeElemento(
            elemento_id=estado.elemento_id,
            capitulo_id=capitulo_de_origem.id,
            descricao=sugestao.descricao,
        )
    )


def _fundamentar_se_necessario(
    sessao: Session,
    provedor: ProvedorIA,
    frame: Frame,
    configuracao: Configuracao,
) -> str | None:
    """A leitura profunda de um frame do tipo CENA — item 4.4.

    Só se aplica a ``TipoDeFrame.CENA`` com pelo menos um elemento — um
    PERSONAGEM não tem "quem, onde, o quê" para conferir, e um frame sem
    ninguém ligado ainda não tem o que verificar. Respeita a mesma cache de
    ``prioridade_ia`` do item 4.4: em modo ``ECONOMIA``, reaproveita
    ``Frame.contexto_do_livro`` se já foi lido uma vez.

    **Não sobrescreve** ``titulo``/``descricao`` do frame — só grava o contexto
    obtido, que ``montar_prompt`` usa com prioridade menor que o que o usuário
    escreveu (a diferença central em relação a ``_fazer_leitura_profunda``).
    """
    if frame.tipo != TipoDeFrame.CENA or not frame.estados_elemento:
        return None

    if (
        configuracao.prioridade_ia == PrioridadeIA.ECONOMIA
        and frame.confirmado_pela_leitura_profunda
    ):
        return frame.contexto_do_livro

    modelo = configuracao.modelo_extracao
    if not modelo:
        raise ModeloNaoEscolhido(
            "Nenhum modelo de extração foi escolhido — ele também é usado na "
            "leitura profunda do frame. Configure um em /configuracao."
        )

    fundamentado = provedor.fundamentar_frame(
        texto_capitulo=frame.capitulo.texto,
        titulo=frame.titulo,
        descricao=frame.descricao,
        horario=frame.horario,
        clima=frame.clima,
        humor=frame.humor,
        participantes=_elementos_do_frame(frame),
        modelo=modelo,
    )
    frame.contexto_do_livro = fundamentado.contexto
    frame.confirmado_pela_leitura_profunda = True
    sessao.add(frame)
    return fundamentado.contexto


def _resolver_perfil(
    sessao: Session, perfil_id: int | None, livro: Livro
) -> PerfilRenderizacao | None:
    """O perfil pedido, ou o padrão do livro na ausência de um pedido explícito.

    Sem nenhum dos dois, devolve ``None`` — quem chama decide o que fazer, porque
    montar um prompt sem perfil nenhum não faz sentido (item 6.6).
    """
    escolhido = perfil_id or livro.perfil_renderizacao_padrao_id
    if escolhido is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Nenhum perfil de renderização foi informado, e o livro não tem "
                "um perfil padrão definido. Informe um ou configure o padrão do "
                "livro em PATCH /livros/{id}."
            ),
        )

    perfil = sessao.get(PerfilRenderizacao, escolhido)
    if perfil is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Não existe perfil de renderização com id {escolhido}.",
        )
    return perfil


def _descricao_do_frame(frame: Frame) -> str:
    """O texto que descreve o frame para a IA montar o prompt.

    Vazio para um frame do tipo PERSONAGEM: um retrato não referencia título,
    descrição nem atributos situacionais — só a aparência do próprio elemento
    (item 4.4). ``montar_prompt`` trata "vazio" como sinal de retrato solo.
    """
    if frame.tipo == TipoDeFrame.PERSONAGEM:
        return ""

    partes = [frame.titulo]
    if frame.descricao:
        partes.append(frame.descricao)

    situacionais = ", ".join(
        f"{rotulo}: {valor}"
        for rotulo, valor in (
            ("horário", frame.horario),
            ("clima", frame.clima),
            ("humor", frame.humor),
        )
        if valor
    )
    if situacionais:
        partes.append(situacionais)

    return "\n".join(partes)


def _elementos_do_frame(frame: Frame) -> list[str]:
    """"Nome (identidade): aparência", para cada elemento que aparece no frame.

    A identidade (``Elemento.descricao``) entra entre parênteses quando existe
    — é o que diz gênero, papel, natureza do elemento — sem ela, a IA que
    fundamenta a cena ou monta o prompt final nunca via essa informação,
    só a leitura profunda de UM estado (``sugerir_estado``) recebia (item 4.4).
    Omitida quando o elemento não tem identidade registrada.
    """
    partes = []
    for estado in sorted(frame.estados_elemento, key=lambda e: (e.elemento.tipo.name, e.elemento.nome)):
        nome = estado.elemento.nome
        if estado.elemento.descricao:
            partes.append(f"{nome} ({estado.elemento.descricao}): {estado.descricao}")
        else:
            partes.append(f"{nome}: {estado.descricao}")
    return partes


def _referencias_visuais(frame: Frame) -> list[Imagem]:
    """As imagens-âncora (item 3.1/4.5) já aprovadas para os elementos do frame.

    O fluxo de geração é manual (o usuário copia o prompt e cola numa
    ferramenta externa — passo 9), então a API não consegue anexar a imagem
    sozinha nessa chamada; o que dá para fazer é avisar quais referências
    existem, para o app oferecer "anexe também" — é o que mantém a aparência
    de um personagem consistente entre capítulos distantes, e entre
    ferramentas de geração diferentes a cada vez (item 4.5).

    Prioridade por elemento: a âncora do **Estado** ligado ao frame, se
    existir (é a mais específica — como ele está *nesta* cena); senão, a
    âncora **padrão** do Elemento (`imagem_ancora_padrao_id`, item 4.5) —
    "como ele normalmente parece". Sem nenhuma das duas, o elemento
    simplesmente não entra na lista.
    """
    vistas: dict[int, Imagem] = {}
    for estado in frame.estados_elemento:
        ancora = estado.imagem_ancora or estado.elemento.imagem_ancora_padrao
        if ancora is not None:
            vistas[ancora.id] = ancora
    return [vistas[identificador] for identificador in sorted(vistas)]


def _descricao_do_perfil(perfil: PerfilRenderizacao | None) -> str:
    """O texto de estilo que vai para a IA, só com os campos preenchidos.

    Cada ferramenta de imagem entende um subconjunto diferente de campos
    (item 3.4c), então só o que o perfil de fato define entra no texto.
    """
    if perfil is None:
        return ""

    partes = [perfil.nome]
    if perfil.estilo:
        partes.append(perfil.estilo)
    if perfil.artista_referencia:
        partes.append(f"referência: {perfil.artista_referencia}")
    if perfil.iluminacao:
        partes.append(f"iluminação: {perfil.iluminacao}")
    if perfil.paleta:
        partes.append(f"paleta: {perfil.paleta}")
    if perfil.formato:
        partes.append(f"formato: {perfil.formato}")

    return "; ".join(partes)


def _contar_imagens(sessao: Session, prompts_ids: list[int]) -> dict[int, int]:
    if not prompts_ids:
        return {}
    return dict(
        sessao.execute(
            select(Imagem.prompt_id, func.count(Imagem.id))
            .where(Imagem.prompt_id.in_(prompts_ids))
            .group_by(Imagem.prompt_id)
        ).all()
    )


def _resumo(prompt: Prompt, total_de_imagens: int) -> PromptResumo:
    return PromptResumo(
        id=prompt.id,
        frame_id=prompt.frame_id,
        perfil_renderizacao_id=prompt.perfil_renderizacao_id,
        modelo_ia=prompt.modelo_ia,
        texto=prompt.texto,
        avaliacao=prompt.avaliacao,
        data_criacao=prompt.data_criacao,
        total_de_imagens=total_de_imagens,
    )


def _detalhe(
    prompt: Prompt, imagens: list[Imagem], referencias: list[Imagem] | None = None
) -> PromptDetalhe:
    return PromptDetalhe(
        **_resumo(prompt, len(imagens)).model_dump(),
        imagens=[ImagemResumo.model_validate(imagem) for imagem in imagens],
        referencias_visuais=[
            ImagemResumo.model_validate(imagem) for imagem in (referencias or [])
        ],
    )


def _buscar_frame(sessao: Session, frame_id: int) -> Frame:
    frame = sessao.get(Frame, frame_id)
    if frame is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe frame com id {frame_id}.",
        )
    return frame


def _buscar_prompt(sessao: Session, prompt_id: int) -> Prompt:
    prompt = sessao.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe prompt com id {prompt_id}.",
        )
    return prompt


def _buscar_imagem(sessao: Session, imagem_id: int) -> Imagem:
    imagem = sessao.get(Imagem, imagem_id)
    if imagem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Não existe imagem com id {imagem_id}.",
        )
    return imagem
