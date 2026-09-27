"""Modelo do Capítulo — o texto extraído de uma parte do EPUB (item 3.4a)."""

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imagineer.banco.base import Base


class Capitulo(Base):
    """Um capítulo de um Livro, com o texto que a IA vai ler.

    É a unidade de trabalho do sistema: o usuário escolhe um capítulo, e é o
    texto dele que alimenta a extração de elementos (passo 6 do fluxo).
    """

    __tablename__ = "capitulos"
    __table_args__ = (
        # Dois capítulos não podem ocupar a mesma posição no mesmo livro.
        # É o banco garantindo uma regra que um erro no parsing do EPUB
        # poderia violar em silêncio.
        UniqueConstraint("livro_id", "ordem", name="uq_capitulo_livro_ordem"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    livro_id: Mapped[int] = mapped_column(
        # ondelete="CASCADE" é a regra no *banco*; o cascade do relationship
        # em Livro.capitulos é a regra no *ORM*. Os dois são necessários: o
        # primeiro protege contra qualquer DELETE (inclusive em SQL direto),
        # o segundo faz o Python se comportar igual sem precisar recarregar.
        ForeignKey("livros.id", ondelete="CASCADE"),
        index=True,
    )

    ordem: Mapped[int] = mapped_column(Integer)
    """Posição no livro, começando em 1. Vem do índice (TOC) do EPUB."""

    titulo: Mapped[str | None] = mapped_column(String(500))
    """O índice do EPUB nem sempre nomeia o capítulo — por isso aceita nulo."""

    texto: Mapped[str] = mapped_column(Text)
    """Conteúdo textual. ``Text`` em vez de ``String(n)``: não há limite útil
    para o tamanho de um capítulo."""

    livro: Mapped["Livro"] = relationship(back_populates="capitulos")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Capitulo id={self.id} livro_id={self.livro_id} ordem={self.ordem}>"
