"""Os limites do servidor compartilhado e a conferência de espaço (itens CT15 a CT20).

**Por que existe.** Com mais de uma pessoa no mesmo Raspberry Pi, um arquivo enorme ou uma geração em excesso de uma delas pode encher o disco de todas.
Aqui ficam: ler os limites (uma linha no banco, editada pelo dono), medir o espaço usado e **recusar com 507** quando o espaço acaba.

**Dois espaços, duas medidas.** O da *aplicação toda* é a soma dos arquivos que ela guarda em disco (``DIRETORIO_IMAGENS``: imagens, vídeos, áudios), medida
andando pela pasta e guardada por alguns segundos (andar por milhares de arquivos a cada pedido seria caro). O da *pessoa* é a soma dos tamanhos que o banco
já guarda das imagens, vídeos e áudios dos livros dela (inclusive o que está na lixeira, que ainda ocupa disco). EPUB e capa não entram: o EPUB não é
guardado e a capa mora no banco.
"""

import time
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imagineer.configuracao import obter_configuracoes
from imagineer.modelos import (
    AudioDeCapitulo,
    Capitulo,
    Frame,
    ID_UNICO_DOS_LIMITES,
    Imagem,
    Limites,
    Livro,
    Prompt,
    Usuario,
    Video,
)
from imagineer.servicos.acesso import usuario_ou_dono
from imagineer.modelos.usuario import DONO_ID

BYTES_POR_MB = 1024 * 1024
BYTES_POR_GB = 1024 * BYTES_POR_MB
FRACAO_MAXIMA_DO_ARMAZENAMENTO = 0.9
"""Ao chegar a 90% do limite da aplicação, novos arquivos são recusados (CT17): sobra folga para o que já está em andamento e para o banco."""

SEGUNDOS_DE_VALIDADE_DO_USO = 15
_uso_guardado: tuple[float, int] | None = None


def obter_limites(sessao: Session) -> Limites:
    """A linha de limites, criada com os padrões se ainda não existir (um banco montado sem a migração, como o dos testes)."""
    limites = sessao.get(Limites, ID_UNICO_DOS_LIMITES)
    if limites is None:
        limites = Limites(id=ID_UNICO_DOS_LIMITES)
        sessao.add(limites)
        sessao.commit()
        sessao.refresh(limites)
    return limites


def limpar_cache_do_uso() -> None:
    """Esquece o último total medido (os testes e a rota de admin chamam; o servidor também o refaz sozinho em segundos)."""
    global _uso_guardado
    _uso_guardado = None


def uso_da_aplicacao_em_bytes() -> int:
    """Quanto a aplicação ocupa em disco: a soma dos arquivos de ``DIRETORIO_IMAGENS``. Guardado por alguns segundos."""
    global _uso_guardado
    agora = time.monotonic()
    if _uso_guardado is not None and agora - _uso_guardado[0] < SEGUNDOS_DE_VALIDADE_DO_USO:
        return _uso_guardado[1]
    raiz = Path(obter_configuracoes().diretorio_imagens)
    total = sum(arquivo.stat().st_size for arquivo in raiz.rglob("*") if arquivo.is_file()) if raiz.is_dir() else 0
    _uso_guardado = (agora, total)
    return total


def uso_da_pessoa_em_bytes(sessao: Session, usuario_id: int) -> int:
    """A soma dos tamanhos das imagens, vídeos e áudios dos livros da pessoa (a lixeira conta: o arquivo ainda está no disco)."""
    imagens = sessao.scalar(
        select(func.coalesce(func.sum(Imagem.tamanho_em_bytes), 0))
        .join(Prompt, Prompt.id == Imagem.prompt_id)
        .join(Frame, Frame.id == Prompt.frame_id)
        .join(Capitulo, Capitulo.id == Frame.capitulo_id)
        .join(Livro, Livro.id == Capitulo.livro_id)
        .where(Livro.usuario_id == usuario_id)
    )
    videos = sessao.scalar(
        select(func.coalesce(func.sum(Video.tamanho_em_bytes), 0))
        .join(Frame, Frame.id == Video.frame_id)
        .join(Capitulo, Capitulo.id == Frame.capitulo_id)
        .join(Livro, Livro.id == Capitulo.livro_id)
        .where(Livro.usuario_id == usuario_id)
    )
    audios = sessao.scalar(
        select(func.coalesce(func.sum(AudioDeCapitulo.tamanho_em_bytes), 0))
        .join(Capitulo, Capitulo.id == AudioDeCapitulo.capitulo_id)
        .join(Livro, Livro.id == Capitulo.livro_id)
        .where(Livro.usuario_id == usuario_id)
    )
    return int(imagens) + int(videos) + int(audios)


def cota_efetiva_em_gb(limites: Limites, usuario: Usuario) -> int | None:
    """A cota que vale para a pessoa: a própria (CT23) ou o padrão; ``None`` para o dono, que não tem cota."""
    if usuario.id == DONO_ID:
        return None
    return usuario.cota_em_gb if usuario.cota_em_gb is not None else limites.cota_por_pessoa_em_gb


def _sem_espaco(detalhe: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_507_INSUFFICIENT_STORAGE, detail=detalhe)


def exigir_espaco(sessao: Session, bytes_novos: int = 0) -> None:
    """Recusa com 507 se guardar mais ``bytes_novos`` passaria dos 90% da aplicação (CT17) ou da cota da pessoa (CT18).

    Usada **antes** de aceitar um upload ou de começar uma geração. Leituras e apagar nunca passam por aqui: quem está sem espaço precisa conseguir
    liberar. O dono não tem cota, mas **vale** o limite da aplicação, para ele também.
    """
    limites = obter_limites(sessao)
    teto_da_aplicacao = int(limites.armazenamento_total_em_gb * BYTES_POR_GB * FRACAO_MAXIMA_DO_ARMAZENAMENTO)
    if uso_da_aplicacao_em_bytes() + bytes_novos > teto_da_aplicacao:
        raise _sem_espaco(
            f"O servidor chegou a 90% do espaço reservado ({limites.armazenamento_total_em_gb} GB). Novos arquivos e gerações estão "
            "recusados até liberar espaço."
        )
    usuario_id = usuario_ou_dono(sessao)
    pessoa = sessao.get(Usuario, usuario_id)
    cota_em_gb = cota_efetiva_em_gb(limites, pessoa) if pessoa is not None else None
    if cota_em_gb is not None and uso_da_pessoa_em_bytes(sessao, usuario_id) + bytes_novos > cota_em_gb * BYTES_POR_GB:
        raise _sem_espaco(f"Você chegou à sua cota de {cota_em_gb} GB. Apague imagens, vídeos ou áudios para liberar espaço.")
