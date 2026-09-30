"""Contratos das rotas de prompts e catálogo de imagens (Etapa 6.6)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ImagemResumo(BaseModel):
    """Uma imagem do catálogo, como a API a devolve.

    Não expõe ``caminho_arquivo``: o app busca os bytes por
    ``GET /imagens/{id}/arquivo``, e o layout do disco não é assunto dele.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    prompt_id: int
    tamanho_em_bytes: int | None = None
    data_importacao: datetime


class MidiaDeImagem(BaseModel):
    """Uma imagem do livro no manifesto de mídias (item 6.9)."""

    imagem_id: int
    prompt_id: int
    frame_id: int
    tamanho_em_bytes: int = Field(description="O tamanho do arquivo **original**, em bytes.")
    tipo_do_arquivo: str = Field(description='O tipo de mídia, como "image/png".')


class MidiasDoLivro(BaseModel):
    """O manifesto de mídias de um livro: o que o app precisa baixar para ler offline.

    `total_em_bytes` permite mostrar **"Baixar — 240 MB" antes de começar**, e a lista diz o
    que falta baixar (item 7.0a, A4).
    """

    total_em_bytes: int
    imagens: list[MidiaDeImagem]


class PromptResumo(BaseModel):
    """Um prompt na listagem de um frame."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    frame_id: int
    perfil_renderizacao_id: int | None
    modelo_ia: str | None
    texto: str
    avaliacao: str | None
    data_criacao: datetime
    total_de_imagens: int = 0


class PromptDetalhe(PromptResumo):
    """O prompt com as imagens que saíram dele."""

    imagens: list[ImagemResumo]
    referencias_visuais: list[ImagemResumo] = Field(
        default_factory=list,
        description=(
            "As imagens-âncora (item 3.1) dos elementos deste frame que já têm "
            "uma aprovada. O fluxo de geração é manual (o usuário copia o "
            "prompt e cola numa ferramenta externa — item 2.1, passo 9), então "
            "a API não anexa a imagem sozinha: isto avisa o app de quais "
            "referências visuais existem, para o usuário anexá-las também, "
            "mantendo a aparência do personagem consistente entre capítulos "
            "distantes em vez de a ferramenta de imagem inventar um rosto novo "
            "a cada geração."
        ),
    )


class PromptNovo(BaseModel):
    """O que o app manda para montar um prompt a partir de um frame (passo 8).

    Os três campos são opcionais: na ausência de ``perfil_renderizacao_id``, vale
    o perfil padrão do livro; na ausência de ``modelo``, vale o ``modelo_prompt``
    da configuração (item 6.6).
    """

    perfil_renderizacao_id: int | None = None
    modelo: str | None = Field(default=None, max_length=200)
    comentario: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Uma correção pontual do usuário, com prioridade sobre a leitura "
            "automática do capítulo (item 4.4). Gerar de novo com um comentário "
            "é como se pede um refinamento — não existe rota separada para isso."
        ),
    )


class PromptAjuste(BaseModel):
    """O que o app manda para anotar como a imagem ficou."""

    avaliacao: str = Field(min_length=1)
