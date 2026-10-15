import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.associations import page_topics
from app.models.base import Base
from app.models.topic import Topic

# pending: fetched, waiting for review. approved: shown by Hop.
# rejected: failed a check. needs_review: for the curator agent or a human.
# dead: an approved page that stopped working.
PAGE_STATUSES = ("pending", "approved", "rejected", "needs_review", "dead")

# voyage-4-lite's default size. Changing it means re-embedding every page.
EMBEDDING_DIMENSIONS = 1024


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'needs_review', 'dead')",
            name="status",
        ),
        Index("ix_pages_status", "status"),
        # GIN index: finds rows whose array shares any element with a given array
        Index("ix_pages_simhash_bands", "simhash_bands", postgresql_using="gin"),
        # HNSW index for fast "most similar pages" queries (the recommender)
        Index(
            "ix_pages_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    # The address people open (after redirects)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    # The normalized address used to spot duplicates (see ingestion/urls.py)
    canonical_url: Mapped[str] = mapped_column(String(2048), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    # Why the page got its status, e.g. "low quality (0.21)"
    status_reason: Mapped[str | None] = mapped_column(String(300))
    # Whether other sites may show this page in an iframe.
    # None means not checked yet (see scripts/check_embeddable.py).
    embeddable: Mapped[bool | None]

    # Filled in by the ingestion pipeline. deferred=True: the article text is
    # only loaded when it's used, not with every page (hops never need it)
    content: Mapped[str | None] = mapped_column(Text, deferred=True)
    word_count: Mapped[int | None]
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    simhash_bands: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Filled in by enrichment (see ingestion/enrich.py)
    quality_score: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), deferred=True
    )
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # lazy="raise": with async code, related rows must be loaded on purpose
    # (selectinload), never by surprise when an attribute is accessed
    topics: Mapped[list[Topic]] = relationship(secondary=page_topics, lazy="raise")
