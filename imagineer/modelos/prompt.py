"""Modelos do Prompt e da Imagem — a geração e o catálogo (item 3.4c)."""

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imagineer.banco.base import Base


class SituacaoDaGeracao(enum.Enum):
    """O que o provedor de imagem respondeu à última tentativa de gerar a imagem (S5).

    Só descreve a geração **dentro do app**: um prompt que o usuário apenas copiou para
    outra ferramenta continua ``NAO_TENTADO``.
    """

    NAO_TENTADO = "NAO_TENTADO"
    """Nunca foi enviado ao provedor de imagem."""

    RECUSADO = "RECUSADO"
    """O provedor recusou o conteúdo (moderação). O motivo fica em ``motivo_da_recusa``."""

    COM_SUCESSO = "COM_SUCESSO"
    """O provedor gerou a imagem."""


class OrigemDaImagem(enum.Enum):
    """De onde veio a imagem do catálogo (T3, item 7.5b)."""

    IMPORTADA = "IMPORTADA"
    """O usuário a gerou fora do app e a importou (item 6.6)."""

    GERADA = "GERADA"
    """O servidor a gerou pelo modelo de imagem (``POST /prompts/{id}/gerar-imagem``)."""


class Prompt(Base):
    """O registro de um prompt gerado, com o que foi usado para montá-lo.

    Guardar cada prompt é o que permite regenerar a imagem depois, ou gerar o
    mesmo prompt em outro modelo de IA e comparar os resultados.
    """

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(primary_key=True)

    frame_id: Mapped[int] = mapped_column(
        ForeignKey("frames.id", ondelete="CASCADE"),
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

    modelo_imagem: Mapped[str | None] = mapped_column(String(200))
    """O modelo de imagem da **última tentativa** de gerar a imagem deste prompt, inclusive a recusada (Z1).

    Nulo se o prompt nunca foi tentado. O prompt suavizado e o editado guardam o modelo com que foram enviados."""

    imagens_de_referencia: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")
    """Os ids das imagens enviadas como **referência** na **última tentativa** (W7); lista vazia = nenhuma."""

    sem_filtro_de_seguranca: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    """A **última tentativa** deste prompt foi com o filtro de segurança do modelo desligado, a pedido do usuário (F16)."""

    situacao_da_geracao: Mapped[SituacaoDaGeracao] = mapped_column(
        Enum(
            SituacaoDaGeracao,
            native_enum=False,
            length=20,
            create_constraint=True,
            name="situacao_da_geracao",
            values_callable=lambda tipo: [membro.value for membro in tipo],
        ),
        default=SituacaoDaGeracao.NAO_TENTADO,
        server_default=SituacaoDaGeracao.NAO_TENTADO.value,
    )
    """O resultado da última tentativa de gerar a imagem no app (S5)."""

    motivo_da_recusa: Mapped[str | None] = mapped_column(Text)
    """A mensagem do provedor quando ``RECUSADO``; nula nos outros casos."""

    prompt_original_id: Mapped[int | None] = mapped_column(
        # SET NULL, e não CASCADE: apagar o original não pode apagar o suavizado, que
        # é um prompt por si só (com texto e situação próprios).
        ForeignKey("prompts.id", ondelete="SET NULL"),
        index=True,
    )
    """No prompt **suavizado**, o prompt de onde ele saiu (S5); nulo nos demais."""

    data_criacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    frame: Mapped["Frame"] = relationship(back_populates="prompts")  # noqa: F821
    perfil_renderizacao: Mapped["PerfilRenderizacao | None"] = relationship()  # noqa: F821

    imagens: Mapped[list["Imagem"]] = relationship(
        back_populates="prompt",
        cascade="all, delete-orphan",
    )
    """**Todas** as imagens do prompt, inclusive as da lixeira (LX3): serve a quem apaga de vez. Quem **mostra** usa
    ``imagens_ativas``."""

    @property
    def imagens_ativas(self) -> list["Imagem"]:
        """As imagens que não estão na lixeira (LX4)."""
        return [imagem for imagem in self.imagens if imagem.apagada_em is None]

    def __repr__(self) -> str:
        return f"<Prompt id={self.id} frame_id={self.frame_id}>"


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

    tamanho_em_bytes: Mapped[int | None] = mapped_column(Integer)
    """O tamanho do arquivo, em bytes (item 6.9).

    Existe para o app mostrar "Baixar — 240 MB" **antes** de começar um download, sem precisar
    olhar o disco. Preenchido na importação. Nulo nas imagens importadas antes desta coluna: o
    manifesto de mídias calcula a partir do arquivo em disco e grava aqui na primeira vez.
    """

    largura: Mapped[int | None] = mapped_column(Integer)
    altura: Mapped[int | None] = mapped_column(Integer)
    """Dimensões em pixels (item 6.9): lidas na importação; nas imagens antigas, calculadas na primeira
    leitura. Nulas = o arquivo não pôde ser lido como imagem (ou ainda não foi calculado). Com elas o app
    decide o layout no texto — retrato em duas colunas, paisagem na largura da tela (item 7.5b, I1)."""

    modelo: Mapped[str | None] = mapped_column(String(200))
    """O modelo de imagem que **gerou** esta imagem (Z1). Nulo se foi importada ou é anterior a esta coluna."""

    sem_filtro_de_seguranca: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    """A imagem foi gerada com o filtro de segurança do modelo desligado, a pedido do usuário (F16)."""

    origem: Mapped[OrigemDaImagem] = mapped_column(
        Enum(
            OrigemDaImagem,
            native_enum=False,
            length=20,
            create_constraint=True,
            name="origem_da_imagem",
            values_callable=lambda tipo: [membro.value for membro in tipo],
        ),
        default=OrigemDaImagem.IMPORTADA,
        server_default=OrigemDaImagem.IMPORTADA.value,
    )
    """Importada ou gerada pelo servidor (T3): o app mostra as geradas em destaque e as importadas numa seção própria.

    Nas imagens que já existiam antes desta coluna vale ``IMPORTADA``."""

    data_importacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    imagens_de_referencia: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")
    """Os ids das imagens enviadas como **referência** quando **esta** imagem foi gerada (item 7.5b, RS2): o histórico por imagem
    (o do prompt, W7, guarda só a última tentativa). Lista vazia = nenhuma, ou imagem importada."""

    apagada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    """Quando foi movida para a **lixeira** (item 7.5b, LX3); nulo = ativa. O arquivo continua no disco até o usuário apagar
    de vez."""

    prompt: Mapped["Prompt"] = relationship(back_populates="imagens")

    @property
    def canonica(self) -> bool:
        """É a imagem canônica do frame dela (item 7.5b, CAN5)."""
        frame = self.prompt.frame if self.prompt is not None else None
        return frame is not None and frame.imagem_canonica_id == self.id

    def __repr__(self) -> str:
        return f"<Imagem id={self.id} caminho={self.caminho_arquivo!r}>"
