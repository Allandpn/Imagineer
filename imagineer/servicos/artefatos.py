"""Os artefatos de um capítulo: os ícones a desenhar sobre o texto (itens 3.4g e 6.8).

Junta, num só lugar, o que o leitor precisa para desenhar o capítulo: as sugestões de elemento e de cena e os frames, cada um com a posição, a situação e a imagem mais recente. Só lê; nunca chama a IA."""

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from imagineer.esquemas.elemento import Artefato, SituacaoDoArtefato, TipoDeArtefato
from imagineer.modelos import Capitulo, Frame, Imagem, SugestaoDeCena, SugestaoDeElemento, TipoDeFrame
from imagineer.servicos.catalogo_imagens import caminho_absoluto
from imagineer.servicos.imagens_reduzidas import garantir_dimensoes, orientacao_de
from imagineer.servicos.posicao_no_texto import posicao_da_primeira_mencao
from imagineer.servicos.sugestoes import chave_normalizada


def _campos_da_imagem(imagem: Imagem | None) -> dict:
    """Os campos ``imagem_*`` de um artefato. Calcula as dimensões de uma imagem antiga (só em memória: quem
    chama, a rota, faz o commit do que isto preencheu)."""
    if imagem is None:
        return {}
    garantir_dimensoes(imagem, caminho_absoluto(imagem.caminho_arquivo))
    orientacao = orientacao_de(imagem.largura, imagem.altura)
    return {
        "imagem_id": imagem.id,
        "imagem_largura": imagem.largura,
        "imagem_altura": imagem.altura,
        "imagem_orientacao": orientacao.value if orientacao else None,
    }


def _situacao_e_imagem(frame: Frame | None, *, confirmado: bool) -> tuple[SituacaoDoArtefato, Imagem | None]:
    """A situação de um artefato e a imagem a mostrar: a **canônica** do frame (CAN4) ou, sem escolha, a mais recente.

    ``confirmado`` diz se a sugestão já virou elemento ou frame; sem isso, é só ``SUGERIDO``.
    """
    if not confirmado:
        return SituacaoDoArtefato.SUGERIDO, None
    # OC1: com a imagem oculta, o capítulo não a mostra (o artefato cai para "prompt pronto", se há prompt).
    imagens = [] if frame is None or frame.imagem_oculta else [imagem for prompt in frame.prompts for imagem in prompt.imagens_ativas]
    canonica = next((i for i in imagens if frame is not None and i.id == frame.imagem_canonica_id), None)
    if canonica is None and frame is not None and not frame.imagem_oculta and frame.imagem_canonica_id is not None:
        # VM3: a canônica de um retrato pode ser a imagem de outro retrato do mesmo elemento (de outro capítulo).
        de_fora = object_session(frame).get(Imagem, frame.imagem_canonica_id)
        canonica = de_fora if de_fora is not None and de_fora.apagada_em is None else None
    ultima = canonica or max(imagens, key=lambda i: (i.data_importacao, i.id), default=None)
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
            else ("nome", *chave_normalizada(sugestao.tipo, sugestao.nome))
        )
        if chave in vistas:
            continue
        vistas.add(chave)
        unicas.append(sugestao)
    return unicas


def artefatos_do_capitulo(sessao: Session, capitulo: Capitulo) -> list[Artefato]:
    """Monta os artefatos do capítulo.

    Cada sugestão **não descartada** vira um artefato. A posição dos **elementos** é achada **pelo
    nome**, no texto, na hora da leitura — funciona também nos capítulos já analisados. A das
    **cenas** vem da citação da IA, **gravada** quando a sugestão nasceu (item 3.4g): cena analisada
    antes disso fica sem posição até o capítulo ser reanalisado. Ordem: por posição; sem posição, depois.

    A situação mostra onde o usuário parou: ``SUGERIDO`` (não confirmado) → ``CONFIRMADO`` (virou
    elemento ou frame) → ``PROMPT_PRONTO`` (o frame tem prompt) → ``ILUSTRADO`` (o frame tem imagem).
    """
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
                # O frame manda: se a pessoa pôs o retrato num lugar, é ali (item 3.4g); depois, a posição posta à mão
                # (PM1); só então a achada pelo nome.
                posicao_no_texto=(
                    frame.posicao_no_texto
                    if frame is not None and frame.posicao_no_texto is not None
                    else sugestao.posicao_manual
                    if sugestao.posicao_manual is not None
                    else posicao_da_primeira_mencao(capitulo.texto, sugestao.nome)
                ),
                situacao=situacao,
                **_campos_da_imagem(ultima),
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
                    else cena.posicao_manual
                    if cena.posicao_manual is not None
                    else cena.posicao_no_texto
                ),
                situacao=situacao,
                **_campos_da_imagem(ultima),
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
                    **_campos_da_imagem(ultima),
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
                        **_campos_da_imagem(ultima),
                    )
                )

    # Por posição; sem posição vêm depois, na ordem em que as sugestões foram criadas (a ordem estável do sort).
    artefatos.sort(key=lambda m: (m.posicao_no_texto is None, m.posicao_no_texto or 0))
    return artefatos
