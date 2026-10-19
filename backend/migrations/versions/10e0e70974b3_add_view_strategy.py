"""add view strategy

Revision ID: 10e0e70974b3
Revises: 75b54501e974
Create Date: 2026-10-19 12:02:36.221600

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "10e0e70974b3"
down_revision: str | Sequence[str] | None = "75b54501e974"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "interactions", sa.Column("strategy", sa.String(length=16), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("interactions", "strategy")
