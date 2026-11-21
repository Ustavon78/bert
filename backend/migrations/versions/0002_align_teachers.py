"""align the teachers table with db.py (abbreviation as primary key)

Databases that were created before the teachers table was part of the schema can have another
layout: an extra id column and TEXT columns. This migration converts such a table and keeps
its data. It does nothing if the table already matches (fresh installs).

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name not in ("mysql", "mariadb"):
        return  # the old layout only existed on MariaDB/MySQL

    def inspect() -> sa.engine.reflection.Inspector:
        return sa.inspect(bind)  # fresh inspector, the schema changes between the steps

    columns = {c["name"]: c for c in inspect().get_columns("teachers")}

    # 1. Old layout: surrogate key "id" -> remove it (abbreviation becomes the key).
    if "id" in columns:
        op.execute("ALTER TABLE teachers MODIFY id INT NOT NULL")  # drop AUTO_INCREMENT first
        op.execute("ALTER TABLE teachers DROP PRIMARY KEY")
        op.execute("ALTER TABLE teachers DROP COLUMN id")

    # 2. A separate unique index on abbreviation is not needed any more (it becomes the key).
    if any(i["name"] == "abbreviation" for i in inspect().get_indexes("teachers")):
        op.execute("ALTER TABLE teachers DROP INDEX abbreviation")

    # 3. Column types as in db.py (fails instead of cutting data if a value is too long).
    abbreviation_type = inspect().get_columns("teachers")
    types = {c["name"]: c["type"] for c in abbreviation_type}
    if not isinstance(types["abbreviation"], sa.String) or getattr(types["abbreviation"], "length", None) != 20:
        op.execute("ALTER TABLE teachers MODIFY abbreviation VARCHAR(20) NOT NULL")
    if not isinstance(types["name"], sa.String) or getattr(types["name"], "length", None) != 80:
        op.execute("ALTER TABLE teachers MODIFY name VARCHAR(80) NOT NULL")

    # 4. Primary key on abbreviation.
    if inspect().get_pk_constraint("teachers")["constrained_columns"] != ["abbreviation"]:
        op.execute("ALTER TABLE teachers ADD PRIMARY KEY (abbreviation)")


def downgrade() -> None:
    # The old layout was never part of a release, there is nothing to go back to.
    pass