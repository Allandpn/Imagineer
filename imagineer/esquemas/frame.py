"""Contratos das rotas de frames e perfis de renderização (Etapas 6.4 e 6.5)."""

from pydantic import BaseModel, ConfigDict, Field

from imagineer.modelos import TipoDeFrame, TipoElemento


class EstadoComElemento(BaseModel):
    """Um estado de elemento com a identidade de quem ele descreve.

    A tela do frame mostra "Ned Stark: capa de pele, barba grisalha" — o nome e o
    tipo vêm do Elemento, a descrição vem do Estado. Devolver os dois juntos é a
    diferença entre a API servir a tela e a tela ter que remontar tudo.
    """

    model_config = ConfigDict(from_attributes=True)

    estado_id: int
    elemento_id: int
    tipo: TipoElemento
    nome: str
    descricao: str
    capitulo_id: int


class FrameResumo(BaseModel):
    """Um frame na listagem de um capítulo."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    capitulo_id: int
    tipo: TipoDeFrame
    titulo: str
    descricao: str | None
    horario: str | None
    clima: str | None
    humor: str | None
    total_de_elementos: int


class FrameDetalhe(FrameResumo):
    """O frame com os elementos que aparecem nele, em seus estados."""

    elementos: list[EstadoComElemento]
    contexto_do_livro: str | None = Field(
        default=None,
        description=(
            "O que a leitura profunda do frame (item 4.4) confirmou no "
            "capítulo — só para tipo=CENA, e só depois da primeira vez que "
            "um prompt foi montado para este frame."
        ),
    )


class FrameNovo(BaseModel):
    """O que o app manda para criar um frame.

    Os três atributos situacionais ficam no próprio frame, sem entidade
    "Contexto" separada (item 3.3).
    """

    tipo: TipoDeFrame = Field(
        default=TipoDeFrame.CENA,
        description=(
            "PERSONAGEM exige exatamente um estado em `estados_ids` — o prompt "
            "usa só a descrição desse elemento, sem citar outros (item 4.4). "
            "CENA aceita um ou mais."
        ),
    )
    titulo: str = Field(min_length=1, max_length=300)
    descricao: str | None = None
    horario: str | None = Field(default=None, max_length=100)
    clima: str | None = Field(default=None, max_length=100)
    humor: str | None = Field(default=None, max_length=100)
    estados_ids: list[int] = Field(
        default_factory=list,
        description="Os estados de elemento que aparecem no frame.",
    )


class FrameAjuste(BaseModel):
    """Os campos ajustáveis de um frame. Só o que vem é aplicado.

    `tipo` não é ajustável: muda a regra de quantos estados o frame aceita e
    como o prompt é montado — é mais claro apagar e recriar do que migrar um
    frame de um tipo para o outro.
    """

    titulo: str | None = Field(default=None, min_length=1, max_length=300)
    descricao: str | None = None
    horario: str | None = Field(default=None, max_length=100)
    clima: str | None = Field(default=None, max_length=100)
    humor: str | None = Field(default=None, max_length=100)


class EstadosDoFrame(BaseModel):
    """A lista completa de estados de um frame.

    É ``PUT`` e não ``PATCH``: o app manda quem está no frame por inteiro, que é
    como a tela funciona — o usuário marca e desmarca e salva o conjunto.
    """

    estados_ids: list[int]


class PerfilRenderizacaoBase(BaseModel):
    """Os campos de estilo de um perfil.

    Todos opcionais menos o nome, porque cada ferramenta de imagem entende um
    subconjunto diferente (item 3.4c).
    """

    estilo: str | None = None
    artista_referencia: str | None = Field(default=None, max_length=200)
    iluminacao: str | None = Field(default=None, max_length=200)
    paleta: str | None = Field(default=None, max_length=200)
    formato: str | None = Field(default=None, max_length=50)
    modelo_alvo: str | None = Field(default=None, max_length=100)


class PerfilRenderizacao(PerfilRenderizacaoBase):
    """Um perfil como a API o devolve."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str


class PerfilRenderizacaoNovo(PerfilRenderizacaoBase):
    """O que o app manda para criar um perfil."""

    nome: str = Field(min_length=1, max_length=100)


class PerfilRenderizacaoAjuste(PerfilRenderizacaoBase):
    """Os campos ajustáveis de um perfil."""

    nome: str | None = Field(default=None, min_length=1, max_length=100)


class LivroAjuste(BaseModel):
    """Os campos ajustáveis de um livro.

    Inclui os metadados porque eles podem vir errados do arquivo: na validação, um
    EPUB de *Treasure Island* declarava-se *Death and the Afterlife in Ancient
    Egypt*. A importação é fiel ao que o arquivo diz, então quem corrige é o
    usuário.
    """

    titulo: str | None = Field(default=None, min_length=1, max_length=500)
    autor: str | None = Field(default=None, max_length=300)
    idioma: str | None = Field(default=None, max_length=20)
    perfil_renderizacao_padrao_id: int | None = None
