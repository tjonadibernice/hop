import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

INTERACTION_KINDS = ("view", "like", "dislike")


class Interaction(Base):
    """One thing a user did with a page. Append-only: rows are never updated."""

    __tablename__ = "interactions"
    __table_args__ = (
        CheckConstraint("kind IN ('view', 'like', 'dislike')", name="kind"),
        Index("ix_interactions_user_id_page_id", "user_id", "page_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
