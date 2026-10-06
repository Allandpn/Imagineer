"""O AudioDeCapitulo: a narração de um capítulo gerada por voz de IA (item NA4)."""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base


class SituacaoDoAudio(enum.Enum):
    """Em que pé está a geração de um áudio (NA5)."""

    GERANDO = "GERANDO"
    PRONTO = "PRONTO"
    FALHOU = "FALHOU"


class AudioDeCapitulo(Base):
    """O MP3 de um capítulo, gerado pelo servidor com a voz e o tom escolhidos.

    **Um áudio por (capítulo, modelo, voz)**: trocar o modelo de voz ou a voz gera **outro** áudio; o antigo fica até ser apagado. Só o caminho
    relativo do arquivo vai para o banco (como nas imagens e nos vídeos); o arquivo mora em ``DIRETORIO_IMAGENS/audios/``. Apagar o
    áudio apaga também o arquivo: um capítulo longo passa de uma dezena de megabytes.
    """

    __tablename__ = "audios_de_capitulo"

    id: Mapped[int] = mapped_column(primary_key=True)

    capitulo_id: Mapped[int] = mapped_column(ForeignKey("capitulos.id", ondelete="CASCADE"), index=True)

    modelo: Mapped[str] = mapped_column(String(200))
    """O modelo de voz do OpenRouter que falou (``configuracao.modelo_narracao``), como ``microsoft/mai-voice-2.1-flash``."""

    voz: Mapped[str] = mapped_column(String(100), default="", server_default="")
    """A voz usada; vazia = a padrão do fornecedor (``configuracao.narracao_voz`` nula)."""

    situacao: Mapped[SituacaoDoAudio] = mapped_column(
        Enum(SituacaoDoAudio, native_enum=False, length=20, create_constraint=False, values_callable=lambda tipo: [m.value for m in tipo]),
        default=SituacaoDoAudio.GERANDO,
    )

    erro: Mapped[str | None] = mapped_column(Text)
    """Por que falhou, em português, para a tela mostrar (NA7)."""

    arquivo: Mapped[str | None] = mapped_column(String(500))
    """Caminho **relativo** em ``DIRETORIO_IMAGENS``; nulo enquanto não está ``PRONTO`` (nunca há arquivo parcial)."""

    tamanho_em_bytes: Mapped[int | None] = mapped_column(Integer)

    caracteres: Mapped[int] = mapped_column(Integer, default=0)
    """Quantos caracteres do capítulo foram narrados (a base da estimativa e do custo)."""

    custo: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    """O custo **estimado** em dólares dos trechos já feitos (NA3: a OpenAI não informa o custo)."""

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<AudioDeCapitulo id={self.id} capitulo={self.capitulo_id} situacao={self.situacao.value}>"
