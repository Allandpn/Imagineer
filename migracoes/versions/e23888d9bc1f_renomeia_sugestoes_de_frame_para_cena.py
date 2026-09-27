"""renomeia sugestoes de frame para cena

Achado revisando a API: a IA sugere uma **cena**, não um Frame — o Frame só
existe depois, quando o usuário confirma que aquela cena (ou um elemento
sozinho) vira de fato um recorte pra gerar imagem. Chamar isso de "Frame"
desde a sugestão (`SugestaoDeFrame`) reintroduzia, na camada de sugestão, a
mesma confusão Cena/Personagem que motivou renomear `Cena` para `Frame` na
Etapa 5 (migration `e4e246883f15`).

`SugestaoDeFrame` vira `SugestaoDeCena`; a coluna `frame_id` (o Frame real
criado a partir da cena, quando confirmada) continua com esse nome — está
correta, é o Frame de verdade, não a sugestão.

Nomes de tabela/coluna/restrição são renomeados explicitamente (não
recriados), preservando os dados já existentes, mesmo padrão da migration
e4e246883f15.

Identificador desta migration: e23888d9bc1f
Vem depois de: 694c20b4e5d2
Criada em: 2026-09-27 17:41:44.917672

"""
from typing import Sequence, Union

from alembic import op


# Identificadores usados pelo Alembic para montar a sequência de migrations.
# "revision" é esta; "down_revision" é a anterior (None se for a primeira).
revision: str = 'e23888d9bc1f'
down_revision: Union[str, Sequence[str], None] = '694c20b4e5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Renomeia sugestoes_frame -> sugestoes_cena (tabela e restrições) e
    sugestoes_participante.sugestao_frame_id -> sugestao_cena_id."""
    op.rename_table('sugestoes_frame', 'sugestoes_cena')
    op.execute('ALTER TABLE sugestoes_cena RENAME CONSTRAINT pk_sugestoes_frame TO pk_sugestoes_cena')
    op.execute(
        'ALTER TABLE sugestoes_cena RENAME CONSTRAINT '
        'fk_sugestoes_frame_capitulo_id TO fk_sugestoes_cena_capitulo_id'
    )
    op.execute(
        'ALTER TABLE sugestoes_cena RENAME CONSTRAINT '
        'fk_sugestoes_frame_frame_id TO fk_sugestoes_cena_frame_id'
    )
    op.execute('ALTER INDEX ix_sugestoes_frame_capitulo_id RENAME TO ix_sugestoes_cena_capitulo_id')

    op.alter_column('sugestoes_participante', 'sugestao_frame_id', new_column_name='sugestao_cena_id')
    op.execute(
        'ALTER TABLE sugestoes_participante RENAME CONSTRAINT '
        'fk_sugestoes_participante_sugestao_frame_id TO '
        'fk_sugestoes_participante_sugestao_cena_id'
    )


def reverter() -> None:
    """Desfaz o rename, voltando a sugestoes_frame/SugestaoDeFrame."""
    op.execute(
        'ALTER TABLE sugestoes_participante RENAME CONSTRAINT '
        'fk_sugestoes_participante_sugestao_cena_id TO '
        'fk_sugestoes_participante_sugestao_frame_id'
    )
    op.alter_column('sugestoes_participante', 'sugestao_cena_id', new_column_name='sugestao_frame_id')

    op.execute('ALTER INDEX ix_sugestoes_cena_capitulo_id RENAME TO ix_sugestoes_frame_capitulo_id')
    op.execute(
        'ALTER TABLE sugestoes_cena RENAME CONSTRAINT '
        'fk_sugestoes_cena_frame_id TO fk_sugestoes_frame_frame_id'
    )
    op.execute(
        'ALTER TABLE sugestoes_cena RENAME CONSTRAINT '
        'fk_sugestoes_cena_capitulo_id TO fk_sugestoes_frame_capitulo_id'
    )
    op.execute('ALTER TABLE sugestoes_cena RENAME CONSTRAINT pk_sugestoes_cena TO pk_sugestoes_frame')
    op.rename_table('sugestoes_cena', 'sugestoes_frame')


# O Alembic chama as funções pelos nomes "upgrade" e "downgrade" — são exigidos
# pela biblioteca, não escolhidos por nós. Os apelidos abaixo deixam a lógica
# com nomes em português e ainda atendem ao que o Alembic espera.
upgrade = aplicar
downgrade = reverter
