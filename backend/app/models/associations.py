from sqlalchemy import Column, Float, ForeignKey, Table

from app.models.base import Base

# Which topics each page belongs to (a page can have several)
page_topics = Table(
    "page_topics",
    Base.metadata,
    Column("page_id", ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True),
    Column("topic_id", ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
    # How sure the enrichment model was (0-1); NULL for hand-picked pages
    Column("confidence", Float),
)

# Which topics each user picked as interests
user_interests = Table(
    "user_interests",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("topic_id", ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
)
