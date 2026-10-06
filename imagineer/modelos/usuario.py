"""O Usuario: quem usa o servidor (itens CT1 a CT5 das contas de usuário)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base

DONO_ID = 1
"""O id do dono (CT4): a migração cria a linha 1, e tudo que existia antes das contas passa a ser dele. Também é o usuário de uma sessão que
não sabe de quem é o pedido (o segundo plano e os testes que a montam à mão) — o mesmo comportamento de antes das contas."""


class Usuario(Base):
    """Uma pessoa que usa o servidor.

    Só existe uma linha no modo ``pessoal`` (o dono). No modo ``tailscale`` cada pessoa que chega com o cabeçalho de identidade do Tailscale
    ganha uma linha na primeira visita (CT4).
    """

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)

    login: Mapped[str | None] = mapped_column(String(200), unique=True)
    """O login da conta do Tailscale (um e-mail), **em minúsculas**. Nulo no dono enquanto ele não for reconhecido (CT4) e no modo ``pessoal``."""

    nome: Mapped[str | None] = mapped_column(String(200))

    dono: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    """O Allan. Só há um; ele é quem libera as chaves do servidor para os outros (CT9)."""

    usa_chaves_do_servidor: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    """Pode gastar as chaves de IA do **servidor** (OpenRouter, fal.ai, Replicate), que são do dono (CT9). Falso para quem chega: essa pessoa usa a
    própria chave do OpenRouter, pelo header."""

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Usuario id={self.id} login={self.login!r} dono={self.dono}>"
