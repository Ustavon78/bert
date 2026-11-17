# SPDX-License-Identifier: GPL-3.0-or-later
"""Alembic environment: uses the tables from db.py and DATABASE_URL from the .env."""

from logging.config import fileConfig

from alembic import context

from config import require_env  # also loads the .env
from db import engine, metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def run_migrations_offline() -> None:
    """Write the SQL instead of running it (alembic upgrade head --sql)."""
    context.configure(
        url=require_env("DATABASE_URL"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot alter tables directly; batch mode rebuilds them.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()