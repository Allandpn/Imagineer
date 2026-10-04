"""Modelo do Livro — os metadados de um EPUB importado (item 3.4a)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, func, true
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from imagineer.banco.base import Base


class Livro(Base):
    """Um e-book importado no sistema.

    Guarda apenas os metadados. O conteúdo em si fica nos Capítulos, para que
    uma listagem de livros não precise carregar o texto inteiro da obra.
    """

    __tablename__ = "livros"

    id: Mapped[int] = mapped_column(primary_key=True)

    titulo: Mapped[str] = mapped_column(String(500))
    autor: Mapped[str | None] = mapped_column(String(300))
    idioma: Mapped[str | None] = mapped_column(String(20))

    titulo_confirmado: Mapped[bool] = mapped_column(Boolean, server_default=true())
    """Se `titulo` veio de verdade do `dc:title` do EPUB (`True`) ou é só um
    fallback (o nome do arquivo, quando o EPUB não declara título — item
    3.4a). `False` até o usuário confirmar/corrigir via `PATCH /livros/{id}`.

    Título e autor são mandatórios do ponto de vista do usuário (a tela de
    importação, Etapa 7, só se dá por concluída com os dois preenchidos) —
    mas o banco continua aceitando o que a extração conseguir, porque o
    import é síncrono e não pode esperar por uma resposta do usuário no meio
    da chamada. `autor is None` já sinaliza pendência sozinho, sem precisar
    de um campo espelho — só `titulo` precisa de um, porque o fallback já
    sobrescreve a coluna com um valor não-nulo indistinguível de um título
    real. Ver `metadados_pendentes` (item 6.2).

    Server default `True`: livros já importados antes desta coluna existir
    não devem ser retroativamente marcados como pendentes.
    """

    identificador_epub: Mapped[str | None] = mapped_column(String(200), index=True)
    """O ``dc:identifier`` do EPUB (ISBN ou UUID).

    Indexado, mas **não único**: serve para avisar que um livro já foi
    importado antes, não para impedir. Muitos EPUBs convertidos repetem
    identificadores genéricos, e unicidade bloquearia importações legítimas.
    """

    nome_arquivo: Mapped[str] = mapped_column(String(500))

    capa: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))
    """A capa do livro, já reduzida (JPEG, lado maior 800 px; item 7.5b, CP1/CP2). ``deferred``: **só é lida quando alguém a pede**,
    para listar livros não arrastar uma imagem por livro. Guardada no banco (dezenas de KB) para ir junto de um ``pg_dump``."""

    capa_tipo: Mapped[str | None] = mapped_column(String(50))
    """O tipo da ``capa`` (``image/jpeg``). Nulo = o livro não tem capa; é também o que diz ``tem_capa`` sem ler a imagem."""

    revisao: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    """Um contador que **sobe a cada mudança no que o leitor mostra** deste livro (item 6.9).

    O app guarda a última revisão que viu e, ao abrir o livro, só relê a lista de capítulos se
    ela mudou — e o `ETag` de `GET /livros/{id}` é este número. Quem o sobe é o ouvinte de
    `imagineer/banco/revisao.py`, e não cada rota: uma rota nova que altere dados **não pode
    esquecer** de fazê-lo.
    """

    data_importacao: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # server_default: quem preenche é o banco, na inserção. Assim o horário
        # é sempre o do servidor, consistente entre registros, sem depender do
        # relógio de quem chamou a API.
        server_default=func.now(),
    )

    perfil_renderizacao_padrao_id: Mapped[int | None] = mapped_column(
        # SET NULL: apagar um perfil de estilo não pode apagar o livro. A
        # referência se desfaz, o dado narrativo permanece.
        ForeignKey("perfis_renderizacao.id", ondelete="SET NULL"),
    )
    """O estilo visual usado por padrão nos prompts deste livro.

    Aceita nulo: um livro recém-importado ainda não tem perfil escolhido. Cada
    prompt pode usar outro perfil pontualmente — por isso o perfil também fica
    registrado no próprio Prompt.
    """

    perfil_renderizacao_padrao: Mapped["PerfilRenderizacao | None"] = relationship()  # noqa: F821

    capitulos: Mapped[list["Capitulo"]] = relationship(  # noqa: F821
        back_populates="livro",
        # A ordem de leitura vem do índice do EPUB, não do id. Definir aqui
        # significa que qualquer acesso a livro.capitulos já vem ordenado,
        # sem precisar lembrar de ordenar em cada consulta.
        order_by="Capitulo.ordem",
        # delete-orphan: apagar o livro apaga os capítulos, e remover um
        # capítulo da lista o apaga do banco. Um capítulo não existe sozinho.
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Livro id={self.id} titulo={self.titulo!r}>"
