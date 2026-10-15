"""add link check columns

Revision ID: a5dcc5ce8146
Revises: b42a16d0b8c0
Create Date: 2026-10-16 02:08:31.956789

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5dcc5ce8146"
down_revision: str | Sequence[str] | None = "b42a16d0b8c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "pages", sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "pages",
        sa.Column(
            "check_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.create_index("ix_pages_next_check_at", "pages", ["next_check_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_pages_next_check_at", table_name="pages")
    op.drop_column("pages", "check_failures")
    op.drop_column("pages", "next_check_at")
