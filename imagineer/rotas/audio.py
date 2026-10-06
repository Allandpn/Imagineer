"""Rotas da narração por voz de IA (itens NA1 a NA10): estimar, gerar, ver a situação, tocar e apagar o áudio de um capítulo."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, sessionmaker

from imagineer.banco.sessao import CriadorDeSessao, obter_sessao
from imagineer.configuracao import obter_configuracoes
from imagineer.esquemas.audio import EstadoDaNarracao, EstimativaDaNarracao, PedidoDeNarracao, SituacaoDaNarracao
from imagineer.ia.narradores import Narrador, NarradorOpenAI, minutos_estimados
from imagineer.modelos import AudioDeCapitulo, SituacaoDoAudio
from imagineer.rotas._comum import buscar_capitulo as _buscar_capitulo
from imagineer.servicos.catalogo_imagens import caminho_absoluto
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.narracao import (
    AudioEmAndamento,
    apagar_audios_do_capitulo,
    audio_de_agora,
    audio_pronto,
    gerar_audio,
    hash_das_instrucoes,
    iniciar_audio,
    parametros_da_narracao,
    situacao_efetiva,
)

rotas = APIRouter(prefix="/capitulos", tags=["Narração"])


def obter_narrador() -> Narrador:
    """Dependência que entrega o narrador já configurado (NA1). Como ``obter_provedor``, existe para os testes a trocarem por um falso."""
    return NarradorOpenAI(chave_api=obter_configuracoes().chave_api_openai.strip())


def obter_criador_de_sessao() -> sessionmaker:
    """Dependência com a fábrica de sessões do trabalho de segundo plano (a sessão da requisição já está fechada quando ele roda)."""
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
    capitulo_id: int, sessao: Session = Depends(obter_sessao), narrador: Narrador = Depends(obter_narrador)
) -> EstimativaDaNarracao:
    """Os caracteres, os minutos e o custo **estimado** (NA3). Não chama nenhum fornecedor e não precisa de chave."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    voz, instrucoes = parametros_da_narracao(obter_ou_criar(sessao))
    caracteres = len(capitulo.texto or "")
    return EstimativaDaNarracao(
        caracteres=caracteres,
        minutos=round(minutos_estimados(caracteres), 1),
        custo_estimado=narrador.custo_estimado(caracteres),
        modelo=narrador.modelo,
        voz=voz or None,
        ja_gerado=audio_pronto(sessao, capitulo.id, voz, hash_das_instrucoes(instrucoes)) is not None,
    )


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
    narrador: Narrador = Depends(obter_narrador),
    criador: sessionmaker = Depends(obter_criador_de_sessao),
) -> EstadoDaNarracao:
    """**202**: a geração começou (acompanhe em `GET .../audio/estado`). **200**: já havia um áudio `PRONTO` com a voz e as instruções de
    agora, devolvido **sem gastar** (mande `refazer: true` para gerar de novo). **409**: já há uma geração deste capítulo rodando. **422**:
    capítulo sem texto, ou o servidor sem chave da OpenAI (NA5)."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    if not (capitulo.texto or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Este capítulo não tem texto para narrar.")
    if not narrador.disponivel:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="O servidor não tem a chave da OpenAI. Defina OPENAI_API_KEY (ou CHAVE_API_OPENAI) no .env e rode `docker compose up -d`.",
        )

    voz, instrucoes = parametros_da_narracao(obter_ou_criar(sessao))
    hash_instrucoes = hash_das_instrucoes(instrucoes)

    pronto = audio_pronto(sessao, capitulo.id, voz, hash_instrucoes)
    if pronto is not None and not (pedido and pedido.refazer):
        resposta.status_code = status.HTTP_200_OK
        return _estado(pronto)

    try:
        audio = iniciar_audio(sessao, capitulo, narrador, voz, hash_instrucoes)
    except AudioEmAndamento as erro:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A narração deste capítulo já está sendo gerada.") from erro

    tarefas.add_task(gerar_audio, criador, audio.id, narrador, capitulo.texto, voz, instrucoes, capitulo.livro_id)
    return _estado(audio)


@rotas.get("/{capitulo_id}/audio/estado", response_model=EstadoDaNarracao, summary="A situação da narração, com a voz e o tom de agora")
def estado_da_narracao(capitulo_id: int, sessao: Session = Depends(obter_sessao)) -> EstadoDaNarracao:
    """`NAO_GERADO`, `GERANDO`, `PRONTO` ou `FALHOU` (com o motivo). Só olha o áudio feito com a voz e as instruções **de agora**: se a
    pessoa trocou o tom, o áudio de antes não conta (NA4)."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    voz, instrucoes = parametros_da_narracao(obter_ou_criar(sessao))
    return _estado(audio_de_agora(sessao, capitulo.id, voz, hash_das_instrucoes(instrucoes)))


@rotas.get("/{capitulo_id}/audio", summary="O MP3 da narração (aceita pedaços, `Range`)")
def baixar_narracao(capitulo_id: int, sessao: Session = Depends(obter_sessao)) -> FileResponse:
    """O arquivo do áudio `PRONTO` com a voz e o tom de agora. O ``FileResponse`` responde ``206`` a um pedido ``Range``, que é o que o
    player precisa para avançar e voltar. **Sem cache imutável**: o endereço é o do capítulo, e o conteúdo muda se a pessoa gerar de novo."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    voz, instrucoes = parametros_da_narracao(obter_ou_criar(sessao))
    audio = audio_pronto(sessao, capitulo.id, voz, hash_das_instrucoes(instrucoes))
    if audio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este capítulo ainda não tem narração gerada com a voz e o tom de agora.")
    caminho = caminho_absoluto(audio.arquivo)
    if not caminho.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="O arquivo desta narração não está mais no disco. Gere de novo.")
    return FileResponse(caminho, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})


@rotas.delete("/{capitulo_id}/audio", status_code=status.HTTP_204_NO_CONTENT, summary="Apaga as narrações do capítulo e os arquivos")
def apagar_narracao(capitulo_id: int, sessao: Session = Depends(obter_sessao)) -> None:
    """Apaga **todos** os áudios do capítulo (de qualquer voz ou tom) e os arquivos (NA5). Sem lixeira: um áudio pesa."""
    capitulo = _buscar_capitulo(sessao, capitulo_id)
    apagar_audios_do_capitulo(sessao, capitulo.id)
    sessao.commit()
