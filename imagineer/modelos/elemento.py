"""Modelos do Elemento e do EstadoElemento (item 3.4b).

A separação entre os dois é a ideia central da modelagem, e vale entender o
porquê: personagens envelhecem e se ferem, objetos quebram, ambientes são
destruídos e reconstruídos. Se a aparência fosse um campo do próprio Elemento,
o prompt do capítulo 40 usaria a descrição do capítulo 3 — ou sobrescreveria
a antiga, perdendo o histórico.

- **Elemento** responde "quem ou o que é isto" — e não muda.
- **EstadoElemento** responde "como está isto agora" — e muda várias vezes.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imagineer.banco.base import Base
from imagineer.modelos.frame import frames_estados_elemento


class TipoElemento(enum.Enum):
    """O que um Elemento é.

    Um enum em vez de tabelas separadas por tipo: personagens, ambientes,
    objetos e criaturas têm exatamente a mesma necessidade — manter
    consistência visual ao longo da narrativa. Tabelas por tipo duplicariam
    schema e lógica sem ganho (item 3.3 da especificação).
    """

    PERSONAGEM = "PERSONAGEM"
    AMBIENTE = "AMBIENTE"
    OBJETO = "OBJETO"
    CRIATURA = "CRIATURA"
    GRUPO = "GRUPO"
    """Rótulo para conjuntos ("os Stark", "a Patrulha da Noite").

    Funciona como qualquer outro tipo, mas **sem membros explícitos**: a tabela
    que ligaria um grupo aos seus integrantes está adiada para a v2.
    """
    VEICULO = "VEICULO"
    EDIFICACAO = "EDIFICACAO"


class Elemento(Base):
    """A identidade de algo recorrente na história."""

    __tablename__ = "elementos"
    __table_args__ = (
        # Impede que a extração automática cadastre o mesmo personagem duas
        # vezes no mesmo livro. O "tipo" entra na chave porque um nome pode
        # designar coisas diferentes: a região Winterfell e o castelo
        # Winterfell são registros distintos.
        UniqueConstraint("livro_id", "tipo", "nome", name="uq_elemento_livro_tipo_nome"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    livro_id: Mapped[int] = mapped_column(
        ForeignKey("livros.id", ondelete="CASCADE"),
        index=True,
    )

    tipo: Mapped[TipoElemento] = mapped_column(
        Enum(
            TipoElemento,
            # native_enum=False guarda o valor como VARCHAR em vez de criar um
            # tipo próprio no PostgreSQL. Acrescentar um tipo novo depois é uma
            # migration curta (trocar a restrição); com ENUM nativo, remover um
            # valor exigiria recriar o tipo inteiro e converter a coluna.
            native_enum=False,
            length=20,
            # create_constraint precisa ser pedido explicitamente: desde o
            # SQLAlchemy 1.4 o padrão é False, e sem isso a coluna seria um
            # VARCHAR sem nenhuma validação no banco.
            create_constraint=True,
            name="tipo_elemento",
            # Guarda o nome do membro ("PERSONAGEM"), não o valor. Aqui os dois
            # coincidem, mas deixar explícito evita surpresa se algum dia um
            # valor diferir do nome.
            values_callable=lambda tipo: [membro.value for membro in tipo],
        )
    )

    nome: Mapped[str] = mapped_column(String(200))
    """Como o elemento é chamado na obra."""

    descricao: Mapped[str | None] = mapped_column(Text)
    """Quem ou o que é: papel na história, natureza, função.

    Aceita nulo porque, ao confirmar uma sugestão da IA, o usuário pode ainda
    não ter definido a identidade — só reconhecido que o elemento existe.
    """

    imagem_ancora_padrao_id: Mapped[int | None] = mapped_column(
        # SET NULL, como a âncora por estado (item 3.1): apagar a imagem do
        # catálogo não pode apagar o elemento, só desfaz a referência.
        ForeignKey("imagens.id", ondelete="SET NULL"),
    )
    """A referência visual "de como este elemento normalmente parece",
    separada da âncora por Estado (aparência numa cena específica).

    Espelha, para imagens, a mesma separação identidade/aparência que já
    existe para texto (`Elemento.descricao` vs. `EstadoElemento.descricao`):
    esta é a foto-base do personagem, escolhida à mão pelo usuário entre as
    imagens já aprovadas do catálogo — nunca a mais recente automaticamente
    (uma cena de ferimento não deveria virar a referência padrão). Serve de
    reserva quando o Estado usado num Frame não tem âncora própria (item 4.5).
    """

    apagado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    """Quando o elemento foi para a **lixeira** (LT4); nulo = ativo. Some do livro; leva estados, identidade e retratos. O nome continua
    ocupado (a unicidade de livro, tipo e nome vale também para ele)."""

    livro: Mapped["Livro"] = relationship()  # noqa: F821

    imagem_ancora_padrao: Mapped["Imagem | None"] = relationship()  # noqa: F821

    estados: Mapped[list["EstadoElemento"]] = relationship(
        back_populates="elemento",
        cascade="all, delete-orphan",
    )

    historico_identidade: Mapped[list["HistoricoIdentidadeElemento"]] = relationship(
        back_populates="elemento",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Elemento id={self.id} tipo={self.tipo.name} nome={self.nome!r}>"


class EstadoElemento(Base):
    """Como um Elemento está em um ponto específico da narrativa."""

    __tablename__ = "estados_elemento"

    id: Mapped[int] = mapped_column(primary_key=True)

    elemento_id: Mapped[int] = mapped_column(
        ForeignKey("elementos.id", ondelete="CASCADE"),
        index=True,
    )

    capitulo_id: Mapped[int] = mapped_column(
        ForeignKey("capitulos.id", ondelete="CASCADE"),
        index=True,
    )
    """Capítulo em que este estado passa a valer.

    Obrigatório porque todo estado nasce de um capítulo: é lá que o usuário
    confirma "possível novo estado" (passo 7 do fluxo). Note que **não** há
    unicidade em (elemento_id, capitulo_id) — um personagem pode entrar ferido
    e sair curado no mesmo capítulo, e cada mudança é um estado.
    """

    descricao: Mapped[str] = mapped_column(Text)
    """A aparência em si: roupas, ferimentos, condição. É o que entra no prompt."""

    data_criacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    """Quando o registro foi criado — **não** serve para ordenar a narrativa.

    O usuário pode processar capítulos fora de ordem ou revisitar um capítulo
    antigo, então a ordem de criação não corresponde à ordem da história. Quem
    define a sequência narrativa é ``Capitulo.ordem`` (ver item 3.4b).
    """

    imagem_ancora_id: Mapped[int | None] = mapped_column(
        # SET NULL: apagar uma imagem do catálogo não pode apagar o estado do
        # personagem. A âncora se desfaz, a descrição narrativa permanece.
        ForeignKey("imagens.id", ondelete="SET NULL"),
    )
    """Uma imagem já aprovada deste estado, usada como referência visual.

    É a "âncora visual" do item 3.1: nas gerações seguintes do mesmo personagem,
    esta imagem serve de referência — o mecanismo que mantém a aparência
    consistente entre capítulos distantes.
    """

    confirmado_pela_leitura_profunda: Mapped[bool] = mapped_column(
        Boolean, server_default=false()
    )
    """Se ``descricao`` já veio da leitura profunda do capítulo de origem
    (item 4.4, fase 2), em vez de só do que o usuário digitou no passo 7.

    Controla o modo ``ECONOMIA`` de ``prioridade_ia``: enquanto verdadeiro, a
    montagem de um novo prompt reaproveita esta descrição em vez de relê-la —
    só volta a ``False`` se o estado for apagado e recriado.
    """

    elemento: Mapped["Elemento"] = relationship(back_populates="estados")
    capitulo: Mapped["Capitulo"] = relationship()  # noqa: F821
    imagem_ancora: Mapped["Imagem | None"] = relationship()  # noqa: F821

    frames: Mapped[list["Frame"]] = relationship(  # noqa: F821
        secondary=frames_estados_elemento,
        back_populates="estados_elemento",
    )
    """Os frames em que o elemento aparece neste estado.

    É o outro lado do muitos-para-muitos do item 3.2: um elemento aparece em
    vários frames de vários capítulos.
    """

    def __repr__(self) -> str:
        return f"<EstadoElemento id={self.id} elemento_id={self.elemento_id}>"


class HistoricoIdentidadeElemento(Base):
    """O que um capítulo específico revela/acrescenta sobre a *identidade*
    de um Elemento — quem ele é, não sua aparência (item 3.4f).

    Ao contrário de ``EstadoElemento`` (aparência, "última vale"), isto é
    **cumulativo**: um registro não substitui o anterior, soma-se a ele. O
    que o capítulo 8 revela sobre um personagem continua verdade no
    capítulo 20 — sobrescrever perderia o que já foi revelado antes (ver a
    justificativa completa no item 3.3 da especificação).
    """

    __tablename__ = "historico_identidade_elemento"

    id: Mapped[int] = mapped_column(primary_key=True)

    elemento_id: Mapped[int] = mapped_column(
        ForeignKey("elementos.id", ondelete="CASCADE"),
        index=True,
    )

    capitulo_id: Mapped[int] = mapped_column(
        ForeignKey("capitulos.id", ondelete="CASCADE"),
        index=True,
    )
    """O capítulo que revelou este incremento."""

    descricao: Mapped[str] = mapped_column(Text)
    """Só o que **este** capítulo especificamente acrescenta sobre a
    identidade — não um resumo acumulado. A "identidade vigente" num ponto
    da narrativa é a soma de ``Elemento.descricao`` com estes registros, em
    ordem narrativa (``servicos/identidade_de_elemento.py``)."""

    confirmado_pela_leitura_profunda: Mapped[bool] = mapped_column(
        Boolean, server_default=true()
    )
    """Mesmo espírito do campo homônimo em ``EstadoElemento``. Na prática já
    nasce ``True``: um registro só é criado depois que a leitura profunda de
    identidade (fase 2b, item 4.4) de fato achou algo novo — não existe
    "rascunho" de identidade como existe de aparência.
    """

    data_criacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    elemento: Mapped["Elemento"] = relationship(back_populates="historico_identidade")
    capitulo: Mapped["Capitulo"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<HistoricoIdentidadeElemento id={self.id} elemento_id={self.elemento_id} "
            f"capitulo_id={self.capitulo_id}>"
        )
