"""Quanto custou cada chamada à IA (item 4.3, "Custo das chamadas de IA")."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base


class UsoDeIA(Base):
    """Uma chamada bem-sucedida ao provedor de IA, com os tokens e o custo que ele informou.

    Serve para métricas futuras (custo por modelo, por operação, por dia). Não aponta para livro
    nem capítulo: o provedor não sabe em que livro está, e o vínculo só será acrescentado se a
    métrica por livro fizer falta.
    """

    __tablename__ = "usos_ia"

    id: Mapped[int] = mapped_column(primary_key=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    """Preenchido pelo banco, como ``Imagem.data_importacao``: o horário é o do servidor."""

    operacao: Mapped[str] = mapped_column(String(40))
    """Qual passo do fluxo chamou: ``extracao``, ``estado``, ``identidade``, ``fundamentacao``,
    ``prompt`` ou ``perfil``."""

    modelo: Mapped[str] = mapped_column(String(200))

    tokens_entrada: Mapped[int | None] = mapped_column()
    tokens_saida: Mapped[int | None] = mapped_column()

    custo: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    """O custo, em dólares, que o OpenRouter informou. **Nulo = ele não informou** (modelos gratuitos,
    chave própria do provedor): nunca um zero inventado."""

    id_da_geracao: Mapped[str | None] = mapped_column(String(100))
    """O ``id`` da resposta no OpenRouter, para conferir a cobrança no painel dele."""

    provedor: Mapped[str] = mapped_column(String(20), default="openrouter", server_default="openrouter")
    """Quem cobrou: ``openrouter``, ``fal`` ou ``replicate`` (CU1)."""

    livro_id: Mapped[int | None] = mapped_column(ForeignKey("livros.id", ondelete="SET NULL"), index=True)
    """De que livro foi o gasto, quando se sabe (gerar imagem, gerar prompt, analisar); nulo = sem livro (CU3)."""

    estimado: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    """O ``custo`` veio de uma **tabela de preços**, e não do fornecedor (CU2)."""

    def __repr__(self) -> str:
        return f"<UsoDeIA id={self.id} operacao={self.operacao!r} modelo={self.modelo!r} custo={self.custo}>"
