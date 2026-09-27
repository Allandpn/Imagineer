"""Modelos do Prompt e da Imagem — a geração e o catálogo (item 3.4c)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imagineer.banco.base import Base


class Prompt(Base):
    """O registro de um prompt gerado, com o que foi usado para montá-lo.

    Guardar cada prompt é o que permite regenerar a imagem depois, ou gerar o
    mesmo prompt em outro modelo de IA e comparar os resultados.
    """

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(primary_key=True)

    cena_id: Mapped[int] = mapped_column(
        ForeignKey("cenas.id", ondelete="CASCADE"),
        index=True,
    )

    perfil_renderizacao_id: Mapped[int | None] = mapped_column(
        # SET NULL, e não CASCADE: apagar um perfil de estilo não pode apagar o
        # histórico de prompts. O registro do prompt é mais valioso que a
        # referência ao perfil — perder um por causa de uma limpeza de perfis
        # seria um prejuízo desproporcional.
        ForeignKey("perfis_renderizacao.id", ondelete="SET NULL"),
    )
    """O perfil realmente usado nesta geração.

    Pode ser o padrão do Livro ou um override pontual — é justamente por existir
    o override que o perfil usado fica registrado aqui, e não apenas no Livro.
    """

    modelo_ia: Mapped[str | None] = mapped_column(String(200))
    """Identificador do modelo no OpenRouter que montou este prompt."""

    texto: Mapped[str] = mapped_column(Text)
    """O prompt em si, exatamente como foi copiado.

    Guarda o texto final, e não os ingredientes para remontá-lo: assim o
    registro continua fiel mesmo que o perfil de renderização ou a descrição de
    um estado mudem depois.
    """

    avaliacao: Mapped[str | None] = mapped_column(Text)
    """Sua anotação sobre como a imagem ficou.

    É a interpretação do campo "resultado" citado no item 3.1. É o que dá
    sentido a comparar modelos depois: sem a anotação, comparar dois modelos
    exigiria reabrir as imagens e lembrar o que achou de cada uma.
    """

    data_criacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    cena: Mapped["Cena"] = relationship(back_populates="prompts")  # noqa: F821
    perfil_renderizacao: Mapped["PerfilRenderizacao | None"] = relationship()  # noqa: F821

    imagens: Mapped[list["Imagem"]] = relationship(
        back_populates="prompt",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Prompt id={self.id} cena_id={self.cena_id}>"


class Imagem(Base):
    """Um arquivo de imagem importado de volta pelo usuário, no catálogo."""

    __tablename__ = "imagens"

    id: Mapped[int] = mapped_column(primary_key=True)

    prompt_id: Mapped[int] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"),
        index=True,
    )
    """O prompt que originou a imagem.

    Obrigatório porque, no fluxo do sistema, toda imagem do catálogo nasce de um
    prompt. Note que **não** há unicidade aqui: um prompt pode ter várias
    imagens, porque na prática você gera o mesmo prompt mais de uma vez, ou em
    duas ferramentas diferentes, e quer guardar mais de um resultado. É uma
    divergência consciente do item 3.2 — ver a nota no item 3.4c.
    """

    caminho_arquivo: Mapped[str] = mapped_column(String(500), unique=True)
    """Caminho **relativo** dentro de ``DIRETORIO_IMAGENS``.

    Só o caminho vai para o banco; o arquivo fica no volume dedicado (item 1.4).
    Guardar a imagem no próprio banco engordaria backup e consultas sem ganho.

    Relativo, e não absoluto, para que mover a pasta de imagens ou trocar o
    Raspberry Pi não invalide todos os registros de uma vez.
    """

    data_importacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    prompt: Mapped["Prompt"] = relationship(back_populates="imagens")

    def __repr__(self) -> str:
        return f"<Imagem id={self.id} caminho={self.caminho_arquivo!r}>"
