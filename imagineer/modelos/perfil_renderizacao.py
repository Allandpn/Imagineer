"""Modelo do PerfilRenderizacao — o estilo visual a aplicar (item 3.4c)."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base


class PerfilRenderizacao(Base):
    """Uma combinação de estilo, iluminação e paleta, reutilizável entre livros.

    Existe como entidade própria, em vez de um campo "estilo" no Livro, por dois
    motivos (item 3.3): permite reaproveitar a mesma combinação em obras
    diferentes, e permite adaptá-la à ferramenta de imagem usada — cada uma tem
    sintaxe própria para descrever o mesmo estilo.

    Note que **não** há ``livro_id`` aqui. O vínculo é o contrário: o Livro
    aponta para o seu perfil padrão. Se o perfil pertencesse a um livro, não
    daria para reaproveitá-lo em outro.
    """

    __tablename__ = "perfis_renderizacao"

    id: Mapped[int] = mapped_column(primary_key=True)

    nome: Mapped[str] = mapped_column(String(100), unique=True)
    """Como você chama o perfil ("Aquarela sombria"). Único, para não acumular
    duplicatas de uma lista que é pequena e curada à mão."""

    # Todos os campos de estilo aceitam nulo porque cada ferramenta de imagem
    # entende um subconjunto diferente: um perfil voltado a uma delas pode não
    # usar artista de referência, outro pode não usar formato.
    estilo: Mapped[str | None] = mapped_column(Text)
    artista_referencia: Mapped[str | None] = mapped_column(String(200))
    iluminacao: Mapped[str | None] = mapped_column(String(200))
    paleta: Mapped[str | None] = mapped_column(String(200))
    formato: Mapped[str | None] = mapped_column(String(50))

    modelo_alvo: Mapped[str | None] = mapped_column(String(100))
    """Ferramenta de imagem a que este perfil se adapta.

    Existe porque o mesmo estilo se escreve de um jeito numa ferramenta e de
    outro jeito noutra.
    """

    def __repr__(self) -> str:
        return f"<PerfilRenderizacao id={self.id} nome={self.nome!r}>"
