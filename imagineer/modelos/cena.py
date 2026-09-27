"""Modelo da Cena e a ligação dela com os estados dos elementos (item 3.4c)."""

from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imagineer.banco.base import Base

cenas_estados_elemento = Table(
    "cenas_estados_elemento",
    Base.metadata,
    Column("cena_id", ForeignKey("cenas.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "estado_elemento_id",
        ForeignKey("estados_elemento.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
"""Liga uma Cena aos estados dos elementos que aparecem nela.

A ligação é com o **EstadoElemento**, não com o Elemento — e essa é a escolha
que faz a modelagem funcionar. É ela que registra *como* cada elemento estava
naquele ponto da narrativa, que é o dado que entra no prompt. Ligar direto ao
Elemento perderia essa informação, e o prompt não saberia qual das versões do
personagem usar.

É uma ``Table`` simples e não uma classe de modelo porque não tem colunas
próprias além das duas chaves: as duas juntas formam a chave primária, o que
já impede ligar o mesmo estado duas vezes à mesma cena.
"""


class Cena(Base):
    """O recorte narrativo de um capítulo que vai virar uma imagem."""

    __tablename__ = "cenas"

    id: Mapped[int] = mapped_column(primary_key=True)

    capitulo_id: Mapped[int] = mapped_column(
        ForeignKey("capitulos.id", ondelete="CASCADE"),
        index=True,
    )

    titulo: Mapped[str] = mapped_column(String(300))
    """Como identificar a cena numa lista ("A chegada do rei a Winterfell")."""

    descricao: Mapped[str | None] = mapped_column(Text)
    """O trecho do capítulo, ou um resumo do que acontece."""

    # Atributos situacionais. Ficam aqui, na própria Cena, em vez de numa
    # entidade "Contexto" separada: horário, clima e humor já são naturalmente
    # parte da cena, e uma tabela extra só acrescentaria uma junção (item 3.3).
    horario: Mapped[str | None] = mapped_column(String(100))
    clima: Mapped[str | None] = mapped_column(String(100))
    humor: Mapped[str | None] = mapped_column(String(100))

    capitulo: Mapped["Capitulo"] = relationship()  # noqa: F821

    estados_elemento: Mapped[list["EstadoElemento"]] = relationship(  # noqa: F821
        secondary=cenas_estados_elemento,
        back_populates="cenas",
    )
    """Os elementos da cena, cada um no estado em que estava.

    Aqui o cascade é de propósito o padrão: apagar uma cena desfaz as ligações
    (as linhas da tabela de associação), mas **não** apaga os estados. Um estado
    pertence ao elemento e à narrativa, não à cena que o referenciou.
    """

    prompts: Mapped[list["Prompt"]] = relationship(  # noqa: F821
        back_populates="cena",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Cena id={self.id} titulo={self.titulo!r}>"
