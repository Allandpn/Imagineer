"""O Favorito: uma estrela da pessoa num livro, num parágrafo, num elemento, numa cena ou numa imagem (RL31 a RL38)."""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base


class TipoDeFavorito(enum.Enum):
    """O que foi favoritado."""

    LIVRO = "LIVRO"
    PARAGRAFO = "PARAGRAFO"
    ELEMENTO = "ELEMENTO"
    CENA = "CENA"
    IMAGEM = "IMAGEM"


class Favorito(Base):
    """Um item favoritado dentro de um livro. **Um por alvo** (o servidor devolve o que já existe ao favoritar de novo).

    Não sobe a ``revisao`` do livro, como o destaque e o marcador: é dado da pessoa, não do conteúdo que o app guarda para ler offline.
    ``banco/revisao.py`` ignora esta tabela por não conhecê-la.
    """

    __tablename__ = "favoritos"

    id: Mapped[int] = mapped_column(primary_key=True)

    livro_id: Mapped[int] = mapped_column(ForeignKey("livros.id", ondelete="CASCADE"), index=True)

    tipo: Mapped[TipoDeFavorito] = mapped_column(
        Enum(
            TipoDeFavorito,
            native_enum=False,
            length=12,
            create_constraint=False,  # sem CHECK: um tipo novo depois não exige mexer em restrição; quem valida é a API
            values_callable=lambda tipo: [membro.value for membro in tipo],
        )
    )

    capitulo_id: Mapped[int | None] = mapped_column(ForeignKey("capitulos.id", ondelete="CASCADE"), index=True)
    posicao: Mapped[int | None] = mapped_column()
    """Só no parágrafo: onde ele **começa**, em UTF-16 desde o início do texto do capítulo (o contrato do item 3.4g)."""

    trecho: Mapped[str | None] = mapped_column(Text)
    """Só no parágrafo: o começo dele (até 300 caracteres), **copiado pelo servidor**, para a lista legível."""

    elemento_id: Mapped[int | None] = mapped_column(ForeignKey("elementos.id", ondelete="CASCADE"), index=True)
    frame_id: Mapped[int | None] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), index=True)
    imagem_id: Mapped[int | None] = mapped_column(ForeignKey("imagens.id", ondelete="CASCADE"), index=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Favorito id={self.id} livro={self.livro_id} tipo={self.tipo.value}>"
