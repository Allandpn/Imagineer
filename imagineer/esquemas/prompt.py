"""Contratos das rotas de prompts e catálogo de imagens (Etapa 6.6)."""

from datetime import datetime
from typing import Literal

from decimal import Decimal

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
    modelo: str | None = Field(
        default=None,
        description="O modelo de imagem que gerou esta imagem; nulo se foi importada (item 7.5b, Z1).",
    )
    sem_filtro_de_seguranca: bool = Field(
        default=False,
        description="A imagem foi gerada com o filtro de segurança do modelo desligado, a pedido do usuário (F16).",
    )
    canonica: bool = Field(default=False, description="É a imagem canônica do frame dela (CAN5).")
    oculta_no_capitulo: bool = Field(default=False, description="O frame desta imagem está com a imagem oculta no capítulo (OC1).")
    imagens_de_referencia: list[int] = Field(
        default_factory=list,
        description="Os ids das imagens enviadas como referência quando **esta** imagem foi gerada (RS2); vazia = nenhuma.",
    )
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
    so_imagem: bool = Field(default=False, description="O prompt existe só para guardar uma imagem importada sem prompt (PI1); não vale como prompt.")
    texto_pt: str | None = Field(default=None, description="A versão em português (PT1); nulo = ainda sem tradução. O que vai à imagem é o `texto`.")
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
    modelo_imagem: str | None = Field(
        default=None,
        description="O modelo de imagem da última tentativa de gerar a imagem deste prompt; nulo se nunca foi tentado (Z1).",
    )
    sem_filtro_de_seguranca: bool = Field(
        default=False,
        description="A última tentativa foi com o filtro de segurança do modelo desligado, a pedido do usuário (F16).",
    )
    imagens_de_referencia: list[int] = Field(
        default_factory=list,
        description="Os ids das imagens enviadas como referência na última tentativa; vazia = nenhuma (W7).",
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


class Traducao(BaseModel):
    """O resultado de uma tradução de prompt (PT2, PT3, PT6)."""

    texto: str
    modelo: str | None = Field(default=None, description="O modelo que traduziu; nulo quando a tradução já estava guardada.")
    custo: Decimal | None = Field(default=None, description="Quanto a chamada custou, em dólares (o que o OpenRouter informou); nulo = sem chamada ou sem custo informado.")
    reaproveitada: bool = Field(default=False, description="`true`: já estava guardada, **sem chamar a IA** (sem custo).")


class PedidoDeTraducaoParaIngles(BaseModel):
    """O corpo de ``POST /prompts/{id}/traduzir-para-ingles`` (PT3): o português que a pessoa escreveu."""

    texto: str = Field(min_length=1, max_length=8000)


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
    texto_pt: str | None = Field(
        default=None,
        max_length=8000,
        description="O português que a pessoa escreveu e que deu origem ao `texto` editado (PT4); o prompt novo o guarda.",
    )
    modelo: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "O modelo de imagem **só deste pedido** (Z3). Ausente ou em branco, vale o `modelo_imagem` da "
            "configuração. Não muda o padrão do servidor."
        ),
    )
    imagens_de_referencia: list[int] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Ids de imagens do catálogo enviadas **como referência visual** neste pedido (W3), no máximo 4. Só vale se "
            "o `modelo` do pedido (ou o padrão) está em `modelos_com_referencia` da configuração, e não no fal.ai; senão, "
            "422. O texto enviado ganha uma frase dizendo qual imagem é de quem (W5); o prompt guardado não muda."
        ),
    )
    sem_filtro_de_seguranca: bool = Field(
        default=False,
        description=(
            "**Desliga o filtro de segurança do modelo** neste pedido (F12 a F19). Só vale se o `modelo` (obrigatório, "
            "escolhido de propósito) é `replicate:` e está em `modelos_sem_filtro`, e se o prompt não traz sinal de "
            "menor de idade; senão, 422. A chamada é direta: não suaviza nada. O app manda isto quando o usuário "
            "escolhe um modelo da lista de modelos sem filtro."
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


class ImagemCandidata(ImagemResumo):
    """Uma imagem que pode ir como referência (W2): a imagem, e se é a **âncora** (a referência principal) do elemento."""

    ancora: bool = Field(default=False, description="É a âncora do estado (ou a padrão do elemento): a referência principal.")


class ElementoDoCapitulo(BaseModel):
    """Um elemento numa lista **por capítulo** (VM2): as imagens do retrato dele **naquele** capítulo."""

    elemento_id: int
    nome: str
    tipo: str = Field(description="O tipo do elemento (`PERSONAGEM`, `AMBIENTE`...).")
    imagens: list[ImagemCandidata] = Field(
        description="As imagens ativas dos retratos dele **neste capítulo**, mais recentes primeiro; vazia se ele só tem estado aqui."
    )


class CapituloComElementos(BaseModel):
    """Um capítulo e os elementos que aparecem nele (com estado ou retrato), para o seletor navegável (VM2)."""

    capitulo_id: int
    ordem: int
    titulo: str | None
    elementos: list[ElementoDoCapitulo]


class ElementosPorCapitulo(BaseModel):
    """O livro inteiro por capítulo: o que o seletor único de vínculo mostra (VM1, VM2)."""

    capitulos: list[CapituloComElementos]


class ElementoComImagens(BaseModel):
    """Um elemento do frame e as imagens dele que podem ir como referência."""

    elemento_id: int
    nome: str
    tipo: str = Field(description="O tipo do elemento (`PERSONAGEM`, `AMBIENTE`...).")
    imagens: list[ImagemCandidata] = Field(
        description="Mais recentes primeiro, até 12, com a âncora sempre incluída; vazia se o elemento ainda não tem imagem."
    )


class ReferenciasCandidatas(BaseModel):
    """O que o modal de referências mostra para um frame (W2, W9)."""

    elementos: list[ElementoComImagens]


class ElementoParaVincular(ElementoComImagens):
    """Um elemento que o usuário pode vincular ao frame, com as imagens dele (EV6)."""

    estado_id: int = Field(description="O estado a ligar ao frame: nos identificados, o vigente até o capítulo; nos outros, o do capítulo.")
    no_frame: bool = Field(description="Já participa da cena ou já está vinculado ao retrato.")
    removivel: bool = Field(
        description=(
            "Está no frame e **pode sair** por este seletor: é um vinculado do retrato ou um participante acrescentado à mão. "
            "Falso para o participante que veio da sugestão da cena e para quem não está no frame."
        )
    )


class ElementosParaVincular(BaseModel):
    """O que o seletor de elementos e imagens mostra (EV2, EV6): as duas seções."""

    identificados: list[ElementoParaVincular] = Field(description="Os elementos que a IA identificou neste capítulo (sugestões ligadas a um elemento).")
    outros: list[ElementoParaVincular] = Field(description="Os elementos com estado neste capítulo que a IA não sugeriu.")
    de_outros_capitulos: list[ElementoParaVincular] = Field(
        default_factory=list,
        description=(
            "Os demais elementos do livro, que não têm estado neste capítulo (VM7). Cada um vem com o estado **vigente até este capítulo** "
            "ou, se só aparece depois, o primeiro que tem: é o que a cena passa a citar."
        ),
    )
