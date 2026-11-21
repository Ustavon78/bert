"""devices: board type and last reported error

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("board", sa.String(length=30), nullable=True))
    op.add_column("devices", sa.Column("last_error", sa.String(length=100), nullable=True))
    op.add_column("devices", sa.Column("last_error_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "last_error_at")
    op.drop_column("devices", "last_error")
    op.drop_column("devices", "board")