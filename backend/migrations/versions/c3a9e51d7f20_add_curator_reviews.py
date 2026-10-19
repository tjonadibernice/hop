"""add curator reviews

Revision ID: c3a9e51d7f20
Revises: 10e0e70974b3
Create Date: 2026-10-19 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3a9e51d7f20"
down_revision: str | Sequence[str] | None = "10e0e70974b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "pages", sa.Column("curated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "curator_reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("proposed", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("blocked_by", sa.String(length=300), nullable=True),
        sa.Column("topics", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("quality", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "proposed IN ('approve', 'reject', 'escalate')",
            name=op.f("ck_curator_reviews_proposed"),
        ),
        sa.CheckConstraint(
            "outcome IN ('approved', 'rejected', 'needs_review')",
            name=op.f("ck_curator_reviews_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["pages.id"],
            name=op.f("fk_curator_reviews_page_id_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curator_reviews")),
    )
    op.create_index(
        "ix_curator_reviews_page_id", "curator_reviews", ["page_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_curator_reviews_page_id", table_name="curator_reviews")
    op.drop_table("curator_reviews")
    op.drop_column("pages", "curated_at")
