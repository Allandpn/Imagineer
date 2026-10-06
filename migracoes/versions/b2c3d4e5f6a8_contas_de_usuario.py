"""contas de usuario: o dono de cada livro, configuracao e perfis por pessoa (CT4 a CT10)

Tabela nova `usuarios`, com o usuario 1 (o dono, que usa as chaves do servidor). Todo livro que existe passa a ser dele (`livros.usuario_id`,
obrigatorio), assim como os gastos de IA (`usos_ia.usuario_id`) e os perfis de renderizacao que nao sao de fabrica (`perfis_renderizacao.usuario_id`,
nulo = de fabrica). O nome do perfil deixa de ser unico no sistema e passa a ser unico por pessoa. A configuracao deixa de ser "linha unica":
o `id` dela passa a ser o id do usuario (a linha 1 ja era a do dono). Nada muda para quem usa o modo `pessoal`.

Identificador desta migration: b2c3d4e5f6a8
Vem depois de: a1b2c3d4e5f7
Criada em: 2026-10-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a8'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def aplicar() -> None:
    """Cria `usuarios` com o dono (sem id explicito: a sequencia entrega o 1 e fica pronta para o 2) e liga tudo a ele."""
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("login", sa.String(length=200), nullable=True),
        sa.Column("nome", sa.String(length=200), nullable=True),
        sa.Column("dono", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("usa_chaves_do_servidor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("login", name=op.f("uq_usuarios_login")),
    )
    op.execute("INSERT INTO usuarios (nome, dono, usa_chaves_do_servidor) VALUES ('Dono', true, true)")

    # livros: obrigatorio, com os que ja existem indo para o dono (id 1)
    op.add_column("livros", sa.Column("usuario_id", sa.Integer(), nullable=True))
    op.execute("UPDATE livros SET usuario_id = 1")
    op.alter_column("livros", "usuario_id", nullable=False)
    op.create_foreign_key(op.f("fk_livros_usuario_id"), "livros", "usuarios", ["usuario_id"], ["id"], ondelete="RESTRICT")
    op.create_index(op.f("ix_livros_usuario_id"), "livros", ["usuario_id"])

    # gastos de IA: de quem foi (nulo = de antes das contas)
    op.add_column("usos_ia", sa.Column("usuario_id", sa.Integer(), nullable=True))
    op.execute("UPDATE usos_ia SET usuario_id = 1")
    op.create_foreign_key(op.f("fk_usos_ia_usuario_id"), "usos_ia", "usuarios", ["usuario_id"], ["id"], ondelete="CASCADE")
    op.create_index(op.f("ix_usos_ia_usuario_id"), "usos_ia", ["usuario_id"])

    # perfis: os de fabrica ficam sem dono (nulo); os proprios vao para o dono. O nome passa a ser unico por pessoa.
    op.add_column("perfis_renderizacao", sa.Column("usuario_id", sa.Integer(), nullable=True))
    op.execute("UPDATE perfis_renderizacao SET usuario_id = 1 WHERE de_fabrica = false")
    op.drop_constraint("uq_perfis_renderizacao_nome", "perfis_renderizacao", type_="unique")
    op.create_unique_constraint(op.f("uq_perfis_renderizacao_usuario_id"), "perfis_renderizacao", ["usuario_id", "nome"])
    op.create_foreign_key(op.f("fk_perfis_renderizacao_usuario_id"), "perfis_renderizacao", "usuarios", ["usuario_id"], ["id"], ondelete="CASCADE")
    op.create_index(op.f("ix_perfis_renderizacao_usuario_id"), "perfis_renderizacao", ["usuario_id"])

    # configuracao: deixa de ser "linha unica"; o id e o do usuario (a linha 1 ja e a do dono)
    op.drop_constraint(op.f("ck_configuracao_linha_unica"), "configuracao", type_="check")
    op.create_foreign_key(op.f("fk_configuracao_id"), "configuracao", "usuarios", ["id"], ["id"], ondelete="CASCADE")


def reverter() -> None:
    """Desfaz tudo. **Perde** os livros, gastos e perfis das outras pessoas se houver mais de um usuario: so serve de volta para o modo pessoal."""
    op.drop_constraint(op.f("fk_configuracao_id"), "configuracao", type_="foreignkey")
    op.execute("DELETE FROM configuracao WHERE id <> 1")
    op.create_check_constraint("linha_unica", "configuracao", "id = 1")

    op.drop_index(op.f("ix_perfis_renderizacao_usuario_id"), table_name="perfis_renderizacao")
    op.drop_constraint(op.f("fk_perfis_renderizacao_usuario_id"), "perfis_renderizacao", type_="foreignkey")
    op.drop_constraint(op.f("uq_perfis_renderizacao_usuario_id"), "perfis_renderizacao", type_="unique")
    op.execute("DELETE FROM perfis_renderizacao WHERE usuario_id IS NOT NULL AND usuario_id <> 1")
    op.create_unique_constraint("uq_perfis_renderizacao_nome", "perfis_renderizacao", ["nome"])
    op.drop_column("perfis_renderizacao", "usuario_id")

    op.drop_index(op.f("ix_usos_ia_usuario_id"), table_name="usos_ia")
    op.drop_constraint(op.f("fk_usos_ia_usuario_id"), "usos_ia", type_="foreignkey")
    op.drop_column("usos_ia", "usuario_id")

    op.execute("DELETE FROM livros WHERE usuario_id <> 1")
    op.drop_index(op.f("ix_livros_usuario_id"), table_name="livros")
    op.drop_constraint(op.f("fk_livros_usuario_id"), "livros", type_="foreignkey")
    op.drop_column("livros", "usuario_id")

    op.drop_table("usuarios")


upgrade = aplicar
downgrade = reverter
