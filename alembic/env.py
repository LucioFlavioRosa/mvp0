import sys
import os
from logging.config import fileConfig

from sqlalchemy import pool
from alembic import context

# Adiciona o diretório atual ao sys.path para importar os módulos locais (mvp0/)
sys.path.append(os.getcwd())

# Importa a Base e a engine da nova localização no mvp0
from app.core.database import engine, Base
import app.models  # Garante que todos os modelos sejam carregados para o autogenerate

# config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Usamos a engine configurada no core/database.py
    connectable = engine

    if connectable is None:
        # No ambiente produtivo, isso pode ocorrer se as variáveis de ambiente não estiverem no App Service
        raise Exception("Erro: Banco de dados não configurado (Variáveis de ambiente ausentes)")

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
