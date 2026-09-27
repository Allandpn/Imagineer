"""Modelo da Configuracao — a integração com IA (item 3.4d)."""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base

ID_UNICO = 1
"""O único id que a tabela de configuração aceita."""


class Configuracao(Base):
    """A configuração da integração com IA, numa linha só.

    Não é a modelagem mais elegante, mas é a mais honesta para o que é: não
    existem "duas configurações" num sistema pessoal de um usuário. A alternativa
    — uma tabela de pares chave/valor — perderia a tipagem de cada campo e
    ganharia só flexibilidade que não vai ser usada.
    """

    __tablename__ = "configuracao"
    __table_args__ = (
        # Impede uma segunda linha aparecer por acidente. Sem isto, dois registros
        # de configuração conviveriam e o sistema leria um deles sem avisar.
        CheckConstraint("id = 1", name="linha_unica"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=ID_UNICO)

    chave_api_openrouter: Mapped[str | None] = mapped_column(String(200))
    """Chave cadastrada pelo app. Sobrepõe a variável de ambiente (item 4.3).

    Existe porque o servidor roda num Raspberry Pi: trocar de chave não deveria
    exigir SSH, editar o ``.env`` e reiniciar o container. Quem preferir só a
    variável de ambiente nunca preenche este campo.
    """

    modelo_extracao: Mapped[str | None] = mapped_column(String(200))
    """Modelo usado para sugerir elementos e estados (passo 6 do fluxo)."""

    modelo_prompt: Mapped[str | None] = mapped_column(String(200))
    """Modelo usado para montar o prompt de imagem (passo 8 do fluxo)."""

    def __repr__(self) -> str:
        return (
            f"<Configuracao extracao={self.modelo_extracao!r} "
            f"prompt={self.modelo_prompt!r}>"
        )
