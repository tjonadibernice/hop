"""add enrichment columns

Revision ID: b42a16d0b8c0
Revises: 79f33b4abc21
Create Date: 2026-10-15 19:10:25.684683

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "b42a16d0b8c0"
down_revision: str | Sequence[str] | None = "79f33b4abc21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("page_topics", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "pages", sa.Column("status_reason", sa.String(length=300), nullable=True)
    )
    op.add_column("pages", sa.Column("quality_score", sa.Float(), nullable=True))
    op.add_column("pages", sa.Column("embedding", Vector(1024), nullable=True))
    op.add_column(
        "pages", sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_pages_embedding",
        "pages",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_pages_embedding",
        table_name="pages",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_column("pages", "enriched_at")
    op.drop_column("pages", "embedding")
    op.drop_column("pages", "quality_score")
    op.drop_column("pages", "status_reason")
    op.drop_column("page_topics", "confidence")
