import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.associations import page_topics
from app.models.base import Base
from app.models.topic import Topic


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # lazy="raise": with async code, related rows must be loaded on purpose
    # (selectinload), never by surprise when an attribute is accessed
    topics: Mapped[list[Topic]] = relationship(secondary=page_topics, lazy="raise")
