"""Contratos de entrada e saída das rotas de livros e capítulos (Etapa 6.2).

Estes esquemas existem separados dos modelos de propósito (item 1.5): o formato
que a API expõe não precisa ser o formato da tabela. A diferença mais importante
aqui é o **texto do capítulo**, que existe no modelo mas fica fora das listagens —
ver ``CapituloResumo``.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CapituloResumo(BaseModel):
    """Um capítulo numa listagem, **sem** o texto.

    O texto fica de fora porque devolvê-lo em toda listagem daria respostas de
    megabytes: *Os 100 Melhores Contos de Crime* tem 104 capítulos e 1,7 MB de
    texto. O que o app precisa para montar a lista é o tamanho, que diz se o
    capítulo é curto ou longo, e o texto vem quando o usuário abre um capítulo.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    ordem: int
    titulo: str | None
    ignorado: bool
    tamanho_do_texto: int = Field(
        description="Número de caracteres do texto do capítulo."
    )
    sugestoes_pendentes: int = Field(
        default=0,
        description=(
            "Sugestões de elemento ou cena deste capítulo ainda não "
            "confirmadas (item 4.6) — indicador não-bloqueante, para o "
            "usuário ver de relance onde falta revisar."
        ),
    )


class CapituloDetalhe(CapituloResumo):
    """Um capítulo com o texto, para quando o usuário abre um capítulo."""

    livro_id: int
    texto: str


class CapituloAjuste(BaseModel):
    """Os campos que o app pode ajustar num capítulo.

    Ambos são opcionais: o app manda só o que mudou. Marcar um capítulo como
    ignorado é o caso mais comum, e é o que confirma ou desfaz a sugestão da
    importação (item 2.2).
    """

    titulo: str | None = None
    ignorado: bool | None = None


class LivroResumo(BaseModel):
    """Um livro na listagem da biblioteca."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    autor: str | None
    idioma: str | None
    nome_arquivo: str
    data_importacao: datetime
    total_de_capitulos: int
    capitulos_ignorados: int = Field(
        description="Quantos capítulos estão marcados como fora da catalogação."
    )


class LivroDetalhe(LivroResumo):
    """O livro com a estrutura de capítulos — a tela principal do app."""

    identificador_epub: str | None
    perfil_renderizacao_padrao_id: int | None
    capitulos: list[CapituloResumo]


class RespostaImportacao(BaseModel):
    """O que o `POST /livros` devolve.

    Além do livro importado, traz os livros que já tinham o mesmo
    ``dc:identifier``. Importar o mesmo livro duas vezes é permitido (item 3.4a),
    então o app **avisa** em vez de impedir — e para avisar precisa saber.
    """

    livro: LivroDetalhe
    livros_semelhantes: list[LivroResumo] = Field(
        default_factory=list,
        description="Livros já importados com o mesmo identificador do EPUB.",
    )
