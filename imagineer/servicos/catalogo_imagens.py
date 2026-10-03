"""Grava e apaga os arquivos de imagem do catálogo em disco (item 6.6).

Só o caminho relativo do arquivo vai para o banco (item 3.4c) — o arquivo em si
mora em ``DIRETORIO_IMAGENS``, fora do banco de dados, para não engordar backup e
consulta com o peso das imagens.
"""

import uuid
from pathlib import Path

from imagineer.configuracao import obter_configuracoes

EXTENSOES_ACEITAS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
"""O que as ferramentas de geração de imagem em uso produzem (item 6.6)."""

TIPOS_POR_EXTENSAO = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
"""O ``Content-Type`` de cada extensão aceita. Explícito, e não pelo módulo ``mimetypes``: no contêiner (Python 3.12 sem
``/etc/mime.types``) ele não conhece ``.webp`` e a resposta saía como ``application/octet-stream``, que o Android recusa ao salvar
na galeria."""


def tipo_da_imagem(caminho: Path) -> str | None:
    """O tipo de mídia pela extensão do arquivo, ou ``None`` se não for uma das aceitas."""
    return TIPOS_POR_EXTENSAO.get(caminho.suffix.lower())


TAMANHO_MAXIMO_DA_IMAGEM = 25 * 1024 * 1024
"""Limite de upload por imagem, em bytes.

Generoso para PNGs de alta resolução, e ainda protege o Raspberry Pi de um
arquivo absurdo — o mesmo raciocínio do limite do EPUB (item 6.2).
"""


class ExtensaoDeImagemInvalida(Exception):
    """A extensão do arquivo enviado não está entre as aceitas."""


def salvar_imagem(prompt_id: int, nome_original: str, conteudo: bytes) -> str:
    """Grava o arquivo em disco e devolve o caminho relativo a guardar no banco.

    O nome do arquivo é gerado, não o nome original — evita colisão entre duas
    imagens de nomes iguais vindas de ferramentas diferentes. A pasta por
    ``prompt_id`` é só para o disco ficar navegável por um humano; o banco nunca
    depende dessa organização, só do caminho completo guardado em cada linha.
    """
    extensao = Path(nome_original).suffix.lower()
    if extensao not in EXTENSOES_ACEITAS:
        raise ExtensaoDeImagemInvalida(
            f"Extensão {extensao or '(nenhuma)'!r} não é aceita. Use uma destas: "
            f"{', '.join(sorted(EXTENSOES_ACEITAS))}."
        )

    caminho_relativo = f"prompts/{prompt_id}/{uuid.uuid4().hex}{extensao}"
    caminho_absoluto(caminho_relativo).parent.mkdir(parents=True, exist_ok=True)
    caminho_absoluto(caminho_relativo).write_bytes(conteudo)
    return caminho_relativo


def caminho_absoluto(caminho_relativo: str) -> Path:
    """Resolve um caminho relativo do banco para o arquivo de verdade em disco."""
    return Path(obter_configuracoes().diretorio_imagens) / caminho_relativo


def remover_arquivo(caminho_relativo: str) -> None:
    """Apaga o arquivo do disco, sem reclamar se ele já não existir.

    Um arquivo ausente não deveria travar a remoção da linha do banco: o
    objetivo é o catálogo ficar consistente, não impedir a limpeza de um
    registro cujo arquivo já sumiu por algum outro motivo.
    """
    caminho_absoluto(caminho_relativo).unlink(missing_ok=True)
