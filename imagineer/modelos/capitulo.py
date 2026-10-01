"""Modelo do Capítulo — o texto extraído de uma parte do EPUB (item 3.4a)."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
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

    ignorado: Mapped[bool] = mapped_column(Boolean, server_default=false())
    """Se este "capítulo" deve ficar de fora do trabalho de catalogação.

    Todo EPUB traz, misturado aos capítulos, material que não é narrativa:
    créditos, glossário, agradecimentos, lista de personagens, notas do
    tradutor, anúncios da editora. Nenhum critério automático separa isso de um
    capítulo legítimo sem arriscar descartar narrativa — e perder um prólogo é
    um erro muito pior que listar um glossário.

    Por isso nada é descartado na importação: ela apenas **sugere**, marcando
    este campo, e o usuário confirma ou desmarca. É o mesmo padrão do item 4.4
    da especificação, onde a IA sugere o estado de um elemento e o usuário
    decide.
    """

    orientacao_da_analise: Mapped[str | None] = mapped_column(String(1000))
    """O que o usuário pediu à IA para procurar neste capítulo na reanálise (item 6.7, M1): "falta a cena
    em que X chega ao porto". Fica guardada e é reaproveitada nas reanálises seguintes, porque só as
    sugestões **não confirmadas** são refeitas — sem isso o pedido sumiria. Nulo = nenhuma."""

    sugestoes_geradas_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Quando a última rodada de `POST /capitulos/{id}/sugestoes` chamou a IA
    de verdade para este capítulo — o texto em si não fica mais aqui, fica em
    linhas próprias (`SugestaoDeElemento`/`SugestaoDeCena`, item 3.4e).

    Controla se a rota pode servir o que já foi sugerido em vez de rechamar a
    IA: sem isso, o usuário via respostas divergentes a cada chamada, porque a
    IA não é determinística (item 4.4, fase 1). Nulo significa "nunca gerado
    para este capítulo"; cada rodada nova (`forcar=true` ou primeira vez)
    apenas atualiza este valor, nunca volta a nulo.
    """

    livro: Mapped["Livro"] = relationship(back_populates="capitulos")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Capitulo id={self.id} livro_id={self.livro_id} ordem={self.ordem}>"
