"""Modelo do Livro — os metadados de um EPUB importado (item 3.4a)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imagineer.banco.base import Base


class Livro(Base):
    """Um e-book importado no sistema.

    Guarda apenas os metadados. O conteúdo em si fica nos Capítulos, para que
    uma listagem de livros não precise carregar o texto inteiro da obra.
    """

    __tablename__ = "livros"

    id: Mapped[int] = mapped_column(primary_key=True)

    titulo: Mapped[str] = mapped_column(String(500))
    autor: Mapped[str | None] = mapped_column(String(300))
    idioma: Mapped[str | None] = mapped_column(String(20))

    identificador_epub: Mapped[str | None] = mapped_column(String(200), index=True)
    """O ``dc:identifier`` do EPUB (ISBN ou UUID).

    Indexado, mas **não único**: serve para avisar que um livro já foi
    importado antes, não para impedir. Muitos EPUBs convertidos repetem
    identificadores genéricos, e unicidade bloquearia importações legítimas.
    """

    nome_arquivo: Mapped[str] = mapped_column(String(500))

    data_importacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # server_default: quem preenche é o banco, na inserção. Assim o horário
        # é sempre o do servidor, consistente entre registros, sem depender do
        # relógio de quem chamou a API.
        server_default=func.now(),
    )

    perfil_renderizacao_padrao_id: Mapped[int | None] = mapped_column(
        # SET NULL: apagar um perfil de estilo não pode apagar o livro. A
        # referência se desfaz, o dado narrativo permanece.
        ForeignKey("perfis_renderizacao.id", ondelete="SET NULL"),
    )
    """O estilo visual usado por padrão nos prompts deste livro.

    Aceita nulo: um livro recém-importado ainda não tem perfil escolhido. Cada
    prompt pode usar outro perfil pontualmente — por isso o perfil também fica
    registrado no próprio Prompt.
    """

    perfil_renderizacao_padrao: Mapped["PerfilRenderizacao | None"] = relationship()  # noqa: F821

    capitulos: Mapped[list["Capitulo"]] = relationship(  # noqa: F821
        back_populates="livro",
        # A ordem de leitura vem do índice do EPUB, não do id. Definir aqui
        # significa que qualquer acesso a livro.capitulos já vem ordenado,
        # sem precisar lembrar de ordenar em cada consulta.
        order_by="Capitulo.ordem",
        # delete-orphan: apagar o livro apaga os capítulos, e remover um
        # capítulo da lista o apaga do banco. Um capítulo não existe sozinho.
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Livro id={self.id} titulo={self.titulo!r}>"
