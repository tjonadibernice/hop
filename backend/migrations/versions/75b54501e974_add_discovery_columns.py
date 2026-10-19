"""add discovery columns

Revision ID: 75b54501e974
Revises: a5dcc5ce8146
Create Date: 2026-10-19 10:50:41.320685

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "75b54501e974"
down_revision: str | Sequence[str] | None = "a5dcc5ce8146"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pages", sa.Column("site", sa.String(length=255), nullable=True))
    op.add_column(
        "pages",
        sa.Column(
            "source",
            sa.String(length=16),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
    )
    op.add_column(
        "pages",
        sa.Column("depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "pages", sa.Column("outlinks", postgresql.ARRAY(sa.Text()), nullable=True)
    )
    op.add_column(
        "pages", sa.Column("links_queued_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Backfill: the host without "www." for existing pages, and their source.
    # Hand-picked seed pages are the ones the pipeline never stored text for.
    op.execute(
        """
        UPDATE pages SET site = regexp_replace(
            substring(canonical_url from '^https?://([^/:]+)'), '^www\\.', ''
        )
        """
    )
    op.execute("UPDATE pages SET source = 'seed' WHERE content IS NULL")
    op.create_index("ix_pages_site", "pages", ["site"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_pages_site", table_name="pages")
    op.drop_column("pages", "links_queued_at")
    op.drop_column("pages", "outlinks")
    op.drop_column("pages", "depth")
    op.drop_column("pages", "source")
    op.drop_column("pages", "site")
