"""ancora visual padrao do elemento

Item 4.5: mitigar a variação de consistência visual entre capítulos distantes
e entre ferramentas de geração de imagem diferentes (o usuário pode gerar o
retrato do capítulo 1 numa IA e a cena do capítulo 10, dias depois, noutra).
`elementos.imagem_ancora_padrao_id` guarda "como este elemento normalmente
parece", separado da âncora por Estado (`estados_elemento.imagem_ancora_id`,
que registra a aparência numa cena específica) — mesma separação
identidade/aparência já usada para texto, agora também para imagem. Serve de
reserva em `referencias_visuais` quando o Estado usado num Frame não tem
âncora própria.

Identificador desta migration: a92e5f1c8d3b
Vem depois de: f3a7c9d1b2e4
Criada em: 2026-09-28 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'a92e5f1c8d3b'
down_revision: Union[str, Sequence[str], None] = 'f3a7c9d1b2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Acrescenta a coluna, nula por padrão — nada muda pra elementos já
    cadastrados até o usuário escolher uma referência principal."""
    op.add_column(
        'elementos',
        sa.Column('imagem_ancora_padrao_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f('fk_elementos_imagem_ancora_padrao_id_imagens'),
        'elementos', 'imagens',
        ['imagem_ancora_padrao_id'], ['id'],
        ondelete='SET NULL',
    )


def reverter() -> None:
    """Remove a coluna, perdendo a referência principal escolhida."""
    op.drop_constraint(
        op.f('fk_elementos_imagem_ancora_padrao_id_imagens'),
        'elementos', type_='foreignkey',
    )
    op.drop_column('elementos', 'imagem_ancora_padrao_id')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
