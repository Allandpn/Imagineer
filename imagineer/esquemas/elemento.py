"""Contratos das rotas de elementos e estados (Etapa 6.3)."""

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
    """

    tipo: TipoElemento
    nome: str = Field(min_length=1, max_length=200)
    descricao: str | None = None
    estado_inicial: EstadoNovo | None = None


class ElementoAjuste(BaseModel):
    """Os campos ajustáveis de um elemento. Só o que vem é aplicado."""

    tipo: TipoElemento | None = None
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    descricao: str | None = None


class ElementoSugerido(BaseModel):
    """Um elemento sugerido pela IA — só identificação (passo 6, item 4.4, fase 1).

    Não é gravado no banco por esta rota — o app mostra a sugestão e o usuário
    confirma pelas rotas de cadastro já existentes (`POST /elementos`,
    `POST /elementos/{id}/estados`).

    Não traz descrição de aparência: essa parte é a leitura profunda (fase 2),
    que acontece depois, dentro de `POST /cenas/{id}/prompts` — pedir isso de
    vários elementos na mesma resposta misturou atributos entre personagens
    num teste com IA real.
    """

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
            "bateu por tipo e nome. Nulo significa elemento novo."
        ),
    )


class ParticipanteSugerido(BaseModel):
    """Um elemento que participa de uma cena sugerida.

    Referenciado por nome, não por `elemento_id` diretamente — o app resolve
    isso batendo `nome_participante` contra a lista de `elementos` da mesma
    resposta (por `elemento_id`, se o nome bateu com um já cadastrado).
    """

    tipo: TipoElemento
    nome: str
    elemento_id: int | None = Field(
        default=None,
        description="O elemento já cadastrado correspondente, se algum bateu.",
    )


class CenaSugerida(BaseModel):
    """Uma cena sugerida pela IA (item 4.4): elementos interagindo num momento.

    Não é gravada no banco por esta rota — é um rascunho para o usuário usar ao
    criar a cena de verdade (`POST /capitulos/{id}/cenas`), pré-preenchendo
    título, atributos situacionais e quais estados marcar.
    """

    titulo: str
    descricao: str | None
    horario: str | None
    clima: str | None
    humor: str | None
    participantes: list[ParticipanteSugerido]


class SugestoesDeCapitulo(BaseModel):
    """O que `POST /capitulos/{id}/sugestoes` devolve."""

    modelo: str
    elementos: list[ElementoSugerido]
    cenas: list[CenaSugerida] = Field(
        default_factory=list,
        description=(
            "Recortes narrativos sugeridos, combinando elementos identificados "
            "acima — o que de fato vale a pena ilustrar, não só uma lista solta "
            "de quem existe no capítulo."
        ),
    )
