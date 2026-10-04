"""perfis de renderizacao de fabrica

Os 10 perfis que ja vem prontos (PF1): uma coluna `de_fabrica` (travados pela API), a semeadura dos 10 e a limpeza dos perfis
antigos (decisao do Allan, PF5). Antes de apagar um perfil antigo, os livros e os prompts que o usavam sao religados ao perfil de
fabrica compativel, pelo nome; sem correspondencia, o vinculo fica nulo (e o livro volta a pedir um perfil).

Identificador desta migration: d4e5f6a7b8c9
Vem depois de: c3d4e5f6a7b8
Criada em: 2026-10-04
"""
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Pedaco do nome do perfil antigo -> categoria do perfil de fabrica que o substitui. A ordem importa: vale o primeiro que casar.
_PALAVRAS_DO_NOME = (
    ("cinemat", "FOTORREALISTA_CINEMATOGRAFICO"),
    ("fotorreal", "FOTORREALISTA_CINEMATOGRAFICO"),
    ("oleo", "PINTURA_A_OLEO"),
    ("aquarela", "AQUARELA"),
    ("digital", "ARTE_DIGITAL_CONCEITUAL"),
    ("quadrinho", "QUADRINHOS"),
    ("cartoon", "CARTOON_ANIMACAO"),
    ("anime", "ANIME"),
    ("pixel", "PIXEL_ART"),
    ("gravura", "GRAVURA_CLASSICA"),
    ("3d", "ANIMACAO_3D"),
)


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def aplicar() -> None:
    """Acrescenta a coluna, semeia os 10, religa livros e prompts dos perfis antigos e apaga os antigos."""
    # Importado aqui dentro: a migracao so precisa da funcao no momento de rodar.
    from imagineer.servicos.perfis_de_fabrica import garantir_perfis_de_fabrica

    op.add_column(
        "perfis_renderizacao",
        sa.Column("de_fabrica", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    conexao = op.get_bind()
    garantir_perfis_de_fabrica(conexao)

    fabrica = {
        categoria: perfil_id
        for perfil_id, categoria in conexao.execute(
            sa.text("SELECT id, categoria_estilo FROM perfis_renderizacao WHERE de_fabrica")
        )
    }
    antigos = conexao.execute(sa.text("SELECT id, nome FROM perfis_renderizacao WHERE NOT de_fabrica")).all()
    for perfil_id, nome in antigos:
        sem_acento = _sem_acento(nome)
        destino = next((fabrica[cat] for palavra, cat in _PALAVRAS_DO_NOME if palavra in sem_acento), None)
        if destino is not None:
            for tabela, coluna in (("livros", "perfil_renderizacao_padrao_id"), ("prompts", "perfil_renderizacao_id")):
                conexao.execute(
                    sa.text(f"UPDATE {tabela} SET {coluna} = :destino WHERE {coluna} = :antigo"),
                    {"destino": destino, "antigo": perfil_id},
                )
            # O app so rebaixa o livro quando a revisao sobe, e mexer por SQL direto nao passa pelo ouvinte que a sobe
            # (item 6.9): sobe aqui, nos livros que acabaram de ser religados (como padrao ou nos prompts dos seus frames).
            conexao.execute(
                sa.text(
                    "UPDATE livros SET revisao = revisao + 1 WHERE perfil_renderizacao_padrao_id = :destino "
                    "OR id IN (SELECT c.livro_id FROM capitulos c JOIN frames f ON f.capitulo_id = c.id "
                    "JOIN prompts p ON p.frame_id = f.id WHERE p.perfil_renderizacao_id = :destino)"
                ),
                {"destino": destino},
            )
        conexao.execute(sa.text("DELETE FROM perfis_renderizacao WHERE id = :antigo"), {"antigo": perfil_id})


def reverter() -> None:
    """Remove a coluna. Os 10 perfis ficam como perfis comuns (editaveis); os antigos apagados nao voltam."""
    op.drop_column("perfis_renderizacao", "de_fabrica")


upgrade = aplicar
downgrade = reverter
