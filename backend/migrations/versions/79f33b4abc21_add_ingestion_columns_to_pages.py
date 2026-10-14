"""add ingestion columns to pages

Revision ID: 79f33b4abc21
Revises: 3e6e7359544b
Create Date: 2026-10-15 02:53:59.727932

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "79f33b4abc21"
down_revision: str | Sequence[str] | None = "3e6e7359544b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing pages get canonical_url = url. Add the column as nullable,
    # fill it in, then require it.
    op.add_column(
        "pages", sa.Column("canonical_url", sa.String(length=2048), nullable=True)
    )
    op.execute("UPDATE pages SET canonical_url = url")
    op.alter_column("pages", "canonical_url", nullable=False)
    op.create_unique_constraint(
        op.f("uq_pages_canonical_url"), "pages", ["canonical_url"]
    )

    # Existing pages are the hand-picked seeds, so they start as approved.
    # New rows default to pending from now on.
    op.add_column(
        "pages",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'approved'"),
            nullable=False,
        ),
    )
    op.alter_column("pages", "status", server_default=sa.text("'pending'"))
    op.create_check_constraint(
        op.f("ck_pages_status"),
        "pages",
        "status IN ('pending', 'approved', 'rejected', 'needs_review', 'dead')",
    )
    op.create_index("ix_pages_status", "pages", ["status"], unique=False)

    op.add_column("pages", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("pages", sa.Column("word_count", sa.Integer(), nullable=True))
    op.add_column("pages", sa.Column("simhash", sa.BigInteger(), nullable=True))
    op.add_column(
        "pages",
        sa.Column("simhash_bands", postgresql.ARRAY(sa.Integer()), nullable=True),
    )
    op.add_column(
        "pages",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_pages_simhash_bands",
        "pages",
        ["simhash_bands"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("uq_pages_canonical_url"), "pages", type_="unique")
    op.drop_constraint(op.f("ck_pages_status"), "pages", type_="check")
    op.drop_index("ix_pages_status", table_name="pages")
    op.drop_index("ix_pages_simhash_bands", table_name="pages", postgresql_using="gin")
    op.drop_column("pages", "last_checked_at")
    op.drop_column("pages", "simhash_bands")
    op.drop_column("pages", "simhash")
    op.drop_column("pages", "word_count")
    op.drop_column("pages", "content")
    op.drop_column("pages", "status")
    op.drop_column("pages", "canonical_url")
