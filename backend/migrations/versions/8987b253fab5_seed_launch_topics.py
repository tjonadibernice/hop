"""seed launch topics

Revision ID: 8987b253fab5
Revises: 8fc89c1b851e
Create Date: 2026-10-11 02:25:46.545267

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8987b253fab5"
down_revision: str | Sequence[str] | None = "8fc89c1b851e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    topics = [
        ("productivity-focus", "Productivity & focus"),
        ("learning-how-to-learn", "Learning how to learn"),
        ("note-taking-knowledge-management", "Note-taking & knowledge management"),
        ("habits-routines", "Habits & routines"),
        ("mental-models-decision-making", "Mental models & decision-making"),
        ("writing-communication", "Writing & communication"),
        ("programming-software-engineering", "Programming & software engineering"),
        ("computer-science-fundamentals", "Computer science fundamentals"),
        ("ai-machine-learning", "AI & machine learning"),
        ("cybersecurity", "Cybersecurity"),
        ("networking-linux", "Networking & Linux"),
        ("cloud-devops", "Cloud & DevOps"),
        ("data-databases", "Data & databases"),
        ("career-growth-in-tech", "Career growth in tech"),
        ("language-learning", "Language learning"),
    ]

    op.bulk_insert(
        sa.table(
            "topics",
            sa.column("slug", sa.String),
            sa.column("name", sa.String),
        ),
        [{"slug": slug, "name": name} for slug, name in topics],
    )


def downgrade() -> None:
    """Downgrade schema."""
    slugs = [
        "productivity-focus",
        "learning-how-to-learn",
        "note-taking-knowledge-management",
        "habits-routines",
        "mental-models-decision-making",
        "writing-communication",
        "programming-software-engineering",
        "computer-science-fundamentals",
        "ai-machine-learning",
        "cybersecurity",
        "networking-linux",
        "cloud-devops",
        "data-databases",
        "career-growth-in-tech",
        "language-learning",
    ]
    topics_table = sa.table("topics", sa.column("slug", sa.String))
    op.execute(sa.delete(topics_table).where(topics_table.c.slug.in_(slugs)))
