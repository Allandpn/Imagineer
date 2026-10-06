"""Rotas de prompts e catálogo de imagens (Etapa 6.6).

Cobrem os passos 8 a 11 do fluxo da Etapa 2: montar o prompt a partir do frame,
levá-lo a uma ferramenta de geração de imagem fora do sistema, e trazer o
resultado de volta para o catálogo.
"""

import mimetypes

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.banco.sessao import obter_sessao
from imagineer.esquemas.prompt import (
    CenaComImagens,
    ElementoComImagens,
    ElementoParaVincular,
    ElementosParaVincular,
    ImagemCandidata,
    ImagemResumo,
    PromptAjuste,
    PromptDetalhe,
    PedidoDeGeracao,
    PedidoDeTraducaoParaIngles,
    PromptNovo,
    PromptResumo,
    ReferenciasCandidatas,
    ResultadoDaGeracao,
    Traducao,
)
from imagineer.ia.blocos_tecnicos import com_bloco_tecnico
from imagineer.ia.provedor import (
    ModeloNaoEscolhido,
    ProvedorIA,
)
from imagineer.servicos.acesso import buscar_visivel
from imagineer.modelos import (
    Capitulo,
    Configuracao,
    Elemento,
    EstadoElemento,
    Frame,
    HistoricoIdentidadeElemento,
    Imagem,
    Livro,
    PerfilRenderizacao,
    PrioridadeIA,
    Prompt,
    SugestaoDeCena,
    SugestaoDeElemento,
    TipoDeFrame,
    TipoDePrompt,
    TipoElemento,
)
from imagineer.rotas._comum import (
    buscar_capitulo as _buscar_capitulo,
    buscar_frame as _buscar_frame,
    buscar_imagem as _buscar_imagem,
    buscar_prompt as _buscar_prompt,
)
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.catalogo_imagens import (
    TAMANHO_MAXIMO_DA_IMAGEM,
    ExtensaoDeImagemInvalida,
    caminho_absoluto,
    remover_arquivo,
    salvar_imagem,
    tipo_da_imagem,
)
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.uso_de_ia import coletando_o_custo, gasto_do_livro
from imagineer.servicos.geracao_de_imagem import PedidoDeGeracaoInvalido, gerar_imagem_do_prompt
from imagineer.servicos.estados_de_elemento import estado_vigente_por_elemento
from imagineer.servicos.aparencia_de_elemento import aparencia_fixa_anterior, e_rascunho_de_identidade
from imagineer.servicos.identidade_de_elemento import LIMITE_DA_IDENTIDADE_NO_PROMPT, identidade_vigente, resumir_texto
from imagineer.servicos.lixeira import mover_para_a_lixeira
from imagineer.servicos.imagens_reduzidas import (
    TamanhoDeImagem,
    arquivo_no_tamanho,
    ler_dimensoes,
    remover_derivadas,
)
from imagineer.servicos.upload import ler_com_limite

rotas_de_frame = APIRouter(prefix="/frames", tags=["Prompts"])
rotas_de_capitulo = APIRouter(prefix="/capitulos", tags=["Prompts"])
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
def listar_prompts(
    frame_id: int,
    tipo: TipoDePrompt = Query(default=TipoDePrompt.IMAGEM, description="`IMAGEM` (padrão) ou `VIDEO` (item 4.8, VD7)."),
    sessao: Session = Depends(obter_sessao),
) -> list[PromptResumo]:
    """Os prompts já montados para o frame, do mais antigo ao mais recente. **Só os de imagem**, a menos que se peça `?tipo=VIDEO`:
    um prompt de vídeo não é "o prompt mais recente" de quem gera imagem."""
    _buscar_frame(sessao, frame_id)

    prompts = list(
        sessao.scalars(select(Prompt).where(Prompt.frame_id == frame_id, Prompt.tipo == tipo).order_by(Prompt.id))
    )
    contagens = _contar_imagens(sessao, [prompt.id for prompt in prompts])
    return [_resumo(prompt, contagens.get(prompt.id, 0)) for prompt in prompts]


@rotas_de_frame.get(
    "/{frame_id}/referencias-candidatas",
    response_model=ReferenciasCandidatas,
    summary="As imagens dos elementos do frame que podem ir como referência",
)
def referencias_candidatas(frame_id: int, sessao: Session = Depends(obter_sessao)) -> ReferenciasCandidatas:
    """Para cada elemento do frame, as imagens dele que o usuário pode mandar como referência visual (W2).

    As dos **frames de retrato** dele (``PERSONAGEM``, só ele), em qualquer capítulo, mais recentes primeiro (até 12), e a
    **âncora** (a do estado, senão a padrão do elemento) marcada e **sempre incluída**. Nunca chama a IA.
    """
    frame = _buscar_frame(sessao, frame_id)
    elementos: list[ElementoComImagens] = []
    for estado in sorted(frame.estados_elemento, key=lambda e: (e.elemento.tipo.name, e.elemento.nome)):
        elemento = estado.elemento
        elementos.append(
            ElementoComImagens(
                elemento_id=elemento.id,
                nome=elemento.nome,
                tipo=elemento.tipo.name,
                imagens=_imagens_candidatas(elemento, estado.imagem_ancora or elemento.imagem_ancora_padrao),
            )
        )
    return ReferenciasCandidatas(elementos=elementos)


def _imagens_candidatas(elemento: Elemento, ancora: Imagem | None) -> list[ImagemCandidata]:
    """As imagens de um elemento que podem ir como referência (W2, EV3).

    As dos **frames de retrato** dele (``PERSONAGEM``, só ele), em qualquer capítulo, mais recentes primeiro (até 12), e a
    **âncora** marcada e **sempre incluída**.
    """
    imagens: dict[int, Imagem] = {}
    for estado_do_elemento in elemento.estados:
        for outro in estado_do_elemento.frames:
            if outro.apagado_em is None and outro.tipo == TipoDeFrame.PERSONAGEM and len(outro.estados_elemento) == 1:
                for prompt in outro.prompts:
                    for imagem in prompt.imagens_ativas:
                        imagens[imagem.id] = imagem
    recentes = sorted(imagens.values(), key=lambda i: i.id, reverse=True)[:12]
    if ancora is not None and all(i.id != ancora.id for i in recentes):
        recentes.append(ancora)
    return [
        ImagemCandidata(
            **ImagemResumo.model_validate(i).model_dump(exclude={"orientacao"}),
            ancora=ancora is not None and i.id == ancora.id,
        )
        for i in recentes
    ]


@rotas_de_frame.get(
    "/{frame_id}/elementos-para-vincular",
    response_model=ElementosParaVincular,
    summary="Os elementos que podem entrar no frame (vinculados ou participantes), com as imagens deles",
)
def elementos_para_vincular(frame_id: int, sessao: Session = Depends(obter_sessao)) -> ElementosParaVincular:
    """O que o seletor de elementos e imagens mostra (EV1 a EV6). Nunca chama a IA.

    **Identificados:** os elementos das sugestões do capítulo (ligadas a um elemento, não descartadas), com o estado vigente
    até o capítulo. **Outros:** os elementos do livro com estado **neste** capítulo que a IA não sugeriu, com esse estado.
    Num **retrato**, só o próprio sujeito fica de fora (um personagem **pode** ser vinculado, V3 revisto) e, se o sujeito é um personagem (individual, V2),
    as duas listas vêm vazias. Numa **cena**, entram todos os tipos.
    """
    frame = _buscar_frame(sessao, frame_id)
    return _candidatos_a_vincular(sessao, frame.capitulo, frame)


@rotas_de_capitulo.get(
    "/{capitulo_id}/elementos-para-cena",
    response_model=ElementosParaVincular,
    summary="Os elementos que uma cena **ainda sem frame** pode levar (a cena de um trecho selecionado)",
)
def elementos_para_cena(capitulo_id: int, sessao: Session = Depends(obter_sessao)) -> ElementosParaVincular:
    """O mesmo seletor de ``GET /frames/{id}/elementos-para-vincular``, para quando a cena ainda não existe (LV8).

    ``identificados``, ``outros`` e ``de_outros_capitulos`` como lá; nenhum vem ``no_frame``, porque não há frame. Nunca chama a IA.
    """
    return _candidatos_a_vincular(sessao, _buscar_capitulo(sessao, capitulo_id), None)


def _candidatos_a_vincular(sessao: Session, capitulo, frame: Frame | None) -> ElementosParaVincular:
    """Monta as três listas do seletor para um capítulo; com ``frame``, marca quem já está nele (EV1 a EV7); sem, é uma cena nova."""
    livro_id = capitulo.livro_id
    retrato = frame is not None and frame.tipo == TipoDeFrame.PERSONAGEM

    sujeito = frame.estados_elemento[0].elemento if retrato and frame.estados_elemento else None
    if retrato and (sujeito is None or sujeito.tipo == TipoElemento.PERSONAGEM):
        return ElementosParaVincular(identificados=[], outros=[])

    no_frame = {e.elemento_id for e in frame.estados_elemento} | {e.elemento_id for e in frame.estados_vinculados} if frame is not None else set()
    # Os participantes que vieram da sugestão da cena nunca saem por este seletor (EV5).
    sugestao_da_cena = sessao.scalar(select(SugestaoDeCena).where(SugestaoDeCena.frame_id == frame.id)) if frame is not None else None
    originais = {s.elemento_id for s in sugestao_da_cena.participantes if s.elemento_id} if sugestao_da_cena else set()

    def pode_aparecer(elemento: Elemento) -> bool:
        if retrato:
            return elemento.id != sujeito.id  # V3 revisto: um personagem pode ser vinculado ao retrato de outro elemento
        return True

    def montar(elemento: Elemento, estado: EstadoElemento) -> ElementoParaVincular:
        ancora = estado.imagem_ancora or elemento.imagem_ancora_padrao
        dentro = elemento.id in no_frame
        return ElementoParaVincular(
            elemento_id=elemento.id,
            estado_id=estado.id,
            nome=elemento.nome,
            tipo=elemento.tipo.name,
            no_frame=dentro,
            removivel=dentro and elemento.id not in originais,
            imagens=_imagens_candidatas(elemento, ancora),
        )

    vigentes = estado_vigente_por_elemento(sessao, livro_id, capitulo.ordem)
    sugestoes = sessao.scalars(
        select(SugestaoDeElemento).where(
            SugestaoDeElemento.capitulo_id == capitulo.id,
            SugestaoDeElemento.elemento_id.is_not(None),
            SugestaoDeElemento.descartada.is_(False),
        )
    )
    identificados: dict[int, ElementoParaVincular] = {}
    for sugestao in sugestoes:
        elemento, estado = sugestao.elemento, vigentes.get(sugestao.elemento_id)
        if elemento is None or estado is None or elemento.id in identificados or not pode_aparecer(elemento):
            continue
        identificados[elemento.id] = montar(elemento, estado)

    outros: dict[int, ElementoParaVincular] = {}
    estados_do_capitulo = sessao.scalars(
        select(EstadoElemento)
        .join(Elemento, Elemento.id == EstadoElemento.elemento_id)
        .where(EstadoElemento.capitulo_id == capitulo.id, Elemento.livro_id == livro_id, Elemento.apagado_em.is_(None))
        .order_by(EstadoElemento.id)
    )
    for estado in estados_do_capitulo:
        elemento = estado.elemento
        if elemento.id in identificados or elemento.id in outros or not pode_aparecer(elemento):
            continue
        outros[elemento.id] = montar(elemento, estado)

    # VM7: os demais elementos do livro (sem estado neste capítulo), com o estado vigente até aqui ou, se só aparecem depois, o primeiro.
    de_outros_capitulos: dict[int, ElementoParaVincular] = {}
    elementos_do_livro = sessao.scalars(select(Elemento).where(Elemento.livro_id == livro_id, Elemento.apagado_em.is_(None)).order_by(Elemento.id))
    for elemento in elementos_do_livro:
        if elemento.id in identificados or elemento.id in outros or not pode_aparecer(elemento):
            continue
        estado = vigentes.get(elemento.id) or next(iter(sorted(elemento.estados, key=lambda e: (e.capitulo.ordem, e.id))), None)
        if estado is not None:
            de_outros_capitulos[elemento.id] = montar(elemento, estado)

    # Quem já está no frame entra sempre numa das listas (EV6), mesmo sem sugestão nem estado neste capítulo: o app grava o conjunto
    # inteiro (`PUT .../estados`), e um participante que sumisse da lista seria apagado da cena sem querer.
    for estado in [*frame.estados_elemento, *frame.estados_vinculados] if frame is not None else []:
        elemento = estado.elemento
        if elemento.id not in identificados and elemento.id not in outros and pode_aparecer(elemento):
            outros[elemento.id] = montar(elemento, estado)

    def ordenar(lista):
        return sorted(lista, key=lambda e: (e.tipo, e.nome))

    # Quem já está no frame, vindo de outro capítulo, aparece em "outros" (acima); aqui só quem ainda não está em nenhuma lista.
    de_outros_capitulos = {i: e for i, e in de_outros_capitulos.items() if i not in outros and i not in identificados}
    return ElementosParaVincular(
        identificados=ordenar(identificados.values()),
        outros=ordenar(outros.values()),
        de_outros_capitulos=ordenar(de_outros_capitulos.values()),
        cenas=_cenas_com_imagens(sessao, livro_id),
    )


def _cenas_com_imagens(sessao: Session, livro_id: int) -> list[CenaComImagens]:
    """As cenas do livro (``CENA``, fora da lixeira) que têm ao menos uma imagem ativa, por ordem do capítulo e do frame (EV15).

    As imagens vêm do mais novo para o mais antigo, até 12. Os prompts de **vídeo** não têm imagem, então não contam.
    """
    frames = sessao.scalars(
        select(Frame)
        .join(Capitulo, Capitulo.id == Frame.capitulo_id)
        .where(Capitulo.livro_id == livro_id, Frame.tipo == TipoDeFrame.CENA, Frame.apagado_em.is_(None))
        .order_by(Capitulo.ordem, Frame.id)
    )
    cenas: list[CenaComImagens] = []
    for frame in frames:
        imagens = sorted((i for prompt in frame.prompts for i in prompt.imagens_ativas), key=lambda i: i.id, reverse=True)[:12]
        if not imagens:
            continue
        cenas.append(
            CenaComImagens(
                frame_id=frame.id,
                titulo=frame.titulo,
                capitulo_id=frame.capitulo_id,
                ordem_do_capitulo=frame.capitulo.ordem,
                titulo_do_capitulo=frame.capitulo.titulo,
                imagens=[
                    ImagemCandidata(**ImagemResumo.model_validate(i).model_dump(exclude={"orientacao"}), ancora=False) for i in imagens
                ],
            )
        )
    return cenas


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
    eh_video = corpo.tipo == TipoDePrompt.VIDEO
    # VD11: o prompt de vídeo tem modelo próprio; vazio, vale o do prompt de imagem.
    modelo_prompt = corpo.modelo or (configuracao.modelo_video if eh_video else None) or configuracao.modelo_prompt
    if not modelo_prompt:
        raise ModeloNaoEscolhido("Nenhum modelo de prompt foi escolhido. Configure um em /configuracao.")
    # VD8: a imagem de partida é conferida **antes** de gastar IA.
    partida = _resolver_imagem_de_partida(sessao, frame, corpo)

    # Os erros do provedor sobem como estão: o tratador global os traduz para HTTP (imagineer/erros.py).
    with gasto_do_livro(livro.id):  # CU3: as chamadas daqui valem como gasto deste livro
        _fazer_leitura_profunda(sessao, provedor, frame, configuracao)
        contexto_do_livro = _fundamentar_se_necessario(sessao, provedor, frame, configuracao)
        if eh_video:
            resultado = provedor.montar_prompt_de_video(
                descricao_do_frame=_descricao_do_frame(frame),
                elementos=_elementos_do_frame(sessao, frame),
                perfil_renderizacao=_descricao_do_perfil(perfil, frame.tipo),
                modelo=modelo_prompt,
                contexto_do_livro=contexto_do_livro,
                comentario_do_usuario=corpo.comentario,
                elementos_vinculados=_elementos_vinculados(sessao, frame) or None,
                trecho_do_livro=frame.trecho,
                prompt_da_imagem=partida.prompt.texto if partida is not None else None,
                eh_retrato=frame.tipo == TipoDeFrame.PERSONAGEM,
            )
        else:
            resultado = provedor.montar_prompt(
                descricao_do_frame=_descricao_do_frame(frame),
                elementos=_elementos_do_frame(sessao, frame),
                perfil_renderizacao=_descricao_do_perfil(perfil, frame.tipo),
                modelo=modelo_prompt,
                contexto_do_livro=contexto_do_livro,
                comentario_do_usuario=corpo.comentario,
                elementos_vinculados=_elementos_vinculados(sessao, frame) or None,
                trecho_do_livro=frame.trecho,
            )

    prompt = Prompt(
        frame_id=frame.id,
        perfil_renderizacao_id=perfil.id if perfil else None,
        modelo_ia=resultado.modelo,
        # BT4: o bloco técnico da categoria do perfil entra aqui, por código, DEPOIS da resposta da IA (que nunca o vê).
        # VD5: no vídeo, o bloco técnico só entra sem imagem de partida (com ela, é a imagem que carrega o estilo).
        texto=(
            resultado.texto
            if eh_video and partida is not None
            else com_bloco_tecnico(resultado.texto, perfil.categoria_estilo if perfil else None)
        ),
        tipo=corpo.tipo,
        imagem_partida_id=partida.id if partida is not None else None,
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
            select(Imagem).where(Imagem.prompt_id == prompt_id, Imagem.apagada_em.is_(None)).order_by(Imagem.id)
        )
    )
    return _detalhe(prompt, imagens, _referencias_visuais(prompt.frame))


@rotas.patch("/{prompt_id}", response_model=PromptDetalhe, summary="Anota a avaliação do resultado")
def ajustar_prompt(
    prompt_id: int, ajuste: PromptAjuste, sessao: Session = Depends(obter_sessao)
) -> PromptDetalhe:
    """Registra o que você achou do resultado, para comparar modelos depois. Num prompt **de vídeo** também esconde/mostra (VD12) e
    edita o texto (VD13); ``oculto``, ``texto`` e ``texto_pt`` num prompt de imagem são 422."""
    prompt = _buscar_prompt(sessao, prompt_id)
    campos = ajuste.model_fields_set
    if campos & {"oculto", "texto", "texto_pt"} and prompt.tipo != TipoDePrompt.VIDEO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Esconder e editar o texto só valem num prompt de vídeo; o de imagem se edita ao gerar a imagem.",
        )
    if "avaliacao" in campos:
        prompt.avaliacao = ajuste.avaliacao
    if "oculto" in campos and ajuste.oculto is not None:
        prompt.oculto = ajuste.oculto
    if "texto" in campos and ajuste.texto is not None:
        prompt.texto = ajuste.texto
        prompt.texto_pt = ajuste.texto_pt if "texto_pt" in campos else None  # o inglês mudou: o português guardado já não o descreve
    elif "texto_pt" in campos:
        prompt.texto_pt = ajuste.texto_pt
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
    imagens = list(
        sessao.execute(
            select(Imagem.id, Imagem.caminho_arquivo).where(Imagem.prompt_id == prompt_id)
        ).all()
    )

    sessao.delete(prompt)
    sessao.commit()

    for imagem_id, caminho in imagens:
        remover_arquivo(caminho)
        remover_derivadas(imagem_id)


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

    # Um arquivo que o Pillow não lê continua aceito, só sem dimensões (como era antes de existirem).
    dimensoes = ler_dimensoes(conteudo)
    imagem = Imagem(
        prompt_id=prompt.id,
        caminho_arquivo=caminho,
        tamanho_em_bytes=len(conteudo),
        largura=dimensoes[0] if dimensoes else None,
        altura=dimensoes[1] if dimensoes else None,
    )
    sessao.add(imagem)
    sessao.commit()
    sessao.refresh(imagem)
    return ImagemResumo.model_validate(imagem)


TEXTO_DO_PROMPT_SO_DA_IMAGEM = "Imagem importada, sem prompt."


@rotas_de_frame.post(
    "/{frame_id}/imagens",
    response_model=ImagemResumo,
    status_code=status.HTTP_201_CREATED,
    summary="Importa uma imagem para o frame, mesmo sem prompt",
)
async def importar_imagem_para_o_frame(
    frame_id: int,
    arquivo: UploadFile = File(description="O arquivo de imagem que a pessoa já tem"),
    sessao: Session = Depends(obter_sessao),
) -> ImagemResumo:
    """A imagem vai para o prompt **mais recente com texto**; sem nenhum, o servidor cria um "prompt só da imagem" (PI1). Não gasta IA."""
    frame = _buscar_frame(sessao, frame_id)
    prompt = sessao.scalars(
        select(Prompt).where(Prompt.frame_id == frame.id, Prompt.so_imagem.is_(False), Prompt.tipo == TipoDePrompt.IMAGEM).order_by(Prompt.id.desc())
    ).first()
    if prompt is None:
        prompt = sessao.scalars(
            select(Prompt).where(Prompt.frame_id == frame.id, Prompt.so_imagem.is_(True), Prompt.tipo == TipoDePrompt.IMAGEM).order_by(Prompt.id.desc())
        ).first()
    if prompt is None:
        prompt = Prompt(frame_id=frame.id, texto=TEXTO_DO_PROMPT_SO_DA_IMAGEM, so_imagem=True)
        sessao.add(prompt)
        sessao.flush()
    try:
        return await importar_imagem(prompt.id, arquivo, sessao)
    except HTTPException:
        sessao.rollback()  # arquivo recusado: o prompt só da imagem, recém-criado, não fica
        raise


@rotas.post(
    "/{prompt_id}/gerar-imagem",
    response_model=ResultadoDaGeracao,
    summary="Gera a imagem pelo servidor, com suavização se o provedor recusar",
)
def gerar_imagem(
    prompt_id: int,
    corpo: PedidoDeGeracao | None = None,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> ResultadoDaGeracao:
    """Envia o prompt ao modelo de imagem (S1); se o provedor recusar o conteúdo, suaviza e tenta de novo (S2).

    Uma segunda recusa **devolve ao usuário** (S3), com o prompt enviado por último para ele editar.
    Recusa responde 200 (``RECUSADA``); só os outros erros do provedor viram 422/502, sem suavizar.
    """
    prompt = _buscar_prompt(sessao, prompt_id)
    try:
        resultado = gerar_imagem_do_prompt(
            sessao,
            provedor,
            prompt,
            obter_ou_criar(sessao),
            corpo.texto if corpo else None,
            corpo.modelo if corpo else None,
            sem_filtro_de_seguranca=bool(corpo and corpo.sem_filtro_de_seguranca),
            imagens_de_referencia=corpo.imagens_de_referencia if corpo else None,
            texto_pt=corpo.texto_pt if corpo else None,
        )
    except PedidoDeGeracaoInvalido as erro:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(erro)) from erro
    return ResultadoDaGeracao(
        resultado="GERADA" if resultado.gerada else "RECUSADA",
        suavizado=resultado.suavizado,
        prompt=_resumo(resultado.prompt, len(resultado.prompt.imagens_ativas)),
        imagem=ImagemResumo.model_validate(resultado.imagem) if resultado.imagem else None,
    )


# --------------------------------------------------------------------------- #
# Camada em português (PT1 a PT6)
# --------------------------------------------------------------------------- #


def _traduzir(sessao: Session, provedor: ProvedorIA, prompt: Prompt, texto: str, para: str) -> Traducao:
    """Chama o modelo da tradução (MT1; vazio: o da suavização, senão o de extração, senão o de prompt), anota o gasto como do livro do prompt
    (operação ``traducao``) e devolve a tradução com o custo da chamada (PT5, PT6)."""
    configuracao = obter_ou_criar(sessao)
    modelo = (
        configuracao.modelo_traducao
        or configuracao.modelo_suavizacao
        or configuracao.modelo_extracao
        or configuracao.modelo_prompt
    )
    if not modelo:
        raise ModeloNaoEscolhido("Nenhum modelo de texto foi escolhido para traduzir. Configure um em /configuracao.")
    livro_id = prompt.frame.capitulo.livro_id if prompt.frame is not None and prompt.frame.capitulo is not None else None
    with gasto_do_livro(livro_id), coletando_o_custo() as custos:
        traduzido = provedor.traduzir_prompt(texto, para, modelo)
    custo = next((c for c in custos if c is not None), None)
    return Traducao(texto=traduzido.texto, modelo=traduzido.modelo, custo=custo)


@rotas.post(
    "/{prompt_id}/traducao-pt",
    response_model=Traducao,
    summary="O prompt em português (traduz uma vez e guarda)",
)
def traduzir_para_portugues(
    prompt_id: int,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> Traducao:
    """PT2: devolve a versão em português do prompt. Se já está guardada (`texto_pt`), devolve **sem chamar a IA**; senão, traduz o
    inglês com o modelo barato, guarda e devolve com o custo da chamada. O que vai à imagem continua sendo o inglês."""
    prompt = _buscar_prompt(sessao, prompt_id)
    if prompt.texto_pt:
        return Traducao(texto=prompt.texto_pt, reaproveitada=True)
    traducao = _traduzir(sessao, provedor, prompt, prompt.texto, "pt")
    prompt.texto_pt = traducao.texto
    sessao.commit()
    return traducao


@rotas.post(
    "/{prompt_id}/traduzir-para-ingles",
    response_model=Traducao,
    summary="O português que a pessoa escreveu, em inglês (prévia, não grava)",
)
def traduzir_para_ingles(
    prompt_id: int,
    corpo: PedidoDeTraducaoParaIngles,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> Traducao:
    """PT3: traduz o português editado para o inglês que iria à imagem, **sem gravar nada**: é a prévia que a pessoa confere
    ("Inglês que será enviado") e pode ajustar. O inglês só vira prompt quando ela manda gerar a imagem (com `texto` e `texto_pt`)."""
    prompt = _buscar_prompt(sessao, prompt_id)
    return _traduzir(sessao, provedor, prompt, corpo.texto, "en")


# --------------------------------------------------------------------------- #
# Uma imagem
# --------------------------------------------------------------------------- #


@rotas_de_imagem.get("/{imagem_id}/arquivo", summary="Devolve o arquivo da imagem")
def baixar_imagem(
    imagem_id: int,
    tamanho: TamanhoDeImagem = Query(
        default=TamanhoDeImagem.ORIGINAL,
        description=(
            "`miniatura` (256 px no lado maior), `leitura` (1280 px) ou `original` (o arquivo como veio, "
            "o padrão). Nunca amplia: se a imagem já cabe, volta o original (item 6.9)."
        ),
    ),
    sessao: Session = Depends(obter_sessao),
) -> FileResponse:
    """O arquivo de imagem em si, para exibir ou baixar no app, no tamanho pedido.

    **Cache imutável** (item 6.9): o arquivo de uma imagem **nunca** muda — o nome é gerado
    (UUID) e nunca é sobrescrito; trocar a imagem é criar outra. Por isso o cliente pode
    guardá-la para sempre (`immutable`) sem nunca revalidar. O `ETag` e o `Last-Modified`
    vêm do próprio `FileResponse`.
    """
    imagem = _buscar_imagem(sessao, imagem_id)
    caminho = caminho_absoluto(imagem.caminho_arquivo)
    if not caminho.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="O arquivo desta imagem não está mais no disco.",
        )

    servido, tipo_da_versao = arquivo_no_tamanho(imagem.id, caminho, tamanho)
    tipo = tipo_da_versao or tipo_da_imagem(caminho) or mimetypes.guess_type(caminho.name)[0]
    return FileResponse(
        servido,
        media_type=tipo or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@rotas_de_imagem.delete(
    "/{imagem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Move a imagem para a lixeira",
)
def remover_imagem(imagem_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """**Move a imagem para a lixeira** (LX4): ela some dos prompts, do capítulo e da galeria, mas o arquivo continua no disco
    até o usuário apagar de vez (``DELETE /lixeira/imagens/{id}``). Mover uma que já está lá não dá erro."""
    mover_para_a_lixeira(sessao, _buscar_imagem(sessao, imagem_id))
    sessao.commit()


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
    # V6: os vinculados também são relidos, para a aparência deles valer neste capítulo.
    estados = list(frame.estados_elemento) + list(frame.estados_vinculados)
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
            # FD3: a identidade que o livro já revelou até este capítulo, e não só a inicial.
            descricao_do_elemento=identidade_vigente(sessao, estado.elemento, capitulo_de_origem.ordem),
            # FD1: o rascunho de identidade não é aparência: sem isto, "jovem nobre exilado" voltava como aparência quando o
            # capítulo não descrevia a pessoa.
            estado_atual=None if e_rascunho_de_identidade(sessao, estado) else estado.descricao,
            modelo=modelo,
            # FD2: o que o elemento já tinha de fixo num capítulo anterior já lido.
            aparencia_anterior=aparencia_fixa_anterior(sessao, estado),
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
        participantes=_elementos_do_frame(sessao, frame),
        modelo=modelo,
        trecho=frame.trecho,
    )
    frame.contexto_do_livro = fundamentado.contexto
    frame.confirmado_pela_leitura_profunda = True
    sessao.add(frame)
    return fundamentado.contexto


def _resolver_imagem_de_partida(sessao: Session, frame: Frame, corpo: PromptNovo) -> Imagem | None:
    """A imagem que será o primeiro quadro do vídeo (VD8), ou ``None`` (modo texto para vídeo, ou prompt de imagem).

    Pedida: tem de existir, não estar na lixeira e ser de um prompt **deste frame** (ou a canônica dele, que pode vir de outro retrato do
    mesmo elemento, VM3): 422 caso contrário. Não pedida: a canônica do frame e, sem ela, a imagem mais recente; só um frame sem imagem
    nenhuma gera o prompt de texto para vídeo. Só vale em ``tipo=VIDEO``: num prompt de imagem, pedir uma é 422.
    """
    if corpo.tipo != TipoDePrompt.VIDEO:
        if corpo.imagem_partida_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A imagem de partida só vale num prompt de vídeo (tipo=VIDEO).",
            )
        return None

    do_frame = [
        imagem
        for prompt in sessao.scalars(select(Prompt).where(Prompt.frame_id == frame.id, Prompt.tipo == TipoDePrompt.IMAGEM))
        for imagem in prompt.imagens_ativas
    ]
    if corpo.imagem_partida_id is not None:
        imagem = buscar_visivel(sessao, Imagem, corpo.imagem_partida_id)
        valida = imagem is not None and imagem.apagada_em is None and (
            imagem in do_frame or imagem.id == frame.imagem_canonica_id
        )
        if not valida:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A imagem de partida tem de ser uma imagem deste frame (que não esteja na lixeira).",
            )
        return imagem

    canonica = sessao.get(Imagem, frame.imagem_canonica_id) if frame.imagem_canonica_id is not None else None
    if canonica is not None and canonica.apagada_em is None:
        return canonica
    return max(do_frame, key=lambda i: (i.data_importacao, i.id), default=None)


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

    perfil = buscar_visivel(sessao, PerfilRenderizacao, escolhido)
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


def _elementos_vinculados(sessao: Session, frame: Frame) -> list[str]:
    """As linhas "Nome (identidade): aparência" dos elementos **vinculados** ao sujeito de um retrato (V5)."""
    return _linhas_de_estados(sessao, frame.estados_vinculados, frame.capitulo.ordem)


def _elementos_do_frame(sessao: Session, frame: Frame) -> list[str]:
    """"Nome (identidade): aparência", para cada elemento que aparece no frame.

    A identidade (``Elemento.descricao``) entra entre parênteses quando existe
    — é o que diz gênero, papel, natureza do elemento — sem ela, a IA que
    fundamenta a cena ou monta o prompt final nunca via essa informação,
    só a leitura profunda de UM estado (``sugerir_estado``) recebia (item 4.4).
    Omitida quando o elemento não tem identidade registrada.
    """
    return _linhas_de_estados(sessao, frame.estados_elemento, frame.capitulo.ordem)


def _linhas_de_estados(sessao: Session, estados, ordem_do_capitulo: int) -> list[str]:
    """"Nome (identidade): aparência" para cada estado, por tipo e nome.

    A identidade é a **vigente até o capítulo do frame** (FD3), e não só a inicial: o que o livro revelou depois (idade, gênero, origem)
    chega ao prompt. Resumida, porque ela cresce a cada capítulo.
    """
    partes = []
    for estado in sorted(estados, key=lambda e: (e.elemento.tipo.name, e.elemento.nome)):
        nome = estado.elemento.nome
        identidade = resumir_texto(identidade_vigente(sessao, estado.elemento, ordem_do_capitulo), LIMITE_DA_IDENTIDADE_NO_PROMPT)
        if identidade:
            partes.append(f"{nome} ({identidade}): {estado.descricao}")
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


_FORMATO_PADRAO_POR_TIPO = {
    TipoDeFrame.PERSONAGEM: "2:3, portrait orientation",
    TipoDeFrame.CENA: "16:9, landscape orientation",
}
"""Proporção usada quando o perfil não define uma (item 4.5/4.7).

Proporção não é escolha de estilo, é escolha ligada a **o que está sendo
retratado** — um retrato solo pede vertical, uma cena pede horizontal, na
maioria dos casos. Antes, `PerfilRenderizacao.formato` era a única fonte, e
por ser um campo só, compartilhado entre os dois tipos de frame, não dava
pra expressar os dois formatos ao mesmo tempo — o que levava a gambiarras
como digitar `"16:9 (para cenários) ou 2:3 (para retratos)"` num campo só,
texto que ia parar literal no prompt final sem funcionar como instrução."""


def _descricao_do_perfil(perfil: PerfilRenderizacao | None, tipo: TipoDeFrame) -> str:
    """O texto de estilo que vai para a IA, só com os campos preenchidos.

    Cada ferramenta de imagem entende um subconjunto diferente de campos
    (item 3.4c), então só o que o perfil de fato define entra no texto —
    exceto o formato, que sempre entra: com o valor do perfil se o usuário
    preencheu (override explícito, vale pros dois tipos de frame igualmente),
    senão com o padrão automático por `tipo` do frame.
    """
    partes = []
    if perfil is not None:
        partes.append(perfil.nome)
        if perfil.estilo:
            partes.append(perfil.estilo)
        if perfil.artista_referencia:
            partes.append(f"referência: {perfil.artista_referencia}")
        if perfil.iluminacao:
            partes.append(f"iluminação: {perfil.iluminacao}")
        if perfil.paleta:
            partes.append(f"paleta: {perfil.paleta}")

    formato = (perfil.formato if perfil else None) or _FORMATO_PADRAO_POR_TIPO[tipo]
    partes.append(f"formato: {formato}")

    return "; ".join(partes)


def _contar_imagens(sessao: Session, prompts_ids: list[int]) -> dict[int, int]:
    if not prompts_ids:
        return {}
    return dict(
        sessao.execute(
            select(Imagem.prompt_id, func.count(Imagem.id))
            .where(Imagem.prompt_id.in_(prompts_ids), Imagem.apagada_em.is_(None))
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
        texto_pt=prompt.texto_pt,
        tipo=prompt.tipo,
        imagem_partida_id=prompt.imagem_partida_id,
        so_imagem=prompt.so_imagem,
        oculto=prompt.oculto,
        avaliacao=prompt.avaliacao,
        data_criacao=prompt.data_criacao,
        total_de_imagens=total_de_imagens,
        situacao_da_geracao=prompt.situacao_da_geracao,
        motivo_da_recusa=prompt.motivo_da_recusa,
        prompt_original_id=prompt.prompt_original_id,
        modelo_imagem=prompt.modelo_imagem,
        sem_filtro_de_seguranca=prompt.sem_filtro_de_seguranca,
        imagens_de_referencia=list(prompt.imagens_de_referencia or []),
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


