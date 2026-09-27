"""Contratos das rotas de elementos e estados (Etapa 6.3 e 6.7)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from imagineer.modelos import TipoElemento


class EstadoResumo(BaseModel):
    """Um estado de elemento como a API o devolve."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    elemento_id: int
    capitulo_id: int
    descricao: str
    imagem_ancora_id: int | None
    data_criacao: datetime


class EstadoNovo(BaseModel):
    """O que o app manda para registrar um estado.

    O capítulo é obrigatório porque todo estado nasce de um ponto da narrativa
    (item 3.4b) — é ele que define quando o estado passa a valer.
    """

    capitulo_id: int
    descricao: str = Field(min_length=1)


class EstadoAjuste(BaseModel):
    """Os campos ajustáveis de um estado. Só o que vem é aplicado."""

    descricao: str | None = Field(default=None, min_length=1)
    imagem_ancora_id: int | None = None


class EstadosDeSugestoes(BaseModel):
    """O que `POST /elementos/{id}/estados-de-sugestoes` recebe (item 3.4e).

    Rota separada de `POST /elementos/{id}/estados`, e não o mesmo campo
    ali: aquela cria **um** estado e devolve **um** `EstadoResumo`; esta cria
    **um estado por sugestão** e devolve uma lista — misturar os dois na
    mesma rota faria o formato da resposta depender do corpo do pedido.
    """

    sugestoes_elemento_ids: list[int] = Field(min_length=1)


class ElementoResumo(BaseModel):
    """Um elemento na listagem, com o estado que vigora no ponto consultado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    livro_id: int
    tipo: TipoElemento
    nome: str
    descricao: str | None
    total_de_estados: int
    estado_vigente: EstadoResumo | None = Field(
        default=None,
        description=(
            "O estado em vigor no ponto consultado, ou nulo se o elemento ainda "
            "não tinha aparecido — o que significa primeira aparição."
        ),
    )


class ElementoDetalhe(BaseModel):
    """O elemento com todos os seus estados, em ordem narrativa."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    livro_id: int
    tipo: TipoElemento
    nome: str
    descricao: str | None
    estados: list[EstadoResumo]


class ElementoNovo(BaseModel):
    """O que o app manda para cadastrar um elemento confirmado pelo usuário.

    O ``estado_inicial`` é opcional mas esperado no caminho normal: no passo 7 do
    fluxo, o usuário confirma que o personagem existe **e** como ele está naquele
    capítulo. Em dois pedidos separados, uma falha no meio deixaria um elemento
    sem estado nenhum.

    ``tipo``/``nome`` são sempre o que o usuário escreveu aqui — nunca inferidos
    de ``sugestoes_elemento_ids`` (item 3.4e), mesmo que as sugestões escolhidas
    tragam um nome ligeiramente diferente entre si.
    """

    tipo: TipoElemento
    nome: str = Field(min_length=1, max_length=200)
    descricao: str | None = None
    estado_inicial: EstadoNovo | None = None
    sugestoes_elemento_ids: list[int] = Field(
        default_factory=list,
        description=(
            "Sugestões de elemento (de um ou mais capítulos) a incorporar como "
            "Estados deste elemento, um por sugestão — resolve o caso em que a "
            "IA sugeriu o mesmo personagem em capítulos diferentes sem casar "
            "pelo nome (item 3.4e). Pode vir junto com estado_inicial."
        ),
    )


class ElementoAjuste(BaseModel):
    """Os campos ajustáveis de um elemento. Só o que vem é aplicado."""

    tipo: TipoElemento | None = None
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    descricao: str | None = None


class ElementoSugerido(BaseModel):
    """Um elemento sugerido pela IA — só identificação (passo 6, item 4.4, fase 1).

    Não é gravado como Elemento por esta rota — o app mostra a sugestão e o
    usuário confirma pelas rotas de cadastro já existentes (`POST /elementos`,
    `POST /elementos/{id}/estados`). Mas a sugestão em si **é** persistida
    (item 3.4e): tem `id` estável, buscável por nome em `GET
    /livros/{id}/sugestoes-elemento`, e pode ser referenciada depois em
    `sugestoes_elemento_ids` para confirmar sem digitar de novo.

    Não traz descrição de aparência: essa parte é a leitura profunda (fase 2),
    que acontece depois, dentro de `POST /frames/{id}/prompts` — pedir isso de
    vários elementos na mesma resposta misturou atributos entre personagens
    num teste com IA real.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Id estável desta sugestão, para referenciar depois.")
    tipo: TipoElemento
    nome: str
    descricao: str | None = Field(
        description="Identidade do elemento: quem ou o que é. Não muda."
    )
    manter_estado_atual: bool = Field(
        description="A IA acha que o estado conhecido continua valendo (item 4.4)."
    )
    elemento_id: int | None = Field(
        default=None,
        description=(
            "O elemento já cadastrado a que esta sugestão corresponde, se algum "
            "bateu por tipo e nome (automaticamente) ou foi confirmado à mão. "
            "Nulo significa elemento ainda não confirmado."
        ),
    )
    modelo: str = Field(description="O modelo de IA que gerou esta sugestão.")


class ParticipanteSugerido(BaseModel):
    """Um elemento que participa de uma cena sugerida.

    Aponta para a `SugestaoDeElemento` correspondente, sempre do mesmo
    capítulo da cena sugerida — o app resolve isso batendo o nome do
    participante contra a lista de `elementos` da mesma resposta.
    """

    model_config = ConfigDict(from_attributes=True)

    sugestao_elemento_id: int = Field(
        description="A SugestaoDeElemento correspondente, do mesmo capítulo."
    )
    tipo: TipoElemento
    nome: str
    elemento_id: int | None = Field(
        default=None,
        description="O elemento já cadastrado correspondente, se algum bateu.",
    )


class FrameSugerido(BaseModel):
    """Um frame do tipo CENA sugerido pela IA (item 4.4): elementos interagindo
    num momento.

    Não é gravado como Frame por esta rota — é um rascunho persistido (item
    3.4e) para o usuário usar ao criar o frame de verdade (`POST
    /capitulos/{id}/frames`, com `sugestao_frame_id`), pré-preenchendo título,
    atributos situacionais e quais estados marcar.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Id estável desta sugestão, para referenciar depois.")
    titulo: str
    descricao: str | None
    horario: str | None
    clima: str | None
    humor: str | None
    participantes: list[ParticipanteSugerido]
    modelo: str = Field(description="O modelo de IA que gerou esta sugestão.")


class SugestoesDeCapitulo(BaseModel):
    """O que `POST /capitulos/{id}/sugestoes` devolve.

    Sem `modelo` no topo: como `forcar=true` só substitui sugestões ainda não
    confirmadas (item 3.4e), um mesmo capítulo pode ter sugestões geradas por
    modelos diferentes ao longo do tempo — por isso `modelo` vive em cada
    sugestão, não uma vez só para a resposta inteira.
    """

    gerado_em: datetime | None = Field(
        description="Quando a última rodada de sugestão deste capítulo rodou a IA."
    )
    elementos: list[ElementoSugerido]
    frames: list[FrameSugerido] = Field(
        default_factory=list,
        description=(
            "Frames do tipo CENA sugeridos, combinando elementos identificados "
            "acima — o que de fato vale a pena ilustrar, não só uma lista solta "
            "de quem existe no capítulo."
        ),
    )


class SugestaoDeElementoBuscada(BaseModel):
    """Uma linha de `GET /livros/{id}/sugestoes-elemento` — com o capítulo
    de origem, porque a busca cruza capítulos diferentes do mesmo livro."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    capitulo_id: int
    capitulo_ordem: int
    capitulo_titulo: str | None
    tipo: TipoElemento
    nome: str
    descricao: str | None
    manter_estado_atual: bool
    elemento_id: int | None
