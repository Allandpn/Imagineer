"""Modelos das sugestões de IA persistidas (item 3.4e).

Cada sugestão que a IA dá num capítulo (fase 1 do item 4.4) vira uma linha
própria, com ``id`` estável — buscável e referenciável entre capítulos, ao
contrário do blob JSON (`Capitulo.sugestoes_ia`) que esta tabela substituiu.
A motivação concreta: a IA sugeriu "Sextus Hospius" num capítulo e "Hospius"
três capítulos depois, sem os dois casarem pelo nome — sem um `id` estável
por sugestão, não havia como o usuário ligar as duas menções antes de
cadastrar o elemento (ver a divergência em ESPECIFICACAO.md, item 6.7).
"""

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String, Table, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imagineer.banco.base import Base
from imagineer.modelos.elemento import TipoElemento

sugestoes_participante = Table(
    "sugestoes_participante",
    Base.metadata,
    Column(
        "sugestao_frame_id",
        ForeignKey("sugestoes_frame.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "sugestao_elemento_id",
        ForeignKey("sugestoes_elemento.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
"""Liga uma SugestaoDeFrame aos elementos sugeridos que participam dela.

Sempre do mesmo capítulo: um frame sugerido é montado a partir dos elementos
que a mesma rodada de sugestão já identificou, nunca de um capítulo diferente
(a mesma regra que já valia na resposta efêmera, antes desta tabela).
"""


class SugestaoDeElemento(Base):
    """Um elemento que a IA identificou num capítulo, persistido.

    Não é gravado como Elemento por si só — o usuário confirma pelas rotas de
    cadastro (Etapa 6.3). `elemento_id` nulo significa "ainda não confirmada".
    """

    __tablename__ = "sugestoes_elemento"

    id: Mapped[int] = mapped_column(primary_key=True)

    capitulo_id: Mapped[int] = mapped_column(
        ForeignKey("capitulos.id", ondelete="CASCADE"), index=True
    )

    tipo: Mapped[TipoElemento] = mapped_column(
        Enum(
            TipoElemento,
            native_enum=False,
            length=20,
            create_constraint=True,
            name="tipo_elemento_sugerido",
            values_callable=lambda tipo: [membro.value for membro in tipo],
        )
    )

    nome: Mapped[str] = mapped_column(String(200))
    """Como a IA nomeou o elemento — pode divergir do nome já cadastrado
    (ex.: "Hospius" vs "Sextus Hospius"), motivo pelo qual o casamento
    automático às vezes falha e a busca por nome (item 6.3) existe."""

    descricao: Mapped[str | None] = mapped_column(Text)
    """Identidade sugerida (fase 1 — quem/o que é, não aparência)."""

    manter_estado_atual: Mapped[bool] = mapped_column(Boolean, server_default=false())
    """Julgamento da IA: o estado já conhecido deste elemento continua valendo."""

    modelo: Mapped[str] = mapped_column(String(200))
    """O modelo que gerou esta sugestão especificamente — sobrevive a uma
    regeneração parcial do capítulo (`forcar=true` só substitui sugestões
    ainda não confirmadas), então linhas diferentes do mesmo capítulo podem
    ter vindo de modelos diferentes."""

    elemento_id: Mapped[int | None] = mapped_column(
        # SET NULL, e não CASCADE: apagar o Elemento não deveria apagar o
        # registro de que a IA um dia sugeriu isso — só desfaz a ligação.
        ForeignKey("elementos.id", ondelete="SET NULL"),
    )
    """O Elemento real a que esta sugestão corresponde — nulo até confirmar,
    automaticamente (nome normalizado casando) ou manualmente pelo usuário."""

    capitulo: Mapped["Capitulo"] = relationship()  # noqa: F821
    elemento: Mapped["Elemento | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return f"<SugestaoDeElemento id={self.id} nome={self.nome!r}>"


class SugestaoDeFrame(Base):
    """Um frame do tipo CENA que a IA sugeriu num capítulo, persistido.

    Sempre representa uma cena: a IA só sugere `tipo=CENA` (item 4.4) — um
    retrato solo nasce direto de um Elemento, por iniciativa do usuário.
    """

    __tablename__ = "sugestoes_frame"

    id: Mapped[int] = mapped_column(primary_key=True)

    capitulo_id: Mapped[int] = mapped_column(
        ForeignKey("capitulos.id", ondelete="CASCADE"), index=True
    )

    titulo: Mapped[str] = mapped_column(String(300))
    descricao: Mapped[str | None] = mapped_column(Text)
    horario: Mapped[str | None] = mapped_column(String(100))
    clima: Mapped[str | None] = mapped_column(String(100))
    humor: Mapped[str | None] = mapped_column(String(100))

    modelo: Mapped[str] = mapped_column(String(200))
    """O modelo que gerou esta sugestão — ver `SugestaoDeElemento.modelo`."""

    frame_id: Mapped[int | None] = mapped_column(
        ForeignKey("frames.id", ondelete="SET NULL"),
    )
    """O Frame real criado a partir desta sugestão — nulo até confirmar."""

    capitulo: Mapped["Capitulo"] = relationship()  # noqa: F821
    frame: Mapped["Frame | None"] = relationship()  # noqa: F821

    participantes: Mapped[list["SugestaoDeElemento"]] = relationship(
        secondary=sugestoes_participante,
    )

    def __repr__(self) -> str:
        return f"<SugestaoDeFrame id={self.id} titulo={self.titulo!r}>"
