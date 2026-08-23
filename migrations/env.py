"""Alembic environment. Reads the DB URL from ATHENA_DATABASE_URL (falling
back to the docker-compose.yml local default) rather than from alembic.ini,
so nothing that looks like a credential ever sits in a checked-in file.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from secondlook.case.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

DEFAULT_LOCAL_URL = "postgresql+psycopg://athena:athena@localhost:5432/athena"
config.set_main_option("sqlalchemy.url", os.environ.get("ATHENA_DATABASE_URL", DEFAULT_LOCAL_URL))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
