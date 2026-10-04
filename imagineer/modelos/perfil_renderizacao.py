"""Modelo do PerfilRenderizacao — o estilo visual a aplicar (item 3.4c)."""

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from imagineer.banco.base import Base
from imagineer.modelos.configuracao import CategoriaEstilo


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

    categoria_estilo: Mapped[CategoriaEstilo | None] = mapped_column(
        Enum(
            CategoriaEstilo,
            native_enum=False,
            length=40,
            # Sem CHECK no banco: uma categoria nova (já houve quatro) não exigiria alterar a restrição. Quem valida o
            # valor é a API (o enum do Pydantic), que é por onde ele entra.
            create_constraint=False,
            values_callable=lambda tipo: [membro.value for membro in tipo],
        ),
        default=None,
    )
    """A categoria de estilo do perfil, ou nulo (BT1).

    Com ela, o prompt ganha o **bloco técnico fixo** da categoria, colado ao fim por código
    (`imagineer/ia/blocos_tecnicos.py`). Nula, o perfil funciona como antes, sem bloco.
    """

    def __repr__(self) -> str:
        return f"<PerfilRenderizacao id={self.id} nome={self.nome!r}>"
