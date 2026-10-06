"""Gerar, guardar e apagar a narração de um capítulo (item NA1 a NA10).

O fluxo (NA5): a rota cria a linha em ``GERANDO`` (``iniciar_audio``) e entrega o trabalho para o segundo plano (``gerar_audio``), que
fala o capítulo trecho a trecho, junta os MP3 e só então grava o arquivo. **Nunca há arquivo parcial** (NA7): se um trecho falha, a linha
vira ``FALHOU`` com o motivo. O gasto de cada trecho concluído é registrado na hora (NA6), em sessão própria.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from imagineer.ia.narradores import Narrador, dividir_em_trechos
from imagineer.ia.provedor import ChaveDeApiAusente, ErroDoProvedorIA, UsoDaChamada
from imagineer.modelos import AudioDeCapitulo, Capitulo, Configuracao, SituacaoDoAudio
from imagineer.servicos.catalogo_imagens import caminho_absoluto, remover_arquivo
from imagineer.servicos.uso_de_ia import gasto_do_livro, gravar_uso

LIMITE_PARA_GERANDO_PRESO = timedelta(minutes=30)
"""Uma linha ``GERANDO`` há mais tempo que isto é lida como ``FALHOU`` (NA7): o servidor reiniciou no meio e ninguém vai terminá-la."""


class AudioEmAndamento(Exception):
    """Já existe uma narração deste capítulo sendo gerada (vira 409 na rota)."""


class CapituloSemTexto(Exception):
    """O capítulo não tem texto para narrar (vira 422 na rota)."""


def hash_das_instrucoes(instrucoes: str | None) -> str:
    """O SHA-1 das instruções de tom, ou vazio se não há instrução (NA4)."""
    texto = (instrucoes or "").strip()
    return hashlib.sha1(texto.encode("utf-8")).hexdigest() if texto else ""


def parametros_da_narracao(configuracao: Configuracao) -> tuple[str, str | None]:
    """A voz e as instruções **de agora** (RL23/RL24): o que a pessoa escolheu em Configurações → Narração. A voz vazia é a padrão."""
    instrucoes = (configuracao.narracao_instrucoes or "").strip() or None
    return (configuracao.narracao_voz or "").strip(), instrucoes


def _aware(momento: datetime) -> datetime:
    """O SQLite devolve datas sem fuso; o PostgreSQL, com. Trata as duas como UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def situacao_efetiva(audio: AudioDeCapitulo) -> SituacaoDoAudio:
    """A situação de verdade: uma linha ``GERANDO`` que ficou presa vale como ``FALHOU`` (NA7)."""
    if audio.situacao == SituacaoDoAudio.GERANDO and datetime.now(timezone.utc) - _aware(audio.criado_em) > LIMITE_PARA_GERANDO_PRESO:
        return SituacaoDoAudio.FALHOU
    return audio.situacao


def audio_de_agora(sessao: Session, capitulo_id: int, voz: str, hash_instrucoes: str) -> AudioDeCapitulo | None:
    """O áudio mais recente do capítulo **com a voz e as instruções de agora**, em qualquer situação; ou ``None``."""
    return sessao.scalar(
        select(AudioDeCapitulo)
        .where(
            AudioDeCapitulo.capitulo_id == capitulo_id,
            AudioDeCapitulo.voz == voz,
            AudioDeCapitulo.instrucoes_hash == hash_instrucoes,
        )
        .order_by(AudioDeCapitulo.id.desc())
        .limit(1)
    )


def audio_pronto(sessao: Session, capitulo_id: int, voz: str, hash_instrucoes: str) -> AudioDeCapitulo | None:
    """O áudio ``PRONTO`` mais recente com a voz e as instruções de agora; ou ``None``."""
    return sessao.scalar(
        select(AudioDeCapitulo)
        .where(
            AudioDeCapitulo.capitulo_id == capitulo_id,
            AudioDeCapitulo.voz == voz,
            AudioDeCapitulo.instrucoes_hash == hash_instrucoes,
            AudioDeCapitulo.situacao == SituacaoDoAudio.PRONTO,
        )
        .order_by(AudioDeCapitulo.id.desc())
        .limit(1)
    )


def iniciar_audio(sessao: Session, capitulo: Capitulo, narrador: Narrador, voz: str, hash_instrucoes: str) -> AudioDeCapitulo:
    """Cria a linha ``GERANDO``, com o commit feito. Levanta ``AudioEmAndamento`` se já há uma geração rodando neste capítulo."""
    for existente in sessao.scalars(select(AudioDeCapitulo).where(AudioDeCapitulo.capitulo_id == capitulo.id, AudioDeCapitulo.situacao == SituacaoDoAudio.GERANDO)):
        if situacao_efetiva(existente) == SituacaoDoAudio.GERANDO:
            raise AudioEmAndamento(capitulo.id)
        existente.situacao = SituacaoDoAudio.FALHOU
        existente.erro = "A geração anterior foi interrompida (o servidor reiniciou no meio)."
    audio = AudioDeCapitulo(
        capitulo_id=capitulo.id,
        motor=narrador.nome,
        modelo=narrador.modelo,
        voz=voz,
        instrucoes_hash=hash_instrucoes,
        situacao=SituacaoDoAudio.GERANDO,
        caracteres=len(capitulo.texto or ""),
    )
    sessao.add(audio)
    sessao.commit()
    sessao.refresh(audio)
    return audio


def gerar_audio(
    criador: sessionmaker,
    audio_id: int,
    narrador: Narrador,
    texto: str,
    voz: str,
    instrucoes: str | None,
    livro_id: int,
) -> None:
    """O trabalho de segundo plano: fala o texto, grava o arquivo e marca ``PRONTO`` (ou ``FALHOU``). Nunca levanta exceção.

    Usa uma sessão **própria** (``criador``): a da requisição já foi fechada quando isto roda.
    """
    partes: list[bytes] = []
    custo_total = Decimal(0)
    try:
        for trecho in dividir_em_trechos(texto):
            mp3 = narrador.narrar(trecho, voz or None, instrucoes)
            custo = narrador.custo_estimado(len(trecho))
            with gasto_do_livro(livro_id):
                gravar_uso(
                    UsoDaChamada(operacao="narracao", modelo=narrador.modelo, custo=custo, provedor=narrador.nome, estimado=True),
                    criador,
                )
            partes.append(mp3)
            custo_total += custo
        conteudo = b"".join(partes)
        with criador() as sessao:
            audio = sessao.get(AudioDeCapitulo, audio_id)
            audio.arquivo = _gravar_arquivo(audio.capitulo_id, conteudo)
            audio.tamanho_em_bytes = len(conteudo)
            audio.custo = custo_total
            audio.situacao = SituacaoDoAudio.PRONTO
            audio.erro = None
            _tirar_os_antigos(sessao, audio)
            sessao.commit()
    except (ErroDoProvedorIA, ChaveDeApiAusente) as erro:
        _marcar_como_falha(criador, audio_id, str(erro), custo_total)
    except Exception:  # noqa: BLE001 — trabalho de segundo plano: ninguém mais está olhando para tratar
        logging.getLogger(__name__).exception("Falha inesperada ao gerar a narração do áudio %s", audio_id)
        _marcar_como_falha(criador, audio_id, "Erro inesperado ao gerar a narração. Veja o log do servidor.", custo_total)


def _tirar_os_antigos(sessao: Session, novo: AudioDeCapitulo) -> None:
    """Gerar de novo (``refazer``) não acumula arquivos: ao ficar ``PRONTO``, o áudio novo substitui os **outros** do mesmo capítulo, voz e
    instruções (disco é do Raspberry Pi). Áudios com outra voz ou outro tom ficam (NA4)."""
    for antigo in sessao.scalars(
        select(AudioDeCapitulo).where(
            AudioDeCapitulo.capitulo_id == novo.capitulo_id,
            AudioDeCapitulo.voz == novo.voz,
            AudioDeCapitulo.instrucoes_hash == novo.instrucoes_hash,
            AudioDeCapitulo.id != novo.id,
        )
    ):
        if antigo.situacao == SituacaoDoAudio.GERANDO and situacao_efetiva(antigo) == SituacaoDoAudio.GERANDO:
            continue
        if antigo.arquivo:
            remover_arquivo(antigo.arquivo)
        sessao.delete(antigo)


def _marcar_como_falha(criador: sessionmaker, audio_id: int, motivo: str, custo_ate_aqui: Decimal) -> None:
    """``FALHOU`` com o motivo e o que já foi gasto (NA6/NA7); sem arquivo."""
    with criador() as sessao:
        audio = sessao.get(AudioDeCapitulo, audio_id)
        if audio is None:  # o capítulo foi apagado no meio
            return
        audio.situacao = SituacaoDoAudio.FALHOU
        audio.erro = motivo
        audio.custo = custo_ate_aqui or None
        sessao.commit()


def _gravar_arquivo(capitulo_id: int, conteudo: bytes) -> str:
    """Grava o MP3 em ``DIRETORIO_IMAGENS/audios/<capítulo>/`` e devolve o caminho relativo (NA4)."""
    relativo = f"audios/{capitulo_id}/{uuid.uuid4().hex}.mp3"
    destino = caminho_absoluto(relativo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(conteudo)
    return relativo


def apagar_audios_do_capitulo(sessao: Session, capitulo_id: int) -> int:
    """Apaga as linhas **e os arquivos** dos áudios do capítulo. Devolve os bytes liberados. Quem chama faz o ``commit``."""
    liberados = 0
    for audio in sessao.scalars(select(AudioDeCapitulo).where(AudioDeCapitulo.capitulo_id == capitulo_id)):
        if audio.arquivo:
            liberados += audio.tamanho_em_bytes or 0
            remover_arquivo(audio.arquivo)
        sessao.delete(audio)
    sessao.flush()
    return liberados


def apagar_audios_do_livro(sessao: Session, livro_id: int) -> int:
    """Apaga do disco os áudios de todos os capítulos do livro (as linhas saem em cascata com ele). Devolve os bytes liberados."""
    liberados = 0
    for audio in sessao.scalars(
        select(AudioDeCapitulo).join(Capitulo, Capitulo.id == AudioDeCapitulo.capitulo_id).where(Capitulo.livro_id == livro_id)
    ):
        if audio.arquivo:
            liberados += audio.tamanho_em_bytes or 0
            remover_arquivo(audio.arquivo)
    return liberados
