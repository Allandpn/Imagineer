"""Leitura de arquivos enviados por upload, com limite de tamanho.

Usado tanto pela importação de EPUB (item 6.2) quanto pelo catálogo de imagens
(item 6.6) — os dois recebem um arquivo binário do app e precisam se proteger do
mesmo jeito contra um upload grande demais para a memória do Raspberry Pi.
"""

from fastapi import HTTPException, UploadFile, status

TAMANHO_DO_BLOCO = 1024 * 1024


async def ler_com_limite(arquivo: UploadFile, limite: int) -> bytes:
    """Lê o arquivo em blocos, abortando assim que passar do limite.

    A leitura em blocos, e não de uma vez, é o que permite recusar um arquivo
    gigante **antes** de ele estar todo na memória — a diferença entre uma
    resposta de erro e o serviço morrer por falta de memória.
    """
    blocos: list[bytes] = []
    total = 0
    while bloco := await arquivo.read(TAMANHO_DO_BLOCO):
        total += len(bloco)
        if total > limite:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"O arquivo passa do limite de {limite // (1024 * 1024)} MB.",
            )
        blocos.append(bloco)

    if not blocos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="O arquivo enviado está vazio.",
        )

    return b"".join(blocos)
