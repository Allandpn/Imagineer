"""Contratos das rotas de prompts e catálogo de imagens (Etapa 6.6)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from imagineer.modelos.prompt import OrigemDaImagem, SituacaoDaGeracao
from imagineer.servicos.imagens_reduzidas import Orientacao, orientacao_de


class ImagemResumo(BaseModel):
    """Uma imagem do catálogo, como a API a devolve.

    Não expõe ``caminho_arquivo``: o app busca os bytes por
    ``GET /imagens/{id}/arquivo``, e o layout do disco não é assunto dele.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    prompt_id: int
    tamanho_em_bytes: int | None = None
    largura: int | None = Field(default=None, description="Largura em pixels; nula se o arquivo não pôde ser lido como imagem.")
    altura: int | None = Field(default=None, description="Altura em pixels; nula como a largura.")
    origem: OrigemDaImagem = Field(
        default=OrigemDaImagem.IMPORTADA,
        description="`IMPORTADA` (o usuário a trouxe de fora) ou `GERADA` (o servidor a gerou): item 7.5b, T3.",
    )
    data_importacao: datetime

    @computed_field(description="RETRATO se a altura é maior que a largura; PAISAGEM no resto; nulo sem dimensões (item 7.5b, I1).")
    @property
    def orientacao(self) -> Orientacao | None:
        return orientacao_de(self.largura, self.altura)


class MidiaDeImagem(BaseModel):
    """Uma imagem do livro no manifesto de mídias (item 6.9)."""

    imagem_id: int
    prompt_id: int
    frame_id: int
    tamanho_em_bytes: int = Field(description="O tamanho do arquivo **original**, em bytes.")
    tipo_do_arquivo: str = Field(description='O tipo de mídia, como "image/png".')
    largura: int | None = Field(default=None, description="Largura em pixels; nula se o arquivo não pôde ser lido.")
    altura: int | None = Field(default=None, description="Altura em pixels; nula como a largura.")

    @computed_field(description="RETRATO, PAISAGEM ou nulo sem dimensões (item 7.5b, I1).")
    @property
    def orientacao(self) -> Orientacao | None:
        return orientacao_de(self.largura, self.altura)


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
    situacao_da_geracao: SituacaoDaGeracao = Field(
        default=SituacaoDaGeracao.NAO_TENTADO,
        description=(
            "O que o provedor de imagem respondeu à última tentativa de gerar a imagem no app: "
            "`NAO_TENTADO`, `RECUSADO` ou `COM_SUCESSO` (item 3.4c)."
        ),
    )
    motivo_da_recusa: str | None = Field(
        default=None, description="A mensagem do provedor quando `RECUSADO`."
    )
    prompt_original_id: int | None = Field(
        default=None,
        description="No prompt suavizado, o prompt de onde ele saiu; nulo nos demais.",
    )


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


class PedidoDeGeracao(BaseModel):
    """O corpo, opcional, de ``POST /prompts/{id}/gerar-imagem``."""

    texto: str | None = Field(
        default=None,
        max_length=8000,
        description=(
            "O prompt **editado à mão** pelo usuário (S3): vira um prompt novo e é enviado direto, sem "
            "suavização. Ausente (ou igual ao texto do prompt), vale o fluxo normal: original e, se o "
            "provedor recusar, a suavização."
        ),
    )


class ResultadoDaGeracao(BaseModel):
    """O que a geração devolveu (item 6.6, "Gerar a imagem"). Responde 200 nos dois desfechos."""

    resultado: Literal["GERADA", "RECUSADA"]
    suavizado: bool = Field(
        description="O prompt enviado por último é uma versão suavizada pelo sistema (não a edição do usuário)."
    )
    prompt: PromptResumo = Field(
        description=(
            "O prompt enviado **por último** (o original, o suavizado ou o editado), com a situação e o "
            "motivo da recusa: é o que o app mostra e deixa editar."
        )
    )
    imagem: ImagemResumo | None = Field(default=None, description="A imagem gerada; nula se `RECUSADA`.")
