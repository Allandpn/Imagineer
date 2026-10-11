"""Rotas da narração por voz de IA (itens NA1 a NA10): estimar, gerar, ver a situação, tocar e apagar o áudio de um capítulo."""

from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from imagineer.banco.sessao import CriadorDeSessao, obter_sessao
from imagineer.esquemas.audio import (
    AudioSalvo,
    EstadoDaNarracao,
    EstimativaDaNarracao,
    EstimativaDoTesteDeVoz,
    ModeloDeNarracao,
    PedidoDeNarracao,
    PedidoDeTesteDeVoz,
    SituacaoDaNarracao,
)
from imagineer.ia.provedor import ErroDoProvedorIA, ProvedorIA
from imagineer.modelos import AudioDeCapitulo, SituacaoDoAudio
from imagineer.rotas._comum import buscar_capitulo as _buscar_capitulo, obter_ou_404
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.catalogo_imagens import caminho_absoluto, remover_arquivo
from imagineer.servicos.acesso import usuario_ou_dono
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.limites import exigir_espaco, obter_limites
from imagineer.servicos.narracao import (
    AudioEmAndamento,
    apagar_audios_do_capitulo,
    audio_de_agora,
    audio_pronto,
    gerar_audio,
    iniciar_audio,
    narracao_em_andamento_da_pessoa,
    parametros_da_narracao,
    situacao_efetiva,
)
from imagineer.servicos.trechos_da_narracao import minutos_estimados

rotas = APIRouter(prefix="/capitulos", tags=["Narração"])
rotas_de_configuracao = APIRouter(prefix="/configuracao", tags=["Narração"])
rotas_de_audios = APIRouter(prefix="/audios", tags=["Narração"])


def _sem_modelo() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="Nenhum modelo de narração foi escolhido. Escolha um em Configurações → Narração (GET /configuracao/modelos-de-narracao).",
    )


def obter_criador_de_sessao() -> sessionmaker:
    """Dependência com a fábrica de sessões do trabalho de segundo plano (a sessão da requisição já está fechada quando ele roda).
    Existe como dependência para os testes a trocarem por uma ligada ao banco de teste."""
    return CriadorDeSessao


def _estado(audio: AudioDeCapitulo | None) -> EstadoDaNarracao:
    if audio is None:
        return EstadoDaNarracao(situacao=SituacaoDaNarracao.NAO_GERADO)
    return EstadoDaNarracao(
        situacao=SituacaoDaNarracao(situacao_efetiva(audio).value),
        audio_id=audio.id,
        modelo=audio.modelo,
        voz=audio.voz or None,
        caracteres=audio.caracteres,
        tamanho_em_bytes=audio.tamanho_em_bytes,
        custo=audio.custo,
        erro=audio.erro if situacao_efetiva(audio) == SituacaoDoAudio.FALHOU else None,
        criado_em=audio.criado_em,
    )


@rotas.get("/{capitulo_id}/audio/estimativa", response_model=EstimativaDaNarracao, summary="Quanto custa narrar o capítulo, antes de gerar")
def estimar_narracao(
    capitulo_id: int, sessao: Session = Depends(obter_sessao), provedor: ProvedorIA = Depends(obter_provedor)
) -> EstimativaDaNarracao:
    """Os caracteres, os minutos e o custo **estimado** (NA3). Lê o preço do catálogo público do OpenRouter (não gasta nada nem precisa de
    chave). **422** se nenhum modelo de voz foi escolhido."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    modelo, voz = parametros_da_narracao(obter_ou_criar(sessao))
    if modelo is None:
        raise _sem_modelo()
    caracteres = len(capitulo.texto or "")
    try:
        preco = next((m.preco_por_caractere for m in provedor.listar_modelos_de_voz() if m.id == modelo), None)
    except ErroDoProvedorIA:
        preco = None  # o catálogo não respondeu: sem estimativa, nunca um número inventado
    return EstimativaDaNarracao(
        caracteres=caracteres,
        minutos=round(minutos_estimados(caracteres), 1),
        custo_estimado=None if preco is None else (preco * caracteres).quantize(Decimal("0.0001")),
        modelo=modelo,
        voz=voz or None,
        ja_gerado=audio_pronto(sessao, capitulo.id, modelo, voz) is not None,
    )


@rotas_de_configuracao.get(
    "/modelos-de-narracao", response_model=list[ModeloDeNarracao], summary="Os modelos de voz do OpenRouter, com as vozes e o preço por caractere"
)
def listar_modelos_de_narracao(provedor: ProvedorIA = Depends(obter_provedor)) -> list[ModeloDeNarracao]:
    """O catálogo para a tela de Narração (NA1). O endpoint do OpenRouter é público: dá para ver a lista antes de cadastrar a chave. Os
    gratuitos vêm primeiro. Falha do serviço de fora vira 502."""
    return [
        ModeloDeNarracao(id=m.id, nome=m.nome, vozes=m.vozes, preco_por_caractere=m.preco_por_caractere, gratuito=m.gratuito)
        for m in provedor.listar_modelos_de_voz()
    ]


@rotas.post(
    "/{capitulo_id}/audio",
    response_model=EstadoDaNarracao,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Gera a narração do capítulo com voz de IA, em segundo plano",
)
def gerar_narracao(
    capitulo_id: int,
    tarefas: BackgroundTasks,
    resposta: Response,
    pedido: PedidoDeNarracao | None = None,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
    criador: sessionmaker = Depends(obter_criador_de_sessao),
) -> EstadoDaNarracao:
    """**202**: a geração começou (acompanhe em `GET .../audio/estado`). **200**: já havia um áudio `PRONTO` com o modelo e a voz de agora,
    devolvido **sem gastar** (mande `refazer: true` para gerar de novo). **409**: já há uma geração deste capítulo rodando. **422**:
    capítulo sem texto, nenhum modelo de voz escolhido, ou sem chave do OpenRouter (NA5)."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    if not (capitulo.texto or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Este capítulo não tem texto para narrar.")
    modelo, voz = parametros_da_narracao(obter_ou_criar(sessao))
    if modelo is None:
        raise _sem_modelo()
    if not provedor.pode_narrar:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não há chave do OpenRouter para narrar. Defina CHAVE_API_OPENROUTER no .env do servidor ou mande a sua chave pelo app.",
        )

    pronto = audio_pronto(sessao, capitulo.id, modelo, voz)
    if pronto is not None and not (pedido and pedido.refazer):
        resposta.status_code = status.HTTP_200_OK
        return _estado(pronto)

    # CT16, CT17, CT18: o teto do capítulo, uma geração por vez por pessoa e espaço em disco, **antes** de gastar.
    limites = obter_limites(sessao)
    if len(capitulo.texto) > limites.caracteres_maximos_da_narracao:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"O capítulo tem {len(capitulo.texto)} caracteres; o limite para narrar é {limites.caracteres_maximos_da_narracao}.",
        )
    if narracao_em_andamento_da_pessoa(sessao, usuario_ou_dono(sessao)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Você já tem uma narração sendo gerada. Espere terminar para pedir outra."
        )
    exigir_espaco(sessao)

    try:
        audio = iniciar_audio(sessao, capitulo, modelo, voz)
    except AudioEmAndamento as erro:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A narração deste capítulo já está sendo gerada.") from erro

    tarefas.add_task(gerar_audio, criador, audio.id, provedor, capitulo.texto, modelo, voz, capitulo.livro_id)
    return _estado(audio)


@rotas.get("/{capitulo_id}/audio/estado", response_model=EstadoDaNarracao, summary="A situação da narração, com o modelo e a voz de agora")
def estado_da_narracao(capitulo_id: int, sessao: Session = Depends(obter_sessao)) -> EstadoDaNarracao:
    """`NAO_GERADO`, `GERANDO`, `PRONTO` ou `FALHOU` (com o motivo). Só olha o áudio feito com o modelo e a voz **de agora**: se a
    pessoa trocou a voz, o áudio de antes não conta (NA4)."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    modelo, voz = parametros_da_narracao(obter_ou_criar(sessao))
    return _estado(audio_de_agora(sessao, capitulo.id, modelo, voz))


@rotas.get("/{capitulo_id}/audio", summary="O MP3 da narração (aceita pedaços, `Range`)")
def baixar_narracao(capitulo_id: int, sessao: Session = Depends(obter_sessao)) -> FileResponse:
    """O arquivo do áudio `PRONTO` com o modelo e a voz de agora. O ``FileResponse`` responde ``206`` a um pedido ``Range``, que é o que o
    player precisa para avançar e voltar. **Sem cache imutável**: o endereço é o do capítulo, e o conteúdo muda se a pessoa gerar de novo."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    modelo, voz = parametros_da_narracao(obter_ou_criar(sessao))
    audio = audio_pronto(sessao, capitulo.id, modelo, voz)
    if audio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este capítulo ainda não tem narração gerada com o modelo e a voz de agora.")
    caminho = caminho_absoluto(audio.arquivo)
    if not caminho.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="O arquivo desta narração não está mais no disco. Gere de novo.")
    return FileResponse(caminho, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})


@rotas.delete("/{capitulo_id}/audio", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga as narrações do capítulo e os arquivos")
def apagar_narracao(capitulo_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga **todos** os áudios do capítulo (de qualquer modelo ou voz) e os arquivos (NA5). Sem lixeira: um áudio pesa."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    apagar_audios_do_capitulo(sessao, capitulo.id)
    sessao.commit()


# --------------------------------------------------------------------------- #
# As narrações salvas e o teste de voz (item 7.5g, AU3 e AU4)
# --------------------------------------------------------------------------- #

FRASE_DO_TESTE_DE_VOZ = "Esta é a voz que vai narrar os seus livros. Se ela agrada aos seus ouvidos, é só abrir um capítulo e ouvir."
"""A frase falada no teste de voz (AU4): curta de propósito, para custar uma fração de centavo."""


@rotas.get("/{capitulo_id}/audios", response_model=list[AudioSalvo], summary="As narrações prontas guardadas do capítulo")
def listar_narracoes(capitulo_id: int, sessao: Session = Depends(obter_sessao)) -> list[AudioSalvo]:
    """Todas as narrações `PRONTO` do capítulo, de **qualquer** modelo e voz, da mais nova para a mais antiga (AU3). `de_agora` marca a feita
    com o modelo e a voz escolhidos agora. As que estão `GERANDO` ou `FALHOU` não aparecem aqui (a situação delas está em `.../audio/estado`)."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    modelo, voz = parametros_da_narracao(obter_ou_criar(sessao))
    audios = sessao.scalars(
        select(AudioDeCapitulo)
        .where(AudioDeCapitulo.capitulo_id == capitulo.id, AudioDeCapitulo.situacao == SituacaoDoAudio.PRONTO)
        .order_by(AudioDeCapitulo.id.desc())
    ).all()
    return [
        AudioSalvo(
            id=a.id,
            modelo=a.modelo,
            voz=a.voz or None,
            caracteres=a.caracteres,
            tamanho_em_bytes=a.tamanho_em_bytes,
            custo=a.custo,
            criado_em=a.criado_em,
            de_agora=(a.modelo == modelo and a.voz == voz),
        )
        for a in audios
        if a.arquivo
    ]


@rotas_de_audios.get("/{audio_id}/arquivo", summary="O MP3 de uma narração guardada (aceita `Range`)")
def baixar_narracao_salva(audio_id: int, sessao: Session = Depends(obter_sessao)) -> FileResponse:
    """O arquivo de uma narração `PRONTO`, pelo id (AU3). **404** se não existe, é de outra pessoa, não está pronta ou o arquivo sumiu do disco."""
    audio = obter_ou_404(sessao, AudioDeCapitulo, audio_id, "áudio")
    if audio.situacao != SituacaoDoAudio.PRONTO or not audio.arquivo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta narração não está pronta.")
    caminho = caminho_absoluto(audio.arquivo)
    if not caminho.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="O arquivo desta narração não está mais no disco. Gere de novo.")
    return FileResponse(caminho, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})


@rotas_de_audios.delete("/{audio_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga uma narração guardada e o arquivo dela")
def apagar_narracao_salva(audio_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga **uma** narração (a linha e o MP3), sem lixeira (AU3). **409** se ela ainda está sendo gerada."""
    audio = obter_ou_404(sessao, AudioDeCapitulo, audio_id, "áudio")
    if situacao_efetiva(audio) == SituacaoDoAudio.GERANDO:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta narração ainda está sendo gerada.")
    if audio.arquivo:
        remover_arquivo(audio.arquivo)
    sessao.delete(audio)
    sessao.commit()


def _modelo_e_voz_do_teste(sessao: Session, pedido: PedidoDeTesteDeVoz | None) -> tuple[str, str]:
    """O modelo e a voz do teste: os do pedido, ou os da configuração. **422** sem modelo (AU4)."""
    modelo_da_configuracao, voz_da_configuracao = parametros_da_narracao(obter_ou_criar(sessao))
    modelo = ((pedido.modelo if pedido else None) or "").strip() or modelo_da_configuracao
    if modelo is None:
        raise _sem_modelo()
    voz = ((pedido.voz if pedido else None) or "").strip() or (voz_da_configuracao if modelo == modelo_da_configuracao else "")
    return modelo, voz


@rotas_de_configuracao.get(
    "/narracao/teste", response_model=EstimativaDoTesteDeVoz, summary="O que o teste de voz fala e quanto custa, antes de gerar"
)
def estimar_teste_de_voz(
    modelo: str | None = None,
    voz: str | None = None,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> EstimativaDoTesteDeVoz:
    """A frase e o custo **estimado** (AU4): caracteres × preço por caractere do catálogo público. Não gasta nada nem precisa de chave.
    `custo_estimado` zero = modelo gratuito; nulo = sem estimativa. **422** se não há modelo (nem no pedido, nem na configuração)."""
    modelo_usado, voz_usada = _modelo_e_voz_do_teste(sessao, PedidoDeTesteDeVoz(modelo=modelo, voz=voz))
    try:
        preco = next((m.preco_por_caractere for m in provedor.listar_modelos_de_voz() if m.id == modelo_usado), None)
    except ErroDoProvedorIA:
        preco = None
    caracteres = len(FRASE_DO_TESTE_DE_VOZ)
    return EstimativaDoTesteDeVoz(
        frase=FRASE_DO_TESTE_DE_VOZ,
        caracteres=caracteres,
        custo_estimado=None if preco is None else (preco * caracteres).quantize(Decimal("0.0001")),
        modelo=modelo_usado,
        voz=voz_usada or None,
    )


@rotas_de_configuracao.post("/narracao/teste", summary="Fala uma frase curta com o modelo e a voz, para ouvir antes de escolher")
def testar_a_voz(
    pedido: PedidoDeTesteDeVoz | None = None,
    sessao: Session = Depends(obter_sessao),
    provedor: ProvedorIA = Depends(obter_provedor),
) -> Response:
    """Devolve o **MP3 sem guardar nada em disco** (AU4). Gasta uma fração de centavo (nada nos modelos gratuitos); o gasto entra em `usos_ia`
    como os outros, sem livro. O custo estimado vai no cabeçalho `X-Custo-Estimado` (ausente se não se sabe). **422** sem modelo ou sem chave
    do OpenRouter; **502** se o provedor falhar."""
    modelo, voz = _modelo_e_voz_do_teste(sessao, pedido)
    if not provedor.pode_narrar:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não há chave do OpenRouter para narrar. Defina CHAVE_API_OPENROUTER no .env do servidor ou mande a sua chave pelo app.",
        )
    falado = provedor.narrar(FRASE_DO_TESTE_DE_VOZ, modelo, voz or None)
    cabecalhos = {"X-Custo-Estimado": str(falado.custo)} if falado.custo is not None else {}
    return Response(content=falado.conteudo, media_type="audio/mpeg", headers=cabecalhos)
