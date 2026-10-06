"""Rotas da narração por voz de IA (itens NA1 a NA10): estimar, gerar, ver a situação, tocar e apagar o áudio de um capítulo."""

from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, sessionmaker

from imagineer.banco.sessao import CriadorDeSessao, obter_sessao
from imagineer.esquemas.audio import EstadoDaNarracao, EstimativaDaNarracao, ModeloDeNarracao, PedidoDeNarracao, SituacaoDaNarracao
from imagineer.ia.provedor import ErroDoProvedorIA, ProvedorIA
from imagineer.modelos import AudioDeCapitulo, SituacaoDoAudio
from imagineer.rotas._comum import buscar_capitulo as _buscar_capitulo
from imagineer.rotas.configuracao import obter_provedor
from imagineer.servicos.catalogo_imagens import caminho_absoluto
from imagineer.servicos.configuracao_ia import obter_ou_criar
from imagineer.servicos.narracao import (
    AudioEmAndamento,
    apagar_audios_do_capitulo,
    audio_de_agora,
    audio_pronto,
    gerar_audio,
    iniciar_audio,
    parametros_da_narracao,
    situacao_efetiva,
)
from imagineer.servicos.trechos_da_narracao import minutos_estimados

rotas = APIRouter(prefix="/capitulos", tags=["Narração"])
rotas_de_configuracao = APIRouter(prefix="/configuracao", tags=["Narração"])


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
