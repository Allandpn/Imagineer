"""Modelo da Configuracao — a integração com IA (item 3.4d)."""

import enum

from sqlalchemy import CheckConstraint, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base

ID_UNICO = 1
"""O único id que a tabela de configuração aceita."""


class PrioridadeIA(enum.Enum):
    """Custo vs. qualidade nas decisões que usam IA (item 4.3).

    Hoje controla só a releitura da fase 2 do item 4.4, mas o campo é pensado
    para valer também em futuras decisões parecidas no sistema — por isso mora
    na configuração geral, e não como um parâmetro isolado daquela rota.
    """

    ECONOMIA = "ECONOMIA"
    """Reaproveita o resultado já obtido; só gasta uma chamada de IA nova
    quando ainda não há um resultado salvo."""

    QUALIDADE = "QUALIDADE"
    """Sempre gasta uma chamada de IA nova, mesmo que já exista um resultado
    salvo — prioriza a leitura mais recente do texto sobre o custo."""


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

    prioridade_ia: Mapped[PrioridadeIA] = mapped_column(
        Enum(
            PrioridadeIA,
            native_enum=False,
            length=20,
            create_constraint=True,
            name="prioridade_ia",
            values_callable=lambda tipo: [membro.value for membro in tipo],
        ),
        default=PrioridadeIA.ECONOMIA,
        server_default=PrioridadeIA.ECONOMIA.value,
    )
    """Custo vs. qualidade nas chamadas de IA que podem ser reaproveitadas
    (item 4.4). ``ECONOMIA`` por padrão — não gasta chamada de IA à toa."""

    def __repr__(self) -> str:
        return (
            f"<Configuracao extracao={self.modelo_extracao!r} "
            f"prompt={self.modelo_prompt!r}>"
        )
