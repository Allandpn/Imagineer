"""Os limites do servidor compartilhado (itens CT15 a CT20): tamanho de arquivo, narração, armazenamento e cota por pessoa."""

from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base

ID_UNICO_DOS_LIMITES = 1


class Limites(Base):
    """Uma linha só (``id = 1``) com os limites do servidor, editados pelo dono (CT20).

    Os padrões são os decididos pelo Allan em 06/10/2026. **Um valor 0 ou negativo não é aceito**: um limite zerado bloquearia o servidor inteiro.
    """

    __tablename__ = "limites"
    __table_args__ = (CheckConstraint("id = 1", name="ck_limites_linha_unica"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=ID_UNICO_DOS_LIMITES)

    tamanho_maximo_do_video_mb: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    """Por vídeo enviado (CT15). Um vídeo de ~8 s do Gemini/Veo tem ~6,5 MB."""

    tamanho_maximo_do_epub_mb: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    """Por EPUB enviado, e também pelo arquivo de onde se tira a capa (CT15)."""

    tamanho_maximo_da_imagem_mb: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    """Por imagem importada (CT15)."""

    caracteres_maximos_da_narracao: Mapped[int] = mapped_column(Integer, default=100_000, server_default="100000")
    """Por capítulo narrado (CT16): passou disso, recusa **antes** de gastar."""

    armazenamento_total_em_gb: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    """O espaço que a aplicação pode ocupar em disco, no todo (CT17). Ao chegar a 90% disso, novos arquivos são recusados."""

    cota_por_pessoa_em_gb: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    """O espaço de cada pessoa que **não** é o dono (CT18). O dono não tem cota."""
