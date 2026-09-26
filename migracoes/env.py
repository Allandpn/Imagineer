"""Configuração de execução das migrations do Alembic.

Duas adaptações foram feitas no arquivo gerado automaticamente:

1. **A URL do banco vem do ambiente**, não do ``alembic.ini``. O ``alembic.ini``
   é versionado no git, e senha de banco não entra no git. Então lemos a mesma
   configuração que a aplicação usa (``imagineer.configuracao``) — o que também
   garante que migration e API nunca apontem para bancos diferentes.

2. **``target_metadata`` aponta para a ``Base`` do projeto**. É esse mapa de
   tabelas que o ``alembic revision --autogenerate`` compara com o banco real
   para descobrir sozinho o que mudou.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from imagineer.banco.base import Base
from imagineer.configuracao import obter_configuracoes

# Importar o pacote de modelos registra as tabelas na Base. Enquanto a pasta
# estiver vazia não há efeito nenhum, mas a partir do primeiro modelo criado é
# isso que faz o autogenerate enxergá-lo.
import imagineer.modelos  # noqa: F401  (import com efeito colateral, de propósito)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Injeta a URL real do banco, sobrescrevendo o valor de exemplo do alembic.ini.
config.set_main_option("sqlalchemy.url", obter_configuracoes().url_banco)

target_metadata = Base.metadata


def executar_migrations_offline() -> None:
    """Gera o SQL das migrations sem se conectar ao banco.

    Útil para revisar o que será executado antes de rodar de verdade:
    ``alembic upgrade head --sql``.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def executar_migrations_online() -> None:
    """Conecta no banco e aplica as migrations."""
    conectavel = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool: a migration é um comando de vida curta, não faz sentido
        # manter um pool de conexões aberto para ela.
        poolclass=pool.NullPool,
    )

    with conectavel.connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    executar_migrations_offline()
else:
    executar_migrations_online()
