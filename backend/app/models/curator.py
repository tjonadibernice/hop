import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CURATOR_DECISIONS = ("approve", "reject", "escalate")


class CuratorReview(Base):
    """One run of the curator agent on one page: what it proposed, what was
    applied, and every tool call it made. Append-only, like interactions."""

    __tablename__ = "curator_reviews"
    __table_args__ = (
        CheckConstraint(
            "proposed IN ('approve', 'reject', 'escalate')", name="proposed"
        ),
        CheckConstraint(
            "outcome IN ('approved', 'rejected', 'needs_review')", name="outcome"
        ),
        Index("ix_curator_reviews_page_id", "page_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE")
    )
    # What the agent asked for, and the status Hop actually set. They differ
    # when a guardrail blocks the request (e.g. "approve" without a safety check)
    proposed: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    # Set when a guardrail changed the agent's decision
    blocked_by: Mapped[str | None] = mapped_column(String(300))
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    quality: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str | None] = mapped_column(String(32))
    # Each step: {"tool": ..., "args": {...}, "result": "first 500 chars"}
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
