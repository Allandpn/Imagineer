"""Onde o leitor parou: o Marcador (automático) e o Pin (manual) — item 3.4h."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base


class Marcador(Base):
    """A posição de leitura automática de um livro: **um por livro**.

    A posição segue o contrato do item 3.4g: deslocamento em **UTF-16** desde o início de
    ``Capitulo.texto``. Quem decide qual marcador vale, quando dois aparelhos gravam, é o
    ``lido_em`` (a hora em que a pessoa chegou ali, segundo o aparelho), não a hora da gravação.

    Não sobe a ``revisao`` do livro, de propósito (item 3.4h): é gravado a cada pouco de leitura e
    faria o app reler a lista do livro sem parar. ``banco/revisao.py`` ignora esta tabela por não
    conhecê-la, e um teste prova isso.
    """

    __tablename__ = "marcadores"
    __table_args__ = (
        # Um por livro: é o banco garantindo que a regra "o mais recente vence" tem um só candidato.
        UniqueConstraint("livro_id", name="uq_marcador_livro"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    livro_id: Mapped[int] = mapped_column(ForeignKey("livros.id", ondelete="CASCADE"))
    capitulo_id: Mapped[int] = mapped_column(ForeignKey("capitulos.id", ondelete="CASCADE"))

    posicao_no_texto: Mapped[int]
    """Deslocamento em UTF-16 desde o início do texto do capítulo."""

    lido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    """Quando a pessoa chegou ali, segundo o aparelho. Um valor no futuro é limitado ao relógio
    do servidor ao gravar."""

    def __repr__(self) -> str:
        return f"<Marcador livro={self.livro_id} capitulo={self.capitulo_id} pos={self.posicao_no_texto}>"


class Pin(Base):
    """Uma posição marcada à mão num livro, com uma nota curta opcional. **Vários por livro.**"""

    __tablename__ = "pins"

    id: Mapped[int] = mapped_column(primary_key=True)

    livro_id: Mapped[int] = mapped_column(ForeignKey("livros.id", ondelete="CASCADE"), index=True)
    capitulo_id: Mapped[int] = mapped_column(ForeignKey("capitulos.id", ondelete="CASCADE"))

    posicao_no_texto: Mapped[int]
    """Deslocamento em UTF-16 desde o início do texto do capítulo (mesmo contrato do marcador)."""

    nota: Mapped[str | None] = mapped_column(String(1000))

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Pin id={self.id} capitulo={self.capitulo_id} pos={self.posicao_no_texto}>"
