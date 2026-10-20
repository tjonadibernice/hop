"""add page kind (article or interactive)

Revision ID: e4a7c2d9b153
Revises: d81f4c2b9e63
Create Date: 2026-10-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4a7c2d9b153"
down_revision: str | Sequence[str] | None = "d81f4c2b9e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Every existing page was stored by the article-only pipeline
    op.add_column(
        "pages",
        sa.Column(
            "kind",
            sa.String(length=16),
            server_default=sa.text("'article'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_pages_kind"), "pages", "kind IN ('article', 'interactive')"
    )
    op.create_index("ix_pages_status_kind", "pages", ["status", "kind"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_pages_status_kind", table_name="pages")
    op.drop_constraint(op.f("ck_pages_kind"), "pages", type_="check")
    op.drop_column("pages", "kind")
