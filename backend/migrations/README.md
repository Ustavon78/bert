# Database migrations (Alembic)

The database schema is defined in `db.py`. Alembic records every change of it as a small,
versioned script in `migrations/versions/`, so that any database (fresh or old) can be brought
to the current state without losing data.

## Normal use

```bash
python init_db.py        # fresh database: creates all tables; existing: applies missing migrations
```

Run it after every update of Bert. It is safe to run any number of times.

## Changing the schema (developers)

1. Edit the tables in `db.py`.
2. Create a migration: `alembic revision --autogenerate -m "short description"`
3. **Read the new file in `migrations/versions/`.** Alembic sees a renamed column as
   "drop + add", which would delete data. Fix such cases by hand (`op.alter_column`).
4. Apply it: `python init_db.py`
5. Check: `alembic check` must say "No new upgrade operations detected".
6. Commit the migration file together with the change in `db.py`.

Never edit a migration that was already released. Create a new one instead.

## Existing database from before Alembic

If the tables already exist but there is no version information, `init_db.py` stops with a
message. If the tables match the current `db.py`, mark the database once:

```bash
alembic stamp head
alembic check            # must report no differences
```

## Useful commands

```bash
alembic current          # version of the database
alembic history          # all migrations
alembic downgrade -1     # undo the last migration (may delete data!)
alembic upgrade head --sql   # print the SQL instead of running it
```

Note: MariaDB/MySQL cannot undo schema changes in a transaction. Make a backup before
migrating a database with real data.