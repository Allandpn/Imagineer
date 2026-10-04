"""Modelo do Frame e a ligação dele com os estados dos elementos (item 3.4c).

Chamado ``Frame`` (e não ``Cena``) porque cobre dois casos que a modelagem
original tratava como se fossem o mesmo: um retrato solo de um elemento
(``tipo=PERSONAGEM``) e um recorte narrativo com vários elementos interagindo
(``tipo=CENA``). Misturar os dois sob um nome só, sem um campo que distinguisse
a intenção, foi o que causou um prompt de personagem citar outro elemento por
engano — ver a divergência registrada na Etapa 5.
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, ForeignKey, String, Table, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imagineer.banco.base import Base

frames_estados_elemento = Table(
    "frames_estados_elemento",
    Base.metadata,
    Column("frame_id", ForeignKey("frames.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "estado_elemento_id",
        ForeignKey("estados_elemento.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
frames_estados_vinculados = Table(
    "frames_estados_vinculados",
    Base.metadata,
    Column("frame_id", ForeignKey("frames.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "estado_elemento_id",
        ForeignKey("estados_elemento.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
"""Liga o frame de um **retrato** aos estados dos elementos **vinculados** ao sujeito dele (item 7.5b, V1).

Separada de ``frames_estados_elemento`` de propósito: o retrato continua com **exatamente um** estado (o sujeito), e os
vinculados — o objeto que ele carrega, o lugar onde está — entram aqui, sem mexer em nada que já procura "o retrato do
elemento"."""

"""Liga um Frame aos estados dos elementos que aparecem nele.

A ligação é com o **EstadoElemento**, não com o Elemento — e essa é a escolha
que faz a modelagem funcionar. É ela que registra *como* cada elemento estava
naquele ponto da narrativa, que é o dado que entra no prompt. Ligar direto ao
Elemento perderia essa informação, e o prompt não saberia qual das versões do
personagem usar.

É uma ``Table`` simples e não uma classe de modelo porque não tem colunas
próprias além das duas chaves: as duas juntas formam a chave primária, o que
já impede ligar o mesmo estado duas vezes ao mesmo frame.
"""


class TipoDeFrame(enum.Enum):
    """O que este Frame representa (item 4.4).

    A distinção existe porque as duas coisas exigem regras diferentes de
    montagem de prompt: um retrato não deveria citar outro elemento; uma cena
    precisa declarar quem, onde e o quê sem ambiguidade.
    """

    PERSONAGEM = "PERSONAGEM"
    """Um retrato solo de UM elemento. Aceita exatamente um estado ligado, e o
    prompt usa só a descrição desse elemento — nunca referencia outros."""

    CENA = "CENA"
    """Um recorte narrativo com um ou mais elementos interagindo num momento
    específico. Passa por uma leitura profunda própria (item 4.4) que verifica
    quem, onde e o quê contra o texto do capítulo."""


class Frame(Base):
    """O recorte de um capítulo que vai virar uma imagem — um retrato ou uma cena."""

    __tablename__ = "frames"

    id: Mapped[int] = mapped_column(primary_key=True)

    capitulo_id: Mapped[int] = mapped_column(
        ForeignKey("capitulos.id", ondelete="CASCADE"),
        index=True,
    )

    tipo: Mapped[TipoDeFrame] = mapped_column(
        Enum(
            TipoDeFrame,
            native_enum=False,
            length=20,
            create_constraint=True,
            name="tipo_de_frame",
            values_callable=lambda tipo: [membro.value for membro in tipo],
        ),
        default=TipoDeFrame.CENA,
        server_default=TipoDeFrame.CENA.value,
    )

    titulo: Mapped[str] = mapped_column(String(300))
    descricao: Mapped[str | None] = mapped_column(Text)

    horario: Mapped[str | None] = mapped_column(String(100))
    clima: Mapped[str | None] = mapped_column(String(100))
    humor: Mapped[str | None] = mapped_column(String(100))

    posicao_no_texto: Mapped[int | None] = mapped_column()
    """Onde, no texto do capítulo, a pessoa **escolheu** pôr este frame ("Ilustrar aqui", item 3.4g):
    deslocamento em UTF-16 desde o início de ``Capitulo.texto``. Nulo = sem escolha: o artefato cai
    para a posição da sugestão que o originou, se houver. **Não é copiada da sugestão.**"""

    imagem_canonica_id: Mapped[int | None] = mapped_column(
        # use_alter: frames -> imagens -> prompts -> frames forma um ciclo; a chave sai por ALTER depois das tabelas.
        # SET NULL: apagar a imagem não apaga o frame, só desfaz a escolha (CAN4).
        ForeignKey("imagens.id", ondelete="SET NULL", use_alter=True, name="fk_frames_imagem_canonica_id"),
    )
    """A imagem **canônica** do frame: a escolhida entre as variações para representá-lo e a que o capítulo mostra
    (item 7.5b, CAN1 a CAN4). Nulo = sem escolha: vale a mais recente."""

    apagado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    """Quando o frame foi para a **lixeira** (LT3); nulo = ativo. Some do capítulo, dos artefatos e da galeria; leva os prompts e as imagens."""

    sugestao_de_cena_antes_id: Mapped[int | None] = mapped_column()
    """De qual ``SugestaoDeCena`` este frame era a confirmação quando foi para a lixeira (sem chave estrangeira, de propósito): restaurar
    o frame a **religa**, se ela ainda existe e continua sem frame (LT3)."""

    imagem_oculta: Mapped[bool] = mapped_column(default=False, server_default="0")
    """O capítulo **não mostra** a imagem deste frame (item 7.5b, OC1 a OC3): o artefato volta a ser só o ícone. A imagem continua
    no catálogo e na galeria; vale só no capítulo. Escolher outra canônica desfaz."""

    imagens_de_referencia: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")
    """Os ids das imagens que o usuário **escolheu** como referência para a próxima geração (item 7.5b, RS1). Fica no servidor
    para valer em qualquer aparelho e depois de fechar o app; quem mostra filtra as que foram para a lixeira."""

    contexto_do_livro: Mapped[str | None] = mapped_column(Text)
    """O que a leitura profunda do frame (item 4.4) confirmou no capítulo sobre
    quem, onde e o quê — só para ``tipo=CENA``.

    **Não substitui** ``titulo``/``descricao``: o que o usuário escreveu tem
    prioridade na montagem do prompt (ele já leu o capítulo); este campo é
    contexto de apoio para preencher o que a descrição não cobriu, e para o
    prompt não se afastar do que o livro realmente mostra.
    """

    confirmado_pela_leitura_profunda: Mapped[bool] = mapped_column(
        Boolean, server_default=false()
    )
    """Se ``contexto_do_livro`` já foi lido do capítulo (modo ``ECONOMIA`` da
    ``prioridade_ia`` reaproveita em vez de reler — item 4.4, mesmo mecanismo
    de ``EstadoElemento.confirmado_pela_leitura_profunda``)."""

    capitulo: Mapped["Capitulo"] = relationship()  # noqa: F821

    estados_elemento: Mapped[list["EstadoElemento"]] = relationship(  # noqa: F821
        secondary=frames_estados_elemento,
        back_populates="frames",
    )

    estados_vinculados: Mapped[list["EstadoElemento"]] = relationship(  # noqa: F821
        secondary=frames_estados_vinculados,
    )
    """Os elementos vinculados ao sujeito de um retrato (V1); vazia na cena e no retrato solo."""

    prompts: Mapped[list["Prompt"]] = relationship(  # noqa: F821
        back_populates="frame",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Frame id={self.id} tipo={self.tipo.name} titulo={self.titulo!r}>"
