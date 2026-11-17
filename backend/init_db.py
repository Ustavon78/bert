# SPDX-License-Identifier: GPL-3.0-or-later
"""Create or update the database tables:  python init_db.py

The schema is managed with Alembic migrations (folder migrations/).
    fresh database      all tables are created
    existing database   the migrations that are still missing are applied
    --reset             delete ALL tables and data and create everything again (development only!)
"""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from db import engine, metadata


def main() -> None:
    if "--reset" in sys.argv:
        answer = input("ALL tables and data will be deleted. Type 'yes' to confirm: ")
        if answer.strip().lower() != "yes":
            sys.exit("Cancelled.")
        metadata.drop_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        print("Tables deleted.")

    tables = set(inspect(engine).get_table_names())
    if tables and "alembic_version" not in tables:
        sys.exit(
            "This database has tables but no version information (it was created before\n"
            "Alembic was introduced). If its tables match the current schema, run once:\n"
            "    alembic stamp head\n"
            "    alembic check\n"
            "'alembic check' must report no differences. Then run init_db.py again."
        )

    command.upgrade(Config(str(Path(__file__).with_name("alembic.ini"))), "head")
    print("The database is up to date.")


if __name__ == "__main__":
    main()